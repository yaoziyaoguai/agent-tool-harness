# Current Implementation — 诚实描述

## 当前是什么

agent-tool-harness v3.2.0 是一个 **tool-use inspection platform**，包含结构化报告洞察层和任务级评测。
Primary path: external runner → trace/log import → inspect/evaluate/report。
所有功能纯本地、离线、不联网、不需要 API 密钥。

## CLI 命令（14 个）

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
| `OpenAITransport` | **已验证（openai-compatible smoke）** | stdlib http.client, normalization layer handles 7 response shapes |
| `AnthropicTransport` | **已验证（anthropic-compatible smoke）** | stdlib http.client, content block iteration skips thinking blocks |
| `LiveAnthropicTransport` (legacy) | superseded | 已被 `AnthropicTransport` 取代，保留在 `judges/provider.py` |

## 模块按 Demo / Core / Real 分类

> 边界定义见 [DEMO_CORE_REAL_BOUNDARY.md](architecture/DEMO_CORE_REAL_BOUNDARY.md)。

### Core candidate（定义契约、流程、对象——不依赖 demo 或真实 provider）

| 模块 | 路径 | 职责 |
|------|------|------|
| Config / Spec | `config/` | ProjectSpec, ToolSpec, EvalSpec 定义 |
| AgentAdapter Protocol | `agents/agent_adapter_base.py` | AgentAdapter + AgentRunResult |
| JudgeProvider Protocol | `judges/provider.py` | JudgeProvider + ProviderJudgeResult |
| ToolExecutor Protocol | `tools/executor_base.py` | 执行器接口 |
| ToolRegistry | `tools/registry.py` | 工具注册与发现 |
| EvalRunner | `runner/eval_runner.py` | 编排器（接受 adapter/judge 接口） |
| RunRecorder | `recorder/run_recorder.py` | 10 个 artifact 写入契约 |
| Artifact Schema | `artifact_schema.py` | schema_version + run_metadata |
| Signal Quality | `signal_quality.py` | 5 级信号质量枚举 |
| ToolDesignAuditor | `audit/tool_design_auditor.py` | 五类原则审计（不依赖 Agent runtime） |
| EvalQualityAuditor | `audit/eval_quality_auditor.py` | eval 结构完整性 |
| TranscriptAnalyzer | `diagnose/transcript_analyzer.py` | failure attribution（消费已记录事实） |
| TraceSignalAnalyzer | `diagnose/trace_signal_analyzer.py` | trace 信号分析 |
| MarkdownReport | `reports/markdown_report.py` | 报告渲染（消费 JSON artifact） |
| CostTracker | `reports/cost_tracker.py` | 成本聚合（不区分数据源） |
| ReportMetrics | `reports/report_insight.py` | 15 项聚合指标（v3.1） |
| MetricsCollector | `reports/report_insight.py` | ExecutionTrace + EvaluationResult → ReportMetrics（v3.1） |
| FindingGrouper | `reports/report_insight.py` | findings 按 severity/category/tool/rule 分桶（v3.1） |
| ReportScorecard | `reports/report_insight.py` | pass/fail + severity 分桶一览（v3.1） |
| RecommendationCatalog | `reports/report_insight.py` | 去重排序的可行动建议（v3.1） |
| ReportInsight | `reports/report_insight.py` | P1-P4 聚合根对象 + from_eval() 工厂（v3.1） |
| core_report_bridge | `core_report_bridge.py` | report_insight_to_json_dict() + task_outcome_to_json_dict() JSON 序列化（v3.1/v3.2） |
| EvalCase / ExpectedOutcome | `task_eval/eval_case.py` | 任务级评测用例 schema + YAML 加载（v3.2） |
| Verifier (5 + Composite) | `task_eval/verifiers.py` | 确定性任务验证器——子串/正则/JSON 子集/精确匹配（v3.2） |
| TaskOutcome / TaskEvaluator | `task_eval/task_evaluator.py` | 任务级评测聚合，3 级 final_answer 提取（v3.2） |
| Task Outcome Render | `task_eval/render.py` | render_task_outcome_markdown/text（v3.2） |

### Demo-only（假材料，教学和 smoke test）

| 模块 | 路径 | 说明 |
|------|------|------|
| MockReplayAdapter | `agents/mock_replay_adapter.py` | good/bad 分支回放 |
| TranscriptReplayAdapter | `agents/transcript_replay_adapter.py` | 历史轨迹重放 |
| RuleJudge | `judges/rule_judge.py` | deterministic baseline（Core 接口的 Demo 实现） |
| RuleJudgeProvider | `judges/provider.py` | RuleJudge 的 provider 包装 |
| RecordedJudgeProvider | `judges/provider.py` | fixture 回放 |
| CompositeJudgeProvider | `judges/provider.py` | 多 advisory 聚合 |
| JudgePromptAuditor | `audit/judge_prompt_auditor.py` | judge prompt 审计 |
| Bootstrap/Scaffold | `scaffold/` | AST 扫描生成 draft |
| FakeTransport | `judges/provider.py` | fake HTTP transport (CI safe) |
| examples/ | `examples/` | 教学样例数据 |

### Real Integration（已验证或 opt-in）

| 模块 | 路径 | 状态 |
|------|------|------|
| OpenAITransport | `openai_transport.py` | ✅ openai-compatible smoke verified (2026-05-14) |
| AnthropicTransport | `anthropic_transport.py` | ✅ anthropic-compatible smoke verified (2026-05-14) |
| LLMJudgeProvider | `llm_judge.py` | ✅ opt-in, fake-testable, rubric framework landed |
| JudgeProviderFactory | `judge_provider_factory.py` | ✅ 6 safety gates, SecretSource protocol |
| LiveAnthropicTransport (legacy) | `judges/provider.py` | superseded — replaced by `AnthropicTransport` |
| JudgeProvider Preflight | `judges/preflight.py` | ⚠️ local only, 不联网 |

> Real Integration 的 ProviderConfig、SecretSource、Transport、Factory 均已落地。
> RealAgentAdapter、EvidenceStore、ReviewWorkflow 当前**均未实现**（非 v3.0.0 scope）。

## 当前输出（10 个 artifact）

`run` 命令每次输出：`transcript.jsonl`, `tool_calls.jsonl`, `tool_responses.jsonl`,
`metrics.json`, `audit_tools.json`, `audit_evals.json`, `judge_results.json`,
`diagnosis.json`, `llm_cost.json`, `report.md`

其中 `llm_cost.json` 的 `estimated_cost_usd` 永远为 `null`，actual cost 永远为 `null`，
永远是 advisory-only，不是真实账单。

## 当前测试

- 60+ 个测试文件
- 1 个 strict xfail（钉住 deterministic 启发式根本限制）
- 覆盖：CLI / artifact / audit / judge / provider / report / report_insight / diagnose / scaffold / security / cost
- 所有 live transport 测试用 fake connection，CI 0 联网

## 当前不支持的能力

- 真实 LLM Agent 执行（无 `RealAgentAdapter`）
- 真实项目 runtime 接入（只有配置文件级 mock 接入）
- Web UI / MCP / HTTP / Shell executor
- RAG / 向量库
- 多租户 / 企业 RBAC
- Benchmark / Leaderboard
- `run` 命令硬编码 `MockReplayAdapter`，不支持注入自定义 AgentAdapter
- 无 Python SDK（`__init__.py` 只导出 `__version__`）

## v3.1.0 新增：Report Insight 层

v3.1.0 在 v3.0.0 基础上新增 **report-level insight**，5 个 Phase 全部落地：

| Phase | 组件 | 说明 |
|-------|------|------|
| P1 | MetricsCollector | 从 ExecutionTrace + EvaluationResult 计算 15 项聚合指标 |
| P2 | FindingGrouper | findings 按 severity / category / tool / rule_id_prefix 四维分桶 |
| P3 | ReportScorecard | pass/fail + error/warning/advisory 分桶计数 + top issues + top tools |
| P4 | RecommendationCatalog | 从 findings 去重生成可行动建议（what/why/how_to_fix） |
| P5 | ReportInsight Integration | 聚合 P1-P4 为 ReportInsight，注入 Markdown + JSON report |

所有组件 deterministic、零网络依赖。Markdown report 新增 6 个 insight section（Scorecard、Metrics、Top Issues、Findings by Severity、Findings by Tool、Recommendations）。JSON report 新增 8 个 top-level key。

详见 [`sdd/SDD_EVALUATION_REPORT_INSIGHT_V3_1.md`](sdd/SDD_EVALUATION_REPORT_INSIGHT_V3_1.md)。

## v3.2.0 新增：Task-level Evaluation

v3.2.0 在 v3.1.0 之上新增 **task-level evaluation**，5 个 Phase 全部落地：

| Phase | 组件 | 说明 |
|-------|------|------|
| P1 | EvalCase / ExpectedOutcome | 任务级评测用例 schema + YAML/dict 加载 |
| P2 | 5 + Composite Verifier | 确定性事实验证（子串/禁止/JSON 子集/精确/正则/组合） |
| P3 | TaskOutcome / TaskEvaluator | 3 级 final_answer 提取 + verifier 聚合 + success/failed/inconclusive |
| P4 | Task Outcome Report | Markdown section + JSON serialization + CLI one-liner |
| P5 | Examples | 3 个 sample eval case YAML |

所有 verifier 为 deterministic（零 LLM 依赖）。TaskOutcome.status 不影响 EvaluationResult.passed——两者回答不同层级的问题。

详见 [`sdd/SDD_TASK_LEVEL_EVALUATION_V3_2.md`](sdd/SDD_TASK_LEVEL_EVALUATION_V3_2.md)。

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
| Tool ergonomics evaluation | ✅ 6 deterministic rules + rubric | `ToolErgonomicsInspector` | — | — |
| Tool response quality checks | ✅ 6 deterministic rules + rubric | `ToolResponseQualityInspector` | — | — |
| Tool spec quality checks | ✅ 10 deterministic rules | `ToolSpecInspector` | — | — |
| Tool-use correctness checks | ✅ 9 deterministic rules | `ToolUseInspector` | — | — |
| Trace import diagnostics | ✅ 4 cap | `TraceDiagnostics` | — | — |
| 工具选择正确性评测 | ✅ rubric advisory | `ToolUseQualityJudge` (fake) | 真实 LLM judge 需 opt-in | — |
| LLM judge rubric framework | ✅ fake-testable 已实现 | `tool_use_quality_rubric.py` + `tool_use_quality_judge.py` | real LLM live execution 需 opt-in | `JudgeProvider` (LLM) |
| Provider cost / latency evidence | ❌ 未实现 | — | 需真实 API 调用 | `ProviderConfig` |

> 表格中的 ❌ 是 **knowingly not yet supported**，不是产品缺陷。这些能力在 BACKLOG.md P2/P3 中规划。

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
