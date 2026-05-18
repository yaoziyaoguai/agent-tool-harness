"""v3.6 P4: Portfolio 报告渲染 —— PortfolioFinding + ToolImprovementBrief → Markdown/JSON。

架构边界
--------
- **负责**：将 PortfolioFinding 和 ToolImprovementBrief 渲染为 Markdown 节或 JSON dict。
- **不负责**：不修改 finding、不生成完整报告（那是 MarkdownReport 的事）。
- **集成方式**：通过 delegation 接入 MarkdownReport 和 core_report_bridge。
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Portfolio Finding → Markdown
# ---------------------------------------------------------------------------


def _severity_icon(severity: str) -> str:
    """严重度图标映射。"""
    return {
        "critical": "🔴",
        "high": "🟠",
        "medium": "🟡",
        "warning": "⚠️",
        "low": "🔵",
        "info": "ℹ️",
    }.get(severity, "•")


def render_portfolio_review_markdown(
    portfolio_findings: list,
) -> str:
    """将 PortfolioFinding 列表渲染为 Markdown 节。

    Args:
        portfolio_findings: PortfolioFinding 列表

    Returns:
        Markdown 字符串，无 finding 时返回空字符串
    """
    if not portfolio_findings:
        return ""

    # 按 check_name 分组
    groups: dict[str, list] = {}
    for pf in portfolio_findings:
        groups.setdefault(pf.check_name, []).append(pf)

    check_labels: dict[str, str] = {
        "namespacing_consistency": "命名空间一致性",
        "overlapping_tools": "工具重叠",
        "shallow_wrappers": "浅层包装",
        "missing_higher_level": "缺失高层工具",
        "resource_grouping": "资源分组合理性",
    }

    lines = ["## 工具组合评审 (Tool Portfolio Review)", ""]

    for check_name, items in groups.items():
        label = check_labels.get(check_name, check_name)
        lines.append(f"### {label}")
        lines.append("")

        for pf in items:
            icon = _severity_icon(pf.severity)
            lines.append(f"- {icon} **[{pf.severity}]** {pf.description}")
            if pf.affected_tools:
                affected = "`, `".join(pf.affected_tools[:5])
                lines.append(f"  - 受影响工具: `{affected}`")
            if pf.suggestion:
                lines.append(f"  - 建议: {pf.suggestion}")
            if pf.evidence:
                for ev in pf.evidence[:3]:
                    lines.append(f"  - 证据: `{ev}`")
            lines.append("")

    return "\n".join(lines)


def render_improvement_brief_markdown(
    briefs: list,
) -> str:
    """将 ToolImprovementBrief 列表渲染为 Markdown 节。

    Args:
        briefs: ToolImprovementBrief 列表

    Returns:
        Markdown 字符串，无 brief 时返回空字符串
    """
    if not briefs:
        return ""

    priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_briefs = sorted(
        briefs, key=lambda b: priority_order.get(b.priority, 99)
    )

    lines = ["## 工具改进建议 (Tool Improvement Briefs)", ""]

    for brief in sorted_briefs:
        icon = _severity_icon(brief.priority)
        lines.append(
            f"### {brief.tool_name} {icon} (优先级: {brief.priority}, "
            f"类别: {brief.category})"
        )
        lines.append("")
        lines.append(f"- **当前状态**: {brief.current_state}")
        lines.append(f"- **建议状态**: {brief.recommended_state}")
        lines.append(f"- **理由**: {brief.rationale}")

        # 证据
        evidence_parts: list[str] = []
        if brief.evidence.finding_ids:
            n = len(brief.evidence.finding_ids)
            evidence_parts.append(
                f"{n} 个相关发现 ({', '.join(brief.evidence.finding_ids[:3])}"
                + (" 等" if n > 3 else "")
                + ")"
            )
        if brief.evidence.metric_values:
            metrics_str = ", ".join(
                f"{k}={v}" for k, v in
                list(brief.evidence.metric_values.items())[:5]
            )
            evidence_parts.append(f"指标: {metrics_str}")
        if brief.evidence.transcript_signal_types:
            evidence_parts.append(
                f"困惑信号: {', '.join(brief.evidence.transcript_signal_types)}"
            )
        if evidence_parts:
            lines.append(f"- **证据**: {'; '.join(evidence_parts)}")

        lines.append(f"- **工作量估计**: {brief.effort_estimate}")
        lines.append("")

    return "\n".join(lines)


def render_portfolio_analysis_markdown(
    portfolio_findings: list,
    improvement_briefs: list,
) -> str:
    """组合渲染 Portfolio Review + Improvement Briefs。

    Args:
        portfolio_findings: PortfolioFinding 列表
        improvement_briefs: ToolImprovementBrief 列表

    Returns:
        完整 Markdown 节
    """
    parts: list[str] = []

    review_section = render_portfolio_review_markdown(portfolio_findings)
    if review_section:
        parts.append(review_section)

    brief_section = render_improvement_brief_markdown(improvement_briefs)
    if brief_section:
        parts.append(brief_section)

    return "\n\n".join(parts) if parts else ""


def portfolio_report_section(
    portfolio_findings: list,
    improvement_briefs: list | None = None,
):
    """把 portfolio review / improvement brief 暴露为统一 ReportSection。

    portfolio 模块保留“finding + brief 只是建议、不会自动修改 tool spec”的领域
    边界；composer 只负责展示这个 section。
    """

    from agent_tool_harness.reports.section_contract import (
        PRIORITY_PORTFOLIO,
        RenderedSection,
        ReportSection,
    )

    briefs = improvement_briefs or []

    def _render() -> RenderedSection:
        return RenderedSection(
            markdown=render_portfolio_analysis_markdown(portfolio_findings, briefs),
            json_data=render_portfolio_analysis_json(portfolio_findings, briefs),
        )

    return ReportSection(
        section_id="portfolio",
        title="Tool Portfolio Review",
        render=_render,
        priority=PRIORITY_PORTFOLIO,
    )


# ---------------------------------------------------------------------------
# Portfolio Finding → JSON
# ---------------------------------------------------------------------------


def render_portfolio_review_json(
    portfolio_findings: list,
) -> list[dict[str, Any]]:
    """将 PortfolioFinding 列表序列化为 JSON 兼容 dict 列表。"""
    result: list[dict[str, Any]] = []
    for pf in portfolio_findings:
        result.append({
            "check_name": pf.check_name,
            "severity": pf.severity,
            "affected_tools": pf.affected_tools,
            "description": pf.description,
            "suggestion": pf.suggestion,
            "evidence": pf.evidence,
        })
    return result


def render_improvement_brief_json(
    briefs: list,
) -> list[dict[str, Any]]:
    """将 ToolImprovementBrief 列表序列化为 JSON 兼容 dict 列表。"""
    result: list[dict[str, Any]] = []
    for brief in briefs:
        result.append({
            "tool_name": brief.tool_name,
            "priority": brief.priority,
            "category": brief.category,
            "evidence": {
                "finding_ids": brief.evidence.finding_ids,
                "metric_values": brief.evidence.metric_values,
                "task_outcome_ids": brief.evidence.task_outcome_ids,
                "transcript_signal_types": brief.evidence.transcript_signal_types,
            },
            "current_state": brief.current_state,
            "recommended_state": brief.recommended_state,
            "rationale": brief.rationale,
            "effort_estimate": brief.effort_estimate,
        })
    return result


def render_portfolio_analysis_json(
    portfolio_findings: list,
    improvement_briefs: list,
) -> dict[str, Any]:
    """组合渲染 JSON。

    Returns:
        {"portfolio_review": [...], "improvement_briefs": [...]}
    """
    return {
        "portfolio_review": render_portfolio_review_json(portfolio_findings),
        "improvement_briefs": render_improvement_brief_json(improvement_briefs),
    }
