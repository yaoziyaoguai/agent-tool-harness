# Trace Import Examples

## native_trace.json

示例 trace 文件，符合 Agent2Harness native schema。可直接通过 `TraceImportAdapter`
导入为 `ExecutionTrace`，然后进入 Core Flow：

```
trace JSON → TraceImportAdapter → ExecutionTrace → Evidence → CoreEvaluation → Report
```

### 使用方式

```python
from agent_tool_harness.trace_import import TraceImportAdapter, import_trace_as_evidence

# 方式 1: 导入为 ExecutionTrace
adapter = TraceImportAdapter()
trace = adapter.import_file("examples/trace_import/native_trace.json")

# 方式 2: 一键导入为 Evidence
evidence = import_trace_as_evidence("examples/trace_import/native_trace.json")
```

### 场景说明

虚构的 knowledge_search 场景——Agent 调用两个知识库搜索工具
（`kb.search.search_articles` + `kb.search.get_article`）定位 SSO session loss
根因。

**不包含**: API key、base_url、model、私密项目数据。

## 当前状态

- **native schema mode**: ✅ 已实现。如果用户 trace 格式与 `native_trace.json` 结构一致，
  可直接导入。

- **simple mapping mode**: ✅ 已实现（2026-05-12）。通过 `SimpleMappingConfig` 声明字段
  key 映射，把非 native 字段名映射到 native schema。

  ```python
  from agent_tool_harness.trace_import import (
      TraceImportAdapter, SimpleMappingConfig
  )

  mapping = SimpleMappingConfig(
      scenario_id_path="sid",
      tool_calls_path="calls",
      tool_results_path="results",
      tool_call_id_field="cid",
      tool_call_name_field="name",
      tool_result_call_id_field="cid",
      tool_result_name_field="name",
  )
  trace = TraceImportAdapter(
      mode="simple_mapping", mapping=mapping
  ).import_file("my_trace.json")
  ```

  **不支持**: JSONPath DSL / 嵌套路径（a.b.c）/ filter / expression / Python eval /
  LLM 自动解析。如果 trace 格式超出 simple mapping 能力，请先用脚本转成 native schema。

- **CLIAgentAdapter**: 已移除。agent-tool-harness 不再内置运行目标 Agent。
  primary integration path 是 external runner / 用户脚本 / CI / 手工命令
  → trace/log import → inspect/evaluate/report。

## 相关文档

- [TRACE_IMPORT_ADAPTER_SPEC.md](../../docs/TRACE_IMPORT_ADAPTER_SPEC.md) — trace import spec
- [EXTERNAL_RUNNER_WORKFLOW.md](../../docs/EXTERNAL_RUNNER_WORKFLOW.md) — 推荐工作流
- [REAL_AGENT_INTEGRATION_SDD.md](../../docs/REAL_AGENT_INTEGRATION_SDD.md) — historical architecture note
