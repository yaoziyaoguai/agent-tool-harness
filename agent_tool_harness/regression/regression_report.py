"""v3.4 P4: Regression Report 渲染。

消费 RegressionReport，产出 Markdown 文本。
JSON 序列化入口仍为 diff_schema.regression_report_to_dict()。

架构边界
--------
- **负责**：将 RegressionReport → 人类可读 Markdown。
- **不负责**：不做对比计算（那是 regression_comparator.py 的事）、
  不修改 RegressionReport、不调 LLM、不访问文件系统。
"""

from __future__ import annotations

from agent_tool_harness.regression.diff_schema import RegressionReport

# ---------------------------------------------------------------------------
# 方向符号映射
# ---------------------------------------------------------------------------

_DIRECTION_ICON: dict[str, str] = {
    "better": "↑ better",
    "worse": "↓ worse",
    "neutral": "─",
}

_SEVERITY_ICON: dict[str, str] = {
    "critical": "🔴",
    "high": "🟠",
    "medium": "🟡",
}


def render_regression_markdown(report: RegressionReport) -> str:
    """RegressionReport → Markdown 字符串。

    Args:
        report: 完整的回归对比报告。

    Returns:
        Markdown 文本（可直接写入 .md 文件）。
    """
    lines: list[str] = []

    # 标题
    lines.append(f"# Regression Report: {report.baseline_id} → {report.candidate_id}")
    lines.append("")

    # 总体判断
    if report.is_regression:
        lines.append("> ⚠️ **Regression Detected** — 发现以下回归信号。")
    else:
        lines.append("> ✅ **No Regression Detected** — 所有指标在阈值范围内。")
    lines.append("")

    # --- Summary ---
    if report.metric_diffs:
        lines.extend(_render_metric_summary(report))

    # --- Suite diff ---
    if report.suite_diff:
        lines.extend(_render_suite_section(report))

    # --- Regression Warnings ---
    if report.regression_warnings:
        lines.extend(_render_warnings(report))

    # --- Finding Diffs ---
    if report.finding_diffs:
        lines.extend(_render_finding_diffs(report))

    # --- Newly Failing Tasks ---
    new_failures = [d for d in report.task_outcome_diffs if d.change == "new_failure"]
    if new_failures:
        lines.extend(_render_new_failures(new_failures))

    # --- Newly Succeeding Tasks ---
    new_successes = [d for d in report.task_outcome_diffs if d.change == "new_success"]
    if new_successes:
        lines.extend(_render_new_successes(new_successes))

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 各 section 渲染
# ---------------------------------------------------------------------------


def _render_metric_summary(report: RegressionReport) -> list[str]:
    """Summary 段：指标对比表格。"""
    lines = [
        "## Summary",
        "",
        "| Metric | Baseline | Candidate | Delta | Direction |",
        "|--------|----------|-----------|-------|-----------|",
    ]
    for d in report.metric_diffs:
        icon = _DIRECTION_ICON.get(d.direction, d.direction)
        b_str = _fmt_value(d.baseline_value)
        c_str = _fmt_value(d.candidate_value)
        delta_str = f"+{d.delta:.2f}" if d.delta > 0 else f"{d.delta:.2f}"
        lines.append(
            f"| {d.metric_name} | {b_str} | {c_str} | {delta_str} | {icon} |"
        )
    lines.append("")
    return lines


def _render_suite_section(report: RegressionReport) -> list[str]:
    """Suite diff 段。"""
    sd = report.suite_diff
    assert sd is not None
    lines = [
        "## Suite Comparison",
        "",
        "| Metric | Baseline | Candidate | Delta |",
        "|--------|----------|-----------|-------|",
        f"| Task Success Rate | {sd.baseline_task_success_rate:.1%} "
        f"| {sd.candidate_task_success_rate:.1%} "
        f"| {sd.task_success_rate_delta:+.1%} |",
        f"| Deterministic Pass Rate | {sd.baseline_deterministic_pass_rate:.1%} "
        f"| {sd.candidate_deterministic_pass_rate:.1%} "
        f"| {sd.deterministic_pass_rate_delta:+.1%} |",
        f"| Total Cases | {sd.baseline_total_cases} | {sd.candidate_total_cases} | — |",
        f"| New Failures | — | {sd.new_failure_count} | — |",
        f"| New Successes | — | {sd.new_success_count} | — |",
        "",
    ]
    return lines


def _render_warnings(report: RegressionReport) -> list[str]:
    """Regression Warnings 段。"""
    lines = [
        "## Regression Warnings",
        "",
    ]
    for w in report.regression_warnings:
        icon = _SEVERITY_ICON.get(w.severity, "⚪")
        lines.append(
            f"- {icon} **{w.warning_type}** [{w.severity}]: {w.message}"
        )
    lines.append("")
    return lines


def _render_finding_diffs(report: RegressionReport) -> list[str]:
    """Finding Diff 段。"""
    lines = [
        "## Finding Changes by Category",
        "",
        "| Category | Baseline | Candidate | Delta | New Rules | Resolved Rules |",
        "|----------|----------|-----------|-------|-----------|----------------|",
    ]
    for d in report.finding_diffs:
        new_str = ", ".join(d.new_rule_ids) if d.new_rule_ids else "—"
        resolved_str = ", ".join(d.resolved_rule_ids) if d.resolved_rule_ids else "—"
        delta_str = f"+{d.delta}" if d.delta >= 0 else str(d.delta)
        lines.append(
            f"| {d.category} | {d.baseline_count} | {d.candidate_count} "
            f"| {delta_str} | {new_str} | {resolved_str} |"
        )
    lines.append("")
    return lines


def _render_new_failures(diffs) -> list[str]:
    """Newly Failing Tasks 段。"""
    lines = [
        "## Newly Failing Tasks",
        "",
        "| Case ID | Baseline | Candidate |",
        "|---------|----------|-----------|",
    ]
    for d in diffs:
        b_status = d.baseline_status.upper()
        c_status = d.candidate_status.upper()
        lines.append(f"| {d.case_id} | {b_status} | {c_status} |")
    lines.append("")
    return lines


def _render_new_successes(diffs) -> list[str]:
    """Newly Succeeding Tasks 段。"""
    lines = [
        "## Newly Succeeding Tasks",
        "",
        "| Case ID | Baseline | Candidate |",
        "|---------|----------|-----------|",
    ]
    for d in diffs:
        b_status = d.baseline_status.upper()
        c_status = d.candidate_status.upper()
        lines.append(f"| {d.case_id} | {b_status} | {c_status} |")
    lines.append("")
    return lines


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fmt_value(v: float) -> str:
    """格式化数值：小数保留 2 位，整数不显示小数点。"""
    if v == int(v) and abs(v) < 1_000_000:
        return str(int(v))
    return f"{v:.2f}"
