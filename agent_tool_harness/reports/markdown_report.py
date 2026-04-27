from __future__ import annotations

from typing import Any


class MarkdownReport:
    """生成面向 review 的 Markdown 报告。

    架构边界：
    - 只聚合 audit、judge、diagnosis、metrics 的摘要，不重新计算判定。
    - 不隐藏 raw artifacts；报告会指向 transcript/tool_calls/tool_responses。
    - 保持文本格式稳定，方便测试和 CI artifact review。
    """

    REQUIRED_SECTIONS = [
        "Tool Design Audit",
        "Eval Quality Audit",
        "Agent Tool-Use Eval",
        "Transcript-derived Diagnosis",
        "Improvement Suggestions",
    ]

    def render(
        self,
        *,
        project: dict[str, Any],
        metrics: dict[str, Any],
        audit_tools: dict[str, Any],
        audit_evals: dict[str, Any],
        judge_results: dict[str, Any],
        diagnosis: dict[str, Any],
    ) -> str:
        """渲染一次 run 的 Markdown 摘要。

        report 是派生视图，不负责重新判定成败。这里会展示 skipped/error 指标，是为了让用户
        一眼区分“Agent 判断失败”和“runner/adapter 执行链路异常”，但最终复盘仍应回到 JSONL。
        """

        low_score_tools = ", ".join(
            audit_tools.get("summary", {}).get("low_score_tools", [])
        ) or "none"
        not_runnable = ", ".join(
            audit_evals.get("summary", {}).get("not_runnable", [])
        ) or "none"
        lines = [
            f"# Agent Tool Harness Report: {project.get('name', 'unknown')}",
            "",
            "## Tool Design Audit",
            "",
            f"- Tool count: {audit_tools.get('summary', {}).get('tool_count', 0)}",
            f"- Average score: {audit_tools.get('summary', {}).get('average_score', 0)}",
            f"- Low score tools: {low_score_tools}",
            "",
            "## Eval Quality Audit",
            "",
            f"- Eval count: {audit_evals.get('summary', {}).get('eval_count', 0)}",
            f"- Average score: {audit_evals.get('summary', {}).get('average_score', 0)}",
            f"- Not runnable: {not_runnable}",
            "",
            "## Agent Tool-Use Eval",
            "",
            f"- Total evals: {metrics.get('total_evals', 0)}",
            f"- Passed: {metrics.get('passed', 0)}",
            f"- Failed: {metrics.get('failed', 0)}",
            f"- Skipped: {metrics.get('skipped_evals', 0)}",
            f"- Errors: {metrics.get('error_evals', 0)}",
            f"- Total tool calls: {metrics.get('total_tool_calls', 0)}",
            "",
        ]
        for result in judge_results.get("results", []):
            status = "PASS" if result.get("passed") else "FAIL"
            lines.append(f"- {result.get('eval_id')}: {status}")
        lines.extend(["", "## Transcript-derived Diagnosis", ""])
        for item in diagnosis.get("results", []):
            lines.append(f"- {item.get('eval_id')}: {item.get('summary')}")
            if item.get("tool_sequence"):
                lines.append(f"  Tool sequence: {', '.join(item['tool_sequence'])}")
        lines.extend(
            [
                "",
                "## Improvement Suggestions",
                "",
                "- Review low-score tool audit findings before adding more evals.",
                "- Keep generated evals as candidates until context and outcomes are complete.",
                "- Inspect transcript/tool call artifacts before changing tests.",
                "- Fix tool descriptions, eval criteria, or adapter behavior from evidence.",
                "",
                "## Artifacts",
                "",
                "- transcript.jsonl",
                "- tool_calls.jsonl",
                "- tool_responses.jsonl",
                "- metrics.json",
                "- audit_tools.json",
                "- audit_evals.json",
                "- judge_results.json",
                "- diagnosis.json",
                "- report.md",
            ]
        )
        return "\n".join(lines) + "\n"
