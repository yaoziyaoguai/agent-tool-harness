# Scenario Design（评测场景模块设计）

> 本文档描述 agent-tool-harness 中 Scenario（评测场景）的概念、数据模型、生成与审核流程。
> 在源码中，Scenario 对应 `EvalSpec` dataclass 和 `eval_generation/` 子包。
>
> 面向读者：eval 设计者、Coding Agent、模块维护者。

---

## 一、模块目的

Scenario 模块负责**定义和管理 Agent 工具使用的评估用例（eval case）**。

一个 Scenario 回答："给定一个用户任务，Agent 应该如何正确使用工具？"

它不是简单的"输入→输出"断言，而是对**工具调用链路**的完整行为期望。

## 二、当前实现现状

### 2.1 数据模型（`config/eval_spec.py`）

`EvalSpec` 是 eval 用例的核心数据类。每个 eval 包含（来自 README §配置文件 段 + `ARTIFACTS.md`）：

| 字段 | 类型 | 含义 |
|------|------|------|
| `id` | str (unique) | eval 唯一标识 |
| `name` | str | 人类可读名称 |
| `category` | str | 分类（如 `regression`, `smoke`） |
| `split` | str | 数据集划分（如 `baseline`, `held_out`） |
| `realism_level` | str | 真实度 |
| `complexity` | str | 复杂度（`single_step`, `multi_step`） |
| `source` | str | 来源标记 |
| `user_prompt` | str | 模拟真实用户对 Agent 说的话。**不应泄露工具名** |
| `initial_context` | dict | Agent 已有的上下文信息 |
| `verifiable_outcome` | dict | 可验证的结果期望（含 `expected_root_cause`） |
| `success_criteria` | list | 成功标准 |
| `expected_tool_behavior` | dict | 期望的工具调用行为（`required_tools`, `allowed_tools`, `forbidden_first_tool` 等） |
| `judge` | dict | judge 规则定义 |
| `missing_context` | list | 标记缺失的上下文（candidate 阶段用） |
| `runnable` | bool | 是否可运行（candidate 阶段为 false） |
| `review_status` | str | 审核状态（`candidate`, `accepted`, `rejected`, `needs_review`） |
| `review_notes` | str | 审核备注 |
| `difficulty` | str | 难度（`trivial`, `single_step`, `multi_step`, `unknown`） |

### 2.2 生成流程（`eval_generation/`）

```
EvalGenerator（generator.py）
    ├── from_tools.py    → 从 tools.yaml 的每个 tool 生成 1+ 条候选 eval
    ├── from_tests.py    → 扫描 pytest 测试函数名/docstring/xfail reason 生成候选
    │
    ▼
CandidateWriter（candidate_writer.py）
    → 写候选 YAML（顶层 key: eval_candidates / warnings）
    → 收集 5 类 warning：empty_input / all_unrunnable / missing_review_notes
      / high_missing_context / cheating_prompt_suspect
    │
    （人工 review + 补字段 + 改 review_status → accepted）
    │
    ▼
CandidatePromoter（promoter.py）
    → 机械搬运 accepted + runnable=true + 字段齐全的候选
    → 拒绝时给具体 reason
    → 默认禁止覆盖已存在文件
```

### 2.3 关键设计决策

**两阶段流程（generate → promote）**：生成阶段产出的是 **候选（candidate）**，不是正式 eval。这刻意阻止了"自动把生成结果当正式 eval 用"的路径——生成没有真实用户上下文，必须经过人工 review。

**`review_status` 状态机**：
- `candidate` → 默认，等待 review
- `needs_review` → 工具契约缺关键字段（`when_to_use` / `output_contract.evidence` 等），正确做法是回 `tools.yaml` 修工具契约
- `accepted` → 人工确认可转正
- `rejected` → 人工确认不该转正

**`runnable: false` 作为安全默认**：所有生成的候选默认不可运行，防止伪造的 PASS/FAIL 进入正式评估。

## 三、核心输入

- `tools.yaml`（`from_tools` 模式下）—— 为每个 tool 生成对应 eval
- `tests/` 目录（`from_tests` 模式下）—— 扫描测试函数签名和 docstring
- 人工 review 输入：`initial_context`、`expected_root_cause`、`judge.rules`、`review_status` 修改

## 四、核心输出

- 候选 eval YAML 文件（`eval_candidates.yaml`）：含 `warnings` 顶层字段 + 每条候选的 `review_status` / `review_notes`
- 正式 eval YAML 文件（`evals.promoted.yaml`）：含 `promote_summary`（`promoted_ids` + `skipped` 详情）

## 五、关键接口

| 接口 | 位置 | 稳定性 |
|------|------|--------|
| `EvalSpec` dataclass | `config/eval_spec.py` | 稳定 |
| `EvalGenerator.generate(from_tools=True/False)` | `eval_generation/generator.py` | 实验性（生成策略可能调整） |
| `CandidateWriter.write(candidates, path)` | `eval_generation/candidate_writer.py` | 实验性 |
| `CandidatePromoter.promote(candidates_path, out_path)` | `eval_generation/promoter.py` | 实验性 |
| `review_status` 字段 4 态全集 | `EvalSpec.review_status` | 稳定（被 promote 和 audit 流程依赖） |

## 六、不负责什么

- ❌ 判断候选质量（那是人类的职责）
- ❌ 审计 eval 质量（那是 `EvalQualityAuditor` 的职责）
- ❌ 运行 eval（那是 `EvalRunner` 的职责）
- ❌ 自动把候选合并到正式 evals.yaml（promoter 只输出新文件）
- ❌ 从真实 transcript 或 docs 生成 eval（那是 v3.0+ backlog）
- ❌ 交互式 reviewer（当前全是 CLI + 人工编辑 YAML）

## 七、和其他模块的关系

```
config/eval_spec.py  ← 定义 EvalSpec（被所有模块共享的数据模型）
        ↑
eval_generation/     ← 生成候选 + 转正
        │
        ├──→ audit/eval_quality_auditor.py  （审计 eval 质量）
        ├──→ runner/eval_runner.py          （执行 eval）
        └──→ judges/rule_judge.py           （评判 eval 结果）
```

## 八、测试证明方式

| 测试文件 | 覆盖内容 |
|---------|---------|
| `test_eval_generation_from_tools.py` | from_tools 生成的候选字段完整性 |
| `test_eval_generation_from_tests.py` | from_tests 生成的候选字段完整性 |
| `test_from_tools_judge_quality.py` | 生成候选的 judge 规则质量 |
| `test_p1b_promote_warnings_schema.py` | promoter 的 rejection reason 和 warning schema |
| `test_eval_quality_auditor.py` | auditor 对候选 runnable 的判断 |

## 九、后续实现或重构建议

1. **`from_tests` 的 initial_context 推断**：当前静态扫描无法构造 initial_context，导致大量候选 `runnable: false`。可考虑解析 fixture 文件或 conftest 推断上下文（v2.x patch）。

2. **`from_docs` / `from_transcripts` 生成源**：ROADMAP 中提到的未来生成源，当前未实现。

3. **`difficulty` 启发式细化**：当前简单映射 `complexity → difficulty`，可考虑基于 expected_tool_behavior 的工具调用数量做更准确的判断。

4. **候选模板质量**：from_tools 生成的候选有时 `user_prompt` 过于接近工具描述，接近 `cheating_prompt_suspect`。generator 已有 warning 收集但无自动改写（设计如此——改写属于人类职责）。

## 十、Review Checklist（审查清单）

Scenarios 模块变更 Review 时，检查以下项：

- [ ] 新增 eval 的 `user_prompt` 是否来自真实用户问题（不含工具名）
- [ ] `expected_tool_behavior.required_tools` 是否引用了 `tools.yaml` 中存在的工具
- [ ] `judge.rules` 是否足够区分 good/bad path（不只靠 `must_call_tool`）
- [ ] `runnable` 是否与 `initial_context` / `expected_root_cause` 的完整性一致
- [ ] `review_status` 是否正确标记（`needs_review` → 回修 tools.yaml，不要强改 accepted）
- [ ] 候选 `warnings` 是否被审核（`cheating_prompt_suspect` 等）
- [ ] promoter rejection 的 reason 是否可行动（不只是"缺字段"而是"缺什么字段"）
- [ ] 新增 eval 是否覆盖了 bad path（有对应的 bad fixture）
