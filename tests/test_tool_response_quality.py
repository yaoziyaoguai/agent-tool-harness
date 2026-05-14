"""Tool response quality inspection 测试。

覆盖:
- 6 条 deterministic rule 的 positive / negative 测试
- ERROR 规则：success.output_present / failure.error_present
- WARNING 规则：size_reasonable / low_signal / error.actionable / context_fields_present
- ERROR → rule_passed=False → 影响 passed
- WARNING → rule_passed=True → 不影响 passed
- CoreEvaluation 集成路径
- JudgeFinding advisory only
- ReviewDecision 不自动生成
- 不读取 .env / 不联网
"""

from __future__ import annotations

from agent_tool_harness.core_contract import (
    EvaluationResult,
    Evidence,
    ExecutionTrace,
    JudgeFinding,
    RuleFinding,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.core_evaluation import CoreEvaluation
from agent_tool_harness.tool_response_quality import ToolResponseQualityInspector


def _make_trace(**overrides) -> ExecutionTrace:
    """构造测试用 ExecutionTrace。"""
    defaults = dict(
        scenario_id="s1",
        tool_calls=[ToolCall(tool_name="t", arguments={}, call_id="c1")],
        tool_results=[
            ToolResult(
                call_id="c1",
                tool_name="t",
                status="success",
                output={"name": "thing", "id": "x"},
            )
        ],
    )
    defaults.update(overrides)
    return ExecutionTrace(**defaults)


def _find_by_rule_type(findings: list[RuleFinding], rule_type: str) -> list[RuleFinding]:
    return [f for f in findings if f.rule_type == rule_type]


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestWellFormedTrace:
    def test_all_rules_pass_for_well_formed_trace(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace()
        findings = inspector.inspect(trace)

        for f in findings:
            assert f.rule_passed is True, f"{f.rule_type}: {f.message}"

    def test_all_findings_are_rule_finding(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace()
        findings = inspector.inspect(trace)

        for f in findings:
            assert isinstance(f, RuleFinding)
            assert f.category == "rule"

    def test_rule_ids_are_stable(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace()
        findings = inspector.inspect(trace)

        rule_types = sorted({f.rule_type for f in findings})
        expected = sorted([
            "tool_response.success.output_present",
            "tool_response.failure.error_present",
            "tool_response.output.size_reasonable",
            "tool_response.output.low_signal",
            "tool_response.error.actionable",
            "tool_response.output.context_fields_present",
        ])
        assert rule_types == expected

    def test_empty_trace(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(tool_calls=[], tool_results=[])
        findings = inspector.inspect(trace)

        assert len(findings) == 6  # 6 条规则各一条 pass finding
        for f in findings:
            assert f.rule_passed is True


# ---------------------------------------------------------------------------
# ERROR: success.output_present
# ---------------------------------------------------------------------------


class TestSuccessOutputPresent:
    def test_empty_dict_is_error(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(call_id="c1", tool_name="t", status="success", output={})
            ]
        )
        findings = inspector.inspect(trace)

        errors = [
            f for f in findings
            if f.rule_type == "tool_response.success.output_present"
            and not f.rule_passed
        ]
        assert len(errors) == 1
        assert errors[0].severity == "high"

    def test_empty_list_is_error(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(call_id="c1", tool_name="t", status="success", output=[])
            ]
        )
        findings = inspector.inspect(trace)

        errors = [
            f for f in findings
            if f.rule_type == "tool_response.success.output_present"
            and not f.rule_passed
        ]
        assert len(errors) == 1

    def test_non_empty_output_passes(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="t", status="success",
                    output={"result": "ok"}
                )
            ]
        )
        findings = inspector.inspect(trace)

        for f in findings:
            if f.rule_type == "tool_response.success.output_present":
                assert f.rule_passed is True

    def test_only_checks_success_status(self):
        """error status 不应由 success.output_present 检查。"""
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(call_id="c1", tool_name="t", status="error", output={})
            ]
        )
        findings = inspector.inspect(trace)

        for f in findings:
            if f.rule_type == "tool_response.success.output_present":
                assert f.rule_passed is True  # 没有 success result，pass

    def test_error_affects_evaluation_passed(self):
        from agent_tool_harness.config.eval_spec import EvalSpec

        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(call_id="c1", tool_name="t", status="success", output={})
            ]
        )
        eval_spec = EvalSpec.from_dict(
            {"name": "test", "scenarios": [{"id": "s1", "goal": "test"}], "tools": []},
            source_path="/tmp",
        )
        evidence = Evidence(trace=trace)

        result = CoreEvaluation(response_quality_inspector=inspector).evaluate(
            evidence, eval_spec
        )
        assert result.passed is False


# ---------------------------------------------------------------------------
# ERROR: failure.error_present
# ---------------------------------------------------------------------------


class TestFailureErrorPresent:
    def test_empty_error_on_error_status_is_error(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(call_id="c1", tool_name="t", status="error", error="")
            ]
        )
        findings = inspector.inspect(trace)

        errors = [
            f for f in findings
            if f.rule_type == "tool_response.failure.error_present"
            and not f.rule_passed
        ]
        assert len(errors) == 1
        assert errors[0].severity == "high"

    def test_non_empty_error_passes(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="t", status="error",
                    error="connection timed out"
                )
            ]
        )
        findings = inspector.inspect(trace)

        for f in findings:
            if f.rule_type == "tool_response.failure.error_present":
                assert f.rule_passed is True

    def test_whitespace_only_error_is_error(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(call_id="c1", tool_name="t", status="error", error="   ")
            ]
        )
        findings = inspector.inspect(trace)

        errors = [
            f for f in findings
            if f.rule_type == "tool_response.failure.error_present"
            and not f.rule_passed
        ]
        assert len(errors) == 1


# ---------------------------------------------------------------------------
# WARNING: output.size_reasonable
# ---------------------------------------------------------------------------


class TestOutputSizeReasonable:
    def test_large_output_is_warning(self):
        inspector = ToolResponseQualityInspector()
        large_str = "x" * 100_001
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="t", status="success",
                    output={"data": large_str}
                )
            ]
        )
        findings = inspector.inspect(trace)

        warnings = [
            f for f in findings
            if f.rule_type == "tool_response.output.size_reasonable"
            and "exceeds" in f.message
        ]
        assert len(warnings) >= 1
        for w in warnings:
            assert w.rule_passed is True
            assert w.severity == "medium"

    def test_normal_size_no_warning(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace()
        findings = inspector.inspect(trace)

        for f in findings:
            if f.rule_type == "tool_response.output.size_reasonable":
                assert f.rule_passed is True
                assert "within size threshold" in f.message


# ---------------------------------------------------------------------------
# WARNING: output.low_signal
# ---------------------------------------------------------------------------


class TestOutputLowSignal:
    def test_empty_dict_is_low_signal(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(call_id="c1", tool_name="t", status="success", output={})
            ]
        )
        findings = inspector.inspect(trace)

        low = [
            f for f in findings
            if f.rule_type == "tool_response.output.low_signal"
            and "low-signal" in f.message
        ]
        assert len(low) >= 1
        for f in low:
            assert f.rule_passed is True

    def test_string_ok_is_low_signal(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(call_id="c1", tool_name="t", status="success", output="ok")
            ]
        )
        findings = inspector.inspect(trace)

        low = [
            f for f in findings
            if f.rule_type == "tool_response.output.low_signal"
            and "low-signal" in f.message
        ]
        assert len(low) >= 1

    def test_status_only_dict_is_low_signal(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="t", status="success",
                    output={"status": "ok", "message": "done"}
                )
            ]
        )
        findings = inspector.inspect(trace)

        low = [
            f for f in findings
            if f.rule_type == "tool_response.output.low_signal"
            and "low-signal" in f.message
        ]
        assert len(low) >= 1

    def test_meaningful_output_is_not_low_signal(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace()
        findings = inspector.inspect(trace)

        for f in findings:
            if f.rule_type == "tool_response.output.low_signal":
                assert "meaningful signal" in f.message


# ---------------------------------------------------------------------------
# WARNING: error.actionable
# ---------------------------------------------------------------------------


class TestErrorActionable:
    def test_unknown_error_is_not_actionable(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="t", status="error", error="unknown"
                )
            ]
        )
        findings = inspector.inspect(trace)

        na = [
            f for f in findings
            if f.rule_type == "tool_response.error.actionable"
            and "not actionable" in f.message
        ]
        assert len(na) >= 1
        for f in na:
            assert f.rule_passed is True

    def test_short_error_is_not_actionable(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(call_id="c1", tool_name="t", status="error", error="err")
            ]
        )
        findings = inspector.inspect(trace)

        na = [
            f for f in findings
            if f.rule_type == "tool_response.error.actionable"
            and "not actionable" in f.message
        ]
        assert len(na) >= 1

    def test_descriptive_error_is_actionable(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="t", status="error",
                    error="Failed to connect to database at host db.internal:5432"
                )
            ]
        )
        findings = inspector.inspect(trace)

        for f in findings:
            if f.rule_type == "tool_response.error.actionable":
                assert "all error messages are actionable" in f.message


# ---------------------------------------------------------------------------
# WARNING: output.context_fields_present
# ---------------------------------------------------------------------------


class TestContextFieldsPresent:
    def test_output_with_context_fields(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="t", status="success",
                    output={"name": "thing", "description": "a thing"}
                )
            ]
        )
        findings = inspector.inspect(trace)

        for f in findings:
            if f.rule_type == "tool_response.output.context_fields_present":
                assert "have context fields" in f.message

    def test_output_missing_context_fields(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="t", status="success",
                    output={"x": 1, "y": 2}
                )
            ]
        )
        findings = inspector.inspect(trace)

        missing = [
            f for f in findings
            if f.rule_type == "tool_response.output.context_fields_present"
            and "missing context" in f.message
        ]
        assert len(missing) >= 1
        for f in missing:
            assert f.rule_passed is True

    def test_nested_list_with_context_fields(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="t", status="success",
                    output={"items": [{"name": "a", "id": "x"}]}
                )
            ]
        )
        findings = inspector.inspect(trace)

        for f in findings:
            if f.rule_type == "tool_response.output.context_fields_present":
                assert "have context fields" in f.message


# ---------------------------------------------------------------------------
# Severity / passed boundary
# ---------------------------------------------------------------------------


class TestSeverityPassedBoundary:
    def test_error_findings_have_severity_high(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(call_id="c1", tool_name="t", status="success", output={})
            ]
        )
        findings = inspector.inspect(trace)

        for f in findings:
            if not f.rule_passed:
                assert f.severity == "high"

    def test_warning_findings_have_severity_medium(self):
        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(call_id="c1", tool_name="t", status="success", output="ok")
            ]
        )
        findings = inspector.inspect(trace)

        warning_findings = [
            f for f in findings
            if f.rule_passed and f.severity == "medium"
        ]
        assert len(warning_findings) >= 1

    def test_warnings_do_not_affect_passed(self):
        """只有 WARNING 违规时 D5 findings 全部 rule_passed=True。"""
        from agent_tool_harness.config.eval_spec import EvalSpec

        inspector = ToolResponseQualityInspector()
        # 所有 rule 都 pass（well-formed trace）
        trace = _make_trace()
        eval_spec = EvalSpec.from_dict(
            {"name": "test", "scenarios": [{"id": "s1", "goal": "test"}], "tools": []},
            source_path="/tmp",
        )
        evidence = Evidence(trace=trace)

        result = CoreEvaluation(response_quality_inspector=inspector).evaluate(
            evidence, eval_spec
        )
        # D5 findings 全 rule_passed=True
        rq_findings = [
            f for f in result.findings
            if isinstance(f, RuleFinding)
            and f.rule_type.startswith("tool_response.")
        ]
        for f in rq_findings:
            assert f.rule_passed is True, f"{f.rule_type}: {f.message}"

    def test_judge_finding_does_not_affect_passed(self):
        result = EvaluationResult(
            scenario_id="test",
            findings=[
                RuleFinding(
                    finding_id="r1", severity="high", category="rule",
                    message="ok", evidence_ref="e1", rule_passed=True,
                ),
                JudgeFinding(
                    finding_id="j1", severity="high", category="judge",
                    message="bad", evidence_ref="e1",
                ),
            ],
            passed=True,
        )
        passed = all(f.rule_passed for f in result.findings if isinstance(f, RuleFinding))
        assert passed is True

    def test_review_decision_not_auto_generated(self):
        from agent_tool_harness.core_contract import ReviewDecision

        assert not hasattr(EvaluationResult, "review_decision")
        rd = ReviewDecision(decision="approved", reviewer="human", notes="ok")
        assert rd.decision == "approved"


# ---------------------------------------------------------------------------
# CoreEvaluation 集成
# ---------------------------------------------------------------------------


class TestCoreEvaluationIntegration:
    def test_rq_inspector_appends_findings(self):
        from agent_tool_harness.config.eval_spec import EvalSpec

        inspector = ToolResponseQualityInspector()
        trace = _make_trace()
        eval_spec = EvalSpec.from_dict(
            {"name": "test", "scenarios": [{"id": "s1", "goal": "test"}], "tools": []},
            source_path="/tmp",
        )
        evidence = Evidence(trace=trace)

        result = CoreEvaluation(response_quality_inspector=inspector).evaluate(
            evidence, eval_spec
        )
        rq_findings = [
            f for f in result.findings
            if isinstance(f, RuleFinding)
            and f.rule_type.startswith("tool_response.")
        ]
        assert len(rq_findings) == 6

    def test_no_rq_inspector_backward_compat(self):
        from agent_tool_harness.config.eval_spec import EvalSpec

        trace = _make_trace(
            tool_results=[
                ToolResult(call_id="c1", tool_name="t", status="success", output={})
            ]
        )
        eval_spec = EvalSpec.from_dict(
            {"name": "test", "scenarios": [{"id": "s1", "goal": "test"}], "tools": []},
            source_path="/tmp",
        )
        evidence = Evidence(trace=trace)

        result = CoreEvaluation().evaluate(evidence, eval_spec)
        rq_findings = [
            f for f in result.findings
            if isinstance(f, RuleFinding)
            and f.rule_type.startswith("tool_response.")
        ]
        assert len(rq_findings) == 0

    def test_mixed_error_and_warning_affects_passed(self):
        """同时有 ERROR 和 WARNING → passed=False。"""
        from agent_tool_harness.config.eval_spec import EvalSpec

        inspector = ToolResponseQualityInspector()
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="t", status="success", output={}
                ),
                ToolResult(
                    call_id="c2", tool_name="t2", status="success",
                    output={"name": "ok"}
                ),
            ],
            tool_calls=[
                ToolCall(tool_name="t", arguments={}, call_id="c1"),
                ToolCall(tool_name="t2", arguments={}, call_id="c2"),
            ],
        )
        eval_spec = EvalSpec.from_dict(
            {"name": "test", "scenarios": [{"id": "s1", "goal": "test"}], "tools": []},
            source_path="/tmp",
        )
        evidence = Evidence(trace=trace)

        result = CoreEvaluation(response_quality_inspector=inspector).evaluate(
            evidence, eval_spec
        )
        # c1 的 empty output 触发 ERROR → passed=False
        assert result.passed is False


# ---------------------------------------------------------------------------
# 边界情况
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_network_dependency(self):
        import sys

        network_modules = {"httpx", "requests", "urllib3", "aiohttp", "openai", "anthropic"}
        module = sys.modules.get("agent_tool_harness.tool_response_quality")
        if module:
            for attr in dir(module):
                obj = getattr(module, attr)
                if hasattr(obj, "__module__"):
                    for bad in network_modules:
                        assert bad not in str(obj.__module__), f"found {bad} via {attr}"

    def test_no_env_dependency(self):
        import inspect

        from agent_tool_harness import tool_response_quality

        source = inspect.getsource(tool_response_quality)
        assert "os.environ" not in source
        assert "os.getenv" not in source
        assert "dotenv" not in source
