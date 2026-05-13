"""ToolUseInspector 确定性不变量检查的单元测试与 CoreEvaluation 集成测试。

架构边界:
- 所有测试 zero-network, deterministic.
- 不读取 .env, 不调用外部 API.
- ReviewDecision 不由机器自动生成.
- JudgeFinding 为 advisory only，不改变 passed.
"""

from __future__ import annotations

from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.core_contract import (
    EvaluationResult,
    Evidence,
    ExecutionTrace,
    ReviewDecision,
    RuleFinding,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.core_evaluation import CoreEvaluation
from agent_tool_harness.tool_inspection import ToolUseInspector

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _clean_trace() -> ExecutionTrace:
    """返回一个干净的 ExecutionTrace，所有 9 条规则都应通过。"""
    return ExecutionTrace(
        scenario_id="test-001",
        tool_calls=[
            ToolCall(
                call_id="c1",
                tool_name="knowledge.search",
                arguments={"query": "test"},
            ),
            ToolCall(
                call_id="c2",
                tool_name="trace.lookup",
                arguments={"trace_id": "abc123"},
            ),
        ],
        tool_results=[
            ToolResult(
                call_id="c1",
                tool_name="knowledge.search",
                status="success",
                output={"articles": []},
            ),
            ToolResult(
                call_id="c2",
                tool_name="trace.lookup",
                status="success",
                output={"trace": {}},
            ),
        ],
        final_answer="All clear.",
    )


def _minimal_eval_spec() -> EvalSpec:
    return EvalSpec(
        id="test-001",
        name="test scenario",
        category="integration",
        split="test",
        realism_level="mock",
        complexity="low",
        source="test",
        user_prompt="test",
        initial_context={},
        verifiable_outcome={},
        success_criteria=["must_call_tool:knowledge.search"],
        expected_tool_behavior={"required_tools": ["knowledge.search"]},
        judge={
            "rules": [{"type": "must_call_tool", "tool": "knowledge.search"}],
        },
    )


# ---------------------------------------------------------------------------
# 干净的 trace 全部通过
# ---------------------------------------------------------------------------


class TestCleanTraceAllPass:
    """干净的 trace 应让所有 9 条规则都通过。"""

    def test_all_rules_pass_on_clean_trace(self):
        inspector = ToolUseInspector()
        findings = inspector.inspect(_clean_trace())

        assert len(findings) == 9
        for f in findings:
            assert isinstance(f, RuleFinding)
            assert f.rule_passed is True, f"rule {f.finding_id} should pass"
            assert f.severity == "info"

    def test_all_finding_ids_are_stable(self):
        """验证所有 9 个 rule_id 稳定。"""
        expected_ids = {
            "tool_call.call_id.duplicate",
            "tool_result.call_id.duplicate",
            "tool_pair.orphan_call",
            "tool_pair.orphan_result",
            "tool_call.arguments.present",
            "tool_call.arguments.is_object",
            "tool_call.tool_name.non_empty",
            "tool_result.tool_name.non_empty",
            "tool_result.status.valid",
        }
        inspector = ToolUseInspector()
        findings = inspector.inspect(_clean_trace())
        actual_ids = {f.finding_id for f in findings}
        assert actual_ids == expected_ids

    def test_empty_trace_passes_all_rules(self):
        """空的 ExecutionTrace 所有规则也应通过（无数据 = 无违规）。"""
        trace = ExecutionTrace(
            scenario_id="empty",
            tool_calls=[],
            tool_results=[],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)
        assert len(findings) == 9
        for f in findings:
            assert f.rule_passed is True, f"rule {f.finding_id} failed on empty trace"


# ---------------------------------------------------------------------------
# 逐规则 failure 测试
# ---------------------------------------------------------------------------


class TestCallIdDuplicate:
    def test_duplicate_call_id_in_calls_fails(self):
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="a", arguments={}),
                ToolCall(call_id="c1", tool_name="b", arguments={}),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="success"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        f = _find_by_id(findings, "tool_call.call_id.duplicate")
        assert f.rule_passed is False
        assert f.severity == "high"
        assert "c1" in f.message


class TestResultCallIdDuplicate:
    def test_duplicate_call_id_in_results_fails(self):
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="a", arguments={}),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="success"),
                ToolResult(call_id="c1", status="error"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        f = _find_by_id(findings, "tool_result.call_id.duplicate")
        assert f.rule_passed is False
        assert f.severity == "high"


class TestOrphanCall:
    def test_orphan_call_fails(self):
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="a", arguments={}),
                ToolCall(call_id="c2", tool_name="b", arguments={}),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="success"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        f = _find_by_id(findings, "tool_pair.orphan_call")
        assert f.rule_passed is False
        assert f.severity == "high"
        assert "c2" in f.message


class TestOrphanResult:
    def test_orphan_result_fails(self):
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="a", arguments={}),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="success"),
                ToolResult(call_id="c2", status="error"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        f = _find_by_id(findings, "tool_pair.orphan_result")
        assert f.rule_passed is False
        assert f.severity == "high"
        assert "c2" in f.message


class TestArgumentsPresent:
    def test_arguments_none_fails(self):
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="a", arguments=None),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="success"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        f = _find_by_id(findings, "tool_call.arguments.present")
        assert f.rule_passed is False
        assert f.severity == "critical"
        assert "c1" in f.message


class TestArgumentsIsObject:
    def test_arguments_not_dict_fails(self):
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="a", arguments=["not", "a", "dict"]),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="success"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        f = _find_by_id(findings, "tool_call.arguments.is_object")
        assert f.rule_passed is False
        assert f.severity == "critical"

    def test_arguments_none_skipped_by_is_object(self):
        """arguments 为 None 时，arguments.is_object 应通过（由 arguments.present 负责）。"""
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="a", arguments=None),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="success"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        f = _find_by_id(findings, "tool_call.arguments.is_object")
        assert f.rule_passed is True  # None is caught by arguments.present, not here


class TestCallToolNameNonEmpty:
    def test_call_tool_name_empty_fails(self):
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="", arguments={}),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="success"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        f = _find_by_id(findings, "tool_call.tool_name.non_empty")
        assert f.rule_passed is False
        assert f.severity == "critical"

    def test_call_tool_name_whitespace_only_fails(self):
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="   ", arguments={}),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="success"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        f = _find_by_id(findings, "tool_call.tool_name.non_empty")
        assert f.rule_passed is False


class TestResultToolNameNonEmpty:
    def test_result_tool_name_empty_fails(self):
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="a", arguments={}),
            ],
            tool_results=[
                ToolResult(call_id="c1", tool_name="", status="success"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        f = _find_by_id(findings, "tool_result.tool_name.non_empty")
        assert f.rule_passed is False
        assert f.severity == "medium"


class TestStatusValid:
    def test_status_invalid_fails(self):
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="a", arguments={}),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="timeout"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        f = _find_by_id(findings, "tool_result.status.valid")
        assert f.rule_passed is False
        assert f.severity == "medium"
        assert "timeout" in f.message

    def test_status_success_passes(self):
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="a", arguments={}),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="success"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        f = _find_by_id(findings, "tool_result.status.valid")
        assert f.rule_passed is True

    def test_status_error_passes(self):
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="a", arguments={}),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="error"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        f = _find_by_id(findings, "tool_result.status.valid")
        assert f.rule_passed is True


# ---------------------------------------------------------------------------
# 多违规场景
# ---------------------------------------------------------------------------


class TestMultipleViolations:
    def test_multiple_violations_produce_multiple_failed_findings(self):
        """同时存在重复 call_id 和 orphan call 时，两条规则都失败。"""
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="a", arguments={}),
                ToolCall(call_id="c1", tool_name="b", arguments=None),
                ToolCall(call_id="c2", tool_name="c", arguments={}),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="timeout"),
            ],
        )
        inspector = ToolUseInspector()
        findings = inspector.inspect(trace)

        failed = [f for f in findings if f.rule_passed is False]
        assert len(failed) >= 3
        failed_ids = {f.finding_id for f in failed}
        assert "tool_call.call_id.duplicate" in failed_ids
        assert "tool_pair.orphan_call" in failed_ids
        assert "tool_call.arguments.present" in failed_ids
        assert "tool_result.status.valid" in failed_ids


# ---------------------------------------------------------------------------
# CoreEvaluation 集成测试
# ---------------------------------------------------------------------------


class TestCoreEvaluationIntegration:
    """ToolUseInspector 已集成到 CoreEvaluation 中。"""

    def test_inspector_integrated_in_core_evaluation(self):
        """CoreEvaluation 默认包含 trace-level RuleFindings。"""
        trace = _clean_trace()
        evidence = Evidence(trace=trace, signal_quality="test")
        eval_spec = _minimal_eval_spec()

        result = CoreEvaluation().evaluate(evidence, eval_spec)

        assert isinstance(result, EvaluationResult)
        # 应包含 trace-level (9) + eval-level (来自 RuleJudge) 的 RuleFinding
        trace_findings = [
            f for f in result.findings
            if isinstance(f, RuleFinding) and f.finding_id.startswith("tool_")
        ]
        assert len(trace_findings) == 9

    def test_trace_level_finding_failure_flips_passed(self):
        """trace-level RuleFinding 失败时，EvaluationResult.passed 为 False。"""
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="", arguments=None),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="timeout"),
            ],
        )
        evidence = Evidence(trace=trace, signal_quality="test")
        eval_spec = _minimal_eval_spec()

        result = CoreEvaluation().evaluate(evidence, eval_spec)
        # 多个 trace-level 规则失败 → passed 应为 False
        assert result.passed is False

        failed_trace = [
            f for f in result.findings
            if isinstance(f, RuleFinding) and f.rule_passed is False
        ]
        assert len(failed_trace) >= 1

    def test_clean_trace_evaluation_passes(self):
        """干净的 trace + 宽松的 eval_spec → passed = True。"""
        trace = _clean_trace()
        evidence = Evidence(trace=trace, signal_quality="test")
        eval_spec = _minimal_eval_spec()

        result = CoreEvaluation().evaluate(evidence, eval_spec)
        assert result.passed is True

    def test_inspector_can_be_disabled(self):
        """传入 inspector=None 可跳过 trace-level 检查（向后兼容测试场景）。"""
        trace = ExecutionTrace(
            scenario_id="test-001",
            tool_calls=[
                ToolCall(call_id="c1", tool_name="", arguments=None),
            ],
            tool_results=[
                ToolResult(call_id="c1", status="timeout"),
            ],
        )
        evidence = Evidence(trace=trace, signal_quality="test")
        eval_spec = _minimal_eval_spec()

        result = CoreEvaluation(inspector=None).evaluate(evidence, eval_spec)
        # 没有 trace-level 检查，仅 RuleJudge eval-level 规则
        trace_findings = [
            f for f in result.findings
            if f.finding_id.startswith("tool_")
        ]
        assert len(trace_findings) == 0


# ---------------------------------------------------------------------------
# JudgeFinding advisory 边界
# ---------------------------------------------------------------------------


class TestJudgeFindingAdvisory:
    """JudgeFinding 不改变 passed。"""

    def test_judge_finding_does_not_affect_passed(self):
        """即使有 FakeJudgeProvider，passed 仍由 RuleFinding 决定。"""
        from agent_tool_harness.fake_judge import FakeJudgeProvider

        trace = _clean_trace()
        evidence = Evidence(trace=trace, signal_quality="test")
        eval_spec = _minimal_eval_spec()

        fake_judge = FakeJudgeProvider(
            responses={"test-001": {"rationale": "advisory note"}}
        )
        result = CoreEvaluation(judge_provider=fake_judge).evaluate(evidence, eval_spec)

        # 干净 trace 应通过
        assert result.passed is True


# ---------------------------------------------------------------------------
# ReviewDecision 边界
# ---------------------------------------------------------------------------


class TestReviewDecisionBoundary:
    """ReviewDecision 不由机器自动生成。"""

    def test_evaluation_result_does_not_auto_generate_review_decision(self):
        """EvaluationResult 不包含自动生成的 ReviewDecision。"""
        trace = _clean_trace()
        evidence = Evidence(trace=trace, signal_quality="test")

        result = CoreEvaluation().evaluate(evidence, _minimal_eval_spec())
        assert not hasattr(result, "review_decision")

    def test_review_decision_must_be_created_explicitly(self):
        """ReviewDecision 只能通过显式构造创建。"""
        decision = ReviewDecision(
            decision="approved",
            reviewer="human-tester",
            notes="Manual review passed.",
        )
        assert decision.reviewer == "human-tester"
        assert decision.decision == "approved"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _find_by_id(findings: list[RuleFinding], finding_id: str) -> RuleFinding:
    for f in findings:
        if f.finding_id == finding_id:
            return f
    raise AssertionError(f"Finding {finding_id} not found in {[f.finding_id for f in findings]}")
