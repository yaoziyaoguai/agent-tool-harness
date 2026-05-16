"""Tool Portfolio Review & Improvement Brief —— v3.6 工具组合评审与改进建议。

识别工具组合级别的结构问题（5 类）并生成含证据引用的改进建议。
所有分析 deterministic、零网络依赖。

组件
----
- ToolPortfolioReview: 5 类静态+信号聚合检查
- PortfolioFinding: 跨工具的结构性发现
- ToolImprovementBrief: per-tool + cross-tool 改进建议
"""

from agent_tool_harness.portfolio.improvement_brief import (
    EvidenceCollector,
    EvidenceRef,
    ToolImprovementBrief,
    ToolImprovementBriefGenerator,
)
from agent_tool_harness.portfolio.portfolio_review import (
    PortfolioFinding,
    ToolPortfolioReview,
)
from agent_tool_harness.portfolio.render import (
    render_improvement_brief_json,
    render_improvement_brief_markdown,
    render_portfolio_analysis_json,
    render_portfolio_analysis_markdown,
    render_portfolio_review_json,
    render_portfolio_review_markdown,
)

__all__ = [
    "PortfolioFinding",
    "ToolPortfolioReview",
    "EvidenceRef",
    "ToolImprovementBrief",
    "EvidenceCollector",
    "ToolImprovementBriefGenerator",
    "render_portfolio_review_markdown",
    "render_improvement_brief_markdown",
    "render_portfolio_analysis_markdown",
    "render_portfolio_review_json",
    "render_improvement_brief_json",
    "render_portfolio_analysis_json",
]
