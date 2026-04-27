import pytest
import yaml

from agent_tool_harness.config.loader import ConfigError, load_evals, load_project, load_tools


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


def test_tools_and_evals_support_list_root(tmp_path):
    tools_path = tmp_path / "tools.yaml"
    evals_path = tmp_path / "evals.yaml"
    tools_path.write_text(
        yaml.safe_dump(
            [
                {
                    "name": "lookup",
                    "namespace": "demo",
                    "input_schema": {},
                    "output_contract": {},
                    "token_policy": {},
                    "side_effects": {},
                    "executor": {},
                }
            ]
        ),
        encoding="utf-8",
    )
    evals_path.write_text(
        yaml.safe_dump(
            [
                {
                    "id": "case_1",
                    "user_prompt": "Diagnose the issue from available evidence.",
                    "initial_context": {},
                    "verifiable_outcome": {},
                    "success_criteria": [],
                    "expected_tool_behavior": {},
                    "judge": {},
                    "runnable": "false",
                }
            ]
        ),
        encoding="utf-8",
    )

    tools = load_tools(tools_path)
    evals = load_evals(evals_path)

    assert tools[0].qualified_name == "demo.lookup"
    assert evals[0].runnable is False


def test_load_evals_rejects_duplicate_ids(tmp_path):
    evals_path = tmp_path / "evals.yaml"
    evals_path.write_text(
        yaml.safe_dump(
            {
                "evals": [
                    {"id": "dup", "user_prompt": "First case."},
                    {"id": "dup", "user_prompt": "Second case."},
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match="eval.id must be unique"):
        load_evals(evals_path)


def test_loaders_raise_config_error_for_bad_entry_types(tmp_path):
    tools_path = tmp_path / "tools.yaml"
    evals_path = tmp_path / "evals.yaml"
    tools_path.write_text(yaml.safe_dump({"tools": ["not-a-mapping"]}), encoding="utf-8")
    evals_path.write_text(
        yaml.safe_dump({"evals": [{"id": "bad", "success_criteria": "not-a-list"}]}),
        encoding="utf-8",
    )

    with pytest.raises(ConfigError, match=r"tools\[0\] must be a mapping"):
        load_tools(tools_path)
    with pytest.raises(ConfigError, match=r"success_criteria must be a list"):
        load_evals(evals_path)


def test_loaders_reject_scalar_yaml_roots_with_config_error(tmp_path):
    tools_path = tmp_path / "tools.yaml"
    evals_path = tmp_path / "evals.yaml"
    tools_path.write_text(yaml.safe_dump("not-a-collection"), encoding="utf-8")
    evals_path.write_text(yaml.safe_dump(123), encoding="utf-8")

    with pytest.raises(ConfigError, match="tools.yaml root must be a mapping or list"):
        load_tools(tools_path)
    with pytest.raises(ConfigError, match="evals.yaml root must be a mapping or list"):
        load_evals(evals_path)
