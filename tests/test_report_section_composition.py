"""v3.1-v3.6 report section 共存的架构保护测试。

这些测试不引入新功能，只刻画当前报告路径的真实边界：v3.1-v3.3 已进入
``MarkdownReport.render_from_core``，v3.4-v3.6 仍通过独立 renderer 拼接。
后续重构 contract/composer 时必须保持这些 section 可共存，且不得修改输入对象。
"""

from __future__ import annotations

import json

from agent_tool_harness.analysis.render import render_analysis_json
from agent_tool_harness.core_contract import (
    EvaluationResult,
    ExecutionTrace,
    ReportSummary,
    RuleFinding,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.core_report_bridge import (
    evaluation_result_to_report_dict,
    report_insight_to_json_dict,
    report_summary_to_report_dict,
    suite_result_to_json_dict,
    task_outcome_to_json_dict,
)
from agent_tool_harness.portfolio.improvement_brief import (
    EvidenceRef,
    ToolImprovementBrief,
)
from agent_tool_harness.portfolio.portfolio_review import PortfolioFinding
from agent_tool_harness.portfolio.render import render_portfolio_analysis_json
from agent_tool_harness.regression.diff_schema import (
    FindingDiff,
    MetricDiff,
    RegressionReport,
    RegressionWarning,
    SuiteDiff,
    TaskOutcomeDiff,
    regression_report_to_dict,
)
from agent_tool_harness.regression.regression_report import render_regression_markdown
from agent_tool_harness.reports.markdown_report import MarkdownReport
from agent_tool_harness.reports.report_insight import ReportInsight
from agent_tool_harness.suite_eval.suite_result import (
    CaseResult,
    SuiteMetrics,
    SuiteResult,
    SuiteScorecard,
)
from agent_tool_harness.task_eval.task_evaluator import TaskOutcome
from agent_tool_harness.task_eval.verifiers import VerifierResult


def test_v31_to_v36_sections_can_coexist_in_one_markdown_document():
    """当前各版本 section 能共存；后续 composer 重构必须保持这一点。"""

    trace = _trace()
    evaluation = _evaluation_result(passed=False)
    insight = ReportInsight.from_eval(trace, evaluation, signal_quality="recorded_trajectory")
    task_outcome = _task_outcome()
    suite_result = _suite_result()
    regression_report = _regression_report()
    analysis_findings = _analysis_findings()
    portfolio_findings = _portfolio_findings()
    improvement_briefs = _improvement_briefs()

    report = MarkdownReport()
    base_markdown = report.render_from_core(
        results=[evaluation_result_to_report_dict(evaluation)],
        report_summary=report_summary_to_report_dict(_summary()),
        signal_quality="recorded_trajectory",
        insight=insight,
        task_outcome=task_outcome,
        suite_result=suite_result,
    )
    composed_markdown = "\n".join([
        base_markdown.rstrip(),
        render_regression_markdown(regression_report),
        report.render_analysis_section(analysis_findings),
        report.render_portfolio_section(portfolio_findings, improvement_briefs),
        "",
    ])

    expected_headings = [
        "## Scorecard",
        "## Metrics",
        "## Task Outcome",
        "## Suite Scorecard",
        "## Suite Metrics",
        "## Regression Warnings",
        "## Transcript & Context Analysis",
        "## 工具组合评审 (Tool Portfolio Review)",
        "## 工具改进建议 (Tool Improvement Briefs)",
        "## Review Decision",
    ]
    for heading in expected_headings:
        assert heading in composed_markdown

    # 这些顶层 heading 在同一报告中必须只有一份，避免 composer 重构后重复插入。
    for unique_heading in [
        "## Task Outcome",
        "## Suite Scorecard",
        "## Transcript & Context Analysis",
        "## 工具组合评审 (Tool Portfolio Review)",
        "## 工具改进建议 (Tool Improvement Briefs)",
        "## Review Decision",
    ]:
        assert _count_exact_heading(composed_markdown, unique_heading) == 1

    _assert_markdown_tables_are_not_broken(composed_markdown)

    # 报告渲染只是派生视图，不得改动 v3.1-v3.6 输入对象的状态。
    assert evaluation.passed is False
    assert task_outcome.status == "success"
    assert suite_result.suite_scorecard.suite_passed is True
    assert regression_report.is_regression is True
    assert improvement_briefs[0].recommended_state == "添加 limit 参数"


def test_report_sections_json_shapes_are_serializable_without_state_mutation():
    """各 section 的 JSON path 可以共存序列化，且不改变业务对象。"""

    trace = _trace()
    evaluation = _evaluation_result(passed=True)
    insight = ReportInsight.from_eval(trace, evaluation, signal_quality="recorded_trajectory")
    task_outcome = _task_outcome()
    suite_result = _suite_result()
    regression_report = _regression_report()
    analysis_findings = _analysis_findings()
    portfolio_findings = _portfolio_findings()
    improvement_briefs = _improvement_briefs()

    payload = {
        "insight": report_insight_to_json_dict(insight),
        "task_outcome": task_outcome_to_json_dict(task_outcome),
        "suite_result": suite_result_to_json_dict(suite_result),
        "regression": regression_report_to_dict(regression_report),
        "analysis": render_analysis_json(analysis_findings),
        "portfolio": render_portfolio_analysis_json(portfolio_findings, improvement_briefs),
    }

    json.dumps(payload, ensure_ascii=False)
    assert payload["task_outcome"]["status"] == "success"
    assert payload["suite_result"]["suite_scorecard"]["suite_passed"] is True
    assert payload["regression"]["is_regression"] is True
    assert payload["portfolio"]["improvement_briefs"][0]["recommended_state"] == (
        "添加 limit 参数"
    )

    assert evaluation.passed is True
    assert task_outcome.status == "success"
    assert regression_report.is_regression is True
    assert improvement_briefs[0].current_state == "一次返回过多结果"


def test_render_from_core_without_optional_sections_stays_backward_compatible():
    """不传 v3.1-v3.6 可选 section 时，旧 core report 仍保持精简路径。"""

    markdown = MarkdownReport().render_from_core(
        results=[],
        report_summary=report_summary_to_report_dict(_summary()),
        signal_quality="tautological_replay",
    )

    assert "## Agent Tool-Use Eval (Core Flow)" in markdown
    assert "## Review Decision" in markdown
    assert "## Task Outcome" not in markdown
    assert "## Suite Scorecard" not in markdown
    assert "## Regression Warnings" not in markdown
    assert "## Transcript & Context Analysis" not in markdown
    assert "## 工具组合评审 (Tool Portfolio Review)" not in markdown


def _assert_markdown_tables_are_not_broken(markdown: str) -> None:
    lines = markdown.splitlines()
    for index, line in enumerate(lines[:-1]):
        if line.startswith("|") and line.endswith("|"):
            next_line = lines[index + 1]
            if set(next_line.replace("|", "").replace("-", "").replace(" ", "")) == set():
                continue
            assert next_line.startswith("|") and next_line.endswith("|"), (
                f"Markdown table row at line {index + 1} is followed by non-table text: "
                f"{next_line!r}"
            )


def _count_exact_heading(markdown: str, heading: str) -> int:
    return sum(1 for line in markdown.splitlines() if line == heading)


def _trace() -> ExecutionTrace:
    return ExecutionTrace(
        scenario_id="case-architecture",
        tool_calls=[
            ToolCall(
                tool_name="search",
                arguments={"query": "alpha"},
                call_id="call-1",
            )
        ],
        tool_results=[
            ToolResult(
                call_id="call-1",
                tool_name="search",
                status="success",
                output={"items": list(range(30)), "has_more": True},
            )
        ],
        final_answer="alpha",
    )


def _evaluation_result(*, passed: bool) -> EvaluationResult:
    return EvaluationResult(
        scenario_id="case-architecture",
        findings=[
            RuleFinding(
                finding_id="tool_response.search.missing_pagination",
                severity="high",
                category="tool_response",
                message="search response needs pagination",
                evidence_ref="tool_results[0]",
                rule_type="tool_response.missing_pagination",
                rule_passed=False,
            )
        ],
        passed=passed,
        summary="deterministic summary",
    )


def _summary() -> ReportSummary:
    return ReportSummary(
        total_scenarios=1,
        passed=0,
        failed=1,
        errors=0,
        signal_quality="recorded_trajectory",
        generated_at="2026-05-18T00:00:00Z",
    )


def _task_outcome() -> TaskOutcome:
    return TaskOutcome(
        case_id="task-case",
        status="success",
        verifier_results=[
            VerifierResult(
                verifier_name="contains_fact",
                passed=True,
                matched=["alpha"],
                missing=[],
                details="matched required fact",
            )
        ],
        final_answer="alpha",
        details="task succeeded",
        matched=["alpha"],
        missing=[],
    )


def _suite_result() -> SuiteResult:
    return SuiteResult(
        suite_id="suite-architecture",
        total_cases=1,
        task_success_count=1,
        task_success_rate=1.0,
        deterministic_pass_rate=1.0,
        per_case_results=[
            CaseResult(
                case_id="task-case",
                trace_ref="trace.json",
                task_status="success",
                deterministic_passed=True,
                finding_count=1,
                metrics_summary={"tool_call_count": 1},
            )
        ],
        suite_metrics=SuiteMetrics(
            mean_tool_call_count=1.0,
            mean_tool_error_rate=0.0,
            mean_findings_per_case=1.0,
            total_findings=1,
            total_tool_calls=1,
            total_tool_errors=0,
            finding_count_by_category={"tool_response": 1},
            finding_count_by_tool={"search": 1},
        ),
        suite_scorecard=SuiteScorecard(
            suite_passed=True,
            task_success_rate=1.0,
            deterministic_pass_rate=1.0,
            top_failing_categories=["tool_response"],
            top_affected_tools=["search"],
            total_cases=1,
            passed_cases=1,
            failed_cases=0,
        ),
    )


def _regression_report() -> RegressionReport:
    return RegressionReport(
        baseline_id="baseline-v3.6",
        candidate_id="candidate-refactor",
        is_regression=True,
        metric_diffs=[MetricDiff("tool_error_rate", 0.01, 0.04, 0.03, "worse")],
        finding_diffs=[
            FindingDiff(
                "tool_response",
                baseline_count=1,
                candidate_count=3,
                delta=2,
                new_rule_ids=["tool_response.missing_pagination"],
                resolved_rule_ids=[],
            )
        ],
        task_outcome_diffs=[
            TaskOutcomeDiff("task-case", "success", "failed", "new_failure")
        ],
        suite_diff=SuiteDiff(
            suite_id="suite-architecture",
            baseline_task_success_rate=1.0,
            candidate_task_success_rate=0.5,
            task_success_rate_delta=-0.5,
            baseline_deterministic_pass_rate=1.0,
            candidate_deterministic_pass_rate=0.5,
            deterministic_pass_rate_delta=-0.5,
            baseline_total_cases=2,
            candidate_total_cases=2,
            new_failure_count=1,
            new_success_count=0,
        ),
        regression_warnings=[
            RegressionWarning(
                "task_success_drop",
                "high",
                "10pp",
                "50pp drop",
                "Task success dropped",
            )
        ],
    )


def _analysis_findings() -> list[RuleFinding]:
    return [
        RuleFinding(
            finding_id="transcript.search.retry_loop",
            severity="high",
            category="transcript",
            message="search retried repeatedly",
            evidence_ref="tool_calls[0:3]",
            rule_type="transcript.repeated_tool_retry_loop",
            rule_passed=False,
        ),
        RuleFinding(
            finding_id="context.search.response_bloat",
            severity="medium",
            category="context",
            message="search returned too much context",
            evidence_ref="tool_results[0]",
            rule_type="context.response_bloat",
            rule_passed=False,
        ),
    ]


def _portfolio_findings() -> list[PortfolioFinding]:
    return [
        PortfolioFinding(
            check_name="overlapping_tools",
            severity="warning",
            affected_tools=["search", "lookup"],
            description="search and lookup overlap",
            suggestion="clarify tool boundaries",
            evidence=["portfolio.overlap.search.lookup"],
        )
    ]


def _improvement_briefs() -> list[ToolImprovementBrief]:
    return [
        ToolImprovementBrief(
            tool_name="search",
            priority="high",
            category="response",
            evidence=EvidenceRef(
                finding_ids=["context.search.response_bloat"],
                metric_values={"response_size_chars_total": 4096.0},
                task_outcome_ids=["task-case"],
                transcript_signal_types=["response_bloat"],
            ),
            current_state="一次返回过多结果",
            recommended_state="添加 limit 参数",
            rationale="减少上下文浪费",
            effort_estimate="small",
        )
    ]
