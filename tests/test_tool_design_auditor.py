from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.config.tool_spec import ToolSpec


def test_tool_design_audit_finds_bad_tool_contract():
    bad_tool = ToolSpec(
        name="get",
        namespace="",
        version="0.1",
        description="Raw API wrapper.",
        when_to_use="",
        when_not_to_use="",
        input_schema={},
        output_contract={},
        token_policy={},
        side_effects={},
        executor={"type": "python", "module": "demo", "function": "get"},
    )

    result = ToolDesignAuditor().audit([bad_tool])
    audited = result["tools"][0]
    rule_ids = {finding["rule_id"] for finding in audited["findings"]}

    assert audited["overall_score"] < 3.0
    assert "right_tools.low_level_wrapper" in rule_ids
    assert "namespacing.missing_namespace" in rule_ids
    assert "meaningful_context.missing_summary_evidence" in rule_ids
    assert "prompt_spec.weak_input_schema" in rule_ids
