"""v3.4 P4: Regression Report 渲染测试。

测试覆盖：
- 空报告渲染（无 diff、无 warning）
- 包含 metric diff 的报告
- 包含 warning 的报告
- 包含 new_failure 的报告
- 包含 finding diff 的报告
- 包含 suite diff 的报告
- regression 检测 vs 正常报告
- Markdown 输出格式验证
"""

from __future__ import annotations

from agent_tool_harness.regression.diff_schema import (
    FindingDiff,
    MetricDiff,
    RegressionReport,
    RegressionWarning,
    SuiteDiff,
    TaskOutcomeDiff,
)
from agent_tool_harness.regression.regression_report import render_regression_markdown


def test_empty_report():
    """空 RegressionReport → 最简 Markdown。"""
    r = RegressionReport(
        baseline_id="baseline-v1",
        candidate_id="candidate-v2",
        is_regression=False,
    )
    md = render_regression_markdown(r)
    assert "baseline-v1" in md
    assert "candidate-v2" in md
    assert "No Regression Detected" in md
    # 无数据时不渲染对应 section
    assert "Summary" not in md
    assert "Regression Warnings" not in md
    assert "Newly Failing" not in md


def test_with_metric_diffs():
    """包含 metric diff → Summary 表格。"""
    r = RegressionReport(
        baseline_id="b1",
        candidate_id="c1",
        is_regression=False,
        metric_diffs=[
            MetricDiff("Tool Error Rate", 0.05, 0.12, 0.07, "worse"),
            MetricDiff("Task Success Rate", 0.8, 0.9, 0.1, "better"),
            MetricDiff("Total Tool Calls", 10.0, 10.0, 0.0, "neutral"),
        ],
    )
    md = render_regression_markdown(r)
    assert "## Summary" in md
    assert "Tool Error Rate" in md
    assert "↓ worse" in md
    assert "↑ better" in md
    assert "─" in md
    # 表格格式
    assert "| Metric | Baseline | Candidate | Delta | Direction |" in md


def test_with_regression_detected():
    """is_regression=True → 回归警告 banner。"""
    r = RegressionReport(
        baseline_id="b1",
        candidate_id="c1",
        is_regression=True,
        metric_diffs=[],
    )
    md = render_regression_markdown(r)
    assert "Regression Detected" in md


def test_with_regression_warnings():
    """包含 regression warning。"""
    r = RegressionReport(
        baseline_id="b1",
        candidate_id="c1",
        is_regression=True,
        regression_warnings=[
            RegressionWarning(
                warning_type="error_rate_spike",
                severity="high",
                threshold="2x (100% increase)",
                actual="0.05 → 0.12 (+140%)",
                message="Tool error rate increased from 5.0% to 12.0%",
            ),
            RegressionWarning(
                warning_type="new_task_failures",
                severity="critical",
                threshold="any new failure",
                actual="2 new failures: case-1, case-2",
                message="2 previously passing cases now fail",
            ),
        ],
    )
    md = render_regression_markdown(r)
    assert "## Regression Warnings" in md
    assert "error_rate_spike" in md
    assert "new_task_failures" in md
    assert "[high]" in md
    assert "[critical]" in md


def test_with_new_failures():
    """包含 new_failure TaskOutcomeDiff → Newly Failing 表格。"""
    r = RegressionReport(
        baseline_id="b1",
        candidate_id="c1",
        is_regression=True,
        task_outcome_diffs=[
            TaskOutcomeDiff("case-1", "success", "failed", "new_failure"),
            TaskOutcomeDiff("case-2", "success", "failed", "new_failure"),
            TaskOutcomeDiff("case-3", "failed", "success", "new_success"),
            TaskOutcomeDiff("case-4", "success", "success", "unchanged"),
        ],
    )
    md = render_regression_markdown(r)
    assert "## Newly Failing Tasks" in md
    assert "case-1" in md
    assert "case-2" in md
    assert "| Case ID | Baseline | Candidate |" in md
    # case-3 是 new_success，不应出现在 failing 表中
    assert "## Newly Succeeding Tasks" in md
    # case-4 不变，不出现在任何表中
    assert md.count("case-4") == 0  # 不变，不出现在任何表中


def test_with_finding_diffs():
    """包含 finding diff → Finding Changes 表格。"""
    r = RegressionReport(
        baseline_id="b1",
        candidate_id="c1",
        is_regression=False,
        finding_diffs=[
            FindingDiff(
                category="tool_call",
                baseline_count=5,
                candidate_count=8,
                delta=3,
                new_rule_ids=["rule_x", "rule_y"],
                resolved_rule_ids=[],
            ),
            FindingDiff(
                category="tool_response",
                baseline_count=3,
                candidate_count=1,
                delta=-2,
                new_rule_ids=[],
                resolved_rule_ids=["rule_z"],
            ),
        ],
    )
    md = render_regression_markdown(r)
    assert "## Finding Changes by Category" in md
    assert "tool_call" in md
    assert "tool_response" in md
    assert "rule_x, rule_y" in md
    assert "rule_z" in md


def test_with_suite_diff():
    """包含 SuiteDiff → Suite Comparison 段。"""
    sd = SuiteDiff(
        suite_id="s1",
        baseline_task_success_rate=0.8,
        candidate_task_success_rate=0.6,
        task_success_rate_delta=-0.2,
        baseline_deterministic_pass_rate=0.9,
        candidate_deterministic_pass_rate=0.7,
        deterministic_pass_rate_delta=-0.2,
        baseline_total_cases=10,
        candidate_total_cases=10,
        new_failure_count=2,
        new_success_count=0,
    )
    r = RegressionReport(
        baseline_id="b1",
        candidate_id="c1",
        is_regression=True,
        suite_diff=sd,
    )
    md = render_regression_markdown(r)
    assert "## Suite Comparison" in md
    assert "80.0%" in md
    assert "60.0%" in md
    assert "10" in md


def test_full_report():
    """完整报告：所有 section 均出现。"""
    sd = SuiteDiff(
        suite_id="s1",
        baseline_task_success_rate=1.0,
        candidate_task_success_rate=0.6,
        task_success_rate_delta=-0.4,
        baseline_deterministic_pass_rate=0.9,
        candidate_deterministic_pass_rate=0.5,
        deterministic_pass_rate_delta=-0.4,
        baseline_total_cases=5,
        candidate_total_cases=5,
        new_failure_count=2,
        new_success_count=1,
    )
    r = RegressionReport(
        baseline_id="baseline-v1",
        candidate_id="candidate-v2",
        is_regression=True,
        metric_diffs=[
            MetricDiff("Tool Error Rate", 0.05, 0.15, 0.10, "worse"),
        ],
        finding_diffs=[
            FindingDiff("tool_call", 5, 8, 3,
                         new_rule_ids=["r1"], resolved_rule_ids=[]),
        ],
        task_outcome_diffs=[
            TaskOutcomeDiff("case-1", "success", "failed", "new_failure"),
            TaskOutcomeDiff("case-2", "failed", "success", "new_success"),
        ],
        regression_warnings=[
            RegressionWarning(
                "error_rate_spike", "high", "2x", "5%→15%",
                "Error rate spiked from 5% to 15%"
            ),
            RegressionWarning(
                "new_task_failures", "critical", "any", "1 new failure",
                "case-1 now fails"
            ),
        ],
        suite_diff=sd,
    )
    md = render_regression_markdown(r)

    # 所有 section 应出现
    assert "## Summary" in md
    assert "## Suite Comparison" in md
    assert "## Regression Warnings" in md
    assert "## Finding Changes by Category" in md
    assert "## Newly Failing Tasks" in md
    assert "## Newly Succeeding Tasks" in md

    # 标题
    assert "baseline-v1" in md
    assert "candidate-v2" in md
    assert "Regression Detected" in md

    # Markdown 结构完整性：标题在上
    summary_pos = md.index("## Summary")
    warnings_pos = md.index("## Regression Warnings")
    failures_pos = md.index("## Newly Failing Tasks")
    assert summary_pos < warnings_pos < failures_pos
