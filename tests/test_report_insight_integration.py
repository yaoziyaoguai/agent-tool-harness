"""P5 ReportInsight Integration 测试。

覆盖:
- ReportInsight.from_eval() happy path + 边界
- 组件自洽（metrics ↔ scorecard ↔ groups ↔ recommendations）
- Markdown render_insight_section() substring 匹配
- JSON report_insight_to_json_dict() shape 验证
- 兼容性（不改变 passed、不修改 findings）
- zero network / no .env / no LLM
"""

from __future__ import annotations

import pytest

from agent_tool_harness.core_contract import (
    EvaluationResult,
    ExecutionTrace,
    JudgeFinding,
    RuleFinding,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.core_report_bridge import report_insight_to_json_dict
from agent_tool_harness.reports.markdown_report import MarkdownReport
from agent_tool_harness.reports.report_insight import (
    ReportInsight,
    ReportInsightMetadata,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _mk_trace(**overrides) -> ExecutionTrace:
    defaults = {
        "scenario_id": "s1",
        "tool_calls": [
            ToolCall(tool_name="search", arguments={"q": "x"}, call_id="c1"),
            ToolCall(tool_name="read", arguments={"path": "f"}, call_id="c2"),
        ],
        "tool_results": [
            ToolResult(call_id="c1", tool_name="search", status="success",
                       output={"results": [1, 2]}),
            ToolResult(call_id="c2", tool_name="read", status="error",
                       output={}, error="not found"),
        ],
    }
    defaults.update(overrides)
    return ExecutionTrace(**defaults)


def _mk_eval_result(**overrides) -> EvaluationResult:
    """构造含混合 findings 的 EvaluationResult。"""
    f1 = RuleFinding(
        finding_id="f1", severity="critical", category="rule",
        message="缺少 arguments", evidence_ref="ref1",
        rule_type="tool_call.arguments.present", rule_passed=False,
    )
    f2 = RuleFinding(
        finding_id="f2", severity="high", category="rule",
        message="输出信号过低", evidence_ref="ref2",
        rule_type="tool_response.output.low_signal", rule_passed=False,
    )
    f3 = JudgeFinding(
        finding_id="j1", severity="medium", category="judge",
        message="LLM judge 发现输出质量一般", evidence_ref="ref3",
        provider="openai-native", model="gpt-4o", confidence=0.7,
        rationale="输出缺少上下文", rubric="response_quality",
    )
    defaults = {
        "scenario_id": "s1",
        "findings": [f1, f2, f3],
        "passed": False,
    }
    defaults.update(overrides)
    return EvaluationResult(**defaults)


def _mk_insight(**overrides) -> ReportInsight:
    """通过 from_eval() 构造 insight，按需覆盖。"""
    trace = _mk_trace()
    eval_result = _mk_eval_result()
    insight = ReportInsight.from_eval(trace, eval_result, signal_quality="mock")
    # 支持覆盖 metadata 字段
    if "metadata" in overrides:
        insight = ReportInsight(
            metrics=insight.metrics,
            scorecard=insight.scorecard,
            grouped_findings=insight.grouped_findings,
            recommendations=insight.recommendations,
            findings=insight.findings,
            judge_findings=insight.judge_findings,
            metadata=overrides["metadata"],
        )
    return insight


# ---------------------------------------------------------------------------
# 1. from_eval() happy path / 组件完整性
# ---------------------------------------------------------------------------


class TestFromEvalHappyPath:
    def test_all_components_non_none(self):
        """from_eval 返回的 insight 各字段均非 None。"""
        insight = _mk_insight()
        assert insight.metrics is not None
        assert insight.scorecard is not None
        assert insight.grouped_findings is not None
        assert insight.recommendations is not None
        assert insight.findings is not None
        assert insight.judge_findings is not None
        assert insight.metadata is not None

    def test_metrics_has_tool_counts(self):
        """metrics 反映 trace 的工具调用统计。"""
        insight = _mk_insight()
        assert insight.metrics.tool_call_count == 2
        assert insight.metrics.tool_result_count == 2
        assert insight.metrics.unique_tool_count == 2
        assert insight.metrics.tool_success_count == 1
        assert insight.metrics.tool_error_count == 1

    def test_scorecard_passed_false(self):
        """scorecard.passed 从 eval_result.passed 透传。"""
        insight = _mk_insight()
        assert insight.scorecard.passed is False

    def test_scorecard_passed_true(self):
        """passed=True 正确透传。"""
        eval_result = _mk_eval_result(passed=True)
        trace = _mk_trace()
        insight = ReportInsight.from_eval(trace, eval_result)
        assert insight.scorecard.passed is True

    def test_judge_findings_separated(self):
        """judge_findings 仅包含 category=="judge"。"""
        insight = _mk_insight()
        assert len(insight.judge_findings) == 1
        assert insight.judge_findings[0].category == "judge"

    def test_metadata_filled(self):
        """metadata 字段正确填充。"""
        insight = _mk_insight()
        assert insight.metadata.schema_version == "3.1.0"
        assert len(insight.metadata.generated_at) > 0
        assert insight.metadata.signal_quality == "mock"


# ---------------------------------------------------------------------------
# 2. 边界条件
# ---------------------------------------------------------------------------


class TestBoundary:
    def test_empty_trace_empty_findings(self):
        """空 trace + 空 findings → 全零 insight，不崩溃。"""
        trace = ExecutionTrace(scenario_id="s1")
        eval_result = EvaluationResult(scenario_id="s1", findings=[], passed=True)
        insight = ReportInsight.from_eval(trace, eval_result)
        assert insight.metrics.tool_call_count == 0
        assert insight.metrics.tool_error_count == 0
        assert insight.scorecard.total_findings == 0
        assert insight.recommendations == []

    def test_only_rule_findings(self):
        """仅 rule findings，无 judge。"""
        f = RuleFinding(
            finding_id="f1", severity="high", category="rule",
            message="test", evidence_ref="ref",
            rule_type="tool_spec.description.exists", rule_passed=False,
        )
        eval_result = EvaluationResult(
            scenario_id="s1", findings=[f], passed=False,
        )
        trace = _mk_trace()
        insight = ReportInsight.from_eval(trace, eval_result)
        assert len(insight.judge_findings) == 0
        assert insight.scorecard.advisory_count == 0


# ---------------------------------------------------------------------------
# 3. 组件自洽
# ---------------------------------------------------------------------------


class TestSelfConsistency:
    def test_finding_count_matches_scorecard(self):
        """metrics.finding_count_by_severity sum == scorecard total_findings。"""
        insight = _mk_insight()
        sev_sum = sum(insight.metrics.finding_count_by_severity.values())
        assert sev_sum == insight.scorecard.total_findings

    def test_judge_count_matches_judge_findings_length(self):
        """metrics.judge_finding_count == len(insight.judge_findings)。"""
        insight = _mk_insight()
        assert insight.metrics.judge_finding_count == len(insight.judge_findings)

    def test_recommendations_deduped(self):
        """去重后 recommendations 数量 ≤ findings 数量。"""
        insight = _mk_insight()
        assert len(insight.recommendations) <= len(insight.findings)


# ---------------------------------------------------------------------------
# 4. 不修改输入
# ---------------------------------------------------------------------------


class TestNoMutation:
    def test_from_eval_does_not_mutate_eval_result(self):
        """from_eval 不修改传入的 eval_result.passed。"""
        eval_result = _mk_eval_result(passed=False)
        original_passed = eval_result.passed
        trace = _mk_trace()
        ReportInsight.from_eval(trace, eval_result)
        assert eval_result.passed == original_passed

    def test_from_eval_does_not_mutate_findings(self):
        """from_eval 不修改传入的 findings 列表。"""
        eval_result = _mk_eval_result()
        original_len = len(eval_result.findings)
        trace = _mk_trace()
        ReportInsight.from_eval(trace, eval_result)
        assert len(eval_result.findings) == original_len


# ---------------------------------------------------------------------------
# 5. Markdown render_insight_section
# ---------------------------------------------------------------------------


class TestMarkdownInsightSection:
    def setup_method(self):
        self.insight = _mk_insight()
        self.report = MarkdownReport()
        self.md_lines = self.report.render_insight_section(self.insight)
        self.md = "\n".join(self.md_lines)

    def test_contains_scorecard(self):
        assert "## Scorecard" in self.md

    def test_contains_metrics(self):
        assert "## Metrics" in self.md

    def test_contains_top_issues(self):
        assert "## Top Issues" in self.md

    def test_contains_findings_by_severity(self):
        assert "## Findings by Severity" in self.md

    def test_contains_findings_by_tool(self):
        assert "## Findings by Tool" in self.md

    def test_contains_recommendations(self):
        assert "## Recommendations" in self.md

    def test_scorecard_table_has_pass_fail(self):
        assert "FAIL" in self.md

    def test_scorecard_table_has_numbers(self):
        assert str(self.insight.scorecard.total_findings) in self.md
        assert str(self.insight.scorecard.errors) in self.md

    def test_non_insight_input_returns_empty(self):
        """非 ReportInsight 输入返回空列表。"""
        result = self.report.render_insight_section({"not": "insight"})
        assert result == []


# ---------------------------------------------------------------------------
# 6. JSON report shape
# ---------------------------------------------------------------------------


class TestJSONReportShape:
    def setup_method(self):
        self.insight = _mk_insight()
        self.json_dict = report_insight_to_json_dict(self.insight)

    def test_is_dict(self):
        assert isinstance(self.json_dict, dict)

    def test_has_summary(self):
        assert "summary" in self.json_dict
        assert "passed" in self.json_dict["summary"]

    def test_has_metrics(self):
        assert "metrics" in self.json_dict
        assert "tool_call_count" in self.json_dict["metrics"]

    def test_has_scorecard(self):
        assert "scorecard" in self.json_dict
        assert "severity_breakdown" in self.json_dict["scorecard"]

    def test_has_findings(self):
        assert "findings" in self.json_dict

    def test_has_grouped_findings(self):
        assert "grouped_findings" in self.json_dict
        gf = self.json_dict["grouped_findings"]
        for key in ["by_severity", "by_category", "by_tool", "by_rule_id_prefix"]:
            assert key in gf

    def test_has_recommendations(self):
        assert "recommendations" in self.json_dict

    def test_has_judge_findings(self):
        assert "judge_findings" in self.json_dict

    def test_has_metadata(self):
        assert "metadata" in self.json_dict
        assert self.json_dict["metadata"]["schema_version"] == "3.1.0"

    def test_summary_passed_is_bool(self):
        assert isinstance(self.json_dict["summary"]["passed"], bool)

    def test_non_insight_input_returns_empty(self):
        assert report_insight_to_json_dict(None) == {}

    def test_grouped_findings_are_counts(self):
        """grouped_findings 序列化为计数字典，不嵌套完整 finding。"""
        gf = self.json_dict["grouped_findings"]
        assert isinstance(gf["by_severity"], dict)
        for count in gf["by_severity"].values():
            assert isinstance(count, int)

    def test_recommendation_fields(self):
        """每条 recommendation 包含所有必需字段。"""
        for rec in self.json_dict["recommendations"]:
            for key in ("rule_id", "category", "severity",
                        "what", "why", "how_to_fix", "affected_count"):
                assert key in rec


# ---------------------------------------------------------------------------
# 7. ReportInsightMetadata dataclass
# ---------------------------------------------------------------------------


class TestMetadataDataclass:
    def test_frozen(self):
        meta = ReportInsightMetadata()
        with pytest.raises(AttributeError):
            meta.schema_version = "4.0"  # type: ignore[misc]

    def test_defaults(self):
        meta = ReportInsightMetadata()
        assert meta.schema_version == "3.1.0"
        assert meta.generated_at == ""
        assert meta.signal_quality == "unknown"


# ---------------------------------------------------------------------------
# 8. ReportInsight dataclass
# ---------------------------------------------------------------------------


class TestReportInsightDataclass:
    def test_frozen(self):
        insight = _mk_insight()
        with pytest.raises(AttributeError):
            insight.metrics = None  # type: ignore[misc]

    def test_defaults(self):
        """empty construction 默认值正确。"""
        insight = ReportInsight(
            metrics=_mk_insight().metrics,
            scorecard=_mk_insight().scorecard,
            grouped_findings=_mk_insight().grouped_findings,
        )
        assert insight.recommendations == []
        assert insight.findings == []
        assert insight.judge_findings == []

    def test_recommendations_not_review_decision(self):
        """recommendations 不生成 ReviewDecision。"""
        insight = _mk_insight()
        for rec in insight.recommendations:
            assert not hasattr(rec, "decision")


# ---------------------------------------------------------------------------
# 9. 兼容性：render_from_core 不带 insight 时不变
# ---------------------------------------------------------------------------


class TestBackwardCompat:
    def test_render_from_core_without_insight(self):
        """不带 insight 参数调用 render_from_core 不崩溃，不含 insight 段。"""
        report = MarkdownReport()
        results = [{
            "eval_id": "s1", "passed": True, "findings": [],
            "summary": "ok",
        }]
        report_summary = {
            "total_scenarios": 1, "passed": 1, "failed": 0,
            "errors": 0, "signal_quality": "mock",
            "generated_at": "2025-01-01T00:00:00Z",
        }
        md = report.render_from_core(
            results=results,
            report_summary=report_summary,
            signal_quality="mock",
        )
        assert "## Agent Tool-Use Eval (Core Flow)" in md
        assert "## Scorecard" not in md

    def test_render_from_core_with_insight(self):
        """带 insight 参数时 render_from_core 包含 insight 段。"""
        report = MarkdownReport()
        results = [{
            "eval_id": "s1", "passed": False, "findings": [],
            "summary": "failed",
        }]
        report_summary = {
            "total_scenarios": 1, "passed": 0, "failed": 1,
            "errors": 0, "signal_quality": "mock",
            "generated_at": "2025-01-01T00:00:00Z",
        }
        insight = _mk_insight()
        md = report.render_from_core(
            results=results,
            report_summary=report_summary,
            signal_quality="mock",
            insight=insight,
        )
        assert "## Scorecard" in md
        assert "## Metrics" in md
        assert "## Recommendations" in md
        assert "## Agent Tool-Use Eval (Core Flow)" in md
