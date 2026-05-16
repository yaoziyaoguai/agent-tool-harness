"""Task Outcome 报告渲染 —— v3.2 任务评测结果的可视化输出。

架构边界
--------
- **负责**：将 TaskOutcome 渲染为 Markdown 节或纯文本摘要。
- **不负责**：不修改 TaskOutcome、不生成完整报告（那是 MarkdownReport 的事）、
  不访问文件系统。
- **为什么独立于 markdown_report.py**：markdown_report.py 是 v3.1 的 trace-level
  报告渲染器（1300+ 行）。task-level 报告节作为独立模块，通过字符串拼接方式
  集成到已有报告中，不对已有渲染器做侵入式修改。
"""

from __future__ import annotations


def render_task_outcome_markdown(outcome) -> str:
    """将 TaskOutcome 渲染为 Markdown 节。

    输出格式：
    - 状态行：case_id + PASS/FAIL/INCONCLUSIVE
    - Verifier 结果表（verifier_name, Status, Details, Matched, Missing）
    - Final Answer 引用块

    Args:
        outcome: TaskOutcome 实例。

    Returns:
        Markdown 格式字符串，可直接插入报告。
    """
    from agent_tool_harness.task_eval.task_evaluator import TaskOutcome

    if not isinstance(outcome, TaskOutcome):
        return ""

    status_icon = {"success": "PASS", "failed": "FAIL", "inconclusive": "INCONCLUSIVE"}
    icon = status_icon.get(outcome.status, "UNKNOWN")

    lines: list[str] = []
    lines.append(f"### Task Outcome: {outcome.case_id}  → **{icon}**")
    lines.append("")

    # Verifier 结果表
    if outcome.verifier_results:
        lines.append("| Verifier | Status | Details | Matched | Missing |")
        lines.append("|----------|--------|---------|---------|---------|")
        for vr in outcome.verifier_results:
            status = "PASS" if vr.passed else "FAIL"
            matched_str = ", ".join(vr.matched) if vr.matched else "-"
            missing_str = ", ".join(vr.missing) if vr.missing else "-"
            lines.append(
                f"| {vr.verifier_name} | {status} | {vr.details} "
                f"| {matched_str} | {missing_str} |"
            )
        lines.append("")

    # 聚合统计
    if outcome.matched:
        lines.append(f"**Matched:** {', '.join(outcome.matched)}  ")
    if outcome.missing:
        lines.append(f"**Missing:** {', '.join(outcome.missing)}  ")

    # Final Answer
    if outcome.final_answer:
        lines.append("")
        lines.append("**Final Answer:**")
        lines.append("")
        lines.append(f"> {outcome.final_answer}")
        lines.append("")

    # Details
    if outcome.details:
        lines.append(f"*{outcome.details}*")

    return "\n".join(lines)


def render_task_outcome_text(outcome) -> str:
    """将 TaskOutcome 渲染为纯文本一行摘要。

    适用于 CLI 输出或日志摘要。

    Args:
        outcome: TaskOutcome 实例。

    Returns:
        单行纯文本字符串。
    """
    from agent_tool_harness.task_eval.task_evaluator import TaskOutcome

    if not isinstance(outcome, TaskOutcome):
        return ""

    status_label = {
        "success": "PASS",
        "failed": "FAIL",
        "inconclusive": "INCONCLUSIVE",
    }
    label = status_label.get(outcome.status, "UNKNOWN")
    return (
        f"[{label}] {outcome.case_id}: {outcome.details or 'no details'}"
    )
