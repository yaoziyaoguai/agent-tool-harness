"""v3.5 P4: Analysis 报告渲染 —— 将 transcript/context analysis findings 渲染为 Markdown/JSON。

架构边界
--------
- **负责**：将 RuleFinding 列表渲染为 Markdown 节或 JSON 兼容 dict。
- **不负责**：不修改 findings、不生成完整报告（那是 MarkdownReport 的事）、
  不访问文件系统。
- **集成方式**：通过字符串拼接插入到已有 MarkdownReport 中，不做侵入式修改。
"""

from __future__ import annotations

from agent_tool_harness.core_contract import RuleFinding

# ---------------------------------------------------------------------------
# rule_id → 修复建议映射表
# ---------------------------------------------------------------------------

RECOMMENDATION_CATALOG: dict[str, str] = {
    "transcript.repeated_tool_retry_loop": (
        "检查工具描述是否清晰、参数是否合理，避免 Agent 死循环重试同一调用"
    ),
    "transcript.tool_switching_confusion": (
        "检查工具间的职责边界是否模糊，考虑合并或明确区分容易混淆的工具"
    ),
    "transcript.invalid_arg_retry": (
        "检查参数验证逻辑，考虑提供更明确的参数格式说明或 examples"
    ),
    "transcript.no_recovery_after_error": (
        "增强工具的错误信息可行动性，提供 fallback 建议或重试策略"
    ),
    "transcript.final_answer_without_support": (
        "检查 Agent 是否基于工具返回的事实作答，考虑在 prompt 中强化引用要求"
    ),
    "transcript.broad_search_loop": (
        "检查搜索工具的返回粒度，考虑提供更精确的过滤参数以减少 Agent 的试错搜索"
    ),
    "context.response_bloat": (
        "为工具添加分页参数（limit/offset）或简洁模式（summary/verbose），"
        "减少单次返回的数据量"
    ),
    "context.missing_pagination": (
        "为返回列表的工具添加 limit/page/offset 等分页参数，避免一次性返回过多数据"
    ),
    "context.missing_concise_mode": (
        "为工具添加 summary/brief 等简洁字段，或提供 verbose=false 参数控制返回粒度"
    ),
    "context.low_value_large_fields": (
        "检查工具返回中占比过大的字段是否必要，考虑移除或改为按需返回"
    ),
    "context.truncation_without_hint": (
        "截断输出时应提供 next_cursor/continuation_token/has_more 等延续提示，"
        "让 Agent 知晓可以继续获取数据"
    ),
}


# ---------------------------------------------------------------------------
# Markdown 渲染
# ---------------------------------------------------------------------------


def render_transcript_analysis_markdown(findings: list[RuleFinding]) -> str:
    """将 transcript confusion findings 渲染为 Markdown 节。

    Args:
        findings: TranscriptPatternAnalyzer.analyze() 返回的 RuleFinding 列表。

    Returns:
        Markdown 格式节，无 finding 时返回空字符串。
    """
    transcript_findings = [f for f in findings if f.category == "transcript"]
    if not transcript_findings:
        return ""

    lines: list[str] = []
    lines.append("### Agent Confusion Patterns")
    lines.append("")
    lines.append("| Severity | Pattern | Detail | Steps |")
    lines.append("|----------|---------|--------|-------|")

    for f in transcript_findings:
        severity_icon = _severity_icon(f.severity)
        lines.append(
            f"| {severity_icon} | {f.rule_type} | {f.message} | {f.evidence_ref} |"
        )

    lines.append("")
    return "\n".join(lines)


def render_context_analysis_markdown(findings: list[RuleFinding]) -> str:
    """将 context efficiency findings 渲染为 Markdown 节。

    Args:
        findings: ContextEfficiencyAnalyzer.analyze() 返回的 RuleFinding 列表。

    Returns:
        Markdown 格式节，无 finding 时返回空字符串。
    """
    context_findings = [f for f in findings if f.category == "context"]
    if not context_findings:
        return ""

    lines: list[str] = []
    lines.append("### Context Efficiency")
    lines.append("")
    lines.append("| Severity | Pattern | Detail | Evidence |")
    lines.append("|----------|---------|--------|----------|")

    for f in context_findings:
        severity_icon = _severity_icon(f.severity)
        lines.append(
            f"| {severity_icon} | {f.rule_type} | {f.message} | {f.evidence_ref} |"
        )

    lines.append("")
    return "\n".join(lines)


def render_analysis_markdown(findings: list[RuleFinding]) -> str:
    """一站式渲染：转录困惑 + 上下文效率 Markdown 节。

    同时附加对应 recommendations。

    Returns:
        完整 Markdown 节（含 "## Transcript & Context Analysis" 标题）。
    """
    transcript_findings = [f for f in findings if f.category == "transcript"]
    context_findings = [f for f in findings if f.category == "context"]
    if not transcript_findings and not context_findings:
        return ""

    lines: list[str] = []
    lines.append("## Transcript & Context Analysis")
    lines.append("")

    if transcript_findings:
        lines.append(render_transcript_analysis_markdown(findings))
    if context_findings:
        lines.append(render_context_analysis_markdown(findings))

    # 附加 recommendations
    recs = _collect_recommendations(findings)
    if recs:
        lines.append("#### Recommendations")
        lines.append("")
        for i, rec in enumerate(recs, 1):
            lines.append(f"{i}. {rec}")
        lines.append("")

    return "\n".join(lines)


def analysis_report_section(findings: list[RuleFinding]):
    """把 transcript/context analysis findings 暴露为统一 ReportSection。

    analysis 模块负责识别 category 和 recommendation；composer 只消费 section，
    不需要知道 ``RuleFinding.category == transcript/context`` 的领域规则。
    """

    from agent_tool_harness.reports.section_contract import (
        RenderedSection,
        ReportSection,
    )

    def _render() -> RenderedSection:
        return RenderedSection(
            markdown=render_analysis_markdown(findings),
            json_data=render_analysis_json(findings),
        )

    return ReportSection(
        section_id="analysis",
        title="Transcript & Context Analysis",
        render=_render,
        priority=50,
    )


# ---------------------------------------------------------------------------
# JSON 渲染
# ---------------------------------------------------------------------------


def render_analysis_json(findings: list[RuleFinding]) -> dict:
    """将 findings 序列化为 JSON 兼容的 dict。

    Returns:
        {"transcript": [...], "context": [...], "recommendations": [...]}
    """
    transcript_items = [
        {
            "rule_type": f.rule_type,
            "severity": f.severity,
            "message": f.message,
            "evidence_ref": f.evidence_ref,
        }
        for f in findings
        if f.category == "transcript"
    ]

    context_items = [
        {
            "rule_type": f.rule_type,
            "severity": f.severity,
            "message": f.message,
            "evidence_ref": f.evidence_ref,
        }
        for f in findings
        if f.category == "context"
    ]

    recs = _collect_recommendations(findings)

    return {
        "transcript": transcript_items,
        "context": context_items,
        "recommendations": recs,
    }


# ---------------------------------------------------------------------------
# 辅助
# ---------------------------------------------------------------------------


def _severity_icon(severity: str) -> str:
    """严重程度 → Markdown 图标。"""
    icons = {
        "critical": "critical",
        "high": "high",
        "medium": "medium",
        "low": "low",
        "info": "info",
    }
    return icons.get(severity, severity)


def _collect_recommendations(findings: list[RuleFinding]) -> list[str]:
    """从 findings 的 rule_type 收集对应的修复建议并去重。"""
    seen: set[str] = set()
    recs: list[str] = []
    for f in findings:
        rule_type = f.rule_type
        if rule_type in seen:
            continue
        if rule_type in RECOMMENDATION_CATALOG:
            seen.add(rule_type)
            recs.append(f"**{rule_type}**: {RECOMMENDATION_CATALOG[rule_type]}")
    return recs
