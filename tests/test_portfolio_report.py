"""Portfolio 报告渲染测试 —— Markdown / JSON 输出。"""

from agent_tool_harness.portfolio.improvement_brief import (
    EvidenceRef,
    ToolImprovementBrief,
)
from agent_tool_harness.portfolio.portfolio_review import PortfolioFinding
from agent_tool_harness.portfolio.render import (
    render_improvement_brief_json,
    render_improvement_brief_markdown,
    render_portfolio_analysis_json,
    render_portfolio_analysis_markdown,
    render_portfolio_review_json,
    render_portfolio_review_markdown,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_portfolio_finding(
    check_name: str = "overlapping_tools",
    severity: str = "warning",
    affected_tools: list[str] | None = None,
    description: str = "测试描述",
    suggestion: str = "测试建议",
    evidence: list[str] | None = None,
) -> PortfolioFinding:
    return PortfolioFinding(
        check_name=check_name,
        severity=severity,
        affected_tools=affected_tools or ["tool_a", "tool_b"],
        description=description,
        suggestion=suggestion,
        evidence=evidence or ["test_evidence"],
    )


def _make_brief(
    tool_name: str = "search",
    priority: str = "high",
    category: str = "response",
) -> ToolImprovementBrief:
    return ToolImprovementBrief(
        tool_name=tool_name,
        priority=priority,
        category=category,
        evidence=EvidenceRef(
            finding_ids=["f-1", "f-2"],
            metric_values={"tool_error_rate": 0.3},
            transcript_signal_types=["response_bloat"],
        ),
        current_state="响应过大",
        recommended_state="添加分页",
        rationale="减少上下文浪费",
        effort_estimate="small",
    )


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


class TestPortfolioReviewMarkdown:
    """组合评审 Markdown 渲染。"""

    def test_renders_single_finding(self):
        pf = [_make_portfolio_finding()]
        md = render_portfolio_review_markdown(pf)
        assert "工具组合评审" in md
        assert "工具重叠" in md
        assert "测试描述" in md
        assert "tool_a" in md

    def test_empty_list_returns_empty(self):
        assert render_portfolio_review_markdown([]) == ""

    def test_groups_by_check_name(self):
        pf = [
            _make_portfolio_finding("namespacing_consistency"),
            _make_portfolio_finding("namespacing_consistency"),
            _make_portfolio_finding("shallow_wrappers"),
        ]
        md = render_portfolio_review_markdown(pf)
        assert "命名空间一致性" in md
        assert "浅层包装" in md


class TestImprovementBriefMarkdown:
    """改进建议 Markdown 渲染。"""

    def test_renders_brief(self):
        briefs = [_make_brief()]
        md = render_improvement_brief_markdown(briefs)
        assert "工具改进建议" in md
        assert "search" in md
        assert "响应过大" in md
        assert "工作量估计" in md

    def test_sorts_by_priority(self):
        briefs = [
            _make_brief("low_tool", priority="low"),
            _make_brief("critical_tool", priority="critical"),
            _make_brief("medium_tool", priority="medium"),
        ]
        md = render_improvement_brief_markdown(briefs)
        # critical 应该在 low 之前
        crit_pos = md.index("critical_tool")
        low_pos = md.index("low_tool")
        assert crit_pos < low_pos

    def test_empty_list_returns_empty(self):
        assert render_improvement_brief_markdown([]) == ""


class TestCombinedMarkdown:
    """组合 Markdown 渲染。"""

    def test_rendes_both_sections(self):
        pf = [_make_portfolio_finding()]
        briefs = [_make_brief()]
        md = render_portfolio_analysis_markdown(pf, briefs)
        assert "工具组合评审" in md
        assert "工具改进建议" in md

    def test_empty_all_returns_empty(self):
        assert render_portfolio_analysis_markdown([], []) == ""


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


class TestPortfolioReviewJSON:
    """JSON 序列化。"""

    def test_serializes_finding(self):
        pf = [_make_portfolio_finding()]
        result = render_portfolio_review_json(pf)
        assert len(result) == 1
        assert result[0]["check_name"] == "overlapping_tools"
        assert result[0]["severity"] == "warning"
        assert "tool_a" in result[0]["affected_tools"]

    def test_empty_list(self):
        assert render_portfolio_review_json([]) == []


class TestImprovementBriefJSON:
    """改进建议 JSON 序列化。"""

    def test_serializes_brief(self):
        briefs = [_make_brief()]
        result = render_improvement_brief_json(briefs)
        assert len(result) == 1
        assert result[0]["tool_name"] == "search"
        assert result[0]["priority"] == "high"
        assert result[0]["evidence"]["finding_ids"] == ["f-1", "f-2"]

    def test_empty_list(self):
        assert render_improvement_brief_json([]) == []


class TestCombinedJSON:
    """组合 JSON。"""

    def test_combined_output(self):
        pf = [_make_portfolio_finding()]
        briefs = [_make_brief()]
        result = render_portfolio_analysis_json(pf, briefs)
        assert "portfolio_review" in result
        assert "improvement_briefs" in result
        assert len(result["portfolio_review"]) == 1
        assert len(result["improvement_briefs"]) == 1

    def test_empty_all(self):
        result = render_portfolio_analysis_json([], [])
        assert result["portfolio_review"] == []
        assert result["improvement_briefs"] == []
