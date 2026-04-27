# Architecture

Agent Tool Harness 的核心链路是：

`Audit -> Generate -> Audit Evals -> Run -> Record -> Judge -> Diagnose -> Report`

这个顺序不是为了流程好看，而是为了避免直接把模型最终回答当成成功证据。先检查工具契约，再生成候选 eval，再审计 eval 质量，最后运行并记录 raw transcript，才能回答 Agent 是否真的会正确使用工具。

## 当前阶段非目标

第二阶段只强化注释、架构文档、Roadmap 和测试纪律，不扩展运行能力。

当前仍然不实现：

- 真实 OpenAI/Anthropic adapter
- MCP/HTTP/Shell executor
- Web UI
- 自动修改用户工具代码
- 复杂 LLM Judge
- 并发执行或大规模 benchmark
- from_transcripts / from_docs 等更强 eval 生成
- held-out vs training 的真实对比与基线 diff

这些能力只能保留在 Roadmap 中，不能以“顺手补齐”的方式进入 MVP 主线。

## 信号质量披露（与 Anthropic 文章方法论的差距）

Anthropic 的 *Writing effective tools for agents* 主张 evaluation 必须由真实 LLM agentic
loop 驱动，从 trajectory 中观察 Agent 是否能正确选用工具。当前 harness 仍只有
`MockReplayAdapter`，它直接把 eval 自带的 `expected_tool_behavior.required_tools` 反向
回放给 RuleJudge，因此 PASS 在结构上是必然的。

为了不让真实团队把这种 PASS 误读为评估信号，框架在 `agent_tool_harness/signal_quality.py`
里定义了显式的 **信号质量等级**：

- `tautological_replay`：当前 MockReplayAdapter 默认等级；
- `rule_deterministic`：未来基于规则但不直接照抄 eval 期望的 adapter；
- `recorded_trajectory`：未来 TranscriptReplayAdapter；
- `real_agent`：未来真实 OpenAI/Anthropic adapter；
- `unknown`：兜底等级，提醒读者“adapter 未声明”。

`AgentAdapter` 协议要求每个实现显式声明 `SIGNAL_QUALITY`。EvalRunner 把这个标签写入
`metrics.json` 的 `signal_quality` / `signal_quality_note`，MarkdownReport 在报告顶部
渲染为 banner。**任何看到 `tautological_replay` 的 run，PASS/FAIL 都不能作为“工具是否
对真实 Agent 好用”的依据。**

这是 MVP 阶段的诚实披露，不是评分；它只解决“信号边界要不要被显式告知”这一问题。
真正缩小与 Anthropic 文章的差距，需要等真实 LLM adapter（计划见 Roadmap）。

## 证据契约

每次 run 的一手证据是三个 JSONL 文件：

- `transcript.jsonl`：用户、assistant、tool 事件流，服务人工复盘；
- `tool_calls.jsonl`：Agent 发出的结构化工具调用，必须保留原始参数；
- `tool_responses.jsonl`：工具返回的结构化结果，包含 success/content/error/metadata。

其余文件是派生证据：

- `metrics.json`：运行统计；
- `audit_tools.json`：工具设计审计结果；
- `audit_evals.json`：eval 质量审计结果；
- `judge_results.json`：规则判定结果；
- `diagnosis.json`：从 transcript/tool calls 派生的失败解释；
- `report.md`：给人 review 的汇总视图。

报告不能替代 raw artifacts。任何 bug 复盘都应先回到 JSONL。

## 模块职责

### config

负责加载 `project.yaml`、`tools.yaml`、`evals.yaml` 并转成 `ProjectSpec`、`ToolSpec`、`EvalSpec`。

不负责审计质量，不执行工具，不判定 eval 成败。

### audit

`ToolDesignAuditor` 按五类 Agent 工具原则审计工具契约：

- right tools
- namespacing
- meaningful context
- token efficiency
- prompt/spec quality

**当前能力边界（重要）：** 这是 **structural / completeness** 检查，不是语义级质量
判断。它只读 `tools.yaml` 字段，不读 Python 工具源码、不调用工具看真实输出。**字段
齐全 ≠ 工具好用**——一个字段写得无懈可击但与已有工具职责重叠的“语义诱饵”工具仍会
被判 5.0。这一 gap 已被 `tests/test_tool_design_audit_decoy_xfail.py` 钉为 strict xfail，
转正条件见 `docs/ROADMAP.md`。

`EvalQualityAuditor` 审计 eval 是否真实、多步、可验证、不过拟合唯一策略，并检查 split/fixture/runnable。

audit 不运行 Agent，也不调用工具。

### eval_generation

`EvalGenerator` 从 tools 或 tests 生成候选 eval。

它不覆盖正式 `evals.yaml`。候选缺上下文时必须标记 `runnable: false` 和 `missing_context`。

### tools

`ToolRegistry` 负责按工具名查找 `ToolSpec` 并分发到 executor。

`PythonToolExecutor` 是 MVP 的本地 Python executor，只负责导入函数并调用。

tools 层不负责 Agent 工具选择，也不负责 judge。

### agents

`AgentAdapter` 定义 Agent 行为接口。

`MockReplayAdapter` 提供 `good` 和 `bad` 两条可复现路径：

- good：按 `expected_tool_behavior.required_tools` 调用关键工具，并引用可验证 evidence；
- bad：优先按 judge 的 `forbidden_first_tool` 选择错误首步，模拟可复现失败路径。

MVP 先用 mock/replay，是为了把 recorder、judge、diagnosis、report 做成可测闭环。
MockReplayAdapter 不应硬编码 `examples/runtime_debug` 的工具名；demo 只是配置输入，真实
OpenAI/Anthropic adapter 后续替换 adapter 层即可。

### recorder

`RunRecorder` 负责写：

- `transcript.jsonl`
- `tool_calls.jsonl`
- `tool_responses.jsonl`
- `metrics.json`
- `audit_tools.json`
- `audit_evals.json`
- `judge_results.json`
- `diagnosis.json`
- `report.md`

recorder 不评判好坏。它只保证失败可以复盘。

recorder 的边界非常重要：它不能过滤错误参数，也不能吞掉失败工具响应。错误调用和失败返回本身就是评估证据。

EvalRunner 会在 adapter 抛错、registry 初始化失败或 eval 被 audit 判定不可运行时写入
runner 事件，并继续生成派生 artifacts。这样失败原因不会只停留在 Python traceback 里。

### judges

`RuleJudge` 根据 tool calls、tool responses 和 final answer 做 deterministic 判定。

当前支持：

- `must_call_tool`
- `must_call_one_of`
- `forbidden_first_tool`
- `max_tool_calls`
- `expected_root_cause_contains`
- `must_use_evidence`
- `must_not_modify_before_evidence`

### diagnose

`TranscriptAnalyzer` 从真实调用链路解释失败，比如第一步工具错误、缺少关键工具、没有 evidence。

它不替代 judge，只生成可读诊断。

### reports

`MarkdownReport` 聚合 audit、metrics、judge 和 diagnosis，输出 `report.md`。

报告不隐藏 raw artifacts，review 时仍应回看 JSONL。

## 扩展边界

### Adapter

真实模型接入应实现 `AgentAdapter`，并继续通过 `RunRecorder` 写 transcript/tool calls/tool responses。

计划中的 adapter：

- OpenAI adapter
- Anthropic adapter
- replay transcript adapter

### Executor

新的工具执行方式应实现 `ToolExecutor` 协议并注册到 `ToolRegistry`。

计划中的 executor：

- MCP executor
- HTTP executor
- Shell executor

### Judge

当前只实现 deterministic `RuleJudge`。后续可以新增 LLM Judge，但不能替代 raw transcript 和 deterministic rules。

当前 RuleJudge 已做基础防误判：

- 空 `expected_root_cause_contains` 不会通过；
- `must_use_evidence` 要求最终回答引用工具返回的 evidence id/label；
- `must_not_modify_before_evidence` 优先读取 tool call 上的 `side_effects`。

## 失败归因流程

当一次 eval 失败时，按这个顺序定位：

1. `audit_tools.json`：工具契约是否让 Agent 容易选错或拿不到 evidence；
2. `audit_evals.json`：eval 是否真实、多步、可验证，是否缺 fixture；
3. `tool_calls.jsonl`：第一步工具、调用顺序、参数是否符合任务；
4. `tool_responses.jsonl`：工具是否返回了足够 evidence 和 next_action；
5. `judge_results.json`：具体是哪条规则失败；
6. `diagnosis.json`：失败是否属于错误第一步、缺关键工具、缺 evidence 等结构性问题。

如果只能通过最终回答判断成败，说明 eval 或 judge 还不合格。

## 变更守卫

新增能力前必须回答：

- 它是否扩大了当前 MVP 范围；
- 是否需要新的 adapter/executor/judge 边界；
- 是否会绕过 RunRecorder；
- 是否仍能生成全部 artifacts；
- bad path 是否仍会失败；
- 是否需要更新 Roadmap 和测试纪律文档。

## 为什么不写死用户项目逻辑

这个 harness 是通用框架。用户项目差异必须通过这些方式注入：

- `project.yaml`
- `tools.yaml`
- `evals.yaml`
- adapter
- executor
- judge
- evidence source

`examples/runtime_debug` 只是 demo，不能进入框架核心逻辑。
