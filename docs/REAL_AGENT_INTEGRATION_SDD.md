# Real Agent Integration SDD (Software Design Document)

> **状态**: Implementation in progress — Phase A (native schema) + Phase B (simple mapping) + Phase C (CLIAgentAdapter Slice 1-4) + Phase D (integration) + Phase E (Level 1+2 dogfood) complete (2026-05-13).
> Phase E Level 3 (real local agent) 和 Level 4 (real LLM) 尚未实现。详见 [DOGFOODING.md](DOGFOODING.md)。
> **依赖**: Agent2Harness Core Flow (landed), CoreJudgeProvider (landed), LLMJudgeProvider (landed), explicit --env-file secret loading (landed).

---

## 1. Problem Statement

Agent2Harness 当前已完成以下能力：

- **Demo/Core Flow**: ScenarioSpec → ExecutionTrace → Evidence → CoreEvaluation → EvaluationResult → ReportSummary
- **RuleJudge**: Deterministic rule-based evaluation (must_call_tool, forbidden_first_tool, etc.)
- **LLMJudgeProvider**: Opt-in real LLM judge（OpenAI / Anthropic / compatible）
- **Explicit secret loading**: --env-file / --allow-os-env
- **Report**: Markdown + JSON artifact output

但是，**所有评测都跑在 mock replay / expected_tool_behavior 上**。用户的真实 Agent 项目无法接入 Harness 体系。

本阶段目标：设计两个互补的接入模块，让用户可以把真实 Agent trace 导入 Harness，复用现有的 Core Flow 和 judge/report 能力。

---

## 2. Goals

1. **TraceImportAdapter**: 导入用户已有 trace 文件（不运行 Agent）
2. **CLIAgentAdapter**: 通过 CLI 命令运行用户 Agent 并收集 trace
3. **复用 Agent2Harness Core Flow**: ExecutionTrace / Evidence / CoreEvaluation 不变
4. **复用 RuleFinding + JudgeFinding + Report**: 现有 judge/report 能力直接消费真实 trace
5. **低接入成本**: 用户不需要改造整个项目
6. **显式 opt-in**: 默认不运行真实 Agent
7. **不作成本追踪**: cost/latency tracking 推迟到后续阶段

---

## 3. Non-goals

以下明确不做（第一版）：

- 不支持任意格式自动智能解析
- 不做复杂 JSONPath DSL（第一版仅支持 simple mapping）
- 不自动读取用户私密项目数据
- 不自动调用真实 Agent（CLIAgentAdapter 需显式配置）
- 不自动生成 ReviewDecision（保持人工裁决边界）
- 不替代 human review
- 不做生产 benchmark 平台
- 不做 cost/latency guard（推迟到后续阶段）
- 不做 Web UI / MCP executor / RAG / 向量库

---

## 4. Architecture

### 4.1 TraceImportAdapter 流程

```
user trace file (JSON)
    │
    ▼
TraceImportAdapter
    │  模式 A: native mode（直接反序列化 ExecutionTrace）
    │  模式 B: simple mapping mode（YAML 字段映射）
    │
    ▼
ExecutionTrace              ← 标准 Core Contract 对象
    │
    ▼
Evidence                    ← execution_trace_to_evidence()（已有）
    │
    ▼
CoreEvaluation              ← 已有，零改动
    │
    ▼
EvaluationResult            ← RuleFinding[] + JudgeFinding[]
    │
    ▼
Report                      ← MarkdownReport + JSON artifacts（已有）
```

### 4.2 CLIAgentAdapter 流程

```
ScenarioSpec
    │
    ▼
scenario input file          ← 从 ScenarioSpec 生成（JSON，写入 temp/out dir）
    │
    ▼
user CLI command             ← 外部进程，Agent2Harness 不感知内部实现
    │  python run_agent.py --input {scenario_file} --trace-out {trace_file}
    │
    ▼
trace output file            ← 用户 Agent 产出的 trace JSON
    │
    ▼
TraceImportAdapter           ← CLIAgentAdapter 委托 TraceImportAdapter 解析 trace
    │
    ▼
ExecutionTrace
    │
    ▼
Evidence → CoreEvaluation → EvaluationResult → Report
```

### 4.3 两者关系

```
          CLIAgentAdapter
               │
               │ 运行命令后，取 trace 文件
               ▼
          TraceImportAdapter
               │
               ▼
          ExecutionTrace
```

CLIAgentAdapter **不自己解析 trace**。它负责运行命令，然后把 trace 文件交给 TraceImportAdapter。

---

## 5. Module Boundaries

| 模块 | 负责 | 不负责 |
|------|------|--------|
| `TraceImportAdapter` | 读取 trace JSON → ExecutionTrace | 不运行 Agent、不调网络、不读 .env |
| `CLIAgentAdapter` | CLI 命令编排 + 文件管理 + 调用 TraceImportAdapter | 不解析复杂 trace、不猜测输出格式 |
| `CoreEvaluation` | Evidence → EvaluationResult | 不知道 trace 来源（demo/import/cli） |
| `RuleJudge` | Determinisic rule checks | 不知道 trace 来源 |
| `LLMJudgeProvider` | Semanic LLM judge | 不知道 trace 来源 |
| `Reporter` | Report 渲染 | 不知道 trace 来源 |
| `ReviewDecision` | 人工裁决 | 仍不自动生成 |

**核心不变式：** ExecutionTrace 一旦产生，所有下游模块行为与 trace 来源无关。

---

## 6. Implementation Phases

### Phase A: TraceImportAdapter — Native Schema

- 接受 Agent2Harness 原生 ExecutionTrace JSON
- 反序列化 + 校验（scenario_id, tool_calls, tool_results, call_id 关联）
- 输出 ExecutionTrace dataclass
- 测试：native trace 成功导入 / 格式错误报错

### Phase B: TraceImportAdapter — Simple Mapping Mode

- 接受任意 JSON + mapping YAML（字段路径映射）
- 第一版不做 JSONPath DSL，只支持顶层字段 + 简单嵌套（如 `tool_calls[].tool_name`）
- 输出 ExecutionTrace dataclass
- 测试：simple mapping 成功导入 / 缺必要字段报错

### Phase C: CLIAgentAdapter — Command Runner

- 接受 ScenarioSpec + command template + working_dir + timeout
- 生成 scenario input file（JSON）
- 执行 CLI 命令（subprocess, no shell=True default）
- 收集 exit code / stdout / stderr / trace file
- 测试：fake CLI 命令输出 native trace / timeout / non-zero exit

### Phase D: CLIAgentAdapter → TraceImportAdapter 集成

- CLIAgentAdapter 调用 TraceImportAdapter 解析 trace 文件
- 端到端链路：ScenarioSpec → CLI agent → trace file → TraceImportAdapter → ExecutionTrace
- 测试：integration test with fake CLI command

### Phase E: Real Agent Dogfood

- 选择一个本地 Agent 项目（用户自己的）
- 用 CLIAgentAdapter + TraceImportAdapter 完成一次真实评测
- 产出 EvaluationResult + Report
- 验证 RuleFinding + JudgeFinding 对真实 trace 有效

---

## 7. Acceptance Criteria

| # | Criteria | Phase |
|---|----------|-------|
| 1 | 能导入 native ExecutionTrace JSON 并产出 ExecutionTrace dataclass | A |
| 2 | 格式错误时产生明确错误信息，不静默吞错 | A |
| 3 | 能通过 simple mapping YAML 导入非标准 trace JSON | B |
| 4 | mapping 中引用的字段不存在时明确报错 | B |
| 5 | 能通过 CLI agent command 生成 trace 文件 | C |
| 6 | 命令超时 / 非零退出 / trace 文件缺失时正确处理 | C |
| 7 | CLIAgentAdapter 委托 TraceImportAdapter 解析 trace | D |
| 8 | 端到端产出 EvaluationResult / Report（复用已有能力） | D |
| 9 | 不自动生成 ReviewDecision | All |
| 10 | 不读取用户私密数据（.env / secrets） | All |
| 11 | 不默认调用真实 API | All |
| 12 | 所有测试零网络依赖 | All |
| 13 | 所有测试 deterministic | All |

---

## 8. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| 用户 trace 格式千差万别 | 第一版只支持 native schema + simple mapping，不做自动推断。引导用户用脚本转格式。 |
| CLI agent command 包含恶意指令 | 默认 no shell=True，command template 必须显式配置，不支持运行时拼接。timeout 强制截断。 |
| trace 文件巨大 | 第一版不设硬限制，后续按需加 truncation。 |
| 用户期望自动解析任意格式 | 文档明确边界：不支持自动智能解析。复杂格式先用脚本转 native schema。 |

---

## 9. Implementation Progress

### Phase A: TraceImportAdapter — Native Schema ✅ (2026-05-12)

| Acceptance Criteria | Status |
|----------------------|--------|
| AC 1: 能导入 native ExecutionTrace JSON → ExecutionTrace dataclass | ✅ 52 tests |
| AC 2: 格式错误时产生明确错误信息，不静默吞错 | ✅ 20+ error path tests |
| AC 12: 所有测试零网络依赖 | ✅ |
| AC 13: 所有测试 deterministic | ✅ |

实现位置:
- `agent_tool_harness/trace_import.py` — TraceImportAdapter
- `examples/trace_import/native_trace.json` — 示例 trace
- `tests/test_trace_import_adapter.py` — 52 tests

### Phase B: TraceImportAdapter — Simple Mapping Mode ✅ (2026-05-12)

| Acceptance Criteria | Status |
|----------------------|--------|
| AC 3: 能通过 simple mapping 导入非标准 trace JSON | ✅ 31 tests |
| AC 4: mapping 中引用的字段不存在时明确报错 | ✅ |
| AC 12: 所有测试零网络依赖 | ✅ |
| AC 13: 所有测试 deterministic | ✅ |

实现位置:
- `agent_tool_harness/trace_import.py` — `SimpleMappingConfig` dataclass + `_apply_simple_mapping()` + mode routing
- `tests/test_trace_import_simple_mapping.py` — 31 tests

不支持: JSONPath DSL / 嵌套路径 / filter / expression / Python eval / CLI entry。

### Phase C: CLIAgentAdapter — Command Runner

| Slice | Status |
|-------|--------|
| Slice 1: command config + input file preparation | ✅ (2026-05-13, 27 tests) |
| Slice 2: subprocess execution + timeout + env | ✅ (2026-05-13, 51 tests) |
| Slice 3: TraceImportAdapter integration | ✅ (2026-05-13, 76 tests) |
| Slice 4: assembly integration | ✅ (2026-05-13, 21 tests, `build_cli_agent_core_flow()`) |

实现位置:
- `agent_tool_harness/cli_agent.py` — CLIAgentAdapterConfig + CLIAgentPreparedRun + CLIAgentResult + CLIAgentAdapter
- `tests/test_cli_agent_adapter.py` — 51 tests

Slice 1 实现: command 必须是 list[str]、占位符 {input_path}/{trace_output_path} 校验、
working_dir 校验、ScenarioSpec → input JSON file、prepare_run() 生成执行计划。
Slice 2 实现: subprocess.run() 执行、timeout 控制、env_policy (minimal/allowlist/inherit)、
stdout/stderr 截断、非零 exit code warning、trace 文件缺失检测。
不集成 TraceImportAdapter。

### Phase D: CLIAgentAdapter → TraceImportAdapter 集成 ✅ (2026-05-13)

已完成。CLIAgentAdapter.run() 委托 TraceImportAdapter 解析 trace，
端到端链路已通过 `build_cli_agent_core_flow()` 验证。

### Phase E: Real Agent Dogfood

- Level 1 (fake CLI agent) ✅ — `examples/cli_agent_fake/`
- Level 2 (toy CLI agent) ✅ — `examples/cli_agent_toy/`
- Level 3 (real local agent) ❌ — 需要用户显式启用
- Level 4 (real LLM / external API) ❌ — 需要用户显式配置密钥

详见 [DOGFOODING.md](DOGFOODING.md)。

---

## 10. References

- [AGENT2HARNESS_MAIN_FLOW.md](AGENT2HARNESS_MAIN_FLOW.md) — Core Flow 架构
- [AGENT2HARNESS_CORE_SPEC.md](AGENT2HARNESS_CORE_SPEC.md) — Core Contract 对象定义
- [TRACE_IMPORT_ADAPTER_SPEC.md](TRACE_IMPORT_ADAPTER_SPEC.md) — TraceImportAdapter 详细 spec
- [CLI_AGENT_ADAPTER_SPEC.md](CLI_AGENT_ADAPTER_SPEC.md) — CLIAgentAdapter 详细 spec
- [ROADMAP.md](ROADMAP.md) — 路线图
- [BACKLOG.md](BACKLOG.md) — Backlog 条目
