# Roadmap

## 最近一次实现状态

当前 MVP 已完成可运行闭环：

- YAML loader
- Tool Design Audit
- Eval Quality Audit
- Eval Generator from_tools
- Eval Generator from_tests
- PythonToolExecutor
- ToolRegistry
- MockReplayAdapter
- EvalRunner
- RunRecorder
- RuleJudge
- TranscriptAnalyzer
- MarkdownReport
- `examples/runtime_debug` demo
- pytest 测试
- README / ARCHITECTURE / ROADMAP / TESTING

每次 run 会生成：

- `transcript.jsonl`
- `tool_calls.jsonl`
- `tool_responses.jsonl`
- `metrics.json`
- `audit_tools.json`
- `audit_evals.json`
- `judge_results.json`
- `diagnosis.json`
- `report.md`

## 当前 MVP 范围

MVP 目标是“可运行闭环”，不是大而全 benchmark。

当前重点：

- 用 deterministic rules 审计工具和 eval；
- 用 replay adapter 固定 good/bad 路径；
- 用 artifacts 证明 Agent 是否真的正确使用工具；
- 用测试保证 bad path 会失败、good path 会成功。

## 暂不做范围

本轮不实现：

- 真实 OpenAI API adapter
- 真实 Anthropic API adapter
- MCP executor
- HTTP executor
- Shell executor
- Web UI
- 自动修改用户工具代码
- 复杂 LLM Judge
- 并发执行
- 大规模 benchmark

## 已知设计债

- Audit 规则是启发式 deterministic rules，后续需要用真实项目反馈调权重。
- `from_tools` 只能生成候选题，缺少真实 fixture 时不可运行。
- `from_tests` 只做静态扫描，不能自动恢复测试 fixture 和用户上下文。
- `MockReplayAdapter` 只覆盖 demo good/bad path，后续需要 replay transcript adapter 和真实 LLM adapter。
- `RuleJudge.must_use_evidence` 当前检查 evidence 关键词和工具 evidence，后续可支持 evidence id 精确引用。
- metrics 只统计基础数量，后续需要 latency、token、tool error、retry 等指标。

## P0 后续

- 增加 transcript replay adapter，从已有 JSONL 重放真实事件链路。
- 扩展 `RuleJudge` 支持 evidence id 精确匹配。
- 给 eval candidate 增加 review 状态和转正命令。
- 增加 artifact schema 校验测试。

## P1 后续

- 实现 OpenAI adapter。
- 实现 Anthropic adapter。
- 实现 MCP executor。
- 增加 tool latency、token estimate、error rate metrics。
- 支持多 eval 文件合并和 split 过滤。

## P2 后续

- HTTP executor。
- Shell executor。
- LLM Judge 作为辅助 reviewer。
- Web UI 查看 transcript、tool calls、diagnosis。
- 自动 patch 建议，但默认不直接修改用户工具代码。
- 大规模 benchmark 和并发执行。

## xfail 测试

当前没有 xfail 测试。

未来允许 xfail 的条件：

- 测试覆盖的是明确的未来能力，例如真实 adapter、MCP executor 或 evidence id 精确引用；
- 必须写清楚 reason；
- 必须写清楚转正条件；
- 不能用 xfail 掩盖当前 MVP 应该满足的需求。

## Mock/Replay 替换计划

当前 `MockReplayAdapter` 是 MVP 的可复现 adapter。

后续替换方向：

- `TranscriptReplayAdapter`：读取历史 transcript/tool_calls/tool_responses；
- `OpenAIAdapter`：直接调用 OpenAI API；
- `AnthropicAdapter`：直接调用 Anthropic API；
- `MCPExecutor`：连接用户 MCP server 执行工具。
