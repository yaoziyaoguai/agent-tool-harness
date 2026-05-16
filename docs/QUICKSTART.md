# 快速开始

最短路径上手 agent-tool-harness。不需要 .env，不需要 API key，不需要联网，不需要运行真实 Agent。

## 安装

```bash
git clone https://github.com/yaoziyaoguai/agent-tool-harness.git
cd agent-tool-harness
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 验证
python -m pytest tests/ -q
```

## 试用：导入 trace 并评测

```bash
python -c "
from agent_tool_harness.trace_import import import_trace_as_evidence
from agent_tool_harness.core_evaluation import CoreEvaluation, EvalSpec

# 导入 example trace
evidence = import_trace_as_evidence('examples/trace_import/native_trace.json')
trace = evidence.trace
print(f'已导入: scenario={trace.scenario_id}')

# 运行确定性检查
eval_spec = EvalSpec(
    id=trace.scenario_id, name=trace.scenario_id,
    category='knowledge_search', split='dev', realism_level='recorded',
    complexity='simple', source='external_runner',
    user_prompt='Find root cause and recommendation',
    initial_context={}, verifiable_outcome={},
    success_criteria=['identify root cause', 'provide recommendation'],
    expected_tool_behavior={}, judge={},
)
result = CoreEvaluation().evaluate(evidence, eval_spec)
print(f'评测通过: {result.passed}')
for f in result.findings:
    print(f'  [{f.severity}] {f.message[:140]}')
"
```

## 试用：mock replay demo

```bash
# 审计工具契约
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out /tmp/harness-demo/audit

# mock replay
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out /tmp/harness-demo/good --mock-path good

# 查看报告
cat /tmp/harness-demo/good/report.md
```

## 下一步

- 接入你自己的 trace：[USER_GUIDE](USER_GUIDE.md)
- 看懂报告：[REPORT_GUIDE](REPORT_GUIDE.md)
- 浏览更多示例：[examples/README.md](../examples/README.md)
- 配置真实 LLM judge（可选）：[PROVIDER_CONFIG](PROVIDER_CONFIG.md)
- 全部文档：[INDEX](INDEX.md)
