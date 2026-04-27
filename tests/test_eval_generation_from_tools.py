from agent_tool_harness.config.loader import load_project, load_tools
from agent_tool_harness.eval_generation.generator import EvalGenerator


def test_from_tools_generates_candidates_without_cheating_prompt():
    """验证 from_tools 候选满足三条治理硬约束：

    1. 不出现作弊词 "请调用"，工具名也不能出现在 user_prompt 中（防止泄露答案）；
    2. 至少标注一个 required_tool；
    3. source 标记为 generated_from_tools，便于审核分流。
    """

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


def test_from_tools_candidates_carry_review_workflow_fields():
    """验证候选审核流程所需字段全部存在，且 review_notes 不空。

    这条测试是 P1 阶段“候选审核流程”最小落地的红线：
    - review_status 必须固定为 "candidate"，框架不能私自把候选标成正式 eval；
    - review_notes 至少 1 条，避免审核者拿到“没有任何说明”的候选；
    - difficulty / runnable / missing_context / source 必须保留，便于审核分流。
    """

    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")

    candidates = EvalGenerator().from_tools(project, tools)

    assert candidates, "至少需要一个候选才能验证审核字段"
    valid_difficulties = {"trivial", "single_step", "multi_step", "unknown"}
    for candidate in candidates:
        assert candidate["review_status"] == "candidate"
        assert isinstance(candidate["review_notes"], list)
        assert len(candidate["review_notes"]) >= 1
        for note in candidate["review_notes"]:
            assert isinstance(note, str) and note.strip()
        assert candidate["difficulty"] in valid_difficulties
        assert "runnable" in candidate
        assert "missing_context" in candidate
        assert candidate["source"] == "generated_from_tools"

    # 第二个候选刻意没有 fixture 与 expected_root_cause；review_notes 必须显式提到。
    notes_text = " | ".join(candidates[1]["review_notes"])
    assert "initial_context" in notes_text or "fixture" in notes_text
    assert "expected_root_cause" in notes_text
