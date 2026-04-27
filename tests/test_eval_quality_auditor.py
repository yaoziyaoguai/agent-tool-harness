from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor
from agent_tool_harness.config.eval_spec import EvalSpec


def test_eval_quality_audit_finds_weak_eval():
    weak_eval = EvalSpec(
        id="weak",
        name="Weak sandbox",
        category="demo",
        split="scratch",
        realism_level="toy",
        complexity="single_step",
        source="manual",
        user_prompt="请调用 runtime_trace_event_chain",
        initial_context={},
        verifiable_outcome={},
        success_criteria=[],
        expected_tool_behavior={"required_tools": ["runtime_trace_event_chain"]},
        judge={"rules": []},
    )

    result = EvalQualityAuditor().audit([weak_eval])
    audited = result["evals"][0]
    rule_ids = {finding["rule_id"] for finding in audited["findings"]}

    assert audited["overall_score"] < 3.5
    assert audited["runnable"] is False
    assert "realism.cheating_prompt" in rule_ids
    assert "fixture.not_runnable" in rule_ids
    assert "verifiability.missing_outcome" in rule_ids
