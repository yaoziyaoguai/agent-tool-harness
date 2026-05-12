"""Core Report Bridge —— EvaluationResult / ReportSummary → 旧 reporter 可消费格式。

架构边界
--------
- **负责**：把 Core Contract 的 EvaluationResult / ReportSummary 转成 dict，
  让现有 MarkdownReport 或任何 report consumer 可以展示 Core Flow 的结果。
- **不负责**：不生成报告文本、不做通过/不通过决策、不渲染 Markdown。
- **为什么是 bridge 而非新 reporter**：现有 MarkdownReport 经过多轮验证，结构稳定。
  本轮目标是让 Core Contract 对象能流入这个已有 reporter，而非重写 reporter。
  后续轮次如果 reporter 需要原生理解 Core Contract，可以在 MarkdownReport 中
  新增 render_from_core() 方法，届时本 bridge 可退役。
- **为什么 reporter 不能承担最终裁决**：Reporter 只生成报告。最终判定由 Human Review
  完成。报告不得自动做"通过/不通过"决策。

未来扩展点
----------
- 当 MarkdownReport 原生支持 Core Contract 输入时，本 bridge 可退役
- 当需要 JSON / HTML 等其他 report 格式时，可新增 parallel bridge
"""

from __future__ import annotations

from typing import Any

from agent_tool_harness.core_contract import EvaluationResult, ReportSummary


def evaluation_result_to_report_dict(
    eval_result: EvaluationResult,
) -> dict[str, Any]:
    """把 EvaluationResult 转成 report-friendly dict。

    输出的 dict 结构与现有 judge_results.json 的单个 entry 兼容，
    让 MarkdownReport 可以无感消费 Core Flow 的输出。

    注意：**不**包含 ReviewDecision——那是人工 Reviewer 的事。
    """
    findings = []
    for f in eval_result.findings:
        item: dict[str, Any] = {
            "finding_id": f.finding_id,
            "severity": f.severity,
            "category": f.category,
            "message": f.message,
            "evidence_ref": f.evidence_ref,
            "rule_type": getattr(f, "rule_type", ""),
            "rule_passed": getattr(f, "rule_passed", None),
        }
        # JudgeFinding metadata 透传（用 getattr 安全获取，不影响 RuleFinding）
        if f.category == "judge":
            item["provider"] = getattr(f, "provider", "")
            item["model"] = getattr(f, "model", "")
            item["confidence"] = getattr(f, "confidence", None)
            item["rubric"] = getattr(f, "rubric", None)
            item["rationale"] = getattr(f, "rationale", "")
            item["usage"] = getattr(f, "usage", None)
        findings.append(item)

    return {
        "eval_id": eval_result.scenario_id,
        "passed": eval_result.passed,
        "findings": findings,
        "summary": eval_result.summary,
    }


def report_summary_to_report_dict(
    summary: ReportSummary,
) -> dict[str, Any]:
    """把 ReportSummary 转成与现有 metrics.json 兼容的 dict。

    signal_quality 显式传递——让 reviewer 知道本次 run 的信号置信度边界。
    """
    return {
        "total_scenarios": summary.total_scenarios,
        "passed": summary.passed,
        "failed": summary.failed,
        "errors": summary.errors,
        "signal_quality": summary.signal_quality,
        "generated_at": summary.generated_at,
    }
