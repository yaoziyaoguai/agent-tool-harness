# Roadmap

## 设计原则

1. **离线优先** — 默认不联网、不需要 API Key，任何需要网络的能力必须 opt-in
2. **确定性优先** — 优先用确定性规则解决问题，LLM 是最后手段
3. **证据驱动** — 每一步产出结构化 artifact，可追溯、可复现
4. **接口隔离** — rule checks ≠ LLM judge，mock replay ≠ RealAgentAdapter
5. **诚实声明** — signal_quality 必须在每次 run 输出中显式披露
6. **范围可控** — 新功能通过独立模块 + Protocol 接口实现，不往现有模块塞逻辑
7. **工具优先** — 核心价值在 tool-use inspection，不在运行 Agent。对齐 [Anthropic effective tools](https://www.anthropic.com/engineering/writing-tools-for-agents)。

## 当前阶段：Agent2Harness Main Flow Landing

**已完成：**
- [x] 14 个 CLI 子命令
- [x] Config Loader（YAML → Spec）
- [x] MockReplayAdapter（good/bad 分支）
- [x] TranscriptReplayAdapter（历史轨迹重放）
- [x] RuleJudge（deterministic 规则）
- [x] ToolDesignAuditor（启发式）
- [x] MarkdownReport（10 artifact + report.md）
- [x] CostTracker（advisory-only）
- [x] TraceSignalAnalyzer（5 类 deterministic 信号）
- [x] TranscriptAnalyzer（failure attribution）
- [x] Bootstrap/Scaffold（AST 扫描生成 draft）
- [x] Core Contract（10 个 dataclass + Agent2HarnessAdapter Protocol）
- [x] Demo-to-Core Bridge（6 个桥接函数）
- [x] Agent2HarnessAdapter Wrapper（DemoAgent2HarnessAdapter + ReplayAgent2HarnessAdapter）
- [x] CoreEvaluation（Evidence → EvaluationResult 编排层）
- [x] Core Report Bridge（EvaluationResult / ReportSummary → dict）
- [x] Assembly Core Flow（build_demo_core_flow() 端到端入口）
- [x] Agent2Harness Main Flow 集成测试（18 个）
- [x] 58+ 个测试文件
- [x] 6 个可运行 example
- [x] **v3.1.0 Report Insight** — MetricsCollector (P1), FindingGrouper (P2), ReportScorecard (P3), RecommendationCatalog (P4), ReportInsight Integration (P5) — 全部落地（2026-05-15）

**当前 signal_quality 上限：** `tautological_replay`（mock replay）和
`recorded_trajectory`（transcript replay）。这些不是真实 Agent 能力信号。

**当前阶段：v3.1.0 Report Insight（2026-05-15）**
v3.1.0 在 v3.0.0 的 deterministic inspection 之上新增 report-level insight 层。
Scorecard、Metrics、Grouped Findings、Recommendations 自动注入 Markdown + JSON report。
所有组件 deterministic、零网络依赖、不修改 v3.0 Core Contract 对象。

**历史阶段：TraceImportAdapter（唯一接入路径）**（2026-05-12）
用户可通过 `trace JSON → TraceImportAdapter → ExecutionTrace → Evidence → CoreEvaluation → Report` 导入已有 trace。
native 和 simple mapping 两种模式均已可用。agent-tool-harness 不运行 Agent。
推荐工作流：外部 runner → trace/log → TraceImportAdapter → CoreEvaluation → Report → Human Review。

## 下一步（按四条 Track 组织）

三条 Track 的边界定义见 [DEMO_CORE_REAL_BOUNDARY.md](architecture/DEMO_CORE_REAL_BOUNDARY.md)。
**Track D (Tool-Use Inspection)** 为新增——后续核心方向。
Backlog 详见 [BACKLOG.md](BACKLOG.md)。

### Track A: Demo（当前可跑，维护不膨胀）

| ID | 事项 | 状态 |
|----|------|------|
| A1 | README 区分 demo / prototype / future | done (2026-05-14) |
| A2 | Mock replay 不被描述为 real eval | done (2026-05-14) |
| A3 | Bootstrap / scaffold UX 硬化 | not started |
| A4 | Demo ↔ Core 依赖审计（CLI 硬编码解耦） | done (2026-05-11) |
| A5 | examples/ 维护与 contract 同步 | not started |

### Track B: Core / Harness（定义契约，当前优先）

| ID | 事项 | 状态 |
|----|------|------|
| B1 | 提取 Core contracts 为显式层 | in progress (main flow landed 2026-05-11) |
| B2 | AgentAdapter Protocol 硬化 | in progress (Agent2HarnessAdapter + wrapper landed) |
| B3 | JudgeProvider Protocol 硬化 | in progress (CoreJudgeProvider + FakeJudgeProvider + LLMJudgeProvider + CLI 集成 landed 2026-05-12) |
| B4 | ToolExecutor Protocol spec | not started |
| B5 | ProviderConfig spec | done (2026-05-12: llm_config.py landed) |
| B6 | EvidenceStore spec | not started |
| B7 | Core contract tests | in progress (81+ tests across 11 test files) |
| B8 | Forbidden dependency tests | in progress (AST-based check) |

**Track B/C 最新进展（2026-05-13）：**

**Real LLM infrastructure & safety gate** 已验证通过（`docs/archive/DOGFOOD_REAL_LLM_001.md`）。
openai-compatible + anthropic-compatible transport + factory wiring + --env-file secret loading 均已跑通。
Response parsing normalization layer 已修复（处理 7 种 compatible provider response shapes）。
Semantic JudgeFinding verified via real LLM smoke (2026-05-14).
TraceImportAdapter 不受此影响。

**Real Agent Integration SDD** 进入实现阶段（`docs/architecture/REAL_AGENT_INTEGRATION_SDD.md`）。
TraceImportAdapter spec 已完成。（CLIAgentAdapter 已移除，runner responsibility 移至外部。）

**Track B 进展（2026-05-13）：** Agent2Harness main flow 端到端落地完成。
新增 4 个模块（`agent2harness_adapter.py`, `core_evaluation.py`, `core_report_bridge.py`,
`assembly.py` 扩展），新增 3 个文档（`architecture/AGENT2HARNESS_MAIN_FLOW.md` + 2 个更新），
新增 18 个集成测试（`test_agent2harness_main_flow.py`）。完整 Core Flow 链路已验证：
ScenarioSpec → ExecutionTrace → Evidence → CoreEvaluation → EvaluationResult → ReportSummary，
ReviewDecision 由人工显式创建。详见 [AGENT2HARNESS_MAIN_FLOW.md](architecture/AGENT2HARNESS_MAIN_FLOW.md)、
[AGENT2HARNESS_CORE_SPEC.md](architecture/AGENT2HARNESS_CORE_SPEC.md)、
[DEMO_TO_CORE_MIGRATION.md](archive/DEMO_TO_CORE_MIGRATION.md)。

### Track C: Real Integration（active，实现阶段）

| ID | 事项 | 状态 |
|----|------|------|
| C1 | Opt-in 安全模型 spec | done (LLM_PROVIDER_CONFIG.md 2026-05-12) |
| C2 | Fake JudgeProvider 先行验证 | done (2026-05-12: fake_judge.py + 9 tests) |
| C3 | RealAgentAdapter skeleton | redesigned → C8/C9 trace import + CLI agent adapter |
| C4 | Real provider opt-in | done (2026-05-14: transport + factory + CLI wiring landed; normalization layer fixed; both openai-compatible + anthropic-compatible real LLM smoke verified) |
| C5 | Cost / latency evidence capture | **deferred** (推迟到 Real Agent Integration 之后——先让 trace 跑通，再加成本预算) |
| C6 | Deterministic + LLM judge 组合 | done (2026-05-12: CoreEvaluation judge_provider 接入; passed 仍由 RuleJudge 决定, JudgeFinding 为 advisory) |
| C7 | LiveAnthropicTransport 验证或删除 | superseded — legacy transport replaced by `openai_transport.py` + `anthropic_transport.py` (both verified via real LLM smoke) |
| C8 | **TraceImportAdapter（唯一接入路径）** | **native + simple mapping done** (2026-05-12: trace_import.py + 83 tests) |
| C9 | **CLIAgentAdapter** | **removed** (2026-05-13: agent-tool-harness 不再运行 Agent) |
| C10 | **Real agent dogfood** | **Level 4A done, Level 4B deferred** (2026-05-13) |

### Track D: Tool-Use Inspection（后续核心方向，spec 已定义）

> 对齐 Anthropic《Writing effective tools for agents — with agents》。
> 核心价值在 tool-use logs 检查与工具质量评测。详见 [TOOL_USE_INSPECTION_SDD.md](architecture/TOOL_USE_INSPECTION_SDD.md)。

| ID | 事项 | 状态 |
|----|------|------|
| D1 | **Trace import diagnostics** (Module 1) | 🟢 done (2026-05-13) — mapping field coverage + type diagnostics + trace confidence + dry-run (48 tests) |
| D2 | **Tool-use correctness checks** (Module 2) | 🟢 9 trace-level invariant rules done (2026-05-13) — `tool_inspection.py`: call_id duplicate, orphan call/result, arguments present/type, tool_name non-empty, status valid。集成到 CoreEvaluation。其余 (fallback/retry/grounding/order) deferred。 |
| D3 | **Tool metrics** (Module 3) | post-v3 future — error rate, redundancy, response size, latency |
| D4 | **Tool ergonomics evaluation** (Module 4) | 🟢 6 deterministic rules + LLM advisory rubric done (2026-05-14) — `tool_ergonomics.py`: 6 deterministic rules (all WARNING)。`tool_use_quality_rubric.py` + `tool_use_quality_judge.py`: 4 D4 LLM advisory rubric dimensions (tool_choice_reasonableness, tool_too_low_level, frequently_chained_tools, missing_domain_tool)。Fake judge with deterministic heuristics。 |
| D5 | **Tool response quality** (Module 5) | 🟢 6 deterministic rules + LLM advisory rubric done (2026-05-14) — `tool_response_quality.py`: 6 rules (2 ERROR + 4 WARNING)。`tool_use_quality_rubric.py` + `tool_use_quality_judge.py`: 2 D5 LLM advisory rubric dimensions (missing_fields_for_next_call, final_answer_faithfulness)。Fake judge with deterministic heuristics。 |
| D6 | **Tool spec quality** (Module 6) | 🟢 10 deterministic rules done (2026-05-13) — `tool_spec_inspection.py`: description.exists, description.useful_length, input_schema.exists, parameter.name.explicit, required_parameter.documented, output_contract.documented, side_effects.documented, when_to_use.documented, when_not_to_use.documented, token_policy.defined。CoreEvaluation 集成。examples/auth/response_format deferred（ToolSpec schema 不支持）。|
| D7 | **Batch / multi-trace evaluation** | post-v3 future |
| D8 | **Human review UX** | post-v3 future |

**实现顺序：** Phase 1 (D1 foundation + D2 trace-level 部分完成) → Phase 2 (D4+D5+D6 deterministic hints + LLM judge advisory rubric)。D2 剩余规则 (fallback/retry/grounding/order/argument validity) 在后续轮次实现。

**Track C 最新进展（2026-05-13）：** CLIAgentAdapter 已移除。TraceImportAdapter 为唯一接入路径。
用户可通过 `trace_import.py` 以 native 或 simple_mapping 模式导入 trace JSON，进入 Core Flow。

**Track D 最新进展（2026-05-14）：** D1/D2/D4/D5/D6 all landed — 37 deterministic rules across 5 inspectors。
Phase 2 LLM judge rubric framework 已落地：`tool_use_quality_rubric.py`（6 rubric dimensions + build_rubric_prompt）+ `tool_use_quality_judge.py`（ToolUseQualityJudge fake implementation，6 heuristic checks producing rubric-aware JudgeFinding），57 tests。所有 JudgeFinding advisory only，不影响 passed。
Post-v3 future work (metrics, batch evaluation, review UX) documented in BACKLOG.

详见 [REAL_AGENT_INTEGRATION_SDD.md](architecture/REAL_AGENT_INTEGRATION_SDD.md)、
[TOOL_USE_INSPECTION_SDD.md](architecture/TOOL_USE_INSPECTION_SDD.md)。

## 明确不做

以下能力当前明确不做（除非未来独立设计并经过审批）：

- Web UI
- MCP executor
- HTTP / Shell executor
- RAG / 向量库
- 多租户 / 企业 RBAC
- Benchmark / Leaderboard 平台
- Python SDK（`__init__.py` 只导出版本号）
- 跨语言工具支持（当前 Python only）
- 把 rule checks 升级成 LLM judge 巨石
- 把 mock replay 升级成 RealAgentAdapter 巨石
- reporter 自动做通过/不通过决策
- 自动 optimizer（不改 tool spec、不改 Agent prompt、不自动重跑 Agent）
- Level 4B target-agent self real provider dogfood
- 运行真实 Agent（agent-tool-harness 不负责 Agent 运行时）
- 为每个 Agent 写专用 wrapper
