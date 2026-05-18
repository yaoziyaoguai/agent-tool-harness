"""Suite report rendering —— v3.3 suite 聚合结果的报告段。

本模块负责理解 SuiteResult 的内部结构，并输出 Markdown / ReportSection。
这样 ``MarkdownReport`` 或未来 composer 只需要消费 section contract，不再直接
耦合 suite_eval 的 dataclass 字段。
"""

from __future__ import annotations


def render_suite_markdown(suite_result) -> str:
    """从 SuiteResult 渲染 Markdown suite 聚合段。"""

    from agent_tool_harness.suite_eval.suite_result import SuiteResult

    if not isinstance(suite_result, SuiteResult):
        return ""

    sc = suite_result.suite_scorecard
    m = suite_result.suite_metrics

    lines: list[str] = []

    passed_mark = "PASS" if sc.suite_passed else "FAIL"
    lines.extend([
        "## Suite Scorecard",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Suite Passed | {passed_mark} |",
        f"| Total Cases | {sc.total_cases} |",
        f"| Passed Cases | {sc.passed_cases} |",
        f"| Failed Cases | {sc.failed_cases} |",
        f"| Task Success Rate | {sc.task_success_rate:.2%} |",
        f"| Deterministic Pass Rate | {sc.deterministic_pass_rate:.2%} |",
    ])

    if sc.top_failing_categories:
        cats = ", ".join(sc.top_failing_categories)
        lines.append(f"| Top Failing Categories | {cats} |")
    if sc.top_affected_tools:
        tools = ", ".join(sc.top_affected_tools)
        lines.append(f"| Top Affected Tools | {tools} |")
    lines.append("")

    lines.extend([
        "## Suite Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Mean Tool Call Count | {m.mean_tool_call_count:.2f} |",
        f"| Mean Tool Error Rate | {m.mean_tool_error_rate:.4f} |",
        f"| Mean Findings Per Case | {m.mean_findings_per_case:.2f} |",
        f"| Total Findings | {m.total_findings} |",
        f"| Total Tool Calls | {m.total_tool_calls} |",
        f"| Total Tool Errors | {m.total_tool_errors} |",
        "",
    ])

    if sc.top_failing_categories:
        lines.append("## Top Failing Categories")
        lines.append("")
        for i, cat in enumerate(sc.top_failing_categories, 1):
            count = m.finding_count_by_category.get(cat, 0)
            lines.append(f"{i}. **{cat}** ({count} findings)")
        lines.append("")

    if sc.top_affected_tools:
        lines.append("## Top Affected Tools")
        lines.append("")
        for i, tool in enumerate(sc.top_affected_tools, 1):
            count = m.finding_count_by_tool.get(tool, 0)
            lines.append(f"{i}. **{tool}** ({count} calls)")
        lines.append("")

    if suite_result.per_case_results:
        lines.extend([
            "## Per-Case Summary",
            "",
            "| Case ID | Trace | Task Status | Deterministic | Findings |",
            "|---------|-------|-------------|---------------|----------|",
        ])
        for cr in suite_result.per_case_results:
            det_status = "PASS" if cr.deterministic_passed else "FAIL"
            lines.append(
                f"| {cr.case_id} | {cr.trace_ref} | {cr.task_status} "
                f"| {det_status} | {cr.finding_count} |"
            )
        lines.append("")

    return "\n".join(lines)


def suite_report_section(suite_result):
    """把 SuiteResult 暴露为统一 ReportSection。

    Suite 模块保留 suite 字段知识；composer 只负责排序和拼接，从而避免主报告
    渲染器直接耦合 suite_eval 内部结构。
    """

    from agent_tool_harness.reports.section_contract import (
        PRIORITY_SUITE_RESULT,
        RenderedSection,
        ReportSection,
    )

    def _render() -> RenderedSection:
        return RenderedSection(
            markdown=render_suite_markdown(suite_result),
            json_data=suite_result_to_json_dict(suite_result),
        )

    return ReportSection(
        section_id="suite_result",
        title="Suite Result",
        render=_render,
        priority=PRIORITY_SUITE_RESULT,
    )


def suite_result_to_json_dict(result) -> dict:
    """把 SuiteResult 序列化为 JSON 兼容 dict。

    Suite 模块拥有 SuiteResult / SuiteScorecard / SuiteMetrics 的字段知识；bridge
    只做兼容转发，从而减少跨模块窥探内部 dataclass 的依赖。
    """

    from agent_tool_harness.suite_eval.suite_result import SuiteResult

    if not isinstance(result, SuiteResult):
        return {}

    sc = result.suite_scorecard
    metrics = result.suite_metrics

    per_case: list[dict] = []
    for case_result in result.per_case_results:
        per_case.append({
            "case_id": case_result.case_id,
            "trace_ref": case_result.trace_ref,
            "task_status": case_result.task_status,
            "deterministic_passed": case_result.deterministic_passed,
            "finding_count": case_result.finding_count,
            "error_count": case_result.error_count,
            "warning_count": case_result.warning_count,
            "metrics_summary": case_result.metrics_summary,
        })

    return {
        "suite_id": result.suite_id,
        "total_cases": result.total_cases,
        "task_success_rate": result.task_success_rate,
        "deterministic_pass_rate": result.deterministic_pass_rate,
        "task_success_count": result.task_success_count,
        "task_failed_count": result.task_failed_count,
        "task_inconclusive_count": result.task_inconclusive_count,
        "suite_scorecard": {
            "suite_passed": sc.suite_passed,
            "task_success_rate": sc.task_success_rate,
            "deterministic_pass_rate": sc.deterministic_pass_rate,
            "top_failing_categories": sc.top_failing_categories,
            "top_affected_tools": sc.top_affected_tools,
            "total_cases": sc.total_cases,
            "passed_cases": sc.passed_cases,
            "failed_cases": sc.failed_cases,
        },
        "suite_metrics": {
            "mean_tool_call_count": metrics.mean_tool_call_count,
            "mean_tool_error_rate": metrics.mean_tool_error_rate,
            "mean_findings_per_case": metrics.mean_findings_per_case,
            "total_findings": metrics.total_findings,
            "total_tool_calls": metrics.total_tool_calls,
            "total_tool_errors": metrics.total_tool_errors,
            "finding_count_by_category": metrics.finding_count_by_category,
            "finding_count_by_tool": metrics.finding_count_by_tool,
        },
        "per_case_results": per_case,
    }
