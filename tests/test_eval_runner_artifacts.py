import json

from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.config.loader import load_evals, load_project, load_tools
from agent_tool_harness.runner.eval_runner import EvalRunner


def test_eval_runner_good_and_bad_paths_generate_required_artifacts(tmp_path):
    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")
    evals = load_evals("examples/runtime_debug/evals.yaml")

    good = EvalRunner().run(project, tools, evals, MockReplayAdapter("good"), tmp_path / "good")
    bad = EvalRunner().run(project, tools, evals, MockReplayAdapter("bad"), tmp_path / "bad")

    for run_name, result in {"good": good, "bad": bad}.items():
        out_dir = tmp_path / run_name
        for artifact in EvalRunner.REQUIRED_ARTIFACTS:
            path = out_dir / artifact
            assert path.exists(), f"missing {artifact}"
            assert path.stat().st_size > 0, f"empty {artifact}"
        assert result["metrics"]["executed_evals"] == 1

    good_judge = json.loads((tmp_path / "good" / "judge_results.json").read_text())
    bad_judge = json.loads((tmp_path / "bad" / "judge_results.json").read_text())
    bad_diagnosis = json.loads((tmp_path / "bad" / "diagnosis.json").read_text())

    assert good_judge["results"][0]["passed"] is True
    assert bad_judge["results"][0]["passed"] is False
    assert bad_diagnosis["results"][0]["first_tool"] == "tui_inspect_snapshot"
    assert bad_diagnosis["results"][0]["missing_required_tools"]
