from agent_tool_harness.config.loader import load_evals, load_project, load_tools


def test_load_project_tools_and_evals_from_yaml():
    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")
    evals = load_evals("examples/runtime_debug/evals.yaml")

    assert project.name == "runtime-debug-demo"
    assert project.evidence_sources
    assert {tool.name for tool in tools} == {
        "runtime_trace_event_chain",
        "runtime_inspect_checkpoint",
        "tui_inspect_snapshot",
    }
    assert tools[0].executor["__base_dir"].endswith("examples/runtime_debug")
    assert evals[0].id == "runtime_input_boundary_regression"
    assert evals[0].judge["rules"]
