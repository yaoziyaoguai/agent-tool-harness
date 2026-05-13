# Fake CLI Agent Example

用于验证 CLIAgentAdapter → Core Flow 端到端闭环的 fake CLI agent 示例。

## 架构边界

- **fake_agent.py**: 模拟 CLI agent——读取 scenario input JSON，调用 available_tools
  中的所有工具，产出 native ExecutionTrace JSON。
- **project.yaml**: 工具定义（仅供 RuleJudge 使用，fake_agent.py 不读取）。
- **evals.yaml**: 评测场景定义。

所有行为 deterministic，零网络依赖。

## 用法

### 1. 直接运行 fake_agent.py

```bash
echo '{"scenario_id":"test","available_tools":["knowledge.search"]}' > /tmp/input.json
python fake_agent.py --input /tmp/input.json --trace-out /tmp/trace.json
cat /tmp/trace.json
```

### 2. 通过 CLIAgentAdapter 运行

```python
from agent_tool_harness.cli_agent import CLIAgentAdapter, CLIAgentAdapterConfig
from agent_tool_harness.core_contract import ScenarioSpec

config = CLIAgentAdapterConfig(
    command=["python", "fake_agent.py", "--input", "{input_path}", "--trace-out", "{trace_output_path}"],
    working_dir="examples/cli_agent_fake",
    timeout_seconds=30,
)

adapter = CLIAgentAdapter(config)
result = adapter.run(
    ScenarioSpec(scenario_id="test", goal="test goal", available_tools=["knowledge.search"]),
    output_dir="/tmp/agent2harness-test",
)
print(result.execution_trace)
```

### 3. 通过 assembly Core Flow 运行

```python
from agent_tool_harness.assembly import build_cli_agent_core_flow
from agent_tool_harness.cli_agent import CLIAgentAdapterConfig
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.tool_spec import ToolSpec

# 加载 tool specs 和 eval spec（省略 YAML 加载细节）
result = build_cli_agent_core_flow(
    tool_specs=tool_specs,
    eval_spec=eval_spec,
    cli_agent_config=CLIAgentAdapterConfig(
        command=["python", "fake_agent.py", "--input", "{input_path}", "--trace-out", "{trace_output_path}"],
        working_dir="examples/cli_agent_fake",
    ),
    output_dir="/tmp/cli-agent-test",
)
print(f"passed: {result.eval_result.passed}")
print(f"signal_quality: {result.signal_quality}")
```

## Signal Quality

此 example 走 CLI agent 路径，signal_quality = `recorded_trajectory`——trace
来自 fake CLI agent 的运行时记录，不是 mock replay。

## ReviewDecision

此 example 产出 EvaluationResult（含 RuleFinding），但不生成 ReviewDecision。
ReviewDecision 必须由人工 Reviewer 显式创建。
