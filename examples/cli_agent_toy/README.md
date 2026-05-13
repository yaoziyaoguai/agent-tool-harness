# Toy CLI Agent Example

C10 Level 2 dogfood: 最小非私密 CLI agent。

与 `examples/cli_agent_fake` 的区别：
- **fake_agent**: 对 available_tools 中每个工具都发调用（全量调用）
- **toy_agent**: 根据 scenario goal 关键词选择工具（模拟"按需选工具"）

## 架构边界

- **toy_agent.py**: 读取 scenario input JSON，根据 goal 关键词 deterministic 选择工具，
  产出 native ExecutionTrace JSON。
- **project.yaml**: 工具定义（仅供 RuleJudge 使用）。
- **evals.yaml**: 评测场景定义。

所有行为 deterministic，零网络依赖，不读 .env，不调用真实 LLM。

## 用法

### 直接运行

```bash
echo '{"scenario_id":"toy-test","goal":"搜索错误根因","available_tools":["knowledge.search","trace.lookup"]}' \
  > /tmp/toy-input.json
python examples/cli_agent_toy/toy_agent.py --input /tmp/toy-input.json --trace-out /tmp/toy-trace.json
cat /tmp/toy-trace.json
```

### Dogfood: 通过 assembly Core Flow

```python
from agent_tool_harness.assembly import build_cli_agent_core_flow
from agent_tool_harness.cli_agent import CLIAgentAdapterConfig
from agent_tool_harness.config.loader import load_tools, load_evals

tools = load_tools('examples/cli_agent_toy/project.yaml')
evals = load_evals('examples/cli_agent_toy/evals.yaml')

for eval_spec in evals:
    result = build_cli_agent_core_flow(
        tool_specs=tools,
        eval_spec=eval_spec,
        cli_agent_config=CLIAgentAdapterConfig(
            command=['python', 'examples/cli_agent_toy/toy_agent.py',
                     '--input', '{input_path}',
                     '--trace-out', '{trace_output_path}'],
        ),
        output_dir='/tmp/agent2harness-toy-dogfood',
    )
    print(f"eval {eval_spec.id}: passed={result.eval_result.passed}")
```

## Signal Quality

signal_quality = `recorded_trajectory`。toy agent 是 deterministic，trace 来自运行时记录。

## ReviewDecision

不自动生成——必须由人工 Reviewer 显式创建。
