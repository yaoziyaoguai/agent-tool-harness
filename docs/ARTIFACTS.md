# Artifact Schema Reference

agent-tool-harness 输出的 JSON artifact 的字段约定与版本管理。

## schema_version

当前 artifact schema 版本：`1.0.0`（定义方 `artifact_schema.py`）。

schema_version 出现在每个 JSON artifact 的顶层，下游工具用它与本文档交叉校验字段预期。

## Core Contract Artifacts

`--core-flow` 路径输出的 artifact（`--out` 目录下）：

### execution_trace.json

Tool-use trace 的标准化表示。

| 字段 | 类型 | 说明 |
|------|------|------|
| `scenario_id` | string | 场景标识 |
| `tool_calls` | list | ToolCall 列表（含 call_id, tool_name, arguments, timestamp） |
| `tool_results` | list | ToolResult 列表（含 call_id, tool_name, status, output, error） |
| `final_answer` | string \| null | Agent 最终回答 |
| `messages` | list | 消息历史 |
| `observations` | list | 观察记录 |

### evidence.json

导入后的 Evidence 包。字段定义见 `agent_tool_harness/trace_import.py:Evidence`。

### evaluation_result.json

EvaluationResult：包含 `passed`（来自 RuleFinding）、`findings`（RuleFinding + JudgeFinding 列表）、`signal_quality`。

### report_summary.json

聚合 ReportSummary：accepted/rejected/review_needed 计数、signal_quality 标签。

### metrics.json

与旧 EvalRunner 路径兼容的指标摘要。

## Audit Artifacts

- `audit_tools.json` / `audit_evals.json` / `audit_judge_prompts.json` — 各类审计输出
- `preflight_report.json` — preflight 静态配置检查输出

## Versioning Policy

- MAJOR：breaking change（字段移除、重命名、语义变更）
- MINOR：新增字段（向后兼容）
- PATCH：文档修正、示例更新

对 artifact schema 的任何修改必须在 `artifact_schema.py` 中更新 `SCHEMA_VERSION`，并在本文档中记录变更。
