# Current Implementation — 诚实描述

## 当前是什么

agent-tool-harness v2.0.0 是一个 **Headless CLI Agent Tool Harness Prototype**。
所有功能纯本地、离线、不联网、不需要 API 密钥。

## CLI 命令（13 个）

| 命令 | 功能 |
|------|------|
| `audit-tools` | 工具契约确定性启发式审计 |
| `audit-evals` | eval 质量审计 |
| `generate-evals` | 从工具/测试生成候选 eval |
| `promote-evals` | 候选 eval 审核后机械转正 |
| `run` | mock replay 执行全链路 |
| `replay-run` | 历史 run 的 deterministic 轨迹重放 |
| `analyze-artifacts` | 离线复盘 trace 信号 |
| `bootstrap` | AST 扫描生成 draft tools.yaml + evals.yaml |
| `scaffold-tools` | 从 Python 源码生成 draft tools.yaml |
| `scaffold-evals` | 从 tools.yaml 生成 draft evals.yaml |
| `scaffold-fixtures` | 生成占位 fixture |
| `validate-generated` | 交叉验证 scaffold 产物 |
| `judge-provider-preflight` | 本地 live readiness 自检（不联网）|
| `audit-judge-prompts` | judge prompt 安全审计 |

## 当前配置文件

- `project.yaml` — 项目元数据
- `tools.yaml` — 工具契约（字段齐全性、命名空间、输入输出契约等）
- `evals.yaml` — eval 用例（用户问题、预期工具行为、判定规则）

## 当前 mock / fake / demo 组件

| 组件 | 类型 | 说明 |
|------|------|------|
| `MockReplayAdapter` | mock | 按 good/bad 分支回放工具调用，signal_quality = tautological_replay |
| `TranscriptReplayAdapter` | replay | 按历史 transcript 重放，signal_quality = recorded_trajectory |
| `RuleJudge` | deterministic | 规则匹配（包含 evidence id、调用顺序等），不是语义判定 |
| `RuleJudgeProvider` | deterministic | RuleJudge 的 provider 包装 |
| `RecordedJudgeProvider` | dry-run | 从 fixture 回放预录判定 |
| `CompositeJudgeProvider` | composite | 聚合多个 advisory provider 投票 |
| `ToolDesignAuditor` | heuristic | 字段齐全性 + 命名 + 描述词袋检查，不是语义审计 |
| `EvalQualityAuditor` | heuristic | eval 结构完整性检查 |
| `JudgePromptAuditor` | heuristic | judge prompt 安全/格式检查 |
| `TraceSignalAnalyzer` | heuristic | 5 类 trace 复盘信号 |
| `TranscriptAnalyzer` | rule-based | failure attribution 分析 |
| `LiveAnthropicTransport` | **代码存在但未验证** | 使用 stdlib http.client，从不对真实端点测试 |
| `AnthropicCompatibleJudgeProvider` | **offline 模式可用，live 模式未验证** | live 模式需要双标志 + 4 个 env var |

## 当前输出（10 个 artifact）

`run` 命令每次输出：`transcript.jsonl`, `tool_calls.jsonl`, `tool_responses.jsonl`,
`metrics.json`, `audit_tools.json`, `audit_evals.json`, `judge_results.json`,
`diagnosis.json`, `llm_cost.json`, `report.md`

其中 `llm_cost.json` 的 `estimated_cost_usd` 永远为 `null`，actual cost 永远为 `null`，
永远是 advisory-only，不是真实账单。

## 当前测试

- 58 个测试文件
- 1 个 strict xfail（钉住 deterministic 启发式根本限制）
- 覆盖：CLI / artifact / audit / judge / provider / report / diagnose / scaffold / security / cost
- 所有 live transport 测试用 fake connection，CI 0 联网

## 当前不支持的能力

- 真实 LLM Agent 执行（无 `RealAgentAdapter`）
- LLM judge 语义评分（`LiveAnthropicTransport` 代码存在但未验证）
- 真实项目 runtime 接入（只有配置文件级 mock 接入）
- Web UI / MCP / HTTP / Shell executor
- RAG / 向量库
- 多租户 / 企业 RBAC
- Benchmark / Leaderboard
- `run` 命令硬编码 `MockReplayAdapter`，不支持注入自定义 AgentAdapter
- 无 Python SDK（`__init__.py` 只导出 `__version__`）

## Current coverage against Anthropic intent

以下表格逐项对照 Anthropic *Writing effective tools for agents* 的主张与当前实现状态：

| 能力 | 当前状态 | 实现证据 | 尚未支持 | 未来模块 |
|------|---------|---------|---------|---------|
| 工具 schema / 设计审计 | ✅ 已实现 | `ToolDesignAuditor` 五类原则 | — | 可扩展更深 |
| Mock replay 执行 | ✅ 已实现 | `MockReplayAdapter` good/bad 分支 | 不是真实 Agent eval | `RealAgentAdapter` |
| Deterministic rule checks | ✅ 已实现 | `RuleJudge` 5 类规则 | 不是 LLM 语义判定 | `JudgeProvider` (LLM) |
| 报告生成 | ✅ 已实现 | `MarkdownReport` + `signal_quality` 声明 | — | `ReviewDecision` |
| Failure attribution | ✅ 已实现 | `TranscriptAnalyzer` 四分类 | 基于 mock 数据未验证 | — |
| 可观测性 artifact | ✅ 已实现 | 10 个结构化 artifact | `llm_cost.json` advisory-only | `EvidenceStore` |
| Human review 支持 | ✅ 已实现 | Report + artifact 追溯链 | 不自动裁决 | — |
| 工具选择正确性评测 | ❌ 未实现 | — | 需真实 Agent 选择工具 | `RealAgentAdapter` |
| 真实 Agent runtime | ❌ 未实现 | — | 需 `AgentAdapter` 扩展 | `RealAgentAdapter` |
| LLM judge 语义评分 | ❌ 未实现 | — | 需独立 `JudgeProvider` | `JudgeProvider` (LLM) |
| Provider cost / latency evidence | ❌ 未实现 | — | 需真实 API 调用 | `ProviderConfig` |

> 表格中的 ❌ 是 **knowingly not yet supported**，不是产品缺陷。当前项目处于
> headless CLI prototype 阶段，这些能力在 BACKLOG.md P2/P3 中规划。

## 当前最小可用路径

1. clone → install → pytest
2. `audit-tools` → 看工具设计审计结果
3. `run --mock-path good` → 看 mock replay PASS
4. `run --mock-path bad` → 看 mock replay FAIL
5. 读 `report.md` + `diagnosis.json`
6. 接入自己的 tools.yaml → 重复上述流程

## 当前不应该被误解为什么

- **不是** 真实 Agent 评测平台
- **不是** LLM eval benchmark
- **不是** 工具质量认证服务
- **不是** 生产级 CI 插件
- `signal_quality: tautological_replay` 的 PASS/FAIL **不是** "工具对真实 Agent 好用"
- deterministic rule checks **不能** 替代 LLM 语义判定
