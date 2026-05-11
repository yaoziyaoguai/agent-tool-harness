# User Scenarios（用户场景）

> 本文档从用户视角描述 agent-tool-harness 的典型使用场景。
> 每个场景包含：谁、输入、执行流程、输出、人类 Review 点。
> 本文档用于指导新用户接入、模块设计和文档组织。

---

## 场景概览

| # | 场景 | 用户角色 | 频率 | 关键文档 |
|---|------|---------|------|---------|
| 1 | 第一次接入：给自己的工具做评估 | Agent 工具开发者 | 一次性（首次接入） | `ONBOARDING.md`, `INTERNAL_TRIAL_QUICKSTART.md` |
| 2 | 设计新 eval 并转正 | Eval 设计者 | 重复（每次新增工具或发现 gap） | `README.md` §候选 eval 审核流程 |
| 3 | 复盘一次 Agent 工具调用失败 | 质量 Reviewer | 按需（CI 红了或怀疑问题时） | `docs/ARTIFACTS.md`, `docs/ARCHITECTURE.md` §失败归因 |
| 4 | 审计同事写的工具设计 | 架构审计者 / TL | 按需（Code Review 或上线前） | `README.md` §审计工具 |
| 5 | Maintainer 处理内部试用反馈 | Maintainer（维护者） | 重复（每次收到反馈） | `FEEDBACK_TRIAGE_WORKFLOW.md` |
| 6 | Maintainer 决定是否 tag / release | Maintainer（维护者） | 重复（每个 release cycle） | `V2_X_RELEASE_CANDIDATE_NOTES.md` |

---

## 场景 1：第一次接入——给自己的工具做评估

### 用户：Agent 工具开发者

### 背景

用户在某个 AI Agent 项目中写了几个工具函数（如 `search_kb`, `classify_issue`, `validate_config`），
想知道这些工具的设计是否合理——Agent 能否正确选用，输出是否包含足够 evidence。

### 输入

- 用户项目的工具源码（`.py` 文件目录）
- 用户对自己工具的业务理解

### 执行流程（推荐 bootstrap 路径，5-15 分钟）

```
1. bootstrap --source <dir> --out my_team/ath-bootstrap
   一条命令完成：静态扫描源码 → draft tools.yaml → draft evals.yaml → draft fixtures → validation

2. 按 REVIEW_CHECKLIST.md 补完 tools.yaml 中的 TODO(reviewer): 字段
   （when_to_use / output_contract / token_policy / side_effects）

3. 按 REVIEW_CHECKLIST.md 补完 evals.yaml 中的 TODO(reviewer): 字段
   （initial_context / expected_root_cause / judge.rules），把 runnable 改为 true

4. validate-generated --strict-reviewed
   确认 0 TODO + 至少 1 条 runnable

5. audit-tools
   检查工具设计的五维评分 + 语义风险信号

6. run --mock-path good && run --mock-path bad
   good 全 PASS / bad 全 FAIL → 证明 judge 没退化为同义复读
```

### 输出

- `tools.yaml`（已 review）
- `evals.yaml`（已 review，含 runnable=true 的正式 eval）
- `runs/demo-good/` 目录（10 个 artifact：`transcript.jsonl`, `tool_calls.jsonl`, `tool_responses.jsonl`, `metrics.json`, `audit_tools.json`, `audit_evals.json`, `judge_results.json`, `diagnosis.json`, `llm_cost.json`, `report.md`）
- `runs/demo-bad/` 目录（同上，bad path）

### 人类 Review 点

- **REVIEW_CHECKLIST 步骤**：所有 `TODO(reviewer):` 字段是否已替换为真实业务语义——**不允许**只删 TODO 不补内容
- **good/bad 双 pass/fail 验证**：good 全 PASS / bad 全 FAIL —— 如果两条命令结果一样，说明 mock fixture 只覆盖了 good path，或 eval 写得太宽松
- **audit-tools semantic_risk_detected warning**：如果有，必须人工 review 是否为真实语义风险

---

## 场景 2：设计新 eval 并转正

### 用户：Eval 设计者

### 背景

用户已经有 `tools.yaml`，现在需要为新发现的工具使用场景（或发现的 gap）补充 eval 用例。
例如：发现 Agent 在"错误日志中包含敏感信息"的情况下会错误地调用 `kb.search` 而不是先 `classify_issue`。

### 输入

- 已有的 `tools.yaml`
- 业务场景描述（用户真实 prompt 模板、预期行为）

### 执行流程

```
1. generate-evals --source tools --tools tools.yaml --out candidates.yaml
   生成候选 eval，review_status=candidate, runnable=false

2. 人工逐条对照 review_notes：
   - 补 initial_context（场景上下文）
   - 补 verifiable_outcome.expected_root_cause（期望根因）
   - 补 expected_tool_behavior.required_tools（期望调用的工具）
   - 确认 user_prompt 来自真实用户问题，不含工具名
   - 把 review_status 改为 accepted

3. promote-evals --candidates candidates.yaml --out evals.new.yaml
   机械搬运 accepted + runnable=true + 字段齐全的候选

4. audit-evals --evals evals.new.yaml
   确认 runnable=true 且 findings 为空

5. 把新 eval 合并到正式 evals.yaml（手动 merge 或替换）

6. run --mock-path good && run --mock-path bad
   验证新 eval good PASS / bad FAIL
```

### 输出

- `candidates.yaml`（含 review_status 标注）
- `evals.new.yaml`（promoted 正式 eval）
- `runs/audit-evals/` （audit 结果）

### 人类 Review 点

- **user_prompt 是否真实**：不能直接写"请用 kb.search.search_articles 搜索"——这等于给 Agent 答案
- **judge 规则是否足够区分 good/bad**：如果只有 `must_call_tool`，任何调了这个工具的路径都会 PASS——需要加 `must_use_evidence` 或 `evidence_from_required_tools`
- **review_status 的诚实性**：`needs_review` 意味着工具契约缺关键字段，应该回去修 `tools.yaml` 而不是强行 accepted

---

## 场景 3：复盘一次 Agent 工具调用失败

### 用户：质量 Reviewer / TL / On-call

### 背景

CI 中某个 eval FAIL 了，或者怀疑线上 Agent 的行为退化。需要从 artifact 中找到"Agent 到底做了什么、
哪里做错了、该改什么"。

### 输入

- 一次 `run` 产出的 `runs/<dir>/` 目录（10 个 artifact）
- 对应的 `tools.yaml` 和 `evals.yaml`（用于对照理解）

### 执行流程（按 `docs/ARCHITECTURE.md` §失败归因流程）

```
1. 看 report.md → Per-Eval Details 段
   定位哪条 eval FAIL，失败类别是什么

2. 看 tool_calls.jsonl
   Agent 第一步调了什么工具？参数是什么？调用顺序是否符合预期？

3. 看 tool_responses.jsonl
   工具返回了什么 evidence？是否缺 next_action？是否有截断但无指引？

4. 看 judge_results.json
   具体是哪条规则失败？must_use_evidence？forbidden_first_tool？evidence_from_required_tools？

5. 看 diagnosis.json
   失败归因到哪个 category——tool_design（改工具） / eval_definition（改 eval） / agent_tool_choice（改 Agent prompt）

6. （可选）analyze-artifacts --run runs/<dir> --tools tools.yaml
   离线复盘 trace 信号：工具是否兑现了自己的契约？调用模式是否浪费？
```

### 输出

- 对失败原因的定性判断 + 修复方向（改 tools.yaml / 改 evals.yaml / 改 Agent prompt）
- 可选的 `tool_use_signals.json` + `tool_use_signals.md`（trace-derived 信号）

### 人类 Review 点

- **不要把 `diagnosis.json` 的 `root_cause_hypothesis` 当成最终根因**——一定要回到 raw artifact 验证
- **不要只看 `report.md`**——report 是派生视图，可能漏掉关键细节
- **区分 deterministic 信号的边界**：`signal_quality: tautological_replay` 时，PASS/FAIL 不能作为"工具对真实 Agent 好用"的证据

---

## 场景 4：审计同事写的工具设计

### 用户：架构审计者 / TL

### 背景

同事提交了一份新的 `tools.yaml`，TL 需要在 Code Review 或上线前判断工具设计是否合理。

### 输入

- 同事提交的 `tools.yaml`

### 执行流程

```
1. audit-tools --tools pr_tools.yaml --out runs/audit-tools
   输出 audit_tools.json + audit_tools.md（如果生成了）

2. 看 overall_score 和 category_scores（五维）
   score 低（<3）→ 工具设计有硬伤

3. 看 findings
   - high severity → 必须修
   - semantic_risk_detected warning → 字段看起来齐但语义可疑（如 shallow_wrapper / semantic_overlap）

4. 看 signal_quality: deterministic_heuristic + signal_quality_note
   记住：字段齐全 ≠ 工具好用，deterministic audit 不会识别"用完全不同的词汇描述同一职责"的诱饵工具
```

### 输出

- `audit_tools.json`（machine-readable 审计结果）
- Review 意见（人工判断，结合 audit findings）

### 人类 Review 点

- **不要把 `overall_score: 5.0` 当成"工具设计完美"**——deterministic audit 只能识别字段缺失/浅封装/词汇重叠，无法识别隐蔽语义诱饵
- **`semantic_risk_detected` warning 必须人工 review**——这是字段评分高但仍有语义风险的护栏信号
- **对照 `when_not_to_use` 字段**——这是最容易写得太空泛的字段

---

## 场景 5：Maintainer 处理内部试用反馈

### 用户：Maintainer（维护者）

### 背景

内部试用者通过 `INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md` 提交了结构化反馈。Maintainer 需要分流处理。

### 输入

- 试用者的反馈（结构化 YAML/Markdown 或自由文本）
- `INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md` 的字段定义

### 执行流程（按 `FEEDBACK_TRIAGE_WORKFLOW.md` 5 类决策表）

```
1. 验证反馈有效性 → feedback/validator.py（Python module，非 CLI）
   检查 16 个必填字段 + 7 条硬规则

2. 分流到 5 类决策桶：
   - v2.x patch：明确的 bug / 文档断点 / CLI 体验问题 → 排期修
   - v3.0 backlog candidate：需要真实 LLM judge / MCP / Web UI → 记入 backlog，不立刻动
   - closed-as-design：设计意图如此，非 bug → 回复解释
   - needs-more-evidence：信息不足 → 追问
   - security-blocker：安全风险（secret 泄漏等）→ 立刻处置

3. 更新 INTERNAL_TRIAL_FEEDBACK_SUMMARY.md
   追踪真实反馈数（maintainer rehearsal 不计入，synthetic 不计入）

4. 判断是否触发 v3.0 gate：≥3 份真实非维护者反馈
```

### 输出

- 分流决策 + 行动项
- 更新后的 `INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`

### 人类 Review 点

- **区分 maintainer rehearsal vs 真实反馈**：rehearsal 不计入 v3.0 ≥3 门槛
- **区分 synthetic feedback vs 真实反馈**：FEEDBACK_TRIAGE_WORKFLOW §6 的 synthetic case 不计入
- **security-blocker 不是 v3.0 触发器**：安全风险立刻处置，不等待 v3.0

---

## 场景 6：Maintainer 决定是否 tag / release

### 用户：Maintainer（维护者）

### 背景

Maintainer 认为当前 main 分支可能已经满足 v2.x 的 release 标准，需要做一个封板判断。

### 输入

- 当前 main 分支的代码和测试状态
- 真实内部反馈统计

### 执行流程（按 `V2_X_RELEASE_CANDIDATE_NOTES.md`）

```
1. 确认已完成能力表全部 green
2. 确认 69+ 测试全 green（1 strict xfail 不算失败）
3. 确认 no-leak 契约未退化
4. 确认 v3.0 gate 条件评估准确
5. 如果决定 tag：创建带注释的 annotated tag
6. 如果决定不 tag：更新 RC notes 注明原因
```

### 输出

- Tag（如 `v2.1`）或不 tag 的明确记录

### 人类 Review 点

- **不 tag 的原因必须写清楚**——避免"永远觉得还差一点"的发布恐惧
- **v3.0 gate 的真实反馈数必须准确**——不能把 maintainer rehearsal 或 synthetic 计为真实反馈

---

## 场景之间的关系

```
场景 1（第一次接入）
  ↓
场景 4（审计工具设计）←→ 场景 2（设计新 eval）
  ↓
场景 3（复盘失败 —— 在 run 之后触发）
  ↓
场景 5（收到反馈 → 处理分流）← Maintainer 专用
  ↓
场景 6（决定 tag / release）← Maintainer 专用
```

- 场景 1/2/3/4 对所有用户角色开放
- 场景 5/6 是 Maintainer 专用流程
- 场景 3 可以在任何 run 之后触发，不依赖其他场景
