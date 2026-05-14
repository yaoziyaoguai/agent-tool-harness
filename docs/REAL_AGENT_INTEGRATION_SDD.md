# Real Agent Integration SDD (Software Design Document)

> **状态**: Implementation complete — Phase A (native schema) + Phase B (simple mapping) complete (2026-05-13).
> Phase E Level 4A (harness-side LLM judge) complete, Level 4B (target agent self real provider) deferred——前置条件未满足，详见 [DOGFOODING.md](DOGFOODING.md)。
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

本阶段目标：设计 TraceImportAdapter 接入模块，让用户可以把真实 Agent trace 导入 Harness，复用现有的 Core Flow 和 judge/report 能力。

---

## 2. Goals

1. **TraceImportAdapter（唯一接入路径）**: 导入用户已有 trace 文件（不运行 Agent）
2. **复用 Agent2Harness Core Flow**: ExecutionTrace / Evidence / CoreEvaluation 不变
3. **复用 RuleFinding + JudgeFinding + Report**: 现有 judge/report 能力直接消费真实 trace
4. **低接入成本**: 用户不需要改造整个项目
5. **显式 opt-in**: 默认不运行真实 Agent
6. **不作成本追踪**: cost/latency tracking 推迟到后续阶段
7. **推荐工作流**: 外部 runner → trace/log → TraceImportAdapter → CoreEvaluation → Report → Human Review

---

## 3. Non-goals

以下明确不做（第一版）：

- 不支持任意格式自动智能解析
- 不做复杂 JSONPath DSL（第一版仅支持 simple mapping）
- 不自动读取用户私密项目数据
- agent-tool-harness 不调用真实 Agent（primary path 是 external runner → trace/log import）
- 不自动生成 ReviewDecision（保持人工裁决边界）
- 不替代 human review
- 不做生产 benchmark 平台
- 不做 cost/latency guard（推迟到后续阶段）
- 不做 Web UI / MCP executor / RAG / 向量库

---

## 4. Architecture

### 4.1 Integration Path: Trace / Log Import

```
External Agent Runner / 用户脚本 / CI / 手工命令
    │  运行要测评的 Agent
    │  产出 trace/log/stdout/json/jsonl
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
    │
    ▼
Human Review → ReviewDecision
```

**这是唯一接入路径。** Agent Tool Harness 不负责运行 Agent——只负责 trace → evidence →
evaluation → report。真实 Agent 的启动、provider、key、联网、业务执行环境均由
外部 runner 或用户负责。

### 4.2 核心不变式

**重要：** ExecutionTrace 一旦产生，所有下游模块行为与 trace 来源无关。

---

## 5. Module Boundaries

| 模块 | 负责 | 不负责 |
|------|------|--------|
| `TraceImportAdapter` | 读取 trace JSON → ExecutionTrace | 不运行 Agent、不调网络、不读 .env |
| `CoreEvaluation` | Evidence → EvaluationResult | 不知道 trace 来源（demo/import） |
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

### Phase E: Real Agent Dogfood

- 用 TraceImportAdapter 导入用户已有 trace，完成评测
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
| 5 | 端到端产出 EvaluationResult / Report（复用已有能力） | A/B |
| 6 | 不自动生成 ReviewDecision | All |
| 7 | 不读取用户私密数据（.env / secrets） | All |
| 8 | 不默认调用真实 API | All |
| 9 | 所有测试零网络依赖 | All |
| 10 | 所有测试 deterministic | All |

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

### Phase E: Real Agent Dogfood

- Level 4A (real LLM judge, harness 侧) ✅ — LLMJudgeProvider opt-in dogfood
- Level 4B (target agent self real provider) ❌ deferred — target agent 尚缺 dogfood contract

详见 [DOGFOODING.md](DOGFOODING.md)。

---

## 10. References

- [AGENT2HARNESS_MAIN_FLOW.md](AGENT2HARNESS_MAIN_FLOW.md) — Core Flow 架构
- [AGENT2HARNESS_CORE_SPEC.md](AGENT2HARNESS_CORE_SPEC.md) — Core Contract 对象定义
- [TRACE_IMPORT_ADAPTER_SPEC.md](TRACE_IMPORT_ADAPTER_SPEC.md) — TraceImportAdapter 详细 spec
- [TOOL_USE_INSPECTION_SDD.md](TOOL_USE_INSPECTION_SDD.md) — **后续核心方向：Tool-use inspection 六大模块**
- [ROADMAP.md](ROADMAP.md) — 路线图
- [BACKLOG.md](BACKLOG.md) — Backlog 条目
