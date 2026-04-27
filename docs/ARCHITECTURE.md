# Architecture

Agent Tool Harness 的核心链路是：

`Audit -> Generate -> Audit Evals -> Run -> Record -> Judge -> Diagnose -> Report`

这个顺序不是为了流程好看，而是为了避免直接把模型最终回答当成成功证据。先检查工具契约，再生成候选 eval，再审计 eval 质量，最后运行并记录 raw transcript，才能回答 Agent 是否真的会正确使用工具。

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

- good：先调用 `runtime_trace_event_chain`，再调用 `runtime_inspect_checkpoint`，最终判断 `input_boundary`；
- bad：先调用 `tui_inspect_snapshot`，不调用关键 trace 工具，最终误判为 UI rendering。

MVP 先用 mock/replay，是为了把 recorder、judge、diagnosis、report 做成可测闭环。真实 OpenAI/Anthropic adapter 后续替换 adapter 层即可。

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
