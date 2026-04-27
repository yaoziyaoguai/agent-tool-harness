from agent_tool_harness.config.loader import load_project, load_tools
from agent_tool_harness.eval_generation.generator import EvalGenerator


def test_from_tools_generates_candidates_without_cheating_prompt():
    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")

    candidates = EvalGenerator().from_tools(project, tools)

    assert len(candidates) == 3
    for candidate, tool in zip(candidates, tools, strict=True):
        assert "请调用" not in candidate["user_prompt"]
        assert tool.name not in candidate["user_prompt"]
        assert candidate["expected_tool_behavior"]["required_tools"]
        assert candidate["source"] == "generated_from_tools"
    assert candidates[0]["runnable"] is True
    assert candidates[1]["runnable"] is False
    assert "fixture" in candidates[1]["missing_context"]
