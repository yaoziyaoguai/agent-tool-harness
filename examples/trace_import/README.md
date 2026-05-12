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

- **native schema mode**: 已实现。如果用户 trace 格式与 `native_trace.json` 结构一致，
  可直接导入。
- **simple mapping mode**: 尚未实现。如果用户 trace 字段名不一致，建议先用脚本
  转成 native schema。
- **CLIAgentAdapter**: 尚未实现。当前无法通过 CLI 命令运行真实 Agent 并自动导入 trace。

## 相关文档

- [TRACE_IMPORT_ADAPTER_SPEC.md](../../docs/TRACE_IMPORT_ADAPTER_SPEC.md)
- [REAL_AGENT_INTEGRATION_SDD.md](../../docs/REAL_AGENT_INTEGRATION_SDD.md)
