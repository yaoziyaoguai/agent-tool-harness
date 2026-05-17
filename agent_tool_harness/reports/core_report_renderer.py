"""Core Flow Markdown renderer.

本模块接管 ``MarkdownReport.render_from_core`` 的实际渲染职责。

架构意图
--------
``markdown_report.py`` 仍保留历史 ``render()`` 和 public API wrapper，但 Core
Flow 报告属于另一条数据路径：它消费 Core Contract bridge dict，并通过
``ReportSection`` contract 接入 v3.2+ 的可选报告段。把这部分放在独立模块里，
可以让 composer 只理解报告段边界，而不继续把每个版本的业务细节堆进
``MarkdownReport`` 巨石类。

本模块不重新计算 pass/fail、不生成 ReviewDecision、不调用 LLM，也不修改输入对象。
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from agent_tool_harness.reports.section_contract import ReportSection


def render_core_report(
    *,
    results: list[dict[str, Any]],
    report_summary: dict[str, Any],
    signal_quality: str,
    judge_provider_kind: str = "none",
    insight: Any = None,
    task_outcome: Any = None,
    suite_result: Any = None,
    sections: Sequence[ReportSection] | None = None,
) -> str:
    """从 Core Contract 对象渲染 Markdown 报告。

    架构边界（关键）：
    - **负责**：把 EvaluationResult / ReportSummary / ExecutionTrace 的
      bridge dict 转成人类可读的 Markdown 报告。
    - **不负责**：不重新计算 passed/failed、不生成 ReviewDecision、
      不做最终裁决。ReviewDecision 必须由人工 Reviewer 显式创建。
    - **为什么从 ``MarkdownReport`` 拆出**：Core Flow、insight 和统一 section
      contract 是 post-v3.1 的报告路径；它们应由 focused renderer 编排，避免
      ``markdown_report.py`` 继续理解每个业务模块内部结构。

    Args:
        results: list of per-eval dict，每个来自
                 core_report_bridge.evaluation_result_to_report_dict()
        report_summary: dict from core_report_bridge.report_summary_to_report_dict()
        signal_quality: str，来自 adapter 的 SIGNAL_QUALITY 声明
        judge_provider_kind: "none"（默认，纯 RuleJudge）| "fake"（FakeJudgeProvider）
                             | "llm"（opt-in 真实 LLM judge）
        insight: 可选 ReportInsight，渲染聚合 insight 段（v3.1）。
        task_outcome: 可选 TaskOutcome，渲染 task-level 评测结果段（v3.2）。
        suite_result: 可选 SuiteResult，渲染 suite-level 聚合报告段（v3.3）。
        sections: 可选 ReportSection 序列，统一接入 v3.4+ 或未来报告段。
    """

    from agent_tool_harness.signal_quality import describe as describe_sq

    sq_note = describe_sq(signal_quality)
    lines = [
        "# Agent Tool Harness Report (Core Flow)",
        "",
        "## Signal Quality",
        "",
        f"- Level: `{signal_quality}`",
        f"- Note: {sq_note}",
        "",
        _signal_quality_banner(judge_provider_kind),
        "",
        "## Methodology Caveats",
        "",
        _core_flow_caveat(judge_provider_kind),
        (
            "- **RuleJudge 是确定性启发式判定**，只覆盖 must_call_tool / "
            "must_use_evidence 等显式规则；不做 LLM 语义判分。"
        ),
        (
            "- **DemoAgent2HarnessAdapter 是 deterministic replay**，按 eval 自带的"
            " expected_tool_behavior 反向回放工具调用；它不是真实 LLM Agent。"
        ),
        (
            "- **ReviewDecision 必须人工显式创建**——本报告不包含任何自动生成的"
            "通过/不通过最终裁决。所有 PASS/FAIL 均为机器评分，不等同于人工审核结论。"
        ),
        "",
    ]

    # v3.1 P5: 如果传了 ReportInsight，在 detailed findings 前插入 insight 段。
    lines.extend(render_insight_section(insight))

    lines.extend([
        "## Agent Tool-Use Eval (Core Flow)",
        "",
        f"- Total scenarios: {report_summary.get('total_scenarios', 0)}",
        f"- Passed: {report_summary.get('passed', 0)}",
        f"- Failed: {report_summary.get('failed', 0)}",
        f"- Errors: {report_summary.get('errors', 0)}",
        f"- Signal quality: `{signal_quality}`",
        f"- Generated at: {report_summary.get('generated_at', '')}",
        "",
    ])

    lines.extend(["## Per-Eval Details", ""])
    for result in results:
        lines.extend(_render_core_eval_detail(result))

    report_sections = _collect_report_sections(
        task_outcome=task_outcome,
        suite_result=suite_result,
        sections=sections,
    )
    if report_sections:
        from agent_tool_harness.reports.section_contract import render_sections_markdown

        rendered_sections = render_sections_markdown(report_sections).rstrip()
        if rendered_sections:
            lines.extend(["", rendered_sections, ""])

    lines.extend([
        "## Review Decision",
        "",
        (
            "> **ReviewDecision 未生成。** 本报告中的所有 PASS/FAIL 均为机器评分。"
            "人工 Reviewer 必须在查看完整 evidence 后显式创建 ReviewDecision，"
            "包含 decision（approved / needs_revision / rejected）、reviewer、"
            "notes 和 reviewed_at。报告不得自动做最终裁决。"
        ),
        "",
    ])

    lines.extend([
        "## Artifacts",
        "",
        "- execution_trace.json",
        "- evidence.json",
        "- evaluation_result.json",
        "- report_summary.json",
        "- report.md",
        "",
        (
            "Core Contract 对象定义详见 "
            "[docs/AGENT2HARNESS_CORE_SPEC.md](../docs/AGENT2HARNESS_CORE_SPEC.md)。"
        ),
        "",
    ])
    return "\n".join(lines) + "\n"


def render_insight_section(insight: Any) -> list[str]:
    """从 ReportInsight 渲染 Markdown insight 段。

    ReportInsight 是 v3.1 的 report-level 聚合视图。它知道 scorecard、metrics、
    grouped findings 和 recommendations 的 shape；主报告 composer 不应该理解这些
    内部字段，因此渲染逻辑留在 focused renderer 中，并通过兼容 wrapper 暴露给旧 API。

    Args:
        insight: ReportInsight 聚合对象。

    Returns:
        Markdown 行列表，可直接 extend 到现有报告。
    """

    from agent_tool_harness.reports.report_insight import ReportInsight

    if not isinstance(insight, ReportInsight):
        return []

    sc = insight.scorecard
    m = insight.metrics
    g = insight.grouped_findings
    recs = insight.recommendations

    lines: list[str] = []

    passed_mark = "PASS" if sc.passed else "FAIL"
    lines.extend([
        "## Scorecard",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Passed | {passed_mark} |",
        f"| Total Findings | {sc.total_findings} |",
        f"| Errors | {sc.errors} |",
        f"| Warnings | {sc.warnings} |",
        f"| Info | {sc.info} |",
        f"| Advisory | {sc.advisory_count} |",
        f"| Tools Called | {sc.tools_called} |",
        f"| Tool Errors | {sc.tool_errors} |",
    ])
    if sc.top_issue_categories:
        cats = ", ".join(sc.top_issue_categories)
        lines.append(f"| Top Issue Categories | {cats} |")
    if sc.top_affected_tools:
        tools = ", ".join(sc.top_affected_tools)
        lines.append(f"| Top Affected Tools | {tools} |")
    lines.append("")

    lines.extend([
        "## Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Tool Calls | {m.tool_call_count} |",
        f"| Tool Results | {m.tool_result_count} |",
        f"| Unique Tools | {m.unique_tool_count} |",
        f"| Success | {m.tool_success_count} |",
        f"| Errors | {m.tool_error_count} |",
        f"| Error Rate | {m.tool_error_rate:.2%} |",
        f"| Orphan Calls | {m.orphan_call_count} |",
        f"| Orphan Results | {m.orphan_result_count} |",
        f"| Repeated Calls | {m.repeated_tool_call_count} |",
        f"| Response Chars | {m.response_size_chars_total} |",
        f"| Est. Tokens | {m.estimated_response_tokens_total} |",
        "",
    ])

    if sc.top_issue_categories:
        lines.append("## Top Issues")
        lines.append("")
        for i, cat in enumerate(sc.top_issue_categories, 1):
            count = len(g.by_category.get(cat, []))
            lines.append(f"{i}. **{cat}** ({count} findings)")
        lines.append("")

    sev_order = ["critical", "high", "medium", "low", "info"]
    lines.extend(["## Findings by Severity", ""])
    for sev in sev_order:
        items = g.by_severity.get(sev, [])
        if not items:
            continue
        lines.append(f"### {sev} ({len(items)})")
        lines.append("")
        for f_item in items:
            fid = getattr(f_item, "finding_id", "?")
            msg = getattr(f_item, "message", "")
            rule_type = getattr(f_item, "rule_type", "")
            rule_str = f" `{rule_type}`" if rule_type else ""
            lines.append(f"- [{sev}] {fid}{rule_str} — {msg}")
        lines.append("")

    if g.by_tool:
        lines.extend(["## Findings by Tool", ""])
        tools_sorted = sorted(
            g.by_tool.items(),
            key=lambda item: (-len(item[1]), item[0]),
        )
        for tool, items in tools_sorted:
            lines.append(f"### {tool} ({len(items)})")
            lines.append("")
            for f_item in items:
                fid = getattr(f_item, "finding_id", "?")
                sev = getattr(f_item, "severity", "?")
                msg = getattr(f_item, "message", "")
                rule_type = getattr(f_item, "rule_type", "")
                rule_str = f" `{rule_type}`" if rule_type else ""
                lines.append(f"- [{sev}] {fid}{rule_str} — {msg}")
            lines.append("")

    if recs:
        lines.extend(["## Recommendations", ""])
        for i, rec in enumerate(recs, 1):
            affected = (
                f" (affected: {rec.affected_count} findings)"
                if rec.affected_count > 1
                else ""
            )
            lines.append(f"{i}. **`{rec.rule_id}`**{affected} — {rec.what}")
            lines.append(f"   - Why: {rec.why}")
            lines.append(f"   - How to fix: {rec.how_to_fix}")
        lines.append("")

    return lines


def _core_flow_caveat(judge_provider_kind: str) -> str:
    """按 judge provider kind 渲染 Core Flow 方法边界说明。"""

    if judge_provider_kind == "llm":
        return (
            "- **Core Flow** 走 ScenarioSpec → ExecutionTrace → Evidence → "
            "CoreEvaluation → EvaluationResult → ReportSummary 链路；"
            "**已启用 opt-in 真实 LLM JudgeProvider**。"
            "JudgeFinding 为 advisory only（辅助信号），不改变 deterministic passed/failed，"
            "不自动生成 ReviewDecision。"
        )
    if judge_provider_kind == "fake":
        return (
            "- **Core Flow** 走 ScenarioSpec → ExecutionTrace → Evidence → "
            "CoreEvaluation → EvaluationResult → ReportSummary 链路；"
            "使用 FakeJudgeProvider（deterministic fake），**不调用真实 LLM**。"
        )
    return (
        "- **Core Flow** 走 ScenarioSpec → ExecutionTrace → Evidence → "
        "CoreEvaluation → EvaluationResult → ReportSummary 链路；"
        "所有步骤都是 deterministic / mock replay，**不调用真实 LLM**。"
    )


def _signal_quality_banner(judge_provider_kind: str) -> str:
    """按 judge provider kind 渲染 signal_quality banner。"""

    if judge_provider_kind == "llm":
        return (
            "> ⚠️ 本次 run 启用了 opt-in 真实 LLM judge；signal_quality 反映"
            " adapter 的信号边界。PASS/FAIL 为机器评分，JudgeFinding 为辅助参考，"
            "不等同于人工审核结论。"
        )
    return (
        "> ⚠️ 当前 Core Flow 使用 demo/mock 材料运行——signal_quality 反映"
        "本次 run 的信号边界。PASS/FAIL 不能替代真实 LLM agentic loop 的评估。"
    )


def _render_core_eval_detail(result: dict[str, Any]) -> list[str]:
    """渲染单个 core eval 的详细 finding 段。"""

    eval_id = result.get("eval_id", "?")
    passed = result.get("passed", False)
    status = "PASS" if passed else "FAIL"
    lines = [
        f"### {eval_id}: {status}",
        "",
    ]

    findings = result.get("findings", [])
    if findings:
        lines.extend(["**Findings:**", ""])
        for finding in findings:
            lines.extend(_render_finding(finding))
        lines.append("")
    lines.append(f"**Summary:** {result.get('summary', '')}")
    lines.append("")
    return lines


def _render_finding(finding: dict[str, Any]) -> list[str]:
    """区分 deterministic rule finding 和 advisory judge finding。"""

    if finding.get("category", "") == "judge":
        return _render_judge_finding(finding)

    finding_status = "✅" if finding.get("rule_passed") else "❌"
    return [
        f"- {finding_status} `{finding.get('rule_type', '?')}` — "
        f"{finding.get('message', '')}"
    ]


def _render_judge_finding(finding: dict[str, Any]) -> list[str]:
    """渲染 LLM judge advisory finding，不参与 deterministic 结论。"""

    provider = finding.get("provider", "")
    model = finding.get("model", "")
    message = finding.get("message", "")
    is_transport_error = "transport error" in message or "bad_response" in message
    if is_transport_error:
        icon = "⚠️"
        tag = "LLM judge transport/parsing error"
    else:
        icon = "🔍"
        tag = "LLM judge advisory finding"
    src = f"{provider}/{model}" if provider else "llm_judge"

    lines = [f"- {icon} `{src}` [{tag}] — {message}"]
    confidence = finding.get("confidence")
    rationale = finding.get("rationale", "")
    rubric = finding.get("rubric")
    usage = finding.get("usage")
    if confidence is not None:
        lines.append(f"  - confidence: {confidence}")
    if rationale:
        lines.append(f"  - rationale: {rationale}")
    if rubric:
        lines.append(f"  - rubric: {rubric}")
    if usage:
        prompt_tokens = usage.get("prompt_tokens", 0) if isinstance(usage, dict) else 0
        completion_tokens = (
            usage.get("completion_tokens", 0) if isinstance(usage, dict) else 0
        )
        lines.append(
            f"  - token usage: prompt={prompt_tokens}, completion={completion_tokens}"
        )
    return lines


def _collect_report_sections(
    *,
    task_outcome: Any,
    suite_result: Any,
    sections: Sequence[ReportSection] | None,
) -> list[ReportSection]:
    """把旧 API 参数和新 section contract 统一成 composer 输入。

    旧调用方可以继续传 ``task_outcome`` / ``suite_result``；新调用方应优先传
    ``sections``。这里是兼容层，不让主渲染逻辑直接读取业务对象字段。
    """

    report_sections: list[ReportSection] = []
    if task_outcome is not None:
        from agent_tool_harness.task_eval.render import task_outcome_report_section

        report_sections.append(task_outcome_report_section(task_outcome))
    if suite_result is not None:
        from agent_tool_harness.suite_eval.render import suite_report_section

        report_sections.append(suite_report_section(suite_result))
    if sections:
        report_sections.extend(sections)
    return report_sections
