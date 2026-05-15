# 用户指南

agent-tool-harness 的完整使用流程：准备 trace → 导入 → 评测 → 查看报告。

## 1. 准备 trace

agent-tool-harness 不运行你的 Agent。你需要用自己的 Agent runner、脚本或 CI 产出 tool-use trace，保存为 JSON 文件。

trace 需要包含两部分核心数据：
- **tool_calls** — Agent 发出的工具调用（每条包含 call_id、tool_name、arguments）
- **tool_results** — 工具返回结果（每条包含 call_id、tool_name、status、output、error）

## 2. 导入 trace

### 方式 A：native 模式

如果你的 trace JSON 结构已经符合 Agent2Harness native schema，直接导入：

```python
from agent_tool_harness.trace_import import import_trace_as_evidence

evidence = import_trace_as_evidence("my_trace.json")
trace = evidence.trace
```

native schema 示例见 [examples/trace_import/native_trace.json](../examples/trace_import/native_trace.json)。

### 方式 B：simple_mapping 模式

如果你的 trace 使用不同的字段名，用 SimpleMappingConfig 做映射：

```python
from agent_tool_harness.trace_import import TraceImportAdapter, SimpleMappingConfig

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

如果你的 trace 是 JSONL、stdout、CSV 格式，先写一个转换脚本转成 native schema JSON，再导入。

## 3. 运行评测

```python
from agent_tool_harness.core_evaluation import CoreEvaluation, EvalSpec

eval_spec = EvalSpec(
    id=trace.scenario_id,
    name=trace.scenario_id,
    category="knowledge_search",
    split="dev",
    realism_level="recorded",
    complexity="simple",
    source="external_runner",
    user_prompt="你的原始 prompt",
    initial_context={},
    verifiable_outcome={},
    success_criteria=["你的评测标准"],
    expected_tool_behavior={},
    judge={},
)

result = CoreEvaluation().evaluate(evidence, eval_spec)
print(f"评测通过: {result.passed}")
print(f"发现项: {len(result.findings)}")
```

## 4. 查看报告

评测结果包含：
- `result.passed` — 确定性规则判定的通过/不通过
- `result.findings` — 所有发现项（RuleFinding + JudgeFinding）

v3.1 的 Report Insight 会自动聚合这些数据，产出结构化报告。详见 [REPORT_GUIDE](REPORT_GUIDE.md)。

## 5. CLI 命令速查

| 命令 | 用途 |
|------|------|
| `audit-tools` | 工具契约确定性审计 |
| `audit-evals` | eval 质量审计 |
| `run` | mock replay 全链路 |
| `run --core-flow` | Core Flow 路径 |
| `generate-evals` | 从工具生成候选 eval |
| `promote-evals` | 候选 eval 转正 |
| `bootstrap` | AST 扫描生成 draft 配置 |

完整 CLI 参考见 [CLI_USAGE.md](CLI_USAGE.md)。

## 常见问题

### 我需要真实 LLM 来评测吗？

不需要。RuleFinding（决定 pass/fail）是完全确定性的，零网络依赖。JudgeFinding 是 advisory 性质，默认不使用真实 LLM。

### 我怎么知道 trace 格式对不对？

运行 trace 诊断：

```python
from agent_tool_harness.trace_import import TraceDiagnostics
diag = TraceDiagnostics().diagnose(trace)
print(diag.summary())
```

### 我的 trace 字段名不标准怎么办？

使用 simple_mapping 模式做字段映射（见上文方式 B）。如果映射不够（如嵌套字段提取），先用脚本转成 native schema。

## 相关文档

- [QUICKSTART](QUICKSTART.md) — 30 秒上手
- [REPORT_GUIDE](REPORT_GUIDE.md) — 报告解读
- [architecture/TRACE_IMPORT_ADAPTER_SPEC.md](architecture/TRACE_IMPORT_ADAPTER_SPEC.md) — trace import 技术规范
