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
| B3 | JudgeProvider Protocol 硬化 | in progress (CoreJudgeProvider + FakeJudgeProvider + CLI 集成 landed 2026-05-12) |
| B4 | ToolExecutor Protocol spec | not started |
| B5 | ProviderConfig spec | done (2026-05-12: llm_config.py landed) |
| B6 | EvidenceStore spec | not started |
| B7 | Core contract tests | in progress (61+ tests across 6 test files) |
| B8 | Forbidden dependency tests | in progress (AST-based check) |

**Track B/C 最新进展（2026-05-12）：** LLM provider 配置模型 + Fake Judge 基础 +
CoreEvaluation JudgeProvider 接入 + CLI 集成落地完成。Phase 3：新增
`--judge-provider fake`（配合 `--core-flow`）、`--llm-config` / `--llm-provider` /
`--dry-run-provider` CLI flags、`load_provider_registry_from_file()` 文件加载。
`build_demo_core_flow()` / `_run_core_flow()` 接受 `judge_provider` 参数。
新增 30 个测试（12 file loading + 11 CLI flags + 7 integration）。
616 全量测试通过。
passed 仍由 RuleJudge 决定，JudgeFinding 仅作为辅助信号。
新增 `llm_config.py`（LLMProviderConfig + Registry + resolve_api_key）、
`fake_judge.py`（CoreJudgeProvider Protocol + FakeJudgeProvider）、
`core_contract.py` 新增 JudgeFinding 数据类、`examples/llm_providers.example.yaml`、
`docs/LLM_PROVIDER_CONFIG.md` 设计文档。新增 30 个测试（19 config + 11 fake judge）。
真实 LLM 仍默认不调用。

**Track B 进展（2026-05-11）：** Agent2Harness main flow 端到端落地完成。
新增 4 个模块（`agent2harness_adapter.py`, `core_evaluation.py`, `core_report_bridge.py`,
`assembly.py` 扩展），新增 3 个文档（`AGENT2HARNESS_MAIN_FLOW.md` + 2 个更新），
新增 18 个集成测试（`test_agent2harness_main_flow.py`）。完整 Core Flow 链路已验证：
ScenarioSpec → ExecutionTrace → Evidence → CoreEvaluation → EvaluationResult → ReportSummary，
ReviewDecision 由人工显式创建。详见 [AGENT2HARNESS_MAIN_FLOW.md](AGENT2HARNESS_MAIN_FLOW.md)、
[AGENT2HARNESS_CORE_SPEC.md](AGENT2HARNESS_CORE_SPEC.md)、
[DEMO_TO_CORE_MIGRATION.md](DEMO_TO_CORE_MIGRATION.md)。

### Track C: Real Integration（future，全部 blocked）

| ID | 事项 | 状态 |
|----|------|------|
| C1 | Opt-in 安全模型 spec | done (LLM_PROVIDER_CONFIG.md 2026-05-12) |
| C2 | Fake JudgeProvider 先行验证 | done (2026-05-12: fake_judge.py + 9 tests) |
| C3 | RealAgentAdapter skeleton | blocked (needs B2 + C1) |
| C4 | Real provider opt-in | blocked (needs B5 + C1) |
| C5 | Cost / latency evidence capture | blocked (needs B5 + C4) |
| C6 | Deterministic + LLM judge 组合 | blocked (needs B3 + C4) |
| C7 | LiveAnthropicTransport 验证或删除 | not started |

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
