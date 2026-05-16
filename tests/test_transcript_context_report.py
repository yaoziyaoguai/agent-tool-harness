"""v3.5 P4: Analysis 报告渲染测试。"""

from __future__ import annotations

from agent_tool_harness.analysis.render import (
    RECOMMENDATION_CATALOG,
    render_analysis_json,
    render_analysis_markdown,
    render_context_analysis_markdown,
    render_transcript_analysis_markdown,
)
from agent_tool_harness.core_contract import RuleFinding

# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


def _make_finding(
    finding_id: str,
    category: str,
    severity: str,
    rule_type: str,
    message: str = "",
    evidence_ref: str = "",
) -> RuleFinding:
    return RuleFinding(
        finding_id=finding_id,
        severity=severity,
        category=category,
        message=message or f"Test message for {rule_type}",
        evidence_ref=evidence_ref or "test_evidence",
        rule_type=rule_type,
        rule_passed=False,
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


class TestRenderTranscriptMarkdown:
    def test_empty(self):
        assert render_transcript_analysis_markdown([]) == ""

    def test_single_finding(self):
        findings = [
            _make_finding("t1", "transcript", "high", "transcript.repeated_tool_retry_loop",
                          message="'search' 连续调用 3 次",
                          evidence_ref="tool_calls[0:3]"),
        ]
        md = render_transcript_analysis_markdown(findings)
        assert "Agent Confusion Patterns" in md
        assert "transcript.repeated_tool_retry_loop" in md
        assert "search" in md
        assert "tool_calls[0:3]" in md

    def test_multiple_findings(self):
        findings = [
            _make_finding("t1", "transcript", "high", "transcript.repeated_tool_retry_loop"),
            _make_finding("t2", "transcript", "medium", "transcript.tool_switching_confusion"),
        ]
        md = render_transcript_analysis_markdown(findings)
        assert "transcript.repeated_tool_retry_loop" in md
        assert "transcript.tool_switching_confusion" in md

    def test_only_context_findings_skipped(self):
        """只有 context category 时 transcript render 返回空。"""
        findings = [
            _make_finding("c1", "context", "high", "context.response_bloat"),
        ]
        assert render_transcript_analysis_markdown(findings) == ""


class TestRenderContextMarkdown:
    def test_empty(self):
        assert render_context_analysis_markdown([]) == ""

    def test_single_finding(self):
        findings = [
            _make_finding("c1", "context", "high", "context.response_bloat",
                          message="'search' 返回异常大输出"),
        ]
        md = render_context_analysis_markdown(findings)
        assert "Context Efficiency" in md
        assert "context.response_bloat" in md
        assert "search" in md

    def test_only_transcript_findings_skipped(self):
        findings = [
            _make_finding("t1", "transcript", "high", "transcript.repeated_tool_retry_loop"),
        ]
        assert render_context_analysis_markdown(findings) == ""


class TestRenderAnalysisMarkdown:
    def test_empty(self):
        assert render_analysis_markdown([]) == ""

    def test_mixed_findings(self):
        findings = [
            _make_finding("t1", "transcript", "high", "transcript.repeated_tool_retry_loop"),
            _make_finding("c1", "context", "high", "context.response_bloat"),
        ]
        md = render_analysis_markdown(findings)
        assert "Transcript & Context Analysis" in md
        assert "Agent Confusion Patterns" in md
        assert "Context Efficiency" in md
        assert "Recommendations" in md

    def test_recommendations_rendered(self):
        """验证 recommendation 确实渲染到了 markdown 中。"""
        findings = [
            _make_finding("c1", "context", "high", "context.missing_pagination"),
        ]
        md = render_analysis_markdown(findings)
        assert "Recommendations" in md
        assert "missing_pagination" in md
        assert "分页参数" in md


# ---------------------------------------------------------------------------
# JSON rendering
# ---------------------------------------------------------------------------


class TestRenderAnalysisJson:
    def test_empty(self):
        result = render_analysis_json([])
        assert result == {"transcript": [], "context": [], "recommendations": []}

    def test_mixed_findings_json(self):
        findings = [
            _make_finding("t1", "transcript", "high", "transcript.repeated_tool_retry_loop",
                          message="test transcript"),
            _make_finding("c1", "context", "high", "context.response_bloat",
                          message="test context"),
        ]
        result = render_analysis_json(findings)
        assert len(result["transcript"]) == 1
        assert len(result["context"]) == 1
        assert result["transcript"][0]["rule_type"] == "transcript.repeated_tool_retry_loop"
        assert result["context"][0]["rule_type"] == "context.response_bloat"
        assert len(result["recommendations"]) == 2

    def test_deduplicated_recommendations(self):
        """相同 rule_type 的多个 finding → recommendations 去重。"""
        findings = [
            _make_finding("t1", "transcript", "high", "transcript.repeated_tool_retry_loop"),
            _make_finding("t2", "transcript", "high", "transcript.repeated_tool_retry_loop"),
        ]
        result = render_analysis_json(findings)
        assert len(result["recommendations"]) == 1


# ---------------------------------------------------------------------------
# Recommendation catalog
# ---------------------------------------------------------------------------


class TestRecommendationCatalog:
    def test_catalog_covers_all_rule_types(self):
        """推荐目录应覆盖全部 11 个 rule type (6 transcript + 5 context)。"""
        expected_types = {
            "transcript.repeated_tool_retry_loop",
            "transcript.tool_switching_confusion",
            "transcript.invalid_arg_retry",
            "transcript.no_recovery_after_error",
            "transcript.final_answer_without_support",
            "transcript.broad_search_loop",
            "context.response_bloat",
            "context.missing_pagination",
            "context.missing_concise_mode",
            "context.low_value_large_fields",
            "context.truncation_without_hint",
        }
        assert set(RECOMMENDATION_CATALOG.keys()) == expected_types

    def test_all_recommendations_non_empty(self):
        for rule_type, rec in RECOMMENDATION_CATALOG.items():
            assert rec, f"推荐 {rule_type} 不应为空"
