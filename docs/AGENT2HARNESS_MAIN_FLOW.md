# Agent2Harness Main Flow

> 本文档定义 Agent Tool Harness 的 **Agent2Harness 主流程**——
> 从 trace/log 导入到 Human Review 的完整 Core Flow。
> 这是后续所有实现工作的依据文档。
>
> **核心定位（2026-05-13 架构纠偏）：**
> Agent Tool Harness 的核心职责是处理 Agent tool-use 日志 / trace / evidence，
> 进行可复现评测和报告。**主要接入路径是 trace/log import**，不是运行真实 Agent。
> CLIAgentAdapter 是 optional convenience runner，不是 Core 必需路径。
> 真实 Agent 的启动、provider、key、联网、业务执行环境由外部 runner 或用户负责。

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
| **TraceImportAdapter (native + simple mapping)** | ✅ 已实现（2026-05-12）— **主要接入路径** | `agent_tool_harness/trace_import.py` |
| **CLIAgentAdapter** | ✅ 已实现（2026-05-13）— **optional convenience** | `agent_tool_harness/cli_agent.py` |
| C10 Real agent dogfood | ✅ Level 1+2+3+4A done, 4B deferred | Track C |
| External runner workflow | 📄 已文档化 | `docs/EXTERNAL_RUNNER_WORKFLOW.md` |

**结论：** Main Flow 已落地。**主要接入路径是 TraceImportAdapter**——
用户用自己的脚本/CI/外部 runner 运行 Agent，产出 trace/log，通过 native 或
simple_mapping 模式导入，进入 CoreEvaluation → Report 链路。
CLIAgentAdapter 是 optional convenience——适合简单场景，但不要求所有用户使用，
也不应让真实 Agent 启动逻辑污染 Core。真实 LLM 调用仍默认不启用。

---

## 2. 目标主流程

### 2.1 主要接入路径：Trace / Log Import（推荐）

外部 runner 或用户自己的脚本/CI 运行 Agent，产出 trace/log 文件，通过
TraceImportAdapter 导入。**这是推荐的主路径**——Agent Tool Harness 不负责
运行 Agent，只负责 trace → evidence → evaluation → report。

```
External Agent Runner / 用户脚本 / CI / 手工命令
    │  运行要测评的 Agent
    │  产出 trace/log/stdout/json/jsonl
    ▼
TraceImportAdapter        （原生 JSON → ExecutionTrace）
    │  native mode: 直接导入标准 schema
    │  simple_mapping mode: 字段映射导入非标准格式
    │
    ▼
ExecutionTrace            （执行轨迹：ToolCall[] + ToolResult[] + final_answer）
    │
    ▼
Evidence                  （证据包：trace + artifacts + cost + latency + signal_quality）
    │
    ▼
CoreEvaluation            （Evidence → EvaluationResult）
    │  RuleJudge（deterministic）+ optional JudgeProvider（advisory）
    │
    ▼
EvaluationResult          （机器评分汇总：RuleFinding[] + JudgeFinding[]）
    │
    ▼
ReportSummary             （统计摘要）
    │
    ▼
Human Review → ReviewDecision  （人工裁决——不由机器自动生成）
```

### 2.2 辅助接入路径：CLIAgentAdapter（optional convenience）

CLIAgentAdapter 通过 subprocess 运行 CLI Agent 命令，收集 trace 输出后委托
TraceImportAdapter 解析。**适合简单场景**，但不是必需路径。

```
ScenarioSpec → CLIAgentAdapter → subprocess → trace file
    → TraceImportAdapter → ExecutionTrace → Evidence → ...（同主路径）
```

CLIAgentAdapter 的适用/不适用场景详见 `docs/CLI_AGENT_ADAPTER_SPEC.md` 和
`docs/EXTERNAL_RUNNER_WORKFLOW.md`。

**关键边界：** 虚线以上所有步骤是机器执行的。`ReviewDecision` 是人工裁决，
**禁止**从 `EvaluationResult` 自动派生。真实 Agent 的启动、provider、key、
联网、业务执行环境由外部 runner 或用户负责——不进入 agent-tool-harness Core。

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

## 4. 当前落地范围

### 4.1 已完成

1. **Core Contract + Demo Bridge + Core Flow** — Core Contract 对象、Demo-to-Core 桥接、
   CoreEvaluation、CoreReportBridge、assembly core flow 均已落地。

2. **TraceImportAdapter**（主要接入路径）— native + simple_mapping 两种模式，
   83 个测试。不运行 Agent，只导入 trace。

3. **CLIAgentAdapter**（optional convenience）— Slice 1-4 已实现，97 个测试。
   通过 subprocess 运行 CLI 命令并委托 TraceImportAdapter 解析 trace。

4. **JudgeProvider Protocol** — FakeJudgeProvider + LLMJudgeProvider + factory + safety gates。

5. **Dogfood** — Level 1+2（fake/toy）+ Level 3（my-first-agent wrapper）+ Level 4A（real LLM judge）。
   Level 4B deferred（target agent 尚缺 dogfood contract）。

### 4.2 不做

- 不实现 RealAgentAdapter（不需要——trace import 是主路径）
- 不让真实 Agent 启动逻辑进入 Core
- 不默认调用真实 LLM
- 不读取 .env
- 不让 EvaluationResult 自动生成 ReviewDecision
- 不删除已有 CLIAgentAdapter
- 不破坏已有测试

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

**已完成（2026-05-13）：**
- TraceImportAdapter（native + simple mapping）— **主要接入路径**
- CLIAgentAdapter（Slice 1-4）— **optional convenience**
- JudgeProvider Protocol + LLMJudgeProvider + safety gates
- Dogfood Level 1+2+3+4A，Level 4B deferred
- 架构纠偏：trace/log import 是主路径，CLIAgentAdapter 是 optional

**下一阶段重点：**
- 更好的 TraceImportAdapter diagnostics（mapping error report）
- 更多 mapping examples（JSON/JSONL/stdout 转 trace）
- external-runner cookbook
- evidence quality report
- report review UX
- prompt 工程 + rubric 设计（LLM judge 侧）
- 成本追踪 + 预算上限

**关键边界：**
- 真实 LLM 调用仍未默认启用
- FakeJudgeProvider 是默认 judge provider
- JudgeFinding 是辅助信号，不改变 deterministic passed
- ReviewDecision 必须人工创建
- `--env-file` 和 `--allow-os-env` 是发起真实 LLM 调用的前置条件
- 真实 Agent 的启动、provider、key、联网由外部 runner 或用户负责
