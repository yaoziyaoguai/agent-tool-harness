"""v3.3 P3: Suite-level Markdown/JSON report 测试。"""

from __future__ import annotations

import pytest

from agent_tool_harness.reports.markdown_report import MarkdownReport
from agent_tool_harness.suite_eval.render import suite_result_to_json_dict
from agent_tool_harness.suite_eval.suite_result import (
    CaseResult,
    SuiteMetrics,
    SuiteResult,
    SuiteScorecard,
)


def _make_sample_suite_result() -> SuiteResult:
    """构造示例 SuiteResult 供测试使用。"""
    return SuiteResult(
        suite_id="suite-001",
        total_cases=3,
        task_success_count=2,
        task_failed_count=1,
        task_inconclusive_count=0,
        task_success_rate=2 / 3,
        deterministic_pass_rate=2 / 3,
        per_case_results=[
            CaseResult(
                case_id="case-1",
                trace_ref="traces/t1.json",
                task_status="success",
                deterministic_passed=True,
                finding_count=2,
                error_count=1,
                warning_count=1,
                metrics_summary={"tool_call_count": 5},
            ),
            CaseResult(
                case_id="case-2",
                trace_ref="traces/t2.json",
                task_status="failed",
                deterministic_passed=False,
                finding_count=5,
                error_count=3,
                warning_count=2,
                metrics_summary={"tool_call_count": 10},
            ),
            CaseResult(
                case_id="case-3",
                trace_ref="traces/t3.json",
                task_status="success",
                deterministic_passed=True,
                finding_count=0,
                metrics_summary={"tool_call_count": 3},
            ),
        ],
        suite_metrics=SuiteMetrics(
            mean_tool_call_count=6.0,
            mean_tool_error_rate=0.1,
            mean_findings_per_case=2.33,
            total_findings=7,
            total_tool_calls=18,
            total_tool_errors=2,
            finding_count_by_category={"tool_use": 4, "response": 3},
            finding_count_by_tool={"search": 5, "read": 2},
        ),
        suite_scorecard=SuiteScorecard(
            suite_passed=False,
            task_success_rate=2 / 3,
            deterministic_pass_rate=2 / 3,
            top_failing_categories=["tool_use", "response"],
            top_affected_tools=["search", "read"],
            total_cases=3,
            passed_cases=2,
            failed_cases=1,
        ),
    )


# ---------------------------------------------------------------------------
# Markdown suite section
# ---------------------------------------------------------------------------


def test_markdown_has_suite_scorecard_heading():
    report = MarkdownReport()
    lines = report.render_suite_section(_make_sample_suite_result())
    md = "\n".join(lines)
    assert "## Suite Scorecard" in md


def test_markdown_has_suite_metrics_heading():
    report = MarkdownReport()
    lines = report.render_suite_section(_make_sample_suite_result())
    md = "\n".join(lines)
    assert "## Suite Metrics" in md


def test_markdown_has_per_case_summary():
    report = MarkdownReport()
    lines = report.render_suite_section(_make_sample_suite_result())
    md = "\n".join(lines)
    assert "## Per-Case Summary" in md
    assert "case-1" in md
    assert "case-2" in md
    assert "case-3" in md


def test_markdown_contains_scorecard_data():
    report = MarkdownReport()
    lines = report.render_suite_section(_make_sample_suite_result())
    md = "\n".join(lines)
    assert "FAIL" in md  # suite_passed=False
    assert "3" in md  # total_cases
    assert "66.67%" in md  # task_success_rate


def test_markdown_contains_top_categories():
    report = MarkdownReport()
    lines = report.render_suite_section(_make_sample_suite_result())
    md = "\n".join(lines)
    assert "## Top Failing Categories" in md
    assert "tool_use" in md
    assert "## Top Affected Tools" in md
    assert "search" in md


def test_markdown_non_suite_result_returns_empty():
    report = MarkdownReport()
    lines = report.render_suite_section("not a suite result")
    assert lines == []


# ---------------------------------------------------------------------------
# JSON suite result
# ---------------------------------------------------------------------------


def test_json_has_suite_id():
    data = suite_result_to_json_dict(_make_sample_suite_result())
    assert data["suite_id"] == "suite-001"


def test_json_has_counts():
    data = suite_result_to_json_dict(_make_sample_suite_result())
    assert data["total_cases"] == 3
    assert data["task_success_count"] == 2
    assert data["task_failed_count"] == 1
    assert data["task_inconclusive_count"] == 0


def test_json_has_rates():
    data = suite_result_to_json_dict(_make_sample_suite_result())
    assert data["task_success_rate"] == pytest.approx(2 / 3)
    assert data["deterministic_pass_rate"] == pytest.approx(2 / 3)


def test_json_has_suite_scorecard():
    data = suite_result_to_json_dict(_make_sample_suite_result())
    sc = data["suite_scorecard"]
    assert sc["suite_passed"] is False
    assert sc["total_cases"] == 3
    assert sc["passed_cases"] == 2
    assert sc["top_failing_categories"] == ["tool_use", "response"]


def test_json_has_suite_metrics():
    data = suite_result_to_json_dict(_make_sample_suite_result())
    m = data["suite_metrics"]
    assert m["mean_tool_call_count"] == 6.0
    assert m["total_findings"] == 7
    assert m["total_tool_calls"] == 18
    assert m["finding_count_by_category"] == {"tool_use": 4, "response": 3}


def test_json_has_per_case_results():
    data = suite_result_to_json_dict(_make_sample_suite_result())
    pcr = data["per_case_results"]
    assert len(pcr) == 3
    assert pcr[0]["case_id"] == "case-1"
    assert pcr[0]["task_status"] == "success"
    assert pcr[1]["deterministic_passed"] is False


def test_json_non_suite_result_returns_empty():
    data = suite_result_to_json_dict({"not": "a suite result"})
    assert data == {}


def test_json_empty_suite_result():
    empty = SuiteResult(suite_id="empty", total_cases=0)
    data = suite_result_to_json_dict(empty)
    assert data["suite_id"] == "empty"
    assert data["total_cases"] == 0
    assert data["per_case_results"] == []
