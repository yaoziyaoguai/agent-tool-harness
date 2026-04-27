from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.config.loader import load_evals
from agent_tool_harness.judges.rule_judge import RuleJudge


def test_rule_judge_good_path_passes():
    case = load_evals("examples/runtime_debug/evals.yaml")[0]
    run = AgentRunResult(
        eval_id=case.id,
        final_answer="Root cause: input_boundary. Evidence: ev-17 and ckpt-input-17.",
        tool_calls=[
            {"call_id": "1", "tool_name": "runtime_trace_event_chain", "arguments": {}},
            {"call_id": "2", "tool_name": "runtime_inspect_checkpoint", "arguments": {}},
        ],
        tool_responses=[
            {
                "call_id": "1",
                "tool_name": "runtime_trace_event_chain",
                "response": {"success": True, "content": {"evidence": [{"id": "ev-17"}]}},
            },
            {
                "call_id": "2",
                "tool_name": "runtime_inspect_checkpoint",
                "response": {"success": True, "content": {"evidence": [{"id": "ckpt-input-17"}]}},
            },
        ],
    )

    result = RuleJudge().judge(case, run)

    assert result.passed is True
    assert all(check.passed for check in result.checks)


def test_rule_judge_bad_path_fails():
    case = load_evals("examples/runtime_debug/evals.yaml")[0]
    run = AgentRunResult(
        eval_id=case.id,
        final_answer="Root cause: UI rendering issue.",
        tool_calls=[
            {"call_id": "1", "tool_name": "tui_inspect_snapshot", "arguments": {}},
        ],
        tool_responses=[
            {
                "call_id": "1",
                "tool_name": "tui_inspect_snapshot",
                "response": {"success": True, "content": {"evidence": [{"id": "snap-03"}]}},
            }
        ],
    )

    result = RuleJudge().judge(case, run)
    failed_messages = [check.message for check in result.checks if not check.passed]

    assert result.passed is False
    assert any("runtime_trace_event_chain" in message for message in failed_messages)
    assert any("first tool" in message for message in failed_messages)
