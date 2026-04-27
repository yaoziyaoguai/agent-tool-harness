from agent_tool_harness.eval_generation.generator import EvalGenerator


def test_from_tests_extracts_docstring_xfail_and_marks_not_runnable(tmp_path):
    test_file = tmp_path / "test_runtime_regression.py"
    test_file.write_text(
        '''
import pytest


@pytest.mark.xfail(reason="Needs real trace fixture before becoming runnable")
def test_regression_checkpoint_boundary():
    """User sees stale input after checkpoint restore."""
    assert False
''',
        encoding="utf-8",
    )

    candidates = EvalGenerator().from_tests(tmp_path)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["split"] == "regression"
    assert candidate["runnable"] is False
    assert "initial_context" in candidate["missing_context"]
    assert candidate["verifiable_outcome"]["xfail_reason"] == (
        "Needs real trace fixture before becoming runnable"
    )
    assert candidate["user_prompt"] == "User sees stale input after checkpoint restore."
