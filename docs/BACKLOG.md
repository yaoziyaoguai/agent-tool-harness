# Backlog

## Current stage

**Headless CLI Agent Tool Harness Prototype**

当前不是：
- Real LLM evaluation platform
- Full real-agent runtime harness
- Web UI product
- Benchmark platform

项目当前 Demo Track（mock replay + deterministic checks）可用。Core Track
合约层已落地。Real Integration Track 中 TraceImportAdapter 已实现（native + simple mapping），
CLIAgentAdapter Slice 1+2 已实现。

三条 track 的边界定义见 [DEMO_CORE_REAL_BOUNDARY.md](DEMO_CORE_REAL_BOUNDARY.md)。

---

## Track A: Demo

> 只维护当前可跑 demo。目标是让 demo 作为教学样例稳定存在，不继续膨胀。
> Demo 可以复用 Core，但不能决定 Core 的设计。

### A1. README distinguishes demo, prototype, and future
- **Status**: in progress
- **Why**: 用户可能看到 9 个 ✅ 而忽视 10 个 ❌，误以为支持真实 LLM eval
- **Acceptance**: README 声明"当前不是真实 LLM Agent evaluation platform"
- **Not doing**: 不在 README 加冗长的能力边界列表

### A2. Mock replay not described as real eval
- **Status**: in progress
- **Why**: "mock replay — 预期 PASS/FAIL" 容易被理解为真实评测
- **Acceptance**: 所有 docs 明确区分 tool design audit（已实现）和 tool use evaluation（未实现）
- **Not doing**: 不修改 mock replay 行为

### A3. Bootstrap / scaffold UX hardening
- **Status**: not started
- **Why**: bootstrap 是新用户入口，从 AST 扫描生成 draft 的体验决定 first impression
- **Acceptance**: `bootstrap` 端到端时间 < 5s；生成的 REVIEW_CHECKLIST 覆盖关键检查点
- **Not doing**: 不让 scaffold 执行用户代码或联网

### A4. Demo ↔ Core dependency audit
- **Status**: not started
- **Why**: CLI 硬编码 MockReplayAdapter（`cli.py:1202`），违反 Core 不应依赖 Demo 的原则
- **Acceptance**: CLI 支持 `--adapter` 注入或 project.yaml 配置 adapter 类型
- **Not doing**: 不删除 MockReplayAdapter；不改变默认行为

### A5. examples/ 维护
- **Status**: not started
- **Why**: 6 个 example 目录需要保持与 Core contract 同步
- **Acceptance**: 所有 example 都能 `run --mock-path good` 通过
- **Not doing**: 不新增 example（除非 Core contract 变更引入新概念）

---

## Track B: Core / Harness

> 定义真实 Agent2Harness 的稳定契约。目标是让 Demo 和 Real 都走同一套 Core Flow。
> Core 不 import examples，不读 .env，不知道 OpenAI/Anthropic/DeepSeek。

### B1. Extract Core contracts as explicit layer
- **Status**: in progress (2026-05-11: main flow 端到端落地完成)
- **Why**: 当前 Core 对象和流程散落在各模块中，没有显式的"这里是 Core"标记
- **Acceptance**:
  - Core 模块清单文档化（见 CURRENT_IMPLEMENTATION.md 的模块分类）
  - Core Protocol 接口集中的 `core/` 或明确的模块内标注
  - [x] `core_contract.py` — 10 个运行时 dataclass + Agent2HarnessAdapter Protocol
  - [x] `AGENT2HARNESS_CORE_SPEC.md` — Core Spec 文档（10 节）
  - [x] `test_core_contract.py` — 19 个 contract test
  - [x] `demo_core_bridge.py` — 旧 Demo → Core Contract 桥接层（6 个映射函数）
  - [x] `test_demo_to_core_bridge.py` — 21 个 bridge 表征测试
  - [x] `agent2harness_adapter.py` — DemoAgent2HarnessAdapter + ReplayAgent2HarnessAdapter wrapper
  - [x] `core_evaluation.py` — CoreEvaluation（Evidence → EvaluationResult）
  - [x] `core_report_bridge.py` — EvaluationResult / ReportSummary → dict bridge
  - [x] `assembly.py` — build_demo_core_flow() + DemoCoreFlowResult
  - [x] `AGENT2HARNESS_MAIN_FLOW.md` — 主流程架构文档
  - [x] `test_agent2harness_main_flow.py` — 18 个集成测试
  - [ ] EvalRunner 消费 Core Contract（后续轮次）
  - [ ] RuleJudge 原生消费 Core Contract（后续轮次，删除反向桥接）
- **Not doing**: 不移动源码文件（除非必要）；不修改 Core 行为

### B2. AgentAdapter Protocol hardening
- **Status**: in progress (2026-05-11: Agent2HarnessAdapter Protocol defined, DemoAdapter wrapper implemented)
- **Why**: 当前 Protocol 只有一个 `run` 方法，未来真实 Agent 需要更丰富的 lifecycle
- **Acceptance**: AgentAdapter Protocol 扩展为支持：
  - [x] `SIGNAL_QUALITY` 声明（已有）
  - [x] `run(ScenarioSpec) → ExecutionTrace` 接口（Agent2HarnessAdapter Protocol + Demo/Replay wrapper 实现）
  - [ ] agentic loop 的 step-by-step observation（spec only）
  - [ ] 错误分类与部分结果返回（spec only）
- **Not doing**: 不实现 RealAgentAdapter

### B3. JudgeProvider Protocol hardening
- **Status**: in progress (2026-05-12: CoreJudgeProvider Protocol + FakeJudgeProvider + LLMJudgeProvider + CoreEvaluation 接入 + CLI 集成 landed)
- **Why**: 当前 Protocol 已定义，需要验证 contract test 覆盖和真实 LLM opt-in 路径
- **Acceptance**: JudgeProvider Protocol 的 contract test 覆盖所有已知 provider 实现
- **Not doing**: 不默认调用真实 LLM（必须显式 opt-in）
- [x] CoreJudgeProvider Protocol（`fake_judge.py`）
- [x] FakeJudgeProvider（11 个 contract tests）
- [x] JudgeFinding 数据类（`core_contract.py`）
- [x] CoreEvaluation 可选消费 JudgeProvider（Phase 2，12 个 tests）
- [x] RuleFinding + JudgeFinding 在 EvaluationResult 中并列
- [x] CLI `--judge-provider fake` + `--core-flow` 集成（Phase 3，2026-05-12）
  - [x] `--llm-config` / `--llm-provider` / `--dry-run-provider` CLI flags
  - [x] `load_provider_registry_from_file()` 文件加载入口
  - [x] `build_demo_core_flow()` / `_run_core_flow()` 接受 `judge_provider`
  - [x] 30 个新测试（12 file loading + 11 CLI flags + 7 integration）
- [x] CLI `--judge-provider llm` + `--live --confirm-i-have-real-key` 集成（Phase 4，2026-05-12）
  - [x] `openai_transport.py` — OpenAI-compatible HTTPS transport（19 tests）
  - [x] `anthropic_transport.py` — Anthropic-compatible HTTPS transport（15 tests）
  - [x] `llm_judge.py` — LLMJudgeProvider（CoreJudgeProvider 实现，11 tests）
  - [x] `judge_provider_factory.py` — 安全门控 factory（10 tests）
  - [x] CLI `--judge-provider llm` 接入 + 双标志 + config 校验（10 tests）
  - [x] 44 个新测试，691 全量测试通过
  - [x] 真实 LLM 默认不调用，必须显式 opt-in

### B4. ToolExecutor Protocol spec
- **Status**: not started
- **Why**: 当前只有 PythonExecutor，MCP/HTTP/Shell 未定义
- **Acceptance**: ToolExecutor Protocol 定义完整执行器接口
- **Not doing**: 不实现 MCP/HTTP/Shell executor

### B5. ProviderConfig spec
- **Status**: done (2026-05-12: LLM provider config model landed)
- **Why**: 模型选择 / cost / latency 可观测需要标准化配置
- **Acceptance**: ProviderConfig 定义 model / API key / base URL / budget 的配置格式
- **Not doing**: 不实现真实 API 调用（配置只存 env var name，不存 key）
- [x] ProviderFamily / ProviderCompatibility enum
- [x] LLMProviderConfig dataclass（四类 provider）
- [x] LLMProviderRegistry（按 name 查找 + 校验）
- [x] resolve_api_key()（唯一读取 os.environ 的入口）
- [x] load_provider_registry()（从 YAML dict 加载）
- [x] inline api_key 显式拒绝
- [x] ConfigValidationError + MissingApiKeyError
- [x] 19 个 config 测试
- [x] 示例 YAML 配置（`examples/llm_providers.example.yaml`）

### B6. EvidenceStore spec
- **Status**: not started
- **Why**: 10 个 artifact 的写入契约需要升级为结构化证据存储
- **Acceptance**: EvidenceStore Protocol 定义证据的存储 / 查询 / 追溯接口
- **Not doing**: 不替换当前 RunRecorder

### B7. Core contract tests
- **Status**: in progress (2026-05-11: 58 tests across 3 test files)
- **Why**: 当前没有显式的"这是 contract test"标记
- **Acceptance**:
  - 所有 Protocol 有对应的 contract test（测试接口而非实现）
  - Contract tests 在 CI 中跑（0 联网）
  - [x] Agent2HarnessAdapter Protocol 的 contract test（19 个）
  - [x] Demo-to-Core bridge 表征测试（21 个）
  - [x] Agent2Harness main flow 集成测试（18 个）
  - [x] 所有 Core dataclass 的 immutability / 聚合测试
  - [x] Core 不 import demo/cli/provider 的 forbidden dependency 测试
  - [ ] JudgeProvider Protocol contract test（后续轮次）
  - [ ] ToolExecutor Protocol contract test（后续轮次）
- **Not doing**: 不替换现有测试

### B8. Forbidden dependency tests
- **Status**: in progress (2026-05-11: AST-based dependency check in test_core_contract.py)
- **Why**: 当前没有自动化检查 Core 是否依赖了 Demo 或 Real
- **Acceptance**: 测试验证：
  - [x] Core 模块不 import `examples/`
  - [x] Core 模块不 import `mock_replay_adapter`
  - [x] Core 模块不 import `LiveAnthropicTransport`
  - [x] Core 模块不读取 `.env`
  - [ ] 扩展到所有 config/ 模块（后续轮次）
- **Not doing**: 不修改现有 import 结构（先检测，后修复）

---

## Track C: Real Integration (active, 设计阶段)

> 真实世界接入。所有 Real 组件通过 Protocol 接口接入 Core，不修改 Core。
> 必须显式 opt-in。
> **当前状态**: 设计阶段。TraceImportAdapter 已完成，CLIAgentAdapter Slice 1+2 已完成。
> 详见 [REAL_AGENT_INTEGRATION_SDD.md](REAL_AGENT_INTEGRATION_SDD.md)。

### C1. Opt-in safety model spec
- **Status**: done (2026-05-12: safety model documented in LLM_PROVIDER_CONFIG.md)
- **Why**: 真实 LLM 调用需要双标志 + env var 的安全模型
- **Acceptance**: `--live --confirm-i-have-real-key` 安全模型在 LLM_PROVIDER_CONFIG.md 中定义
- **Not doing**: 不实现真实 API 调用
- [x] 9 条安全规则文档化
- [x] parse config ≠ 读取 key
- [x] 禁止 inline api_key
- [x] 不自动 load_dotenv
- [x] 测试默认只使用 fake provider

### C2. Fake JudgeProvider first
- **Status**: done (2026-05-12: FakeJudgeProvider + CoreJudgeProvider Protocol landed)
- **Why**: 在接真实 LLM judge 之前，先用 fake provider 验证 JudgeProvider 接口
- **Acceptance**: FakeJudgeProvider 通过 JudgeProvider Protocol 的所有 contract tests
- **Not doing**: 不接真实 LLM
- [x] CoreJudgeProvider Protocol（`evaluate(Evidence) → list[JudgeFinding]`）
- [x] FakeJudgeProvider（deterministic preset responses）
- [x] 9 个 contract tests（全部通过）
- [x] JudgeFinding ≠ ReviewDecision 边界测试

### C3. RealAgentAdapter skeleton
- **Status**: redesigned → split into C8 (TraceImportAdapter) + C9 (CLIAgentAdapter)
- **Why**: 单一大适配器无法覆盖"导入已有 trace"和"运行 CLI Agent"两种不同场景。拆分为两个独立模块。
- **Acceptance**: 见 C8 / C9
- **Not doing**: 不实现单一大 RealAgentAdapter

### C4. Real provider opt-in
- **Status**: done (2026-05-12: transport + factory + CLI wiring landed; infrastructure & safety gates verified; semantic judge parsing pending debug)
- **Why**: 真实 LLM 评估需要安全模型和配置标准化
- **Acceptance**: opt-in 真实 LLM dogfood 完成一次端到端闭环 (DOGFOOD_REAL_LLM_001.md)
- **Not doing**: 不作为默认行为
- [x] openai_transport.py + anthropic_transport.py
- [x] llm_judge.py + judge_provider_factory.py
- [x] --live --confirm-i-have-real-key + --env-file / --allow-os-env
- [x] 真实 dogfood 已验证

### C5. Cost / latency evidence capture
- **Status**: **deferred** — 推迟到 Real Agent Integration 落地之后。先让真实 trace 跑通 Core Flow，再加成本预算。
- **Why**: 成本追踪需要真实 provider 调用量积累才有意义，在 trace import / CLI agent 未落地时无有效数据源
- **Acceptance**: llm_cost.json 的 estimated_cost_usd 不再永远为 null
- **Not doing**: 当前不假装有真实成本数据

### C6. Combining deterministic checks + LLM judge output
- **Status**: done (2026-05-12: CoreEvaluation judge_provider 接入; passed 仍由 RuleJudge 决定, JudgeFinding 为 advisory)
- **Why**: RuleJudge 和 LLM judge 应该是互补的，不是替代的
- **Acceptance**: RuleFinding + JudgeFinding 在 EvaluationResult 中并列
- **Not doing**: 不让 LLM judge 替代 rule checks

### C7. LiveAnthropicTransport verification or removal
- **Status**: not started
- **Why**: v1.3 起存在的未验证代码，如果继续不验证也不删除，会误导新贡献者
- **Acceptance**: 要么验证通过（对真实端点），要么删除并用 FakeTransport 替代
- **Not doing**: 不保留"代码存在但未验证"的灰色状态

### C8. TraceImportAdapter
- **Status**: **native + simple mapping 已实现** (2026-05-12: `agent_tool_harness/trace_import.py`, 83 tests)
- **Why**: 用户已有 trace 文件需要导入为 Agent2Harness ExecutionTrace，不运行 Agent
- **Acceptance**:
  - [x] native mode: 直接导入 ExecutionTrace JSON
  - [x] simple mapping mode: `SimpleMappingConfig` 字段映射（Phase B done）
  - [x] 完整校验 + 明确错误信息
  - [x] 不猜测/不修复/不 LLM 解析
- **Not doing**: 不做复杂 JSONPath DSL（第一版），不自动推断格式，不新增 CLI entry
- **Phase**: A (native) ✅ → B (simple mapping) ✅

### C9. CLIAgentAdapter
- **Status**: **Slice 1+2 已实现** (2026-05-13: `agent_tool_harness/cli_agent.py`, 51 tests)
- **Why**: 通过 CLI 命令运行用户 Agent，复用 TraceImportAdapter 解析 trace
- **Acceptance**:
  - [x] Slice 1: command list[str] 校验 + 占位符检查 + working_dir 校验
  - [x] Slice 1: ScenarioSpec → input file + 受控 trace output path
  - [x] Slice 1: prepare_run() 生成 CLIAgentPreparedRun 执行计划
  - [x] Slice 2: subprocess 执行 + timeout + env policy + truncation
  - [x] Slice 3: TraceImportAdapter 解析 trace → ExecutionTrace + Evidence
  - [ ] Slice 4: assembly 集成
- **Not doing**: 不自己解析复杂 trace, 不自动读取 .env
- **Phase**: Slice 1 ✅ → Slice 2 ✅ → Slice 3 ✅ → Slice 4 pending

### C10. Real agent dogfood (local project)
- **Status**: **blocked** (needs C8 + C9)
- **Why**: 在 TraceImportAdapter + CLIAgentAdapter 实现后，用本地真实 Agent 项目验证
- **Acceptance**: 一次完整评测闭环：ScenarioSpec → 真实 Agent trace → ExecutionTrace → CoreEvaluation → Report
- **Not doing**: 不做 benchmark, 不发布结果

---

## Explicit non-goals for now

- No Web UI
- No MCP executor
- No HTTP / Shell executor
- No RAG / vector database
- No automatic production benchmark
- No default real API calls
- No hidden .env reading
- No cost tracking (deferred to after Real Agent Integration)
- No latency tracking (deferred to after Real Agent Integration)
- No multi-tenant / enterprise RBAC
- No Python SDK

---

## Track dependency rules

```
Track B (Core)  ←  Track A (Demo) 可以依赖 Core，反之禁止
Track B (Core)  ←  Track C (Real) 可以依赖 Core，反之禁止
Track A (Demo)  ←/→  Track C (Real)  互相禁止依赖
```

- Core 不 import examples
- Core 不读取 .env
- Core 不知道 OpenAI / Anthropic / DeepSeek
- Core 不散落 if demo / if real 分支
- Demo 可以复用 Core，但 Core 不迁就 Demo
- Real 可以复用 Core，但 Core 不依赖 Real
