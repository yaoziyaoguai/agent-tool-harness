#!/usr/bin/env python3
"""v3.4 Regression Comparison 使用示例。

演示 RegressionComparator API 的典型用法：
1. 构造 baseline/candidate 数据
2. 执行对比
3. 检查回归警告
4. 渲染 Markdown 报告
5. JSON 序列化

可直接运行::

    python examples/regression_comparison_demo.py
"""

from __future__ import annotations

from agent_tool_harness.regression import (
    RegressionComparator,
    RegressionReport,
    RegressionThresholds,
    regression_report_to_dict,
    render_regression_markdown,
)
from agent_tool_harness.regression.regression_comparator import (
    compute_metric_diffs,
    compute_task_outcome_diffs,
)
from agent_tool_harness.reports.report_insight import (
    GroupedFindings,
    ReportInsight,
    ReportInsightMetadata,
    ReportMetrics,
    ReportScorecard,
)
from agent_tool_harness.task_eval.task_evaluator import TaskOutcome

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_insight(
    tool_error_rate=0.05,
    finding_count_by_severity=None,
    finding_count_by_tool=None,
) -> ReportInsight:
    """构造 demo ReportInsight。"""
    return ReportInsight(
        metrics=ReportMetrics(
            tool_call_count=20,
            tool_success_count=18,
            tool_error_count=2,
            tool_error_rate=tool_error_rate,
            finding_count_by_severity=finding_count_by_severity or {},
            finding_count_by_tool=finding_count_by_tool or {},
        ),
        scorecard=ReportScorecard(
            passed=True,
            total_findings=0,
            errors=0,
            warnings=0,
            info=0,
            advisory_count=0,
            tools_called=3,
            tool_errors=0,
        ),
        grouped_findings=GroupedFindings(),
        metadata=ReportInsightMetadata(generated_at="2026-05-01T00:00:00Z"),
    )


# ===================================================================
# 示例 1: 检测到回归（error rate spike + new failure）
# ===================================================================


def example1_regression_detected():
    """error rate 剧增 + task 失败 = 回归信号。"""
    print("=" * 60)
    print("示例 1: 回归检测")
    print("=" * 60)

    # baseline
    baseline = _make_insight(
        tool_error_rate=0.05,
        finding_count_by_severity={"high": 1, "medium": 2},
        finding_count_by_tool={"tool_a": 1},
    )
    # candidate — error rate 飙升
    candidate = _make_insight(
        tool_error_rate=0.20,
        finding_count_by_severity={"critical": 1, "high": 3, "medium": 5},
        finding_count_by_tool={"tool_a": 3, "tool_b": 2},
    )

    comparator = RegressionComparator(
        thresholds=RegressionThresholds(
            error_rate_spike_pct=100.0,
            finding_explosion_pct=50.0,
            task_success_drop_pp=10.0,
        )
    )

    # 模拟 task outcome 变化
    baseline_tasks = [
        TaskOutcome(case_id="case-1", status="success"),
        TaskOutcome(case_id="case-2", status="success"),
        TaskOutcome(case_id="case-3", status="failed"),
    ]
    candidate_tasks = [
        TaskOutcome(case_id="case-1", status="failed"),   # 回归！
        TaskOutcome(case_id="case-2", status="success"),
        TaskOutcome(case_id="case-3", status="success"),  # 改善
    ]

    report = comparator.compare(
        baseline, candidate,
        baseline_task_outcomes=baseline_tasks,
        candidate_task_outcomes=candidate_tasks,
    )

    print(f"\n回归检测: {report.is_regression}")
    print(f"警告数: {len(report.regression_warnings)}")
    for w in report.regression_warnings:
        print(f"  [{w.severity}] {w.warning_type}: {w.message}")

    # 指标对比
    print("\n指标变化:")
    for d in report.metric_diffs:
        if d.direction != "neutral":
            print(f"  {d.metric_name}: {d.delta:+.2f} [{d.direction}]")

    # task 状态变化
    print("\nTask 状态变化:")
    for d in report.task_outcome_diffs:
        if d.change != "unchanged":
            print(f"  {d.case_id}: {d.baseline_status} → {d.candidate_status} ({d.change})")

    return report


# ===================================================================
# 示例 2: 无回归（指标改善）
# ===================================================================


def example2_no_regression():
    """所有指标改善或保持不变 = 无回归。"""
    print("\n" + "=" * 60)
    print("示例 2: 无回归（改善）")
    print("=" * 60)

    baseline = _make_insight(
        tool_error_rate=0.15,
        finding_count_by_severity={"critical": 2, "high": 3},
    )
    candidate = _make_insight(
        tool_error_rate=0.05,
        finding_count_by_severity={"high": 1, "medium": 1},
    )

    baseline_tasks = [
        TaskOutcome(case_id="task-1", status="failed"),
        TaskOutcome(case_id="task-2", status="failed"),
    ]
    candidate_tasks = [
        TaskOutcome(case_id="task-1", status="success"),
        TaskOutcome(case_id="task-2", status="success"),
    ]

    report = RegressionComparator().compare(
        baseline, candidate,
        baseline_task_outcomes=baseline_tasks,
        candidate_task_outcomes=candidate_tasks,
    )

    print(f"\n回归检测: {report.is_regression}")
    print(f"警告数: {len(report.regression_warnings)}")

    print("\n指标变化:")
    for d in report.metric_diffs:
        if d.direction != "neutral":
            print(f"  {d.metric_name}: {d.delta:+.2f} [{d.direction}]")

    print("\nTask 状态变化:")
    for d in report.task_outcome_diffs:
        print(f"  {d.case_id}: {d.baseline_status} → {d.candidate_status} ({d.change})")

    return report


# ===================================================================
# 示例 3: Markdown / JSON 输出
# ===================================================================


def example3_report_output(report: RegressionReport):
    """演示 Markdown 渲染和 JSON 序列化。"""
    print("\n" + "=" * 60)
    print("示例 3: Markdown / JSON 输出")
    print("=" * 60)

    # Markdown
    md = render_regression_markdown(report)
    print("\n--- Markdown (前 20 行) ---")
    for line in md.split("\n")[:20]:
        print(f"  {line}")

    # JSON
    json_dict = regression_report_to_dict(report)
    import json
    json_str = json.dumps(json_dict, indent=2, ensure_ascii=False)
    print("\n--- JSON (前 30 行) ---")
    for line in json_str.split("\n")[:30]:
        print(f"  {line}")


# ===================================================================
# 示例 4: 自定义阈值
# ===================================================================


def example4_custom_thresholds():
    """演示自定义阈值配置和禁用检测。"""
    print("\n" + "=" * 60)
    print("示例 4: 自定义阈值")
    print("=" * 60)

    baseline = _make_insight(
        tool_error_rate=0.02,
        finding_count_by_severity={"medium": 1},
    )
    candidate = _make_insight(
        tool_error_rate=0.06,  # +200%，默认阈值就触发
        finding_count_by_severity={"medium": 2},  # +100%
    )

    # 严格阈值：error_rate +50% 就报警，但禁用 finding_explosion
    strict = RegressionThresholds(
        error_rate_spike_pct=50.0,
        finding_explosion_pct=None,  # 禁用以外的检测
        task_success_drop_pp=None,
    )
    report = RegressionComparator(thresholds=strict).compare(baseline, candidate)

    print("\n严格阈值模式:")
    print(f"  error_rate_spike_pct={strict.error_rate_spike_pct}")
    print(f"  finding_explosion_pct={strict.finding_explosion_pct}")
    print(f"  回归检测: {report.is_regression}")
    for w in report.regression_warnings:
        print(f"  [{w.severity}] {w.warning_type}: {w.message}")


# ===================================================================
# 示例 5: 单独使用 compute_* 函数（非编排模式）
# ===================================================================


def example5_standalone_functions():
    """演示单独使用 compute_* 函数。"""
    print("\n" + "=" * 60)
    print("示例 5: 独立 compute_* 函数")
    print("=" * 60)

    b_metrics = ReportMetrics(tool_call_count=10, tool_error_count=1, tool_error_rate=0.1)
    c_metrics = ReportMetrics(tool_call_count=10, tool_error_count=3, tool_error_rate=0.3)

    # 只用指标对比
    diffs = compute_metric_diffs(b_metrics, c_metrics)
    print("\n指标 diff:")
    for d in diffs[:3]:
        print(f"  {d.metric_name}: {d.delta:+.2f} [{d.direction}]")

    # 只用 task outcome diff
    baseline_tasks = [TaskOutcome(case_id="c1", status="success")]
    candidate_tasks = [TaskOutcome(case_id="c1", status="failed")]
    outcome_diffs = compute_task_outcome_diffs(baseline_tasks, candidate_tasks)
    print("\nTask outcome diff:")
    for d in outcome_diffs:
        print(f"  {d.case_id}: {d.baseline_status} → {d.candidate_status} ({d.change})")


# ===================================================================
# main
# ===================================================================


def main():
    report1 = example1_regression_detected()
    example2_no_regression()
    example3_report_output(report1)
    example4_custom_thresholds()
    example5_standalone_functions()
    print("\n所有示例执行完毕。")


if __name__ == "__main__":
    main()
