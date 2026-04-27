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

第二阶段强化已加入当前工作范围：

- 补强关键模块中文学习型注释，强调证据流和架构边界；
- 补强架构文档中的证据契约、失败归因流程和变更守卫；
- 补强测试纪律文档，明确不允许改弱测试、空测试和无理由 xfail；
- 增加治理纪律测试，防止文档/范围约束被无意削弱。

第三阶段基础修复已加入当前工作范围：

- EvalRunner 在 adapter/registry 失败时尽量写完整 artifacts；
- EvalRunner 使用 EvalQualityAuditor 的 runnable 结果作为执行闸门；
- MockReplayAdapter 从 eval/tool spec 推导 good/bad path，不再硬编码 runtime_debug 工具名；
- ToolRegistry 不再静默覆盖歧义短名；
- PythonToolExecutor 增加最小 input_schema 校验和单参数绑定修正；
- RuleJudge 修复空 root cause 和弱 evidence 引用的明显误判。
- 配置 loader 支持 tools/evals list root，并拒绝重复 eval id 和明显错误字段类型。

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

本轮和第二阶段均不实现：

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

任何新增文件如果实现上述能力，都应先进入 Roadmap review，而不是直接进入代码。

## 已知设计债

- Audit 规则是启发式 deterministic rules，后续需要用真实项目反馈调权重。
- `from_tools` 只能生成候选题，缺少真实 fixture 时不可运行。
- `from_tests` 只做静态扫描，不能自动恢复测试 fixture 和用户上下文。
- `MockReplayAdapter` 仍只是 deterministic mock，不代表真实模型能力；后续需要 replay transcript adapter 和真实 LLM adapter。
- `RuleJudge.must_use_evidence` 已支持基础 evidence id/label 引用，后续仍需要更完整的 evidence matcher。
- metrics 只统计基础数量，后续需要 latency、token、tool error、retry 等指标。
- 当前文档测试只能检查关键短语和范围守卫，不能替代人工架构 review。
- loader 仍不是完整 schema validator；它只做接入期结构校验，深层质量判断仍依赖 audit。

## P0 后续

- 增加 transcript replay adapter，从已有 JSONL 重放真实事件链路。
- 扩展 `RuleJudge` 支持 evidence id 精确匹配。
- 给 eval candidate 增加 review 状态和转正命令。
- 增加 artifact schema 校验测试。
- 将治理纪律测试扩展为文档章节/schema 的更细粒度检查。

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

xfail 转正条件必须满足：

- 对应能力进入当前阶段范围；
- 有真实 fixture 或 replay 证据；
- bad path 仍能被判失败；
- 相关文档和 Roadmap 已同步更新。

## Mock/Replay 替换计划

当前 `MockReplayAdapter` 是 MVP 的可复现 adapter。

后续替换方向：

- `TranscriptReplayAdapter`：读取历史 transcript/tool_calls/tool_responses；
- `OpenAIAdapter`：直接调用 OpenAI API；
- `AnthropicAdapter`：直接调用 Anthropic API；
- `MCPExecutor`：连接用户 MCP server 执行工具。
