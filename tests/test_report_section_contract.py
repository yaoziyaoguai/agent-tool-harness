"""ReportSection contract 的架构边界测试。

这些测试保护“composer 只认识 section contract，不认识业务模块内部对象”的设计。
每个 adapter 可以消费自己的领域对象，但输出必须是稳定、可序列化、不可变输入的
``ReportSection``。
"""

from __future__ import annotations

import json

from agent_tool_harness.analysis.render import analysis_report_section
from agent_tool_harness.core_contract import RuleFinding
from agent_tool_harness.portfolio.improvement_brief import (
    EvidenceRef,
    ToolImprovementBrief,
)
from agent_tool_harness.portfolio.portfolio_review import PortfolioFinding
from agent_tool_harness.portfolio.render import portfolio_report_section
from agent_tool_harness.regression.diff_schema import MetricDiff, RegressionReport
from agent_tool_harness.regression.regression_report import regression_report_section
from agent_tool_harness.reports.section_contract import (
    RenderedSection,
    ReportSection,
    render_sections_markdown,
    sections_to_json_dict,
)
from agent_tool_harness.suite_eval.render import suite_report_section
from agent_tool_harness.suite_eval.suite_result import (
    CaseResult,
    SuiteMetrics,
    SuiteResult,
    SuiteScorecard,
)
from agent_tool_harness.task_eval.render import task_outcome_report_section
from agent_tool_harness.task_eval.task_evaluator import TaskOutcome


def test_sections_render_in_stable_priority_order():
    """section ordering 由 contract 统一控制，不依赖调用方拼接顺序。"""

    low = ReportSection("later", "Later", lambda: RenderedSection("## Later\n", {}), 20)
    high = ReportSection("earlier", "Earlier", lambda: RenderedSection("## Earlier\n", {}), 10)

    markdown = render_sections_markdown([low, high])
    payload = sections_to_json_dict([low, high])

    assert markdown.index("## Earlier") < markdown.index("## Later")
    assert list(payload) == ["earlier", "later"]
    json.dumps(payload)


def test_domain_adapters_return_serializable_sections_without_mutating_inputs():
    """v3.2-v3.6 adapters 输出统一 contract，且不修改领域对象。"""

    task = TaskOutcome(case_id="task-1", status="success", final_answer="ok")
    suite = _suite_result()
    regression = RegressionReport(
        baseline_id="b",
        candidate_id="c",
        is_regression=False,
        metric_diffs=[MetricDiff("tool_error_rate", 0.0, 0.1, 0.1, "worse")],
    )
    analysis_findings = [
        RuleFinding(
            finding_id="context.search.response_bloat",
            severity="high",
            category="context",
            message="large output",
            evidence_ref="tool_results[0]",
            rule_type="context.response_bloat",
        )
    ]
    portfolio_findings = [
        PortfolioFinding(
            check_name="overlapping_tools",
            severity="warning",
            affected_tools=["search", "lookup"],
            description="overlap",
            suggestion="clarify",
        )
    ]
    briefs = [
        ToolImprovementBrief(
            tool_name="search",
            priority="high",
            category="response",
            evidence=EvidenceRef(finding_ids=["context.search.response_bloat"]),
            current_state="large output",
            recommended_state="add limit",
            rationale="reduce context",
            effort_estimate="small",
        )
    ]

    sections = [
        task_outcome_report_section(task),
        suite_report_section(suite),
        regression_report_section(regression),
        analysis_report_section(analysis_findings),
        portfolio_report_section(portfolio_findings, briefs),
    ]
    markdown = render_sections_markdown(sections)
    payload = sections_to_json_dict(sections)

    assert "## Task Outcome" in markdown
    assert "## Suite Scorecard" in markdown
    assert "# Regression Report: b → c" in markdown
    assert "## Transcript & Context Analysis" in markdown
    assert "## 工具组合评审 (Tool Portfolio Review)" in markdown
    assert set(payload) == {"task_outcome", "suite_result", "regression", "analysis", "portfolio"}
    json.dumps(payload, ensure_ascii=False)

    assert task.status == "success"
    assert suite.suite_scorecard.suite_passed is True
    assert regression.is_regression is False
    assert briefs[0].recommended_state == "add limit"


def _suite_result() -> SuiteResult:
    return SuiteResult(
        suite_id="suite-1",
        total_cases=1,
        task_success_count=1,
        task_success_rate=1.0,
        deterministic_pass_rate=1.0,
        per_case_results=[
            CaseResult(
                case_id="task-1",
                trace_ref="trace.json",
                task_status="success",
                deterministic_passed=True,
                finding_count=0,
            )
        ],
        suite_metrics=SuiteMetrics(
            mean_tool_call_count=1.0,
            mean_tool_error_rate=0.0,
            mean_findings_per_case=0.0,
            total_findings=0,
            total_tool_calls=1,
            total_tool_errors=0,
        ),
        suite_scorecard=SuiteScorecard(
            suite_passed=True,
            task_success_rate=1.0,
            deterministic_pass_rate=1.0,
            total_cases=1,
            passed_cases=1,
            failed_cases=0,
        ),
    )
