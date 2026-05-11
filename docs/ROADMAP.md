# Roadmap

## 设计原则

1. **离线优先** — 默认不联网、不需要 API Key，任何需要网络的能力必须 opt-in
2. **确定性优先** — 优先用确定性规则解决问题，LLM 是最后手段
3. **证据驱动** — 每一步产出结构化 artifact，可追溯、可复现
4. **接口隔离** — rule checks ≠ LLM judge，mock replay ≠ RealAgentAdapter
5. **诚实声明** — signal_quality 必须在每次 run 输出中显式披露
6. **范围可控** — 新功能通过独立模块 + Protocol 接口实现，不往现有模块塞逻辑

## 当前阶段：Headless CLI Demo Prototype

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
- [x] 58 个测试文件
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
| B1 | 提取 Core contracts 为显式层 | in progress (2026-05-11) |
| B2 | AgentAdapter Protocol 硬化 | in progress (Agent2HarnessAdapter defined) |
| B3 | JudgeProvider Protocol 硬化 | not started |
| B4 | ToolExecutor Protocol spec | not started |
| B5 | ProviderConfig spec | not started |
| B6 | EvidenceStore spec | not started |
| B7 | Core contract tests | in progress (19 tests) |
| B8 | Forbidden dependency tests | in progress (AST-based check) |

**Track B 最新进展（2026-05-11）：** `agent_tool_harness/core_contract.py` 新增 10 个
Core dataclass + Agent2HarnessAdapter Protocol，`docs/AGENT2HARNESS_CORE_SPEC.md` 定义
完整 Core Spec（10 节），`tests/test_core_contract.py` 含 19 个 contract test。
详见 commit 记录和 [AGENT2HARNESS_CORE_SPEC.md](AGENT2HARNESS_CORE_SPEC.md)。

### Track C: Real Integration（future，全部 blocked）

| ID | 事项 | 状态 |
|----|------|------|
| C1 | Opt-in 安全模型 spec | not started |
| C2 | Fake JudgeProvider 先行验证 | not started |
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
