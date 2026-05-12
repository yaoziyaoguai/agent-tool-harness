# TraceImportAdapter Specification

> **状态**: Draft — Design phase. No implementation yet.
> **父文档**: [REAL_AGENT_INTEGRATION_SDD.md](REAL_AGENT_INTEGRATION_SDD.md)

---

## 1. Purpose

`TraceImportAdapter` 负责把用户已有 trace 文件导入为 Agent2Harness `ExecutionTrace`。

**负责**:
- 读取 trace JSON 文件
- 校验必要字段
- 映射到 `ExecutionTrace` dataclass

**不负责**:
- 不运行任何 Agent
- 不调用外部 API
- 不读取 .env
- 不猜测复杂格式
- 不用 LLM 解析 trace

---

## 2. Supported Modes

第一版支持两种模式：

### 2.1 Mode A: Native

用户直接提供符合 `ExecutionTrace` schema 的 JSON 文件。

**适用场景**: 用户愿意适配标准 schema，已有脚本可将自有 trace 转为标准格式。

**优势**: 最稳定——不经过任何字段映射，反序列化后直接校验。

### 2.2 Mode B: Simple Mapping

用户提供普通 JSON + 字段映射 YAML。Adapter 按映射关系提取字段。

**适用场景**: 用户已有 trace JSON，字段名与 Agent2Harness 不完全一致，但结构简单。

**限制**: 第一版不做复杂 JSONPath DSL。只支持：
- 顶层字段映射（`scenario_id_path: "scenario_id"`）
- 简单 list 内字段映射（`tool_calls_path: "calls"`, `tool_name: "name"`）
- 不做嵌套 filter / wildcard / expression

---

## 3. Native Schema

### 3.1 Minimum required fields

```json
{
  "scenario_id": "kb_sso_session_loss_regression",
  "tool_calls": [
    {
      "call_id": "c1",
      "tool_name": "kb.search.search_articles",
      "arguments": {"query": "SSO session loss", "limit": 5}
    }
  ],
  "tool_results": [
    {
      "call_id": "c1",
      "tool_name": "kb.search.search_articles",
      "status": "success",
      "output": {"articles": [...]},
      "error": null
    }
  ],
  "final_answer": "Root cause: SSO misconfiguration in session storage layer.",
  "messages": [],
  "observations": []
}
```

### 3.2 Field specification

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `scenario_id` | string | **Yes** | 场景 ID，标识此 trace 对应哪个 eval 场景 |
| `tool_calls` | list[object] | **Yes** | Agent 发起的工具调用列表 |
| `tool_calls[].call_id` | string | **Yes** | 唯一调用 ID，与 `tool_results[].call_id` 对应 |
| `tool_calls[].tool_name` | string | **Yes** | 工具名 |
| `tool_calls[].arguments` | object | **Yes** | 调用参数 |
| `tool_calls[].timestamp` | string | No | ISO8601 时间戳，可选 |
| `tool_results` | list[object] | **Yes** | 工具返回结果列表 |
| `tool_results[].call_id` | string | **Yes** | 关联 `tool_calls` 中的 `call_id` |
| `tool_results[].tool_name` | string | **Yes** | 工具名 |
| `tool_results[].status` | string | **Yes** | `"success"` 或 `"error"` |
| `tool_results[].output` | object | No* | 工具输出（success 时必须可空 object） |
| `tool_results[].error` | string | No* | 错误信息（error 时必须可空 string） |
| `final_answer` | string | Recommended | Agent 最终输出 |
| `messages` | list[object] | No | Agent 中间消息（可空 list） |
| `observations` | list[object] | No | Agentic loop 中间步骤（可空 list） |

*至少 `output` 或 `error` 之一存在。两者可共存。

### 3.3 Validation rules

| Rule | Error on failure |
|------|------------------|
| `scenario_id` 非空字符串 | `ImportError: missing scenario_id` |
| `tool_calls` 为 list | `ImportError: tool_calls must be a list` |
| `tool_results` 为 list | `ImportError: tool_results must be a list` |
| 每个 tool_call 有 `call_id` | `ImportError: tool_call missing call_id` |
| 每个 tool_call 有 `tool_name` | `ImportError: tool_call missing tool_name` |
| 每个 tool_result 有 `call_id` | `ImportError: tool_result missing call_id` |
| 每个 tool_result 有 `tool_name` | `ImportError: tool_result missing tool_name` |
| `output` 或 `error` 至少一个非空 | `ImportError: tool_result needs output or error` |
| JSON 可解析 | `ImportError: invalid JSON` |

---

## 4. Simple Mapping Mode

### 4.1 Mapping YAML

```yaml
trace_import:
  mode: simple_mapping
  scenario_id_path: scenario_id
  tool_calls_path: tool_calls
  tool_results_path: tool_results
  final_answer_path: final_answer
  field_mapping:
    tool_call:
      call_id: call_id
      tool_name: tool_name
      arguments: arguments
      timestamp: timestamp
    tool_result:
      call_id: call_id
      tool_name: tool_name
      status: status
      output: output
      error: error
```

### 4.2 Mapping rules

- `scenario_id_path`: 指向 trace JSON 中 scenario_id 的顶层 key。默认 `"scenario_id"`。
- `tool_calls_path`: 指向工具调用 list 的顶层 key。默认 `"tool_calls"`。
- `tool_results_path`: 指向工具结果 list 的顶层 key。默认 `"tool_results"`。
- `final_answer_path`: 指向最终回答的顶层 key。默认 `"final_answer"`。
- `field_mapping`: 定义 list 内每个对象的字段映射。如未提供，使用与 native schema 相同的字段名。

### 4.3 Limitations (v1)

- 只支持顶层 key 映射
- 不支持 `a.b.c` 嵌套路径
- 不支持 `items[*].field` JSONPath
- 不支持 expression / filter / transform
- 不支持跨字段计算

如果用户格式超出 simple mapping 能力，建议：**先用脚本转成 native schema，再用 native mode 导入**。

---

## 5. Error Handling

### 5.1 Error taxonomy

| Error class | When | User action |
|-------------|------|-------------|
| `ImportError: invalid JSON` | 文件不是合法 JSON | 检查文件格式 |
| `ImportError: missing scenario_id` | scenario_id 缺失或为空 | 确认 trace 有场景 ID |
| `ImportError: tool_calls must be a list` | tool_calls 字段不是 list | 确认 trace 结构 |
| `ImportError: missing field X` | 必要字段缺失 | 补齐字段或调整 mapping |
| `ImportError: mapping target not found` | mapping YAML 指向的 key 不存在 | 检查 mapping 配置 |

### 5.2 Non-behaviors

- **不猜测**: 字段缺失时报错，不尝试从其他字段推断
- **不修复**: 格式错误时报错，不尝试静默修补
- **不降级**: 错误就停止，不产出部分 ExecutionTrace
- **不 LLM**: 绝不用 LLM 解析 trace

---

## 6. Interface

```python
class TraceImportAdapter:
    """导入用户 trace 文件为 ExecutionTrace。"""

    def __init__(
        self,
        mode: str = "native",          # "native" | "simple_mapping"
        mapping: dict | None = None,   # simple_mapping 时的字段映射配置
    ) -> None: ...

    def import_trace(
        self,
        trace_path: str | Path,
    ) -> ExecutionTrace: ...
```

---

## 7. Test Plan

| # | Test | Mode |
|---|------|------|
| 1 | native trace 成功导入 → ExecutionTrace | native |
| 2 | scenario_id / tool_calls / tool_results roundtrip 不丢 | native |
| 3 | call_id 关联保持正确 | native |
| 4 | final_answer 正确传递 | native |
| 5 | messages / observations 空 list 兼容 | native |
| 6 | simple mapping 成功导入（自定义字段名） | simple_mapping |
| 7 | mapping target 不存在 → ImportError | simple_mapping |
| 8 | 缺 scenario_id → ImportError | native |
| 9 | tool_name roundtrip 不丢 | native |
| 10 | malformed JSON → ImportError | native |
| 11 | tool_calls 非 list → ImportError | native |
| 12 | tool_results 非 list → ImportError | native |
| 13 | tool_result 缺 output 且 缺 error → ImportError | native |
| 14 | 不读取 .env | native |
| 15 | 不调用外部 API | native |
| 16 | 不 import os.environ | native |

所有测试零网络依赖，纯 deterministic。
