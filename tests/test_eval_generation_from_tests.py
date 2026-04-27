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

    # 候选审核流程字段：from_tests 也必须落 review_status / review_notes / difficulty。
    # 此处刻意检查 xfail 提醒被加进 notes，避免审核者把 xfail reason 误读为可放宽判定。
    assert candidate["review_status"] == "candidate"
    assert candidate["difficulty"] == "unknown"
    assert isinstance(candidate["review_notes"], list)
    assert len(candidate["review_notes"]) >= 3
    notes_text = " | ".join(candidate["review_notes"])
    assert "initial_context" in notes_text
    assert "expected_tool_behavior" in notes_text
    assert "xfail" in notes_text.lower()
