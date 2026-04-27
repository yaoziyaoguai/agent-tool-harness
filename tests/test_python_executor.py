from agent_tool_harness.config.loader import load_tools
from agent_tool_harness.tools.registry import ToolRegistry


def test_python_tool_executor_calls_demo_tool():
    tools = load_tools("examples/runtime_debug/tools.yaml")
    registry = ToolRegistry(tools)

    result = registry.execute(
        "runtime_trace_event_chain",
        {"trace_id": "trace-demo-001", "focus": "input_boundary"},
    )

    assert result.success is True
    assert result.content["summary"]
    assert result.content["evidence"][0]["id"] == "ev-17"
    assert result.content["next_action"]
