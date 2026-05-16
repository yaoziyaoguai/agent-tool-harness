"""v3.4 P1: Regression comparison 核心数据结构。

定义 baseline vs candidate 对比所需的全部 frozen dataclass。
所有对象 immutable，方便测试和序列化。

架构边界
--------
- **负责**：定义 MetricDiff / FindingDiff / TaskOutcomeDiff / RegressionWarning /
  RegressionThresholds / RegressionReport / SuiteDiff 的数据结构。
- **不负责**：不做 diff 计算（那是 regression_comparator.py 的事）、
  不做报告渲染、不修改任何 v3.1-v3.3 对象。
- **为什么用 frozen dataclass**：immutability 保证对比结果不会被意外修改，
  JSON 序列化/反序列化也需要确定性的 schema。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# MetricDiff —— 单指标 baseline vs candidate 对比
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MetricDiff:
    """单指标对比结果。

    direction 由 delta 符号和 metric 语义共同决定：
    - error_rate / finding_count 上升 = worse
    - success_rate / pass_rate 上升 = better
    - 无显著变化 = neutral
    """

    metric_name: str
    """指标名称（如 tool_error_rate、task_success_rate）。"""

    baseline_value: float
    """baseline 侧的值。"""

    candidate_value: float
    """candidate 侧的值。"""

    delta: float
    """candidate - baseline。正数表示上升，负数表示下降。"""

    direction: str
    """"better" | "worse" | "neutral"。"""


# ---------------------------------------------------------------------------
# FindingDiff —— 按 category 的 finding 数量变化
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FindingDiff:
    """按 category 聚合的 finding 数量对比。

    不逐条比较 finding 内容——只比较数量变化。
    new_rule_ids 和 resolved_rule_ids 帮助定位具体变化来源。
    """

    category: str
    """finding 类别（如 tool_use、response、tool_design）。"""

    baseline_count: int
    """baseline 侧该 category 的 finding 总数。"""

    candidate_count: int
    """candidate 侧该 category 的 finding 总数。"""

    delta: int
    """candidate_count - baseline_count。正数表示新增 finding。"""

    new_rule_ids: list[str] = field(default_factory=list)
    """candidate 中新增的 rule_id（baseline 中未出现）。"""

    resolved_rule_ids: list[str] = field(default_factory=list)
    """baseline 中存在但 candidate 中已消除的 rule_id。"""


# ---------------------------------------------------------------------------
# TaskOutcomeDiff —— 单 case 状态变化
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TaskOutcomeDiff:
    """单个 eval case 的 task 状态变化。

    change 字段三态：
    - "new_failure"：baseline passed → candidate failed（回归）
    - "new_success"：baseline failed → candidate passed（改善）
    - "unchanged"：状态未变
    - "new_inconclusive"：变为 inconclusive
    - "resolved_inconclusive"：从 inconclusive 变为 success/failed
    """

    case_id: str
    """EvalCase.case_id。"""

    baseline_status: str
    """baseline 侧的 TaskOutcome.status。"""

    candidate_status: str
    """candidate 侧的 TaskOutcome.status。"""

    change: str
    """new_failure | new_success | unchanged | new_inconclusive | resolved_inconclusive。"""


# ---------------------------------------------------------------------------
# SuiteDiff —— suite 级别对比
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SuiteDiff:
    """两个 SuiteResult 的对比摘要。

    不存储完整的 per_case_results——只存聚合数字。
    逐 case diff 由 TaskOutcomeDiff 列表承载。
    """

    suite_id: str
    """对比的 suite_id（baseline 和 candidate 应相同）。"""

    baseline_task_success_rate: float
    candidate_task_success_rate: float
    task_success_rate_delta: float

    baseline_deterministic_pass_rate: float
    candidate_deterministic_pass_rate: float
    deterministic_pass_rate_delta: float

    baseline_total_cases: int
    candidate_total_cases: int

    new_failure_count: int
    """baseline passed → candidate failed 的 case 数。"""

    new_success_count: int
    """baseline failed → candidate passed 的 case 数。"""


# ---------------------------------------------------------------------------
# RegressionThresholds —— 可配置检测阈值
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegressionThresholds:
    """回归检测阈值配置。

    RFC Decision 3 定义了 5 种 warning 的默认阈值。
    所有阈值可独立配置——设 None 表示禁用该检测。
    """

    error_rate_spike_pct: float | None = 100.0
    """tool_error_rate 增长超过此百分比触发 error_rate_spike。默认 100%（2x）。"""

    finding_explosion_pct: float | None = 50.0
    """finding 总数增长超过此百分比触发 finding_explosion。默认 50%。"""

    task_success_drop_pp: float | None = 10.0
    """task_success_rate 下降超过此百分点触发 task_success_drop。默认 10 pp。"""


# ---------------------------------------------------------------------------
# RegressionWarning —— 自动检测的回归信号
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegressionWarning:
    """一条自动检测的回归警告。

    RFC Decision 3 定义了 5 种 warning_type：
    - new_task_failures
    - error_rate_spike
    - finding_explosion
    - new_tool_errors
    - task_success_drop
    """

    warning_type: str
    """警告类型标识（new_task_failures 等）。"""

    severity: str
    """"critical" | "high" | "medium"。"""

    threshold: str
    """触发阈值的人类可读描述。"""

    actual: str
    """实际值的人类可读描述。"""

    message: str
    """完整警告消息。"""


# ---------------------------------------------------------------------------
# RegressionReport —— 顶层回归报告
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RegressionReport:
    """baseline vs candidate 回归对比的完整结果。

    RFC Decision 1：is_regression 是 advisory flag，不自动阻止 CI。
    由人工或 CI 规则基于 warnings 决定是否 block。

    RegressionReport 是 v3.4 报告渲染的单一数据源。
    """

    baseline_id: str
    """baseline 报告标识。"""

    candidate_id: str
    """candidate 报告标识。"""

    is_regression: bool
    """是否存在任何回归信号（有 regression_warnings 即为 True）。"""

    metric_diffs: list[MetricDiff] = field(default_factory=list)
    """所有指标的对比结果。"""

    finding_diffs: list[FindingDiff] = field(default_factory=list)
    """按 category 的 finding 变化。"""

    task_outcome_diffs: list[TaskOutcomeDiff] = field(default_factory=list)
    """逐 case 状态变化。"""

    suite_diff: SuiteDiff | None = None
    """suite 级别对比（仅当提供了 SuiteResult 时）。"""

    regression_warnings: list[RegressionWarning] = field(default_factory=list)
    """自动检测的回归警告列表。"""


# ---------------------------------------------------------------------------
# JSON serialization helpers
# ---------------------------------------------------------------------------


def metric_diff_to_dict(d: MetricDiff) -> dict[str, Any]:
    """MetricDiff → JSON-serializable dict。"""
    return {
        "metric_name": d.metric_name,
        "baseline_value": d.baseline_value,
        "candidate_value": d.candidate_value,
        "delta": d.delta,
        "direction": d.direction,
    }


def finding_diff_to_dict(d: FindingDiff) -> dict[str, Any]:
    """FindingDiff → JSON-serializable dict。"""
    return {
        "category": d.category,
        "baseline_count": d.baseline_count,
        "candidate_count": d.candidate_count,
        "delta": d.delta,
        "new_rule_ids": list(d.new_rule_ids),
        "resolved_rule_ids": list(d.resolved_rule_ids),
    }


def task_outcome_diff_to_dict(d: TaskOutcomeDiff) -> dict[str, Any]:
    """TaskOutcomeDiff → JSON-serializable dict。"""
    return {
        "case_id": d.case_id,
        "baseline_status": d.baseline_status,
        "candidate_status": d.candidate_status,
        "change": d.change,
    }


def suite_diff_to_dict(d: SuiteDiff) -> dict[str, Any]:
    """SuiteDiff → JSON-serializable dict。"""
    return {
        "suite_id": d.suite_id,
        "baseline_task_success_rate": d.baseline_task_success_rate,
        "candidate_task_success_rate": d.candidate_task_success_rate,
        "task_success_rate_delta": d.task_success_rate_delta,
        "baseline_deterministic_pass_rate": d.baseline_deterministic_pass_rate,
        "candidate_deterministic_pass_rate": d.candidate_deterministic_pass_rate,
        "deterministic_pass_rate_delta": d.deterministic_pass_rate_delta,
        "baseline_total_cases": d.baseline_total_cases,
        "candidate_total_cases": d.candidate_total_cases,
        "new_failure_count": d.new_failure_count,
        "new_success_count": d.new_success_count,
    }


def regression_warning_to_dict(w: RegressionWarning) -> dict[str, Any]:
    """RegressionWarning → JSON-serializable dict。"""
    return {
        "warning_type": w.warning_type,
        "severity": w.severity,
        "threshold": w.threshold,
        "actual": w.actual,
        "message": w.message,
    }


def regression_report_to_dict(r: RegressionReport) -> dict[str, Any]:
    """RegressionReport → JSON-serializable dict。

    这是 v3.4 JSON 报告的序列化入口。
    """
    result: dict[str, Any] = {
        "baseline_id": r.baseline_id,
        "candidate_id": r.candidate_id,
        "is_regression": r.is_regression,
        "metric_diffs": [metric_diff_to_dict(d) for d in r.metric_diffs],
        "finding_diffs": [finding_diff_to_dict(d) for d in r.finding_diffs],
        "task_outcome_diffs": [
            task_outcome_diff_to_dict(d) for d in r.task_outcome_diffs
        ],
        "regression_warnings": [
            regression_warning_to_dict(w) for w in r.regression_warnings
        ],
    }
    if r.suite_diff is not None:
        result["suite_diff"] = suite_diff_to_dict(r.suite_diff)
    return result
