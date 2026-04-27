from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.config.loader import load_evals, load_project, load_tools
from agent_tool_harness.runner.eval_runner import EvalRunner


def test_report_contains_required_sections(tmp_path):
    EvalRunner().run(
        load_project("examples/runtime_debug/project.yaml"),
        load_tools("examples/runtime_debug/tools.yaml"),
        load_evals("examples/runtime_debug/evals.yaml"),
        MockReplayAdapter("good"),
        tmp_path,
    )

    report = (tmp_path / "report.md").read_text(encoding="utf-8")

    assert "Tool Design Audit" in report
    assert "Eval Quality Audit" in report
    assert "Agent Tool-Use Eval" in report
    assert "Transcript-derived Diagnosis" in report
    assert "Improvement Suggestions" in report
