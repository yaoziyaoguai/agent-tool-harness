"""Regression Comparison —— v3.4 回归对比。

对比 baseline vs candidate 报告，自动检测回归信号。
所有组件 deterministic、零网络依赖。

主要入口
--------
- RegressionComparator: baseline vs candidate 对比编排器
- RegressionReport / MetricDiff / FindingDiff / TaskOutcomeDiff / SuiteDiff: 核心数据结构
- RegressionWarning / RegressionThresholds: 自动检测警告和可配置阈值
- render_regression_markdown: RegressionReport → Markdown 渲染
- regression_report_to_dict: RegressionReport → JSON 序列化（在 diff_schema 模块中）
"""

from agent_tool_harness.regression.diff_schema import (
    FindingDiff,
    MetricDiff,
    RegressionReport,
    RegressionThresholds,
    RegressionWarning,
    SuiteDiff,
    TaskOutcomeDiff,
    regression_report_to_dict,
)
from agent_tool_harness.regression.regression_comparator import (
    RegressionComparator,
)
from agent_tool_harness.regression.regression_report import (
    render_regression_markdown,
)

__all__ = [
    "FindingDiff",
    "MetricDiff",
    "RegressionComparator",
    "RegressionReport",
    "RegressionThresholds",
    "RegressionWarning",
    "SuiteDiff",
    "TaskOutcomeDiff",
    "regression_report_to_dict",
    "render_regression_markdown",
]
