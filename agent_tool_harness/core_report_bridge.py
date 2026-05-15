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
- v3.1 P5: 新增 report_insight_to_json_dict()，ReportInsight → JSON 兼容 dict
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


def report_insight_to_json_dict(insight: Any) -> dict[str, Any]:
    """把 ReportInsight 序列化为 JSON 兼容 dict。

    JSON report shape（按 SDD §8.2）：

    - summary: 顶层摘要（passed, total_findings, errors, warnings, info 等）
    - metrics: P1 ReportMetrics 全字段序列化
    - scorecard: P3 ReportScorecard 全字段 + severity_breakdown
    - findings: 原始 findings 透传（桥接为 dict 列表）
    - grouped_findings: 按 severity/category/tool/rule_id_prefix 分组的计数
    - recommendations: P4 建议列表
    - judge_findings: 仅 judge category 的 finding
    - metadata: schema_version, generated_at, signal_quality

    为什么 JSON report 保持兼容：
    - v3.0 的 findings 透传路径不变——只是多包了一层 insight 字段
    - 旧 consumer 如果只读 findings 数组，不受影响
    - 新 consumer 可以按 schema_version 判断是否可用 insight 字段

    Args:
        insight: ReportInsight 聚合对象。

    Returns:
        JSON-serializable dict。
    """
    from agent_tool_harness.reports.report_insight import ReportInsight

    if not isinstance(insight, ReportInsight):
        return {}

    sc = insight.scorecard
    m = insight.metrics
    g = insight.grouped_findings

    # findings 透传 —— 用 evaluation_result_to_report_dict 的格式
    findings_list: list[dict[str, Any]] = []
    for f in insight.findings:
        item: dict[str, Any] = {
            "finding_id": f.finding_id,
            "severity": f.severity,
            "category": f.category,
            "message": f.message,
            "evidence_ref": f.evidence_ref,
        }
        rule_type = getattr(f, "rule_type", "")
        if rule_type:
            item["rule_type"] = rule_type
        rule_passed = getattr(f, "rule_passed", None)
        if rule_passed is not None:
            item["rule_passed"] = rule_passed
        if getattr(f, "category", "") == "judge":
            item["provider"] = getattr(f, "provider", "")
            item["model"] = getattr(f, "model", "")
            item["confidence"] = getattr(f, "confidence", None)
            item["rationale"] = getattr(f, "rationale", "")
            item["rubric"] = getattr(f, "rubric", None)
            item["usage"] = getattr(f, "usage", None)
        findings_list.append(item)

    # grouped_findings —— 序列化为 count dict（不嵌套完整 finding，避免 JSON 过大）
    grouped_dict: dict[str, dict[str, int]] = {}
    for view_name, view_dict in [
        ("by_severity", g.by_severity),
        ("by_category", g.by_category),
        ("by_tool", g.by_tool),
        ("by_rule_id_prefix", g.by_rule_id_prefix),
    ]:
        grouped_dict[view_name] = {
            key: len(items) for key, items in view_dict.items()
        }

    # recommendations
    recs_list: list[dict[str, Any]] = []
    for rec in insight.recommendations:
        recs_list.append({
            "rule_id": rec.rule_id,
            "category": rec.category,
            "severity": rec.severity,
            "what": rec.what,
            "why": rec.why,
            "how_to_fix": rec.how_to_fix,
            "affected_count": rec.affected_count,
        })

    # judge_findings
    judge_list: list[dict[str, Any]] = []
    for jf in insight.judge_findings:
        judge_list.append({
            "finding_id": jf.finding_id,
            "severity": jf.severity,
            "category": jf.category,
            "message": jf.message,
            "evidence_ref": jf.evidence_ref,
            "provider": getattr(jf, "provider", ""),
            "model": getattr(jf, "model", ""),
            "confidence": getattr(jf, "confidence", None),
            "rationale": getattr(jf, "rationale", ""),
            "rubric": getattr(jf, "rubric", None),
        })

    return {
        "summary": {
            "passed": sc.passed,
            "total_findings": sc.total_findings,
            "errors": sc.errors,
            "warnings": sc.warnings,
            "info": sc.info,
            "advisory_count": sc.advisory_count,
            "generated_at": insight.metadata.generated_at,
        },
        "metrics": {
            "tool_call_count": m.tool_call_count,
            "tool_result_count": m.tool_result_count,
            "unique_tool_count": m.unique_tool_count,
            "tool_success_count": m.tool_success_count,
            "tool_error_count": m.tool_error_count,
            "tool_error_rate": m.tool_error_rate,
            "orphan_call_count": m.orphan_call_count,
            "orphan_result_count": m.orphan_result_count,
            "repeated_tool_call_count": m.repeated_tool_call_count,
            "response_size_chars_total": m.response_size_chars_total,
            "response_size_chars_by_tool": m.response_size_chars_by_tool,
            "estimated_response_tokens_total": m.estimated_response_tokens_total,
            "finding_count_by_severity": m.finding_count_by_severity,
            "finding_count_by_category": m.finding_count_by_category,
            "finding_count_by_tool": m.finding_count_by_tool,
            "judge_finding_count": m.judge_finding_count,
        },
        "scorecard": {
            "passed": sc.passed,
            "total_findings": sc.total_findings,
            "severity_breakdown": {
                "error": sc.errors,
                "warning": sc.warnings,
                "info": sc.info,
            },
            "advisory_count": sc.advisory_count,
            "tools_called": sc.tools_called,
            "tool_errors": sc.tool_errors,
            "tool_error_rate": m.tool_error_rate,
            "top_issue_categories": sc.top_issue_categories,
            "top_affected_tools": sc.top_affected_tools,
        },
        "findings": findings_list,
        "grouped_findings": grouped_dict,
        "recommendations": recs_list,
        "judge_findings": judge_list,
        "metadata": {
            "schema_version": insight.metadata.schema_version,
            "generated_at": insight.metadata.generated_at,
            "signal_quality": insight.metadata.signal_quality,
        },
    }
