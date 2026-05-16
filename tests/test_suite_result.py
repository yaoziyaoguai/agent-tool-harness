"""v3.3 P2: SuiteResult 聚合 + SuiteEvaluator 测试。"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from unittest.mock import MagicMock, patch

import pytest

from agent_tool_harness.core_contract import (
    ExecutionTrace,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.suite_eval.eval_suite import EvalCaseRef, EvalSuite, TraceInputRef
from agent_tool_harness.suite_eval.suite_evaluator import SuiteEvaluator
from agent_tool_harness.suite_eval.suite_result import (
    CaseResult,
    SuiteMetrics,
    SuiteResult,
    SuiteScorecard,
    aggregate_suite_results,
)
from agent_tool_harness.task_eval.task_evaluator import TaskEvaluator

# ---------------------------------------------------------------------------
# SuiteMetrics / SuiteScorecard / SuiteResult 基础
# ---------------------------------------------------------------------------


def test_suite_metrics_defaults():
    m = SuiteMetrics()
    assert m.mean_tool_call_count == 0.0
    assert m.mean_tool_error_rate == 0.0
    assert m.total_findings == 0
    assert m.finding_count_by_category == {}
    assert m.finding_count_by_tool == {}


def test_suite_scorecard_defaults():
    sc = SuiteScorecard(
        suite_passed=False,
        task_success_rate=0.0,
        deterministic_pass_rate=0.0,
    )
    assert sc.suite_passed is False
    assert sc.total_cases == 0


def test_suite_result_frozen():
    sr = SuiteResult(suite_id="s1", total_cases=0)
    with pytest.raises(FrozenInstanceError):
        sr.suite_id = "other"  # type: ignore[misc]


def test_case_result_frozen():
    cr = CaseResult(
        case_id="c1",
        trace_ref="t1.json",
        task_status="success",
        deterministic_passed=True,
    )
    with pytest.raises(FrozenInstanceError):
        cr.case_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# aggregate_suite_results — 空列表
# ---------------------------------------------------------------------------


def test_aggregate_empty():
    result = aggregate_suite_results("empty-suite", [])
    assert result.suite_id == "empty-suite"
    assert result.total_cases == 0
    assert result.task_success_count == 0
    assert result.task_failed_count == 0
    assert result.suite_scorecard.suite_passed is True  # 空 suite 视为通过
    assert result.suite_scorecard.total_cases == 0


# ---------------------------------------------------------------------------
# _make_case_result helper
# ---------------------------------------------------------------------------


def _make_case_result(
    case_id: str,
    task_status: str = "success",
    deterministic_passed: bool = True,
    finding_count: int = 2,
    error_count: int = 0,
    warning_count: int = 1,
    tool_call_count: int = 5,
    tool_error_count: int = 1,
    findings_by_tool: dict | None = None,
    findings_by_category: dict | None = None,
) -> CaseResult:
    return CaseResult(
        case_id=case_id,
        trace_ref=f"traces/{case_id}.json",
        task_status=task_status,
        deterministic_passed=deterministic_passed,
        finding_count=finding_count,
        error_count=error_count,
        warning_count=warning_count,
        metrics_summary={
            "tool_call_count": tool_call_count,
            "tool_error_count": tool_error_count,
            "finding_count_by_tool": findings_by_tool or {},
            "finding_count_by_category": findings_by_category or {},
        },
    )


# ---------------------------------------------------------------------------
# aggregate_suite_results — 单个 case
# ---------------------------------------------------------------------------


def test_aggregate_single_success():
    results = [_make_case_result("c1", task_status="success")]
    sr = aggregate_suite_results("s1", results)
    assert sr.total_cases == 1
    assert sr.task_success_count == 1
    assert sr.task_failed_count == 0
    assert sr.task_success_rate == 1.0
    assert sr.deterministic_pass_rate == 1.0
    assert sr.suite_scorecard.suite_passed is True
    assert sr.suite_metrics.mean_tool_call_count == 5.0
    assert sr.suite_metrics.total_findings == 2


def test_aggregate_single_failed():
    results = [_make_case_result("c1", task_status="failed", deterministic_passed=False)]
    sr = aggregate_suite_results("s1", results)
    assert sr.task_success_count == 0
    assert sr.task_failed_count == 1
    assert sr.task_success_rate == 0.0
    assert sr.suite_scorecard.suite_passed is False


def test_aggregate_single_inconclusive():
    results = [_make_case_result("c1", task_status="inconclusive")]
    sr = aggregate_suite_results("s1", results)
    assert sr.task_success_count == 0
    assert sr.task_inconclusive_count == 1


# ---------------------------------------------------------------------------
# aggregate_suite_results — 多个 case
# ---------------------------------------------------------------------------


def test_aggregate_multiple_mixed():
    results = [
        _make_case_result("c1", task_status="success", deterministic_passed=True,
                          findings_by_tool={"search": 3, "read": 2},
                          findings_by_category={"tool_use": 2}),
        _make_case_result("c2", task_status="failed", deterministic_passed=False,
                          findings_by_tool={"search": 1},
                          findings_by_category={"tool_use": 1, "response": 1}),
        _make_case_result("c3", task_status="success", deterministic_passed=True,
                          findings_by_tool={"read": 1},
                          findings_by_category={"tool_use": 1}),
    ]
    sr = aggregate_suite_results("s1", results)
    assert sr.total_cases == 3
    assert sr.task_success_count == 2
    assert sr.task_failed_count == 1
    assert sr.task_success_rate == pytest.approx(2 / 3)
    assert sr.deterministic_pass_rate == pytest.approx(2 / 3)
    assert sr.suite_scorecard.suite_passed is False  # c2 failed
    assert sr.suite_scorecard.passed_cases == 2
    assert sr.suite_scorecard.failed_cases == 1


def test_aggregate_metrics():
    results = [
        _make_case_result("c1", tool_call_count=10, tool_error_count=2,
                          finding_count=5),
        _make_case_result("c2", tool_call_count=20, tool_error_count=3,
                          finding_count=3),
    ]
    sr = aggregate_suite_results("s1", results)
    assert sr.suite_metrics.total_findings == 8
    assert sr.suite_metrics.total_tool_calls == 30
    assert sr.suite_metrics.total_tool_errors == 5
    assert sr.suite_metrics.mean_tool_call_count == 15.0
    assert sr.suite_metrics.mean_tool_error_rate == pytest.approx(5 / 30)
    assert sr.suite_metrics.mean_findings_per_case == 4.0


def test_aggregate_top_categories_and_tools():
    results = [
        _make_case_result("c1",
                          findings_by_tool={"search": 5, "read": 1},
                          findings_by_category={"tool_use": 3, "response": 2}),
        _make_case_result("c2",
                          findings_by_tool={"read": 3},
                          findings_by_category={"tool_use": 1, "security": 1}),
    ]
    sr = aggregate_suite_results("s1", results)
    # top tools 按 finding 总数排
    assert sr.suite_scorecard.top_affected_tools == ["search", "read"]
    # top categories
    assert "tool_use" in sr.suite_scorecard.top_failing_categories


# ---------------------------------------------------------------------------
# aggregate_suite_results — 边界情况
# ---------------------------------------------------------------------------


def test_aggregate_all_passed_suite_passed_true():
    results = [
        _make_case_result("c1", deterministic_passed=True),
        _make_case_result("c2", deterministic_passed=True),
    ]
    sr = aggregate_suite_results("s1", results)
    assert sr.suite_scorecard.suite_passed is True


def test_aggregate_zero_tool_calls():
    """没有 tool call 时 error_rate 为 0.0，不除零。"""
    results = [_make_case_result("c1", tool_call_count=0, tool_error_count=0)]
    sr = aggregate_suite_results("s1", results)
    assert sr.suite_metrics.mean_tool_error_rate == 0.0


# ---------------------------------------------------------------------------
# SuiteEvaluator.evaluate — mock-based 核心流程
# ---------------------------------------------------------------------------


def _make_minimal_trace(
    scenario_id: str = "s1",
    final_answer: str = "test answer",
    tool_calls: list | None = None,
    tool_results: list | None = None,
) -> ExecutionTrace:
    """构造最小 ExecutionTrace 供 test 使用。"""
    return ExecutionTrace(
        scenario_id=scenario_id,
        final_answer=final_answer,
        tool_calls=tool_calls or [],
        tool_results=tool_results or [],
    )


PATCH_TARGET = "agent_tool_harness.task_eval.eval_case.load_eval_case_from_yaml"


class TestSuiteEvaluatorWithMock:
    """用 mock trace_loader 测试 SuiteEvaluator.evaluate() 核心流程。"""

    def test_evaluate_single_trace_success(self):
        suite = EvalSuite(
            suite_id="s1",
            name="Test Suite",
            cases=[EvalCaseRef(case_path="cases/c1.yaml", case_id="c1")],
            trace_inputs=[TraceInputRef(trace_path="traces/t1.json", case_id="c1")],
        )

        trace = _make_minimal_trace(final_answer="expected output")
        trace_loader = MagicMock(return_value=trace)

        from agent_tool_harness.task_eval.eval_case import EvalCase
        mock_case = EvalCase(case_id="c1", task="test task")

        with patch(PATCH_TARGET, return_value=mock_case):
            evaluator = SuiteEvaluator()
            result = evaluator.evaluate(suite, TaskEvaluator(), trace_loader)

        assert result.suite_id == "s1"
        assert result.total_cases == 1
        assert len(result.per_case_results) == 1
        cr = result.per_case_results[0]
        assert cr.case_id == "c1"
        assert cr.trace_ref == "traces/t1.json"
        # 无 ExpectedOutcome → inconclusive
        assert cr.task_status == "inconclusive"
        trace_loader.assert_called_once_with("traces/t1.json")

    def test_evaluate_multiple_traces(self):
        suite = EvalSuite(
            suite_id="s2",
            name="Multi Trace Suite",
            cases=[
                EvalCaseRef(case_path="cases/c1.yaml", case_id="c1"),
                EvalCaseRef(case_path="cases/c2.yaml", case_id="c2"),
            ],
            trace_inputs=[
                TraceInputRef(trace_path="traces/t1.json", case_id="c1"),
                TraceInputRef(trace_path="traces/t2.json", case_id="c2"),
            ],
        )

        def loader(path: str) -> ExecutionTrace:
            return _make_minimal_trace(final_answer=f"answer for {path}")

        from agent_tool_harness.task_eval.eval_case import EvalCase

        with patch(PATCH_TARGET, side_effect=[
            EvalCase(case_id="c1", task="task 1"),
            EvalCase(case_id="c2", task="task 2"),
        ]):
            evaluator = SuiteEvaluator()
            result = evaluator.evaluate(suite, TaskEvaluator(), loader)

        assert result.total_cases == 2
        assert len(result.per_case_results) == 2
        case_ids = {r.case_id for r in result.per_case_results}
        assert case_ids == {"c1", "c2"}

    def test_evaluate_skips_unmatched_case_id(self):
        """trace 引用的 case_id 不在 suite cases 中时跳过。"""
        suite = EvalSuite(
            suite_id="s3",
            name="Partial Match",
            cases=[EvalCaseRef(case_path="cases/c1.yaml", case_id="c1")],
            trace_inputs=[
                TraceInputRef(trace_path="traces/t1.json", case_id="c1"),
                TraceInputRef(trace_path="traces/t2.json", case_id="nonexistent"),
            ],
        )

        call_count = 0

        def loader(path: str) -> ExecutionTrace:
            nonlocal call_count
            call_count += 1
            return _make_minimal_trace()

        from agent_tool_harness.task_eval.eval_case import EvalCase

        with patch(PATCH_TARGET, return_value=EvalCase(case_id="c1", task="task")):
            evaluator = SuiteEvaluator()
            result = evaluator.evaluate(suite, TaskEvaluator(), loader)

        assert result.total_cases == 1  # 只评测了 c1
        assert call_count == 1

    def test_evaluate_empty_suite(self):
        suite = EvalSuite(suite_id="empty", name="Empty")
        evaluator = SuiteEvaluator()
        result = evaluator.evaluate(suite, TaskEvaluator(), MagicMock())
        assert result.total_cases == 0
        assert result.suite_scorecard.suite_passed is True

    def test_evaluate_with_deterministic_findings(self):
        """验证 CaseResult 携带 finding 统计。"""
        suite = EvalSuite(
            suite_id="s4",
            name="Finding Suite",
            cases=[EvalCaseRef(case_path="cases/c1.yaml", case_id="c1")],
            trace_inputs=[TraceInputRef(trace_path="traces/t1.json", case_id="c1")],
        )

        trace = ExecutionTrace(
            scenario_id="s4",
            final_answer="answer",
            tool_calls=[
                ToolCall(tool_name="search", call_id="1", arguments={}),
                ToolCall(tool_name="read", call_id="2", arguments={}),
            ],
            tool_results=[
                ToolResult(tool_name="search", call_id="1", output={}, status="success"),
                ToolResult(tool_name="read", call_id="2", output={}, status="error"),
            ],
        )

        from agent_tool_harness.task_eval.eval_case import EvalCase

        with patch(PATCH_TARGET, return_value=EvalCase(case_id="c1", task="task")):
            evaluator = SuiteEvaluator()
            result = evaluator.evaluate(suite, TaskEvaluator(), lambda p: trace)

        cr = result.per_case_results[0]
        assert cr.metrics_summary["tool_call_count"] == 2
        assert cr.metrics_summary["tool_error_count"] == 1
        assert cr.metrics_summary["tool_result_count"] == 2
        assert cr.metrics_summary["finding_count_by_tool"] == {"search": 1, "read": 1}
