"""RegressionComparator —— v3.4 回归对比编排器。

消费 baseline + candidate ReportInsight，产出 RegressionReport。
所有计算 deterministic、零网络依赖、不修改输入。

架构边界
--------
- **负责**：计算 metric diff、finding diff、task outcome diff、
  生成 regression warnings、组装 RegressionReport。
- **不负责**：不做报告渲染（那是 regression_report.py 的事）、
  不修改 v3.1-v3.3 对象、不运行 Agent、不调 LLM。
- **为什么用独立 Comparator 类而非纯函数**：
  可配置 thresholds 需要携带状态；compare() 从多种输入（ReportInsight、
  TaskOutcome 列表、SuiteResult）组装输出，编排逻辑适合放在类中。
"""

from __future__ import annotations

from agent_tool_harness.regression.diff_schema import (
    FindingDiff,
    MetricDiff,
    RegressionReport,
    RegressionThresholds,
    RegressionWarning,
    SuiteDiff,
    TaskOutcomeDiff,
)
from agent_tool_harness.reports.report_insight import ReportInsight
from agent_tool_harness.suite_eval.suite_result import SuiteResult
from agent_tool_harness.task_eval.task_evaluator import TaskOutcome

# ---------------------------------------------------------------------------
# metric 语义映射：哪些指标上升是 worse，哪些上升是 better
# ---------------------------------------------------------------------------

# 指标值上升 = 变差
_WORSE_WHEN_HIGHER = {
    "tool_error_rate",
    "tool_error_count",
    "orphan_call_count",
    "orphan_result_count",
    "repeated_tool_call_count",
    "total_findings",
    "errors",
    "warnings",
    "info",
    "advisory_count",
}

# 指标值上升 = 变好
_BETTER_WHEN_HIGHER = {
    "tool_success_count",
    "tool_success_rate",
    "task_success_rate",
    "deterministic_pass_rate",
    "unique_tool_count",
}


def _direction(metric_name: str, delta: float) -> str:
    """根据 metric 语义和 delta 符号计算 direction。

    Args:
        metric_name: 指标名。
        delta: candidate - baseline。

    Returns:
        "better" | "worse" | "neutral"。
    """
    if delta == 0.0:
        return "neutral"
    if metric_name in _BETTER_WHEN_HIGHER:
        return "better" if delta > 0 else "worse"
    if metric_name in _WORSE_WHEN_HIGHER:
        return "worse" if delta > 0 else "better"
    # 未知 metric：正 delta = worse（保守）
    return "worse" if delta > 0 else "better"


# ---------------------------------------------------------------------------
# Metric diff
# ---------------------------------------------------------------------------

# 需要进行回归对比的指标及 label
_METRICS_TO_COMPARE: list[tuple[str, str]] = [
    # (ReportMetrics 属性名, 显示名)
    ("tool_error_rate", "Tool Error Rate"),
    ("tool_error_count", "Tool Error Count"),
    ("tool_success_count", "Tool Success Count"),
    ("orphan_call_count", "Orphan Call Count"),
    ("orphan_result_count", "Orphan Result Count"),
    ("repeated_tool_call_count", "Repeated Tool Call Count"),
    ("unique_tool_count", "Unique Tool Count"),
    ("tool_call_count", "Total Tool Calls"),
    ("judge_finding_count", "LLM Judge Findings"),
]


def compute_metric_diffs(
    baseline_metrics,
    candidate_metrics,
) -> list[MetricDiff]:
    """计算 baseline vs candidate 的指标 diff 列表。

    Args:
        baseline_metrics: ReportMetrics（baseline 侧）。
        candidate_metrics: ReportMetrics（candidate 侧）。

    Returns:
        MetricDiff 列表，按 metric_name 稳定排序。
    """
    diffs: list[MetricDiff] = []
    for attr, label in _METRICS_TO_COMPARE:
        b_val = float(getattr(baseline_metrics, attr, 0.0))
        c_val = float(getattr(candidate_metrics, attr, 0.0))
        delta = c_val - b_val
        direction = _direction(attr, delta)
        diffs.append(MetricDiff(
            metric_name=label,
            baseline_value=b_val,
            candidate_value=c_val,
            delta=delta,
            direction=direction,
        ))

    # 添加 finding 派生统计
    b_sev = getattr(baseline_metrics, "finding_count_by_severity", {})
    c_sev = getattr(candidate_metrics, "finding_count_by_severity", {})

    b_total = sum(b_sev.values())
    c_total = sum(c_sev.values())
    if b_total > 0 or c_total > 0:
        diffs.append(MetricDiff(
            metric_name="Total Findings",
            baseline_value=float(b_total),
            candidate_value=float(c_total),
            delta=float(c_total - b_total),
            direction=_direction("total_findings", float(c_total - b_total)),
        ))

    b_errors = b_sev.get("critical", 0) + b_sev.get("high", 0)
    c_errors = c_sev.get("critical", 0) + c_sev.get("high", 0)
    if b_errors > 0 or c_errors > 0:
        diffs.append(MetricDiff(
            metric_name="Errors (critical+high)",
            baseline_value=float(b_errors),
            candidate_value=float(c_errors),
            delta=float(c_errors - b_errors),
            direction=_direction("errors", float(c_errors - b_errors)),
        ))

    b_warnings = b_sev.get("medium", 0) + b_sev.get("low", 0)
    c_warnings = c_sev.get("medium", 0) + c_sev.get("low", 0)
    if b_warnings > 0 or c_warnings > 0:
        diffs.append(MetricDiff(
            metric_name="Warnings (medium+low)",
            baseline_value=float(b_warnings),
            candidate_value=float(c_warnings),
            delta=float(c_warnings - b_warnings),
            direction=_direction("warnings", float(c_warnings - b_warnings)),
        ))

    # 稳定排序：按 metric_name
    diffs.sort(key=lambda d: d.metric_name)
    return diffs


# ---------------------------------------------------------------------------
# Finding diff
# ---------------------------------------------------------------------------


def compute_finding_diffs(
    baseline_insight: ReportInsight,
    candidate_insight: ReportInsight,
) -> list[FindingDiff]:
    """计算 baseline vs candidate 的 finding 数量变化。

    按 category 聚合，识别新增和消除的 rule_id。

    Args:
        baseline_insight: baseline ReportInsight。
        candidate_insight: candidate ReportInsight。

    Returns:
        FindingDiff 列表，按 category 稳定排序。
    """
    b_by_cat = baseline_insight.grouped_findings.by_category
    c_by_cat = candidate_insight.grouped_findings.by_category

    # 收集所有 category
    all_cats = sorted(set(b_by_cat.keys()) | set(c_by_cat.keys()))

    # 提取每个 category 的 rule_id 集合
    b_rule_ids_by_cat: dict[str, set[str]] = {}
    for cat, items in b_by_cat.items():
        b_rule_ids_by_cat[cat] = {
            getattr(f, "rule_type", "") or getattr(f, "finding_id", "")
            for f in items
        }

    c_rule_ids_by_cat: dict[str, set[str]] = {}
    for cat, items in c_by_cat.items():
        c_rule_ids_by_cat[cat] = {
            getattr(f, "rule_type", "") or getattr(f, "finding_id", "")
            for f in items
        }

    diffs: list[FindingDiff] = []
    for cat in all_cats:
        b_count = len(b_by_cat.get(cat, []))
        c_count = len(c_by_cat.get(cat, []))
        delta = c_count - b_count

        b_rule_ids = b_rule_ids_by_cat.get(cat, set())
        c_rule_ids = c_rule_ids_by_cat.get(cat, set())

        new_rule_ids = sorted(c_rule_ids - b_rule_ids)
        resolved_rule_ids = sorted(b_rule_ids - c_rule_ids)

        diffs.append(FindingDiff(
            category=cat,
            baseline_count=b_count,
            candidate_count=c_count,
            delta=delta,
            new_rule_ids=new_rule_ids,
            resolved_rule_ids=resolved_rule_ids,
        ))

    diffs.sort(key=lambda d: d.category)
    return diffs


# ---------------------------------------------------------------------------
# Task outcome diff
# ---------------------------------------------------------------------------


def _determine_change(baseline_status: str, candidate_status: str) -> str:
    """根据 baseline/candidate 状态确定 change 类型。

    五态：
    - new_failure: success/failed → failed（且与 baseline 不同，变得更差）
    - new_success: failed → success
    - new_inconclusive: 任意 → inconclusive
    - resolved_inconclusive: inconclusive → success/failed
    - unchanged: 相同状态
    """
    if baseline_status == candidate_status:
        return "unchanged"

    if candidate_status == "inconclusive":
        return "new_inconclusive"

    if baseline_status == "inconclusive":
        return "resolved_inconclusive"

    # success/failed 之间的转换
    if candidate_status == "failed":
        return "new_failure"
    if candidate_status == "success":
        return "new_success"

    return "unchanged"


def compute_task_outcome_diffs(
    baseline_outcomes: list[TaskOutcome] | None,
    candidate_outcomes: list[TaskOutcome] | None,
) -> list[TaskOutcomeDiff]:
    """计算 baseline vs candidate 的任务状态变化。

    Args:
        baseline_outcomes: baseline TaskOutcome 列表。
        candidate_outcomes: candidate TaskOutcome 列表。

    Returns:
        TaskOutcomeDiff 列表，按 case_id 稳定排序。
    """
    if not baseline_outcomes and not candidate_outcomes:
        return []

    b_map: dict[str, str] = {}
    if baseline_outcomes:
        for t in baseline_outcomes:
            b_map[t.case_id] = t.status

    c_map: dict[str, str] = {}
    if candidate_outcomes:
        for t in candidate_outcomes:
            c_map[t.case_id] = t.status

    all_case_ids = sorted(set(b_map.keys()) | set(c_map.keys()))

    diffs: list[TaskOutcomeDiff] = []
    for case_id in all_case_ids:
        b_status = b_map.get(case_id, "unknown")
        c_status = c_map.get(case_id, "unknown")
        change = _determine_change(b_status, c_status)
        diffs.append(TaskOutcomeDiff(
            case_id=case_id,
            baseline_status=b_status,
            candidate_status=c_status,
            change=change,
        ))

    diffs.sort(key=lambda d: d.case_id)
    return diffs


# ---------------------------------------------------------------------------
# Suite diff
# ---------------------------------------------------------------------------


def compute_suite_diff(
    baseline_suite: SuiteResult | None,
    candidate_suite: SuiteResult | None,
    task_outcome_diffs: list[TaskOutcomeDiff] | None = None,
) -> SuiteDiff | None:
    """计算 suite 级别对比。

    Args:
        baseline_suite: baseline SuiteResult。
        candidate_suite: candidate SuiteResult。
        task_outcome_diffs: 已计算的 TaskOutcomeDiff 列表（用于统计 new_failure/new_success）。

    Returns:
        SuiteDiff 或 None（当任一 SuiteResult 为 None 时）。
    """
    if baseline_suite is None or candidate_suite is None:
        return None

    new_failure_count = 0
    new_success_count = 0
    if task_outcome_diffs:
        new_failure_count = sum(1 for d in task_outcome_diffs if d.change == "new_failure")
        new_success_count = sum(1 for d in task_outcome_diffs if d.change == "new_success")

    return SuiteDiff(
        suite_id=baseline_suite.suite_id,
        baseline_task_success_rate=baseline_suite.task_success_rate,
        candidate_task_success_rate=candidate_suite.task_success_rate,
        task_success_rate_delta=(
            candidate_suite.task_success_rate - baseline_suite.task_success_rate
        ),
        baseline_deterministic_pass_rate=baseline_suite.deterministic_pass_rate,
        candidate_deterministic_pass_rate=candidate_suite.deterministic_pass_rate,
        deterministic_pass_rate_delta=(
            candidate_suite.deterministic_pass_rate
            - baseline_suite.deterministic_pass_rate
        ),
        baseline_total_cases=baseline_suite.total_cases,
        candidate_total_cases=candidate_suite.total_cases,
        new_failure_count=new_failure_count,
        new_success_count=new_success_count,
    )


# ---------------------------------------------------------------------------
# Regression warnings
# ---------------------------------------------------------------------------


def compute_regression_warnings(
    metric_diffs: list[MetricDiff],
    task_outcome_diffs: list[TaskOutcomeDiff],
    finding_diffs: list[FindingDiff],
    thresholds: RegressionThresholds,
    baseline_metrics,
    candidate_metrics,
) -> list[RegressionWarning]:
    """检测 5 种回归警告。

    RFC Decision 3 定义的 5 种 warning：
    1. new_task_failures
    2. error_rate_spike
    3. finding_explosion
    4. new_tool_errors
    5. task_success_drop

    Args:
        metric_diffs: 已计算的 metric diff 列表。
        task_outcome_diffs: 已计算的 task outcome diff 列表。
        finding_diffs: 已计算的 finding diff 列表。
        thresholds: 可配置阈值。
        baseline_metrics: baseline ReportMetrics。
        candidate_metrics: candidate ReportMetrics。

    Returns:
        RegressionWarning 列表。
    """
    warnings: list[RegressionWarning] = []

    # 1. new_task_failures
    new_failures = [d for d in task_outcome_diffs if d.change == "new_failure"]
    if new_failures:
        case_ids = ", ".join(d.case_id for d in new_failures)
        warnings.append(RegressionWarning(
            warning_type="new_task_failures",
            severity="critical",
            threshold="any new failure",
            actual=f"{len(new_failures)} new failures: {case_ids}",
            message=(
                f"{len(new_failures)} previously passing task(s) now fail: {case_ids}"
            ),
        ))

    # 2. error_rate_spike
    b_error_rate = getattr(baseline_metrics, "tool_error_rate", 0.0)
    c_error_rate = getattr(candidate_metrics, "tool_error_rate", 0.0)
    if thresholds.error_rate_spike_pct is not None and b_error_rate > 0:
        pct_change = ((c_error_rate - b_error_rate) / b_error_rate) * 100
        if pct_change > thresholds.error_rate_spike_pct:
            warnings.append(RegressionWarning(
                warning_type="error_rate_spike",
                severity="high",
                threshold=f">{thresholds.error_rate_spike_pct}% increase",
                actual=(
                    f"{b_error_rate:.1%} → {c_error_rate:.1%} "
                    f"(+{pct_change:.0f}%)"
                ),
                message=(
                    f"Tool error rate increased from {b_error_rate:.1%} to "
                    f"{c_error_rate:.1%} (+{pct_change:.0f}%, "
                    f"threshold: {thresholds.error_rate_spike_pct:.0f}%)"
                ),
            ))

    # 3. finding_explosion
    b_total = sum(
        getattr(baseline_metrics, "finding_count_by_severity", {}).values()
    )
    c_total = sum(
        getattr(candidate_metrics, "finding_count_by_severity", {}).values()
    )
    if thresholds.finding_explosion_pct is not None and b_total > 0:
        pct_change = ((c_total - b_total) / b_total) * 100
        if pct_change > thresholds.finding_explosion_pct:
            warnings.append(RegressionWarning(
                warning_type="finding_explosion",
                severity="high",
                threshold=f">{thresholds.finding_explosion_pct}% increase",
                actual=(
                    f"{b_total} → {c_total} findings "
                    f"(+{pct_change:.0f}%)"
                ),
                message=(
                    f"Finding count increased from {b_total} to {c_total} "
                    f"(+{pct_change:.0f}%, "
                    f"threshold: {thresholds.finding_explosion_pct:.0f}%)"
                ),
            ))

    # 4. new_tool_errors
    b_tool_errs = set(
        getattr(baseline_metrics, "finding_count_by_tool", {}).keys()
    )
    c_tool_errs = set(
        getattr(candidate_metrics, "finding_count_by_tool", {}).keys()
    )
    new_tool_err_set = c_tool_errs - b_tool_errs
    # 排除 "(unknown)"
    new_tool_err_set.discard("(unknown)")
    if new_tool_err_set:
        tools = ", ".join(sorted(new_tool_err_set))
        warnings.append(RegressionWarning(
            warning_type="new_tool_errors",
            severity="medium",
            threshold="any new tool with errors",
            actual=f"{len(new_tool_err_set)} new tool(s): {tools}",
            message=(
                f"{len(new_tool_err_set)} tool(s) with no errors in baseline "
                f"now have findings: {tools}"
            ),
        ))

    # 5. task_success_drop
    b_task_success = _compute_task_success_rate(task_outcome_diffs, "baseline")
    c_task_success = _compute_task_success_rate(task_outcome_diffs, "candidate")
    if (
        thresholds.task_success_drop_pp is not None
        and b_task_success is not None
        and c_task_success is not None
    ):
        drop = b_task_success - c_task_success
        if drop > thresholds.task_success_drop_pp / 100.0:
            warnings.append(RegressionWarning(
                warning_type="task_success_drop",
                severity="critical",
                threshold=f">{thresholds.task_success_drop_pp}pp drop",
                actual=(
                    f"{b_task_success:.1%} → {c_task_success:.1%} "
                    f"(-{drop:.1%})"
                ),
                message=(
                    f"Task success rate dropped from {b_task_success:.1%} to "
                    f"{c_task_success:.1%} (-{drop:.1%}, "
                    f"threshold: {thresholds.task_success_drop_pp}pp)"
                ),
            ))

    return warnings


def _compute_task_success_rate(
    diffs: list[TaskOutcomeDiff],
    side: str,
) -> float | None:
    """从 TaskOutcomeDiff 列表估算 task success rate。

    只统计非 unknown 状态的 case。
    """
    if not diffs:
        return None

    status_attr = f"{side}_status"
    valid = [d for d in diffs if getattr(d, status_attr) != "unknown"]
    if not valid:
        return None

    success_count = sum(1 for d in valid if getattr(d, status_attr) == "success")
    return success_count / len(valid)


# ---------------------------------------------------------------------------
# RegressionComparator —— 编排类
# ---------------------------------------------------------------------------


class RegressionComparator:
    """baseline vs candidate 回归对比编排器。

    消费 ReportInsight、TaskOutcome 列表、SuiteResult，产出 RegressionReport。
    所有计算 deterministic，不修改输入。

    用法::

        comparator = RegressionComparator()
        report = comparator.compare(baseline_insight, candidate_insight)
        print(f"Regression detected: {report.is_regression}")
        for w in report.regression_warnings:
            print(f"  [{w.severity}] {w.warning_type}: {w.message}")
    """

    def __init__(self, thresholds: RegressionThresholds | None = None):
        """初始化 comparator。

        Args:
            thresholds: 可配置阈值。None 使用默认值。
        """
        self.thresholds = thresholds or RegressionThresholds()

    def compare(
        self,
        baseline: ReportInsight,
        candidate: ReportInsight,
        baseline_task_outcomes: list[TaskOutcome] | None = None,
        candidate_task_outcomes: list[TaskOutcome] | None = None,
        baseline_suite: SuiteResult | None = None,
        candidate_suite: SuiteResult | None = None,
    ) -> RegressionReport:
        """执行完整回归对比。

        Args:
            baseline: baseline ReportInsight。
            candidate: candidate ReportInsight。
            baseline_task_outcomes: 可选 baseline TaskOutcome 列表。
            candidate_task_outcomes: 可选 candidate TaskOutcome 列表。
            baseline_suite: 可选 baseline SuiteResult。
            candidate_suite: 可选 candidate SuiteResult。

        Returns:
            RegressionReport：完整对比结果。
        """
        # metric diff
        metric_diffs = compute_metric_diffs(
            baseline.metrics, candidate.metrics
        )

        # finding diff
        finding_diffs = compute_finding_diffs(baseline, candidate)

        # task outcome diff
        task_outcome_diffs = compute_task_outcome_diffs(
            baseline_task_outcomes, candidate_task_outcomes
        )

        # suite diff
        suite_diff = compute_suite_diff(
            baseline_suite, candidate_suite, task_outcome_diffs
        )

        # regression warnings
        regression_warnings = compute_regression_warnings(
            metric_diffs=metric_diffs,
            task_outcome_diffs=task_outcome_diffs,
            finding_diffs=finding_diffs,
            thresholds=self.thresholds,
            baseline_metrics=baseline.metrics,
            candidate_metrics=candidate.metrics,
        )

        is_regression = len(regression_warnings) > 0

        # 生成 baseline_id / candidate_id
        b_id = getattr(baseline.metadata, "generated_at", "baseline")
        c_id = getattr(candidate.metadata, "generated_at", "candidate")

        return RegressionReport(
            baseline_id=str(b_id),
            candidate_id=str(c_id),
            is_regression=is_regression,
            metric_diffs=metric_diffs,
            finding_diffs=finding_diffs,
            task_outcome_diffs=task_outcome_diffs,
            suite_diff=suite_diff,
            regression_warnings=regression_warnings,
        )
