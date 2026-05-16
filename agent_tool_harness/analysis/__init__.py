"""Transcript & Context Analysis —— v3.5 转录与上下文效率分析。

识别 Agent 困惑模式（6 种）和上下文浪费信号（5 种）。
所有分析 deterministic、零网络依赖。

组件
----
- TranscriptPatternAnalyzer: 6 种 confusion pattern 检测
- ContextEfficiencyAnalyzer: 5 种 context inefficiency 检测
- render: Markdown/JSON 报告渲染 + recommendation catalog
"""

from agent_tool_harness.analysis.context_efficiency_analyzer import (
    ContextEfficiencyAnalyzer,
)
from agent_tool_harness.analysis.render import (
    RECOMMENDATION_CATALOG,
    render_analysis_json,
    render_analysis_markdown,
    render_context_analysis_markdown,
    render_transcript_analysis_markdown,
)
from agent_tool_harness.analysis.transcript_pattern_analyzer import (
    TranscriptPatternAnalyzer,
)

__all__ = [
    "TranscriptPatternAnalyzer",
    "ContextEfficiencyAnalyzer",
    "RECOMMENDATION_CATALOG",
    "render_analysis_json",
    "render_analysis_markdown",
    "render_context_analysis_markdown",
    "render_transcript_analysis_markdown",
]
