# Agent2Harness Main Flow

> 本文档定义 Agent Tool Harness 的 **Agent2Harness 主流程**——
> 从 ScenarioSpec 到 Human Review 的完整 Core Flow。
> 这是后续所有实现工作的依据文档。

---

## 1. 当前阶段判断

| 组件 | 状态 | 位置 |
|------|------|------|
| Demo（MockReplayAdapter） | ✅ 可跑 | `agents/mock_replay_adapter.py` |
| Demo（TranscriptReplayAdapter） | ✅ 可跑 | `agents/transcript_replay_adapter.py` |
| CLI（13 子命令） | ✅ 可跑 | `cli.py` + `assembly.py` |
| RuleJudge（deterministic） | ✅ 可跑 | `judges/rule_judge.py` |
| EvalRunner（旧编排器） | ✅ 可跑 | `runner/eval_runner.py` |
| MarkdownReport（旧 reporter） | ✅ 可跑 | `reports/markdown_report.py` |
| Core Contract 对象 | ✅ 已定义 | `core_contract.py`（10 dataclass + 1 Protocol） |
| Core Contract tests | ✅ 19 个 | `tests/test_core_contract.py` |
| Demo → Core bridge | ✅ 已实现 | `demo_core_bridge.py`（5 个映射函数） |
| Bridge tests | ✅ 21 个 | `tests/test_demo_to_core_bridge.py` |
| **Main Flow 端到端落地** | ✅ 已完成（2026-05-11） | `assembly.py` + `cli.py` |
| Demo adapter wrapper（Agent2HarnessAdapter） | ✅ 已实现 | `agent2harness_adapter.py` |
| Core evaluation（Evidence → EvaluationResult） | ✅ 已实现 | `core_evaluation.py` |
| Core report bridge（EvaluationResult → report） | ✅ 已实现 | `core_report_bridge.py` |
| **JudgeFinding + LLM provider config** | ✅ 已完成（2026-05-12） | `llm_config.py` + `fake_judge.py` |
| Real LLM JudgeProvider (transport + factory) | ✅ 已完成（2026-05-12） | `openai_transport.py` + `anthropic_transport.py` + `llm_judge.py` + `judge_provider_factory.py` |
| **Real LLM infrastructure & safety gate verified** | ⚠️ transport verified, semantic judge pending (2026-05-12) | `docs/DOGFOOD_REAL_LLM_001.md` |
| **TraceImportAdapter (native schema)** | ✅ 已实现（2026-05-12） | `agent_tool_harness/trace_import.py` |
| **TraceImportAdapter (simple mapping)** | ✅ 已实现（2026-05-12） | `docs/TRACE_IMPORT_ADAPTER_SPEC.md` |
| **CLIAgentAdapter** | 📐 设计阶段（2026-05-12） | `docs/CLI_AGENT_ADAPTER_SPEC.md` |
| RealAgentAdapter | ❌ 尚未实现 | future（Track C） |

**结论：** Main Flow 已落地。LLM provider 配置模型（四类 provider）和
FakeJudgeProvider（接口验证骨架）已就绪。真实 LLM 调用仍默认不启用。
TraceImportAdapter native schema 已实现（`agent_tool_harness/trace_import.py`），
用户可通过 `trace JSON → TraceImportAdapter → ExecutionTrace → Evidence → CoreEvaluation → Report` 导入已有 trace。

---

## 2. 目标主流程

```
ScenarioSpec              （评测场景纯数据）
    │
    ▼
Agent2HarnessAdapter      （adapter 协议：ScenarioSpec → ExecutionTrace）
    │                      DemoAgent2HarnessAdapter（本轮实现）
    │                      ReplayAgent2HarnessAdapter（本轮实现）
    │
    ▼
ExecutionTrace            （执行轨迹：ToolCall[] + ToolResult[] + final_answer）
    │
    ▼
Evidence                  （证据包：trace + artifacts + cost + latency + signal_quality）
    │
    ▼
CoreEvaluation            （本轮实现：Evidence → EvaluationResult）
    │                     复用 RuleJudge + demo_core_bridge
    │
    ▼
EvaluationResult          （机器评分汇总：findings[] + passed + summary）
    │
    ▼
ReportSummary             （统计摘要）
    │
    ▼
Human Review → ReviewDecision  （人工裁决——不由机器自动生成）
```

**关键边界：** 虚线以上所有步骤是机器执行的。`ReviewDecision` 是人工裁决，
**禁止**从 `EvaluationResult` 自动派生。

---

## 3. 当前旧流程 vs 目标流程对照

### 3.1 当前旧流程（仍可跑，不删除）

```
EvalSpec (from YAML)
  → assembly.build_demo_runtime() → MockReplayAdapter
  → adapter.run(case, registry, recorder) → AgentRunResult (list[dict])
  → RuleJudge.judge(case, run_result) → JudgeResult (RuleCheckResult[])
  → EvalRunner._write_artifacts() → JSON files
  → MarkdownReport.render() → report.md
```

### 3.2 目标 Core Flow（本轮落地，与旧流程并存）

```
ScenarioSpec (from EvalSpec 构造)
  → DemoAgent2HarnessAdapter(SIGNAL_QUALITY=tautological_replay)
  → adapter.run(scenario) → ExecutionTrace (ToolCall[] + ToolResult[])
  → execution_trace_to_evidence(trace) → Evidence
  → CoreEvaluation.evaluate(evidence, eval_spec) → EvaluationResult (RuleFinding[])
  → build_report_summary(metrics) → ReportSummary
  → MarkdownReport.render() 或 CoreReportBridge → report.md
  → Human Reviewer → ReviewDecision（人工显式创建）
```

### 3.3 对象对照表

| 旧对象 | 新 Core Contract 对象 | 桥接方式 |
|--------|----------------------|---------|
| `AgentRunResult` | `ExecutionTrace` | `demo_core_bridge.agent_run_result_to_execution_trace()` |
| `AgentRunResult.tool_calls` (list[dict]) | `ToolCall` (frozen dataclass) | `_dict_to_tool_call()` |
| `AgentRunResult.tool_responses` (list[dict]) | `ToolResult` (frozen dataclass) | `_dict_to_tool_result()` |
| — | `Evidence` | `execution_trace_to_evidence()` |
| `RuleCheckResult` | `RuleFinding` | `rule_check_to_rule_finding()` |
| `JudgeResult` | `EvaluationResult` | `judge_result_to_evaluation_result()` |
| `metrics` dict | `ReportSummary` | `build_report_summary()` |
| —（人工创建） | `ReviewDecision` | **禁止自动生成** |
| 旧 `AgentAdapter` Protocol | `Agent2HarnessAdapter` Protocol | `DemoAgent2HarnessAdapter` wrapper（本轮） |

### 3.4 模块对照表

| 旧模块 | 本轮新增/更新 | 关系 |
|--------|-------------|------|
| `assembly.py` | 新增 `build_demo_core_flow()` | 平行函数，不替换旧函数 |
| `runner/eval_runner.py` | 不修改 | 旧 EvalRunner 保留 |
| `reports/markdown_report.py` | 可选新增 `CoreReportBridge` | 旧 reporter 保留 |
| `agents/mock_replay_adapter.py` | 不修改 | Wrapper 包装它 |
| `agents/transcript_replay_adapter.py` | 不修改 | Wrapper 包装它 |
| `judges/rule_judge.py` | 不修改 | CoreEvaluation 调用它 |
| — | `core_evaluation.py`（新增） | Evidence → EvaluationResult |
| — | `core_report_bridge.py`（新增） | EvaluationResult → 旧 reporter 消费 |

---

## 4. 本轮落地范围

### 4.1 做

1. **Demo adapter wrapper** — `DemoAgent2HarnessAdapter` / `ReplayAgent2HarnessAdapter`
   - 包装现有 `MockReplayAdapter` / `TranscriptReplayAdapter`
   - 实现 `Agent2HarnessAdapter` Protocol
   - 输入 `ScenarioSpec`，输出 `ExecutionTrace`
   - 不修改旧 adapter 内部逻辑

2. **Core evaluation** — `core_evaluation.py`
   - 输入 `Evidence` + `EvalSpec`（可选）
   - 内部复用 `RuleJudge` + `demo_core_bridge`
   - 输出 `EvaluationResult`
   - 不生成 `ReviewDecision`

3. **Core report bridge** — `core_report_bridge.py`
   - 输入 `EvaluationResult` / `ReportSummary`
   - 让现有 `MarkdownReport` 或最小新代码可以展示 Core Contract 结果
   - 不大改现有 report 结构

4. **Integration entry point** — `assembly.py` 新增 `build_demo_core_flow()`
   - 从 `ScenarioSpec` 开始
   - 经过 demo adapter wrapper
   - 产出 `Evidence` → `EvaluationResult` → `ReportSummary`
   - 不接 CLI（先通过 tests 固化）

5. **Integration tests** — `tests/test_agent2harness_main_flow.py`

### 4.2 不做

- 不实现 RealAgentAdapter
- 不实现真实 LLM Judge
- 不实现真实 ProviderConfig
- 不读取 .env
- 不调用外部 API
- 不让 EvaluationResult 自动生成 ReviewDecision
- 不让 Reporter 做最终裁决
- 不大改 CLI 命令结构
- 不删除旧 EvalRunner / MockReplayAdapter

---

## 5. 模块职责

### 5.1 core_contract.py（已有，不改）

**负责：** 定义所有 Core Contract 对象和协议。
- `ToolCall`, `ToolResult`, `ExecutionTrace`, `Evidence`
- `Finding`, `RuleFinding`
- `EvaluationResult`, `ReportSummary`, `ReviewDecision`
- `ScenarioSpec`
- `Agent2HarnessAdapter` Protocol

**不负责：** 不执行工具、不调用 Agent、不评判结果。

### 5.2 assembly.py（已有，本轮扩展）

**当前负责：** `build_demo_runtime()` / `build_replay_runtime()` → 旧 `AgentAdapter`

**本轮新增：** `build_demo_core_flow()` → 完整的 Core Flow 链路

**不负责：** 不实现真实 adapter、不读 .env。

### 5.3 demo_core_bridge.py（已有，不改）

**负责：** 旧对象 → Core Contract 对象的纯数据映射。

**不负责：** 不执行工具、不 IO。

### 5.4 core_evaluation.py（本轮新增）

**负责：** `Evidence` + judge 逻辑 → `EvaluationResult`

**内部复用：** `RuleJudge` + `demo_core_bridge.rule_check_to_rule_finding()` + `judge_result_to_evaluation_result()`

**不负责：** 不实现 LLM judge、不生成 ReviewDecision。

### 5.5 core_report_bridge.py（本轮新增）

**负责：** `EvaluationResult` / `ReportSummary` → 让现有 reporter 可消费 Core Contract

**可能实现：** 最小的 `EvaluationResult → dict` 适配（让 MarkdownReport 现有的 render 逻辑可直接消费），或仅提供数据转换。

**不负责：** 不做最终裁决、不做 pass/fail 决策。

### 5.6 旧模块（本轮不改）

| 模块 | 本轮行为 |
|------|---------|
| `runner/eval_runner.py` | 不修改——旧 EvalRunner 保留 |
| `reports/markdown_report.py` | 不修改——旧 MarkdownReport 保留 |
| `agents/mock_replay_adapter.py` | 不修改——由 wrapper 包装 |
| `agents/transcript_replay_adapter.py` | 不修改——由 wrapper 包装 |
| `judges/rule_judge.py` | 不修改——由 CoreEvaluation 调用 |
| `cli.py` | 不修改——CLI 行为不变 |

---

## 6. 验收标准

### 6.1 功能标准

- [ ] `DemoAgent2HarnessAdapter` 实现 `Agent2HarnessAdapter` Protocol
- [ ] `ReplayAgent2HarnessAdapter` 实现 `Agent2HarnessAdapter` Protocol
- [ ] `ScenarioSpec` → adapter wrapper → `ExecutionTrace` 链路可运行
- [ ] `ExecutionTrace` → `Evidence` 链路可运行
- [ ] `Evidence` → `CoreEvaluation` → `EvaluationResult` 链路可运行
- [ ] `EvaluationResult` / `ReportSummary` 可进入 report bridge
- [ ] `build_demo_core_flow()` 端到端可运行
- [ ] 当前 demo CLI 行为不变（`run --mock-path good` 仍通过）

### 6.2 架构标准

- [ ] `ReviewDecision` 不由任何机器代码自动生成
- [ ] Wrapper 不修改旧 adapter 内部行为
- [ ] 新模块不 import demo adapter / cli / provider
- [ ] 新模块不读取 .env
- [ ] 新模块不调用外部 API
- [ ] 新模块不包含 `if real / if live` 分支

### 6.3 测试标准

- [ ] `tests/test_agent2harness_main_flow.py` 14+ 测试通过
- [ ] `tests/test_core_contract.py` 19 个测试仍通过
- [ ] `tests/test_demo_to_core_bridge.py` 21 个测试仍通过
- [ ] `tests/test_assembly.py` 6 个测试仍通过
- [ ] CLI 相关测试仍通过
- [ ] 全量测试套件通过

---

## 7. 当前阶段与下一阶段

**已完成（2026-05-12）：**
- [x] LLM Provider Config 模型（`llm_config.py`）— 四类 provider 配置 + Registry + resolve_api_key
- [x] JudgeFinding 数据类（`core_contract.py`）— LLM judge advisory finding
- [x] CoreJudgeProvider Protocol（`fake_judge.py`）— `evaluate(Evidence) → list[JudgeFinding]`
- [x] FakeJudgeProvider（`fake_judge.py`）— deterministic fake，零网络依赖
- [x] 示例配置（`examples/llm_providers.example.yaml`）
- [x] 设计文档（`docs/LLM_PROVIDER_CONFIG.md`）
- [x] 30 个测试（19 config + 11 fake judge）
- [x] **Phase 2：CoreEvaluation 可选消费 JudgeProvider**（2026-05-12）
  - `CoreEvaluation.__init__` 新增 `judge_provider: CoreJudgeProvider | None = None`
  - `evaluate()` 调用 `judge_provider.evaluate(evidence)`，追加 JudgeFinding 到 findings
  - `EvaluationResult.passed` 仍由 RuleJudge 决定
  - 12 个新测试（`tests/test_core_evaluation.py`）
- [x] **Phase 3：CLI flags + dry-run + fake judge 集成**（2026-05-12）
  - `--judge-provider fake` CLI flag（仅与 `--core-flow` 配合）
  - `--llm-config` / `--llm-provider` / `--dry-run-provider` flags
  - `load_provider_registry_from_file()` 文件加载入口
  - `build_demo_core_flow()` / `_run_core_flow()` 接受 `judge_provider`
  - 30 个新测试（12 file loading + 11 CLI flags + 7 integration）
  - 616 全量测试通过

- [x] **Phase 4：OpenAI + Anthropic transport + CLI wiring**（2026-05-12）
  - `openai_transport.py` — OpenAI-compatible HTTPS transport（19 tests）
  - `anthropic_transport.py` — Anthropic-compatible HTTPS transport（15 tests）
  - `llm_judge.py` — LLMJudgeProvider（CoreJudgeProvider 实现，11 tests）
  - `judge_provider_factory.py` — 安全门控 factory（10 tests）
  - CLI `--judge-provider llm` 接入 + 双标志 + config 校验（10 tests）
  - 零新依赖、injected http_factory、8 类 error taxonomy
  - 44 个新测试，691 全量测试通过

- [x] **Phase 5：真实 LLM infrastructure & safety gate 验证**（2026-05-12）
  - openai-compatible transport + factory wiring + --env-file secret loading 跑通
  - RuleFinding + JudgeFinding 在 EvaluationResult 中正确并列
  - ReviewDecision 未自动生成（符合预期）
  - `model_env` 从 .env 正确解析
  - CLI log 中 model= 显示 resolved model（修复：使用 `provider.model` 而非 `config.model`）
  - ⚠️ Semantic JudgeFinding 因 provider response parsing bad_response 尚未成功产出，待调试
  - 详见 `docs/DOGFOOD_REAL_LLM_001.md`

**下一阶段（Phase 6）：**
- prompt 工程 + rubric 设计
- 成本追踪 + 预算上限
- 多 provider 分歧率分析

**关键边界：**
- 真实 LLM 调用仍未默认启用
- FakeJudgeProvider 是默认 judge provider
- JudgeFinding 是辅助信号，不改变 deterministic passed
- ReviewDecision 必须人工创建
- `--env-file` 和 `--allow-os-env` 是发起真实 LLM 调用的前置条件
- dry-run 不读取 .env 或 os.environ
