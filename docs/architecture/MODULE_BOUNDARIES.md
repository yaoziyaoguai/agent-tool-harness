# Module Boundaries（模块边界）

> 本文档定义 agent-tool-harness 各核心模块的职责边界、允许的依赖方向、不允许的耦合模式。
> 它是"架构层面的 lint 规则"——任何修改模块边界的行为都必须先过本文档。
>
> 面向读者：后续 Coding Agent、代码 Review 者、新模块的引入者。

---

## 一、当前源码模块全景（11 个子包 + 3 个根模块）

```
agent_tool_harness/
├── __init__.py              # 包声明 + __version__
├── cli.py                   # CLI 入口（argparse，1707 行）
├── artifact_schema.py       # schema_version + run_metadata 戳
├── signal_quality.py        # SignalQuality 枚举
│
├── config/                  # 配置加载
│   ├── loader.py            #   YAML → Spec 对象
│   ├── project_spec.py      #   ProjectSpec dataclass
│   ├── tool_spec.py         #   ToolSpec dataclass
│   └── eval_spec.py         #   EvalSpec dataclass
│
├── audit/                   # 设计审计
│   ├── tool_design_auditor.py    # 5 维工具设计审计
│   ├── eval_quality_auditor.py   # 5 维 eval 质量审计
│   └── judge_prompt_auditor.py   # judge prompt 安全审计
│
├── eval_generation/         # eval 候选生成与转正
│   ├── generator.py         #   EvalGenerator 主逻辑
│   ├── from_tools.py        #   从 tools.yaml 生成
│   ├── from_tests.py        #   从 pytest 测试扫描
│   ├── candidate_writer.py  #   候选写盘 + warning 收集
│   └── promoter.py          #   CandidatePromoter（非交互转正）
│
├── scaffold/                # 新用户 bootstrap
│   ├── bootstrap.py         #   一键 bootstrap 编排
│   ├── from_python_ast.py   #   AST 静态扫描 → draft tools.yaml
│   ├── from_tools_yaml.py   #   tools.yaml → draft evals + fixtures
│   └── validate_generated.py #  交叉校验 + strict-reviewed 模式
│
├── agents/                  # Agent 行为适配
│   ├── agent_adapter_base.py     # AgentAdapter 协议 + SIGNAL_QUALITY
│   ├── mock_replay_adapter.py    # 按 eval 期望回放
│   └── transcript_replay_adapter.py # 从已有 run 录制重放
│
├── tools/                   # 工具执行
│   ├── executor_base.py     #   ToolExecutor 协议
│   ├── python_executor.py   #   Python 本地执行器
│   └── registry.py          #   ToolRegistry（按名查找+分发）
│
├── runner/                  # 执行编排
│   └── eval_runner.py       #   EvalRunner 主循环
│
├── recorder/                # 事件记录
│   └── run_recorder.py      #   写 10 个 artifact
│
├── judges/                  # 评判
│   ├── rule_judge.py        #   RuleJudge（8 类规则）
│   ├── provider.py          #   JudgeProvider 协议 + 各实现 + LiveTransport
│   └── preflight.py         #   live readiness 本地侧自检
│
├── diagnose/                # 失败诊断
│   ├── transcript_analyzer.py    # 交叉关联 → 12 类 finding
│   └── trace_signal_analyzer.py  # contract/模式层信号
│
├── reports/                 # 报告生成
│   ├── markdown_report.py   #   report.md 渲染
│   └── cost_tracker.py      #   llm_cost.json 聚合
│
└── feedback/                # 反馈验证
    └── validator.py         #   结构化反馈校验 + secret 扫描
```

---

## 二、模块职责与反职责

### 2.1 config/

**负责**：
- 加载 `project.yaml` / `tools.yaml` / `evals.yaml` 并转为 `ProjectSpec` / `ToolSpec` / `EvalSpec` dataclass 对象
- 校验 YAML 顶层结构合法性

**不负责**（即使看起来相关）：
- ❌ 审计工具设计质量 → 那是 `audit/` 的职责
- ❌ 执行工具 → 那是 `tools/` 的职责
- ❌ 评判 eval 成败 → 那是 `judges/` 的职责
- ❌ 校验 eval 字段的语义正确性（如 `expected_tool_behavior.required_tools` 是否引用真实工具名）→ 那是 `audit/eval_quality_auditor.py` 的职责

### 2.2 audit/

**负责**：
- 对 `tools.yaml` 做 deterministic 5 维审计（ToolDesignAuditor）
- 对 `evals.yaml` 做 deterministic 5 维审计 + runnable 判断（EvalQualityAuditor）
- 对 judge prompt + rubric 做 deterministic 安全审计（JudgePromptAuditor）
- 显式标记 `signal_quality: deterministic_heuristic`

**不负责**：
- ❌ 读 Python 工具源码 → audit 只看 yaml 字段
- ❌ 调用工具看真实输出 → audit 不执行工具
- ❌ 做 LLM 语义判断 → audit 是 deterministic 启发式
- ❌ 判定 eval 最终 PASS/FAIL → 那是 `judges/` 的职责
- ❌ 运行 Agent → 那是 `agents/` + `runner/` 的职责

### 2.3 eval_generation/

**负责**：
- 从 `tools.yaml` 生成候选 eval（from_tools）
- 从 pytest 测试扫描生成候选 eval（from_tests）
- 写候选文件 + 收集 warning（CandidateWriter）
- 机械搬运 accepted 候选为正式 eval（CandidatePromoter）

**不负责**：
- ❌ 判断候选质量（"这条 eval 该不该转正"）→ 那是人类的职责
- ❌ 审计 eval 质量 → 那是 `audit/` 的职责
- ❌ 运行 eval → 那是 `runner/` 的职责
- ❌ 自动把候选合并到正式 evals.yaml → promoter 只输出新文件

### 2.4 scaffold/

**负责**：
- AST 静态扫描 Python 源码生成 draft `tools.yaml`（**不 import、不执行**）
- 从 draft `tools.yaml` 生成 draft `evals.yaml` + draft fixtures
- 交叉校验 bootstrap 产出（validate-generated）
- 一键 bootstrap 编排

**不负责**：
- ❌ 执行用户代码 → scaffold 全程不 import
- ❌ 联网 → scaffold 纯本地 AST 扫描
- ❌ 生成"正确"的业务语义（`when_to_use` / `output_contract` 等）→ 全部写 `TODO(reviewer):`

### 2.5 agents/

**负责**：
- 定义 `AgentAdapter` 协议 + `SIGNAL_QUALITY` 等级
- 提供 `MockReplayAdapter`（按 eval 期望回放）
- 提供 `TranscriptReplayAdapter`（从已有 run 录制重放）
- 声明每次实现的信号质量等级

**不负责**：
- ❌ 判断 Agent 行为正确性 → 那是 `judges/` 的职责
- ❌ 记录 Agent 行为 → 那是 `recorder/` 的职责
- ❌ 执行工具 → adapter 只发出 tool_call，由 `runner/` 协调 `tools/` 执行
- ❌ 连接真实 LLM → 当前所有 adapter 都是 deterministic

### 2.6 tools/

**负责**：
- 定义 `ToolExecutor` 协议
- 按工具名查找 `ToolSpec`（ToolRegistry）
- 提供 `PythonToolExecutor`（本地 Python 函数调用 + minimal schema validation）

**不负责**：
- ❌ Agent 工具选择 → 那是 `agents/` 的职责
- ❌ 评判工具输出 → 那是 `judges/` 的职责
- ❌ 审计工具设计 → 那是 `audit/` 的职责

### 2.7 runner/

**负责**：
- EvalRunner 主循环：对每条 eval 协调 adapter / registry / recorder / judge / diagnoser / reporter
- 生成 metrics 聚合
- 异常路径兜底（adapter 抛错、registry 初始化失败、eval 不可运行）

**不负责**：
- ❌ 直接的 Agent 模拟 → 委托给 `agents/`
- ❌ 直接的文件写入 → 委托给 `recorder/`
- ❌ 评判 → 委托给 `judges/`
- ❌ 诊断 → 委托给 `diagnose/`
- ❌ 报告渲染 → 委托给 `reports/`

### 2.8 recorder/

**负责**：
- 写 10 个 artifact：`transcript.jsonl`, `tool_calls.jsonl`, `tool_responses.jsonl`, `metrics.json`, `audit_tools.json`, `audit_evals.json`, `judge_results.json`, `diagnosis.json`, `llm_cost.json`, `report.md`
- 保证失败时也能完整写入（runner_error 事件兜底）

**不负责**：
- ❌ 评判好坏 → recorder 只记录，不评判
- ❌ 过滤错误参数或失败响应 → 错误本身就是评估证据，必须保留

### 2.9 judges/

**负责**：
- RuleJudge：8 类 deterministic 规则评判
- JudgeProvider 协议：RuleJudgeProvider / RecordedJudgeProvider / AnthropicCompatibleJudgeProvider / CompositeJudgeProvider
- LiveAnthropicTransport：真实 HTTPS transport 骨架
- judge-provider-preflight：本地侧 live readiness 自检

**不负责**：
- ❌ 诊断失败原因 → 那是 `diagnose/` 的职责
- ❌ 在 CI 或默认模式下联网 → transport 默认 disabled，双标志 opt-in

### 2.10 diagnose/

**负责**：
- TranscriptAnalyzer：交叉关联 raw artifact → 12 类 failure attribution finding
- TraceSignalAnalyzer：消费 tool_calls / tool_responses payload → 5 类 trace-derived 信号
- 两个分析器正交并存，互补不替换

**不负责**：
- ❌ 替代 RuleJudge → PASS/FAIL 仍以 judge 为准
- ❌ 作为 LLM Judge → 全部 deterministic 启发式
- ❌ 重新执行工具或 Agent

### 2.11 reports/

**负责**：
- MarkdownReport：聚合 audit + metrics + judge + diagnosis → `report.md`
- CostTracker：聚合 dry_run 结果 → `llm_cost.json`
- 显式声明方法论边界（Methodology Caveats）

**不负责**：
- ❌ 生成新数据 → report 是派生视图，不新增一手证据
- ❌ 作为复盘的一手证据 → review 时必须回到 raw JSONL

### 2.12 feedback/

**负责**：
- 结构化反馈校验（16 必填字段 + 7 硬规则）
- secret 字面扫描（sk- / Bearer / Authorization）
- 区分真实反馈 vs maintainer rehearsal vs synthetic

**不负责**：
- ❌ 联网 → 纯本地模块
- ❌ 调 LLM → deterministic 校验
- ❌ 暴露 CLI 子命令（避免 snippet drift scope 蔓延）

---

## 三、允许的依赖方向

```
                    ┌─────────┐
                    │  cli.py │  ← CLI 入口，可以 import 所有模块
                    └────┬────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   ┌─────────┐    ┌──────────┐    ┌───────────┐
   │ scaffold│    │  runner  │    │  feedback │
   └────┬────┘    └────┬─────┘    └───────────┘
        │              │
   ┌────┴────┐    ┌────┴─────┬──────────────┐
   ▼         ▼    ▼          ▼              ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────────┐
│config│ │audit │ │agents│ │tools │ │ eval_gen │
└──────┘ └──────┘ └──────┘ └──────┘ └──────────┘
                      │
              ┌───────┴───────┬──────────┬──────────┐
              ▼               ▼          ▼          ▼
         ┌────────┐    ┌──────────┐ ┌────────┐ ┌────────┐
         │judges  │    │recorder  │ │diagnose│ │reports │
         └────────┘    └──────────┘ └────────┘ └────────┘
```

**关键规则**：

1. **`cli.py` 是唯一的顶层编排入口**：它可以 import 所有模块，但模块之间不能通过 cli.py 互相通信。

2. **`runner/` 是核心编排器**：它可以依赖 `agents/`、`tools/`、`judges/`、`recorder/`、`diagnose/`、`reports/`，但这些模块**不应**反向依赖 `runner/`。

3. **`scaffold/` 只能依赖 `config/`**：bootstrap 是独立流程，不与 runner pipeline 耦合。

4. **底层模块间的最小交叉依赖**：
   - `diagnose/` 可以读 `audit/` 的输出（audit_tools.json / audit_evals.json），但不应调用 auditor 的方法
   - `reports/` 可以读 `judges/`、`diagnose/`、`audit/` 的输出，但不应调用它们的方法
   - `recorder/` 被 `runner/` 独占调用，不应被其他模块直接调用

---

## 四、不允许出现的耦合

以下耦合模式被明确禁止（来自 ROADMAP §全局停止规则 + 架构实践）：

### 4.1 禁止核心包硬编码 example 业务符号

```python
# ❌ 不允许
if tool_name == "kb.search.search_articles":  # knowledge_search example 的工具名
    ...
```

核心包（`agent_tool_harness/` 下任何 `.py`）不应出现 `examples/` 中任何业务符号。这一规则由 `test_example_knowledge_search.py::test_core_package_does_not_hardcode_kb_example_symbols` 钉死。

### 4.2 禁止模块间通过 import 绕过职责边界

```python
# ❌ 不允许：audit/ 直接调用 runner/
from agent_tool_harness.runner import EvalRunner

# ❌ 不允许：judges/ 直接调用 recorder/
from agent_tool_harness.recorder import RunRecorder

# ✅ 允许：cli.py 协调各模块
from agent_tool_harness.runner import EvalRunner
from agent_tool_harness.recorder import RunRecorder
```

### 4.3 禁止在 RuleJudge / Auditor 中加"为了让本次 run PASS"的临时支路

```python
# ❌ 不允许
if eval_id == "problematic_eval":
    return True  # 跳过这个 case 让 CI 绿
```

### 4.4 禁止偷偷升级 signal_quality

```python
# ❌ 不允许
class MockReplayAdapter:
    SIGNAL_QUALITY = SignalQuality.REAL_AGENT  # 必须是 TAUTOLOGICAL_REPLAY
```

### 4.5 禁止 artifact 层静默过滤错误

```python
# ❌ 不允许：recorder 过滤掉失败的工具响应
if not tool_response["success"]:
    return  # 不写入 tool_responses.jsonl
```

---

## 五、如何保持高内聚、低耦合

### 5.1 新增模块前的检查清单

在创建新模块或新子包之前，必须回答：

1. 这个模块是否**只做一件事**？（单一职责）
2. 它是否可以用**已有模块的组合**实现？（避免不必要的模块分裂）
3. 它的**依赖方向**是否指向稳定模块？（不应依赖实验性模块的内部实现）
4. 它是否会**绕过 RunRecorder** 直接写文件？（如果有，不行）
5. 它是否会绕过**已有 artifact schema** 定义新文件格式？（如果有，需要先更新 `ARTIFACTS.md`）

### 5.2 修改现有模块时的检查清单

1. 修改是否**扩大了模块的职责范围**？（如果是，应该考虑拆模块）
2. 修改是否**引入了新的模块间依赖**？（如果是，检查依赖方向是否合法）
3. 修改是否**削弱了模块的"不负责"边界**？（如给 audit 加了网络调用能力）
4. 修改是否**需要更新本文档**？（如果是，同步更新）

### 5.3 保持架构优美（而非巨石化）

- **一个模块 ≤ 5 个 `.py` 文件**（当前最大的是 `eval_generation/` 5 个文件）。如果超过，考虑拆子域。
- **一个文件 ≤ 800 行**（来自 coding-style.md，当前 `cli.py` 1707 行已超标，但作为 CLI 入口有其合理性——未来可考虑拆为 `cli/` 子包）。
- **模块间依赖 ≤ 3 层深度**。如果出现 A→B→C→D 的 4 层链，说明中间层可以扁平化。

---

## 六、模块边界的测试验证

每个模块边界都应被测试覆盖：

| 边界 | 验证测试 | 验证内容 |
|------|---------|---------|
| scaffold 不执行用户代码 | `test_bootstrap_pipeline_smoke.py` | canary `raise RuntimeError` 确保任何 import 退路会让测试 FAIL |
| audit 不调用工具 | `test_tool_design_auditor.py` | auditor 不接受 executor 参数 |
| recorder 不评判 | `test_eval_runner_artifacts.py` | runner_error 路径下 artifact 仍然完整 |
| judge 不透传 deterministic baseline | `test_judge_provider_skeleton.py` | advisory PASS 不覆盖 deterministic FAIL |
| CLI 命令名稳定性 | `test_doc_cli_snippets.py` | 文档中所有 CLI 命令真实可解析 |
| no-leak 边界 | `test_artifact_consistency.py` + `test_cli_anthropic_compatible_live.py` | artifact 不写 key/url/Authorization |
| 核心包不硬编码 example 符号 | `test_example_knowledge_search.py` | `CORE_FORBIDDEN_KB_SYMBOLS` 不在核心包出现 |
