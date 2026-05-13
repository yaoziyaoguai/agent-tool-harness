# External Runner Workflow

> 本文档定义 agent-tool-harness 的推荐用户工作流：用外部 runner 运行 Agent，
> 通过 TraceImportAdapter 导入 trace/log，进入 CoreEvaluation → Report 链路。

---

## 1. 推荐工作流

```
1. 用自己的脚本/CI/外部 runner 运行 Agent
       ↓
2. 保存 tool-use trace/log/stdout/json/jsonl
       ↓
3. 根据 Agent 输出格式写 mapping config（如非 native schema）
       ↓
4. TraceImportAdapter 导入 trace → ExecutionTrace
       ↓
5. CoreEvaluation → EvaluationResult（RuleFinding + optional JudgeFinding）
       ↓
6. Report（Markdown + JSON artifacts）
       ↓
7. Human Review → ReviewDecision
```

---

## 2. 职责边界

### agent-tool-harness 负责

- 接收 trace/log 文件（JSON/JSONL/structured stdout）
- 通过 TraceImportAdapter 解析为 ExecutionTrace
- 生成 Evidence、运行 CoreEvaluation、产出 Report
- 提供 mapping config 校验和 diagnostics

### agent-tool-harness 不负责

- 启动或运行真实 Agent
- 管理 Agent 的 provider、API key、联网策略
- 提供 Agent 运行时环境（GPU、容器、集群调度）
- 为每个 Agent 写专用 wrapper
- 读取 .env（除非用户显式 opt-in 用于 LLM judge）

### 外部 runner / 用户负责

- 配置和启动 Agent
- 管理 secrets、provider、网络、运行环境
- 确保 trace/log 输出为结构化格式（JSON 或接近 JSON）
- 保存 trace 文件到 agent-tool-harness 可访问的位置

---

## 3. Trace 格式建议

### 3.1 最佳路径：直接产出 native schema

```json
{
  "scenario_id": "my-eval-001",
  "tool_calls": [
    {
      "call_id": "c1",
      "tool_name": "knowledge.search",
      "arguments": {"query": "how to fix SSO", "limit": 5}
    }
  ],
  "tool_results": [
    {
      "call_id": "c1",
      "tool_name": "knowledge.search",
      "status": "success",
      "output": {"results": [...]},
      "error": null
    }
  ],
  "final_answer": "Root cause: ...",
  "messages": []
}
```

如果 Agent 能直接输出这个格式，用 `TraceImportAdapter(mode="native")` 导入即可。

### 3.2 次优路径：非标准 JSON + mapping config

如果 Agent 输出的字段名不同（如 `tool_calls` → `calls`，`tool_name` → `name`）：

```yaml
# mapping.yaml
trace_import:
  mode: simple_mapping
  scenario_id_path: scenario_id
  tool_calls_path: calls
  tool_results_path: results
  field_mapping:
    tool_call:
      call_id: id
      tool_name: name
      arguments: args
    tool_result:
      call_id: id
      tool_name: name
      status: status
      output: output
      error: error
```

用 `TraceImportAdapter(mode="simple_mapping", mapping=...)` 导入。

### 3.3 最小路径：stdout/JSONL → 预处理脚本 → native schema

如果 Agent 输出是 JSONL（每行一个 event）或非结构化 stdout：

1. 写一个简单转换脚本（Python 10-20 行）
2. 把 JSONL/stdout 转为 native schema JSON
3. 用 native mode 导入

```python
# 示例：JSONL → native schema
import json, sys

tool_calls = []
tool_results = []
for line in sys.stdin:
    event = json.loads(line)
    if event["type"] == "tool_call":
        tool_calls.append({...})
    elif event["type"] == "tool_result":
        tool_results.append({...})

trace = {
    "scenario_id": "from-env",
    "tool_calls": tool_calls,
    "tool_results": tool_results,
    "final_answer": "...",
    "messages": [],
}
json.dump(trace, sys.stdout, indent=2)
```

不要求 agent-tool-harness 内部支持所有格式——转换脚本由用户维护。

---

## 4. agent-tool-harness 不运行 Agent

agent-tool-harness **不运行 Agent**。所有 Agent 启动由外部 runner/CI/用户脚本负责。
harness 只负责 trace → evidence → evaluation → report。

之前存在的 CLIAgentAdapter（内部 subprocess runner）已移除。

---

## 5. secrets / .env / real provider 边界

- agent-tool-harness 的 TraceImportAdapter 和 CoreEvaluation **不需要也不应该**访问
  Agent 的 API key、.env、provider 配置
- 外部 runner 管理自己的 secrets——不传递给 agent-tool-harness
- agent-tool-harness 仅当使用 LLMJudgeProvider 时才需要自己的 API key，且必须通过
  `--env-file` + `--live` + `--confirm-i-have-real-key` 三重 opt-in
- 不自动读取 .env、不自动加载 dotenv、不自动调用外部 API

---

## 6. 为什么不要求 agent-tool-harness 内部运行所有 Agent

1. **职责单一**：agent-tool-harness 的核心价值在 trace → evidence → evaluation → report，
   不在 Agent 运行时管理
2. **安全边界**：不接触 Agent secrets、不管理 Agent 网络、不进入 Agent 业务环境
3. **通用性**：每种 Agent 的运行方式不同（CLI、HTTP、容器、K8s Job、CI pipeline）——
   不可能也不应该用一个内部 runner 覆盖所有场景
4. **低耦合**：外部 runner 可以是任何东西（bash 脚本、Makefile、GitHub Actions、
   Jenkins、Airflow）——agent-tool-harness 不限制用户的选择
5. **可维护性**：不把 Agent 运行时的复杂性塞进 Core，保持 Core 简单可测

---

## 7. 未来重点

- TraceImportAdapter diagnostics 增强（mapping error report、missing field 提示）
- 更多 mapping examples（JSONL、CSV、stdout parse）
- mapping config validation 硬化
- tool-use inspection（工具正确性、工效学、响应质量、spec 质量）——详见 [TOOL_USE_INSPECTION_SDD.md](TOOL_USE_INSPECTION_SDD.md)
- evidence quality report
- report review UX
- external-runner cookbook（更多语言和框架的转换示例）
