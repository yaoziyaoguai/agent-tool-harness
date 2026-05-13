# Roadmap

## 设计原则

1. **离线优先** — 默认不联网、不需要 API Key，任何需要网络的能力必须 opt-in
2. **确定性优先** — 优先用确定性规则解决问题，LLM 是最后手段
3. **证据驱动** — 每一步产出结构化 artifact，可追溯、可复现
4. **接口隔离** — rule checks ≠ LLM judge，mock replay ≠ RealAgentAdapter
5. **诚实声明** — signal_quality 必须在每次 run 输出中显式披露
6. **范围可控** — 新功能通过独立模块 + Protocol 接口实现，不往现有模块塞逻辑

## 当前阶段：Agent2Harness Main Flow Landing

**已完成：**
- [x] 13 个 CLI 子命令
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

**当前 signal_quality 上限：** `tautological_replay`（mock replay）和
`recorded_trajectory`（transcript replay）。这些不是真实 Agent 能力信号。

**当前阶段：TraceImportAdapter native + simple mapping**（2026-05-12）
用户可通过 `trace JSON → TraceImportAdapter → ExecutionTrace → Evidence → CoreEvaluation → Report` 导入已有 trace。
native 和 simple mapping 两种模式均已可用。下一步是 CLIAgentAdapter（Phase C）。

## 下一步（按三条 Track 组织）

三条 Track 的边界定义见 [DEMO_CORE_REAL_BOUNDARY.md](DEMO_CORE_REAL_BOUNDARY.md)。
Backlog 详见 [BACKLOG.md](BACKLOG.md)。

### Track A: Demo（当前可跑，维护不膨胀）

| ID | 事项 | 状态 |
|----|------|------|
| A1 | README 区分 demo / prototype / future | in progress |
| A2 | Mock replay 不被描述为 real eval | in progress |
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

**Track B/C 最新进展（2026-05-12）：**

**Real LLM infrastructure & safety gate** 已验证通过（`docs/DOGFOOD_REAL_LLM_001.md`）。
openai-compatible transport + factory wiring + --env-file secret loading 均已跑通。
Semantic JudgeFinding 因 provider response parsing bad_response 尚未成功产出，
待后续调试。TraceImportAdapter / CLIAgentAdapter 不受此影响。

**Real Agent Integration SDD** 进入设计阶段（`docs/REAL_AGENT_INTEGRATION_SDD.md`）。
TraceImportAdapter + CLIAgentAdapter spec 已完成。

**Track B 进展（2026-05-11）：** Agent2Harness main flow 端到端落地完成。
新增 4 个模块（`agent2harness_adapter.py`, `core_evaluation.py`, `core_report_bridge.py`,
`assembly.py` 扩展），新增 3 个文档（`AGENT2HARNESS_MAIN_FLOW.md` + 2 个更新），
新增 18 个集成测试（`test_agent2harness_main_flow.py`）。完整 Core Flow 链路已验证：
ScenarioSpec → ExecutionTrace → Evidence → CoreEvaluation → EvaluationResult → ReportSummary，
ReviewDecision 由人工显式创建。详见 [AGENT2HARNESS_MAIN_FLOW.md](AGENT2HARNESS_MAIN_FLOW.md)、
[AGENT2HARNESS_CORE_SPEC.md](AGENT2HARNESS_CORE_SPEC.md)、
[DEMO_TO_CORE_MIGRATION.md](DEMO_TO_CORE_MIGRATION.md)。

### Track C: Real Integration（active，设计阶段）

| ID | 事项 | 状态 |
|----|------|------|
| C1 | Opt-in 安全模型 spec | done (LLM_PROVIDER_CONFIG.md 2026-05-12) |
| C2 | Fake JudgeProvider 先行验证 | done (2026-05-12: fake_judge.py + 9 tests) |
| C3 | RealAgentAdapter skeleton | redesigned → C8/C9 trace import + CLI agent adapter |
| C4 | Real provider opt-in | done (2026-05-12: openai_transport.py + anthropic_transport.py + factory + CLI wiring landed) |
| C5 | Cost / latency evidence capture | **deferred** (推迟到 Real Agent Integration 之后——先让 trace 跑通，再加成本预算) |
| C6 | Deterministic + LLM judge 组合 | done (2026-05-12: CoreEvaluation judge_provider 接入; passed 仍由 RuleJudge 决定, JudgeFinding 为 advisory) |
| C7 | LiveAnthropicTransport 验证或删除 | not started (legacy LiveAnthropicTransport 保持不动，新 transport 独立) |
| C8 | **TraceImportAdapter** | **native + simple mapping done** (2026-05-12: trace_import.py + 83 tests) |
| C9 | **CLIAgentAdapter** | **Slice 1+2+3+4 done** (config + subprocess + trace import + assembly integration, 97 tests) |
| C10 | **Real agent dogfood (本地项目)** | **Level 1+2 done** (2026-05-13: fake + toy CLI agent dogfood, 12 smoke tests) |

**Track C 最新进展（2026-05-13）：** CLIAgentAdapter Slice 4 完成——assembly 集成落地。
`build_cli_agent_core_flow()` 实现端到端闭环：ScenarioSpec → CLIAgentAdapter → fake CLI agent
→ trace file → TraceImportAdapter → ExecutionTrace → Evidence → CoreEvaluation →
EvaluationResult → ReportSummary。新增 21 个集成测试 + fake CLI agent example。
Demo 路径（`build_demo_core_flow()`）未受影响，零回归（948 passed）。

用户可通过 `trace_import.py` 以 native 或 simple_mapping 模式导入 trace JSON，进入 Core Flow：

```
trace JSON → TraceImportAdapter → ExecutionTrace → Evidence → CoreEvaluation → Report
```

详见 [REAL_AGENT_INTEGRATION_SDD.md](REAL_AGENT_INTEGRATION_SDD.md)、
[TRACE_IMPORT_ADAPTER_SPEC.md](TRACE_IMPORT_ADAPTER_SPEC.md)、
[CLI_AGENT_ADAPTER_SPEC.md](CLI_AGENT_ADAPTER_SPEC.md)。

**实现顺序：** Phase A (TraceImportAdapter native) → Phase B (Simple mapping) → Phase C (CLIAgentAdapter) → Phase D (集成) → Phase E (real dogfood)。成本追踪明确推到 later。

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
