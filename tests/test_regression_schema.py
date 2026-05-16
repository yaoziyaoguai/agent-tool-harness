"""v3.4 P1: Regression comparison schema 测试。

测试保护：
- frozen dataclass 不可变性（RegressionReport 一旦生成不可篡改）
- JSON 序列化/反序列化确定性（CI 消费需要稳定输出）
- 默认值行为（空列表、None suite_diff）
- direction 三态（better/worse/neutral）
- change 五态（new_failure/new_success/unchanged/new_inconclusive/resolved_inconclusive）
"""

from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from agent_tool_harness.regression.diff_schema import (
    FindingDiff,
    MetricDiff,
    RegressionReport,
    RegressionThresholds,
    RegressionWarning,
    SuiteDiff,
    TaskOutcomeDiff,
    finding_diff_to_dict,
    metric_diff_to_dict,
    regression_report_to_dict,
    regression_warning_to_dict,
    suite_diff_to_dict,
    task_outcome_diff_to_dict,
)

# ---------------------------------------------------------------------------
# MetricDiff
# ---------------------------------------------------------------------------


def test_metric_diff_basic():
    """MetricDiff 基本创建和字段访问。"""
    d = MetricDiff(
        metric_name="tool_error_rate",
        baseline_value=0.05,
        candidate_value=0.12,
        delta=0.07,
        direction="worse",
    )
    assert d.metric_name == "tool_error_rate"
    assert d.baseline_value == 0.05
    assert d.candidate_value == 0.12
    assert d.delta == 0.07
    assert d.direction == "worse"


def test_metric_diff_frozen():
    """MetricDiff 不可修改。"""
    d = MetricDiff("rate", 0.0, 0.0, 0.0, "neutral")
    with pytest.raises(FrozenInstanceError):
        d.direction = "worse"  # type: ignore[misc]


def test_metric_diff_direction_values():
    """direction 三态：better / worse / neutral。"""
    better = MetricDiff("success_rate", 0.8, 0.9, 0.1, "better")
    worse = MetricDiff("error_rate", 0.05, 0.12, 0.07, "worse")
    neutral = MetricDiff("tool_count", 5.0, 5.0, 0.0, "neutral")
    assert better.direction == "better"
    assert worse.direction == "worse"
    assert neutral.direction == "neutral"


def test_metric_diff_to_dict():
    """MetricDiff → dict 序列化。"""
    d = MetricDiff("rate", 0.1, 0.2, 0.1, "worse")
    result = metric_diff_to_dict(d)
    assert result == {
        "metric_name": "rate",
        "baseline_value": 0.1,
        "candidate_value": 0.2,
        "delta": 0.1,
        "direction": "worse",
    }
    # 确认 JSON 可序列化
    json.dumps(result)


# ---------------------------------------------------------------------------
# FindingDiff
# ---------------------------------------------------------------------------


def test_finding_diff_basic():
    """FindingDiff 基本创建。"""
    d = FindingDiff(
        category="tool_use",
        baseline_count=10,
        candidate_count=15,
        delta=5,
        new_rule_ids=["rule_a", "rule_b"],
        resolved_rule_ids=["rule_c"],
    )
    assert d.category == "tool_use"
    assert d.baseline_count == 10
    assert d.candidate_count == 15
    assert d.delta == 5
    assert d.new_rule_ids == ["rule_a", "rule_b"]
    assert d.resolved_rule_ids == ["rule_c"]


def test_finding_diff_defaults():
    """FindingDiff 默认值。"""
    d = FindingDiff(category="test", baseline_count=0, candidate_count=0, delta=0)
    assert d.new_rule_ids == []
    assert d.resolved_rule_ids == []


def test_finding_diff_to_dict():
    """FindingDiff → dict 序列化。"""
    d = FindingDiff(
        category="response",
        baseline_count=3,
        candidate_count=5,
        delta=2,
        new_rule_ids=["r1"],
        resolved_rule_ids=[],
    )
    result = finding_diff_to_dict(d)
    assert result["category"] == "response"
    assert result["delta"] == 2
    assert result["new_rule_ids"] == ["r1"]
    assert result["resolved_rule_ids"] == []
    json.dumps(result)


# ---------------------------------------------------------------------------
# TaskOutcomeDiff
# ---------------------------------------------------------------------------


def test_task_outcome_diff_new_failure():
    """baseline success → candidate failed = new_failure（回归）。"""
    d = TaskOutcomeDiff(
        case_id="case-1",
        baseline_status="success",
        candidate_status="failed",
        change="new_failure",
    )
    assert d.change == "new_failure"


def test_task_outcome_diff_new_success():
    """baseline failed → candidate success = new_success（改善）。"""
    d = TaskOutcomeDiff(
        case_id="case-2",
        baseline_status="failed",
        candidate_status="success",
        change="new_success",
    )
    assert d.change == "new_success"


def test_task_outcome_diff_unchanged():
    """状态不变的 case。"""
    d = TaskOutcomeDiff(
        case_id="case-3",
        baseline_status="success",
        candidate_status="success",
        change="unchanged",
    )
    assert d.change == "unchanged"


def test_task_outcome_diff_inconclusive():
    """inconclusive 相关变化。"""
    d1 = TaskOutcomeDiff("c1", "success", "inconclusive", "new_inconclusive")
    d2 = TaskOutcomeDiff("c2", "inconclusive", "failed", "resolved_inconclusive")
    assert d1.change == "new_inconclusive"
    assert d2.change == "resolved_inconclusive"


def test_task_outcome_diff_to_dict():
    """TaskOutcomeDiff → dict 序列化。"""
    d = TaskOutcomeDiff("case-x", "success", "failed", "new_failure")
    result = task_outcome_diff_to_dict(d)
    assert result["case_id"] == "case-x"
    assert result["change"] == "new_failure"
    json.dumps(result)


# ---------------------------------------------------------------------------
# SuiteDiff
# ---------------------------------------------------------------------------


def test_suite_diff_basic():
    """SuiteDiff 基本创建。"""
    d = SuiteDiff(
        suite_id="suite-001",
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
    assert d.suite_id == "suite-001"
    assert d.task_success_rate_delta == -0.2
    assert d.new_failure_count == 2


def test_suite_diff_to_dict():
    """SuiteDiff → dict 序列化。"""
    d = SuiteDiff(
        suite_id="s1",
        baseline_task_success_rate=1.0,
        candidate_task_success_rate=0.5,
        task_success_rate_delta=-0.5,
        baseline_deterministic_pass_rate=1.0,
        candidate_deterministic_pass_rate=0.5,
        deterministic_pass_rate_delta=-0.5,
        baseline_total_cases=4,
        candidate_total_cases=4,
        new_failure_count=2,
        new_success_count=0,
    )
    result = suite_diff_to_dict(d)
    assert result["suite_id"] == "s1"
    assert result["new_failure_count"] == 2
    json.dumps(result)


# ---------------------------------------------------------------------------
# RegressionThresholds
# ---------------------------------------------------------------------------


def test_thresholds_defaults():
    """RegressionThresholds 默认值。"""
    t = RegressionThresholds()
    assert t.error_rate_spike_pct == 100.0
    assert t.finding_explosion_pct == 50.0
    assert t.task_success_drop_pp == 10.0


def test_thresholds_custom():
    """RegressionThresholds 自定义值。"""
    t = RegressionThresholds(
        error_rate_spike_pct=50.0,
        finding_explosion_pct=None,  # 禁用
        task_success_drop_pp=5.0,
    )
    assert t.error_rate_spike_pct == 50.0
    assert t.finding_explosion_pct is None
    assert t.task_success_drop_pp == 5.0


def test_thresholds_frozen():
    """RegressionThresholds 不可修改。"""
    t = RegressionThresholds()
    with pytest.raises(FrozenInstanceError):
        t.error_rate_spike_pct = 200.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# RegressionWarning
# ---------------------------------------------------------------------------


def test_regression_warning_basic():
    """RegressionWarning 基本创建。"""
    w = RegressionWarning(
        warning_type="error_rate_spike",
        severity="high",
        threshold="2x (100% increase)",
        actual="0.05 → 0.12 (+140%)",
        message="Tool error rate increased from 5.0% to 12.0%",
    )
    assert w.warning_type == "error_rate_spike"
    assert w.severity == "high"


def test_regression_warning_to_dict():
    """RegressionWarning → dict 序列化。"""
    w = RegressionWarning(
        warning_type="new_task_failures",
        severity="critical",
        threshold="any new failure",
        actual="2 new failures: case-1, case-2",
        message="2 previously passing cases now fail",
    )
    result = regression_warning_to_dict(w)
    assert result["warning_type"] == "new_task_failures"
    assert result["severity"] == "critical"
    json.dumps(result)


# ---------------------------------------------------------------------------
# RegressionReport
# ---------------------------------------------------------------------------


def test_regression_report_empty():
    """空 RegressionReport（无 diff、无 warning）。"""
    r = RegressionReport(baseline_id="b1", candidate_id="c1", is_regression=False)
    assert r.baseline_id == "b1"
    assert r.candidate_id == "c1"
    assert r.is_regression is False
    assert r.metric_diffs == []
    assert r.finding_diffs == []
    assert r.task_outcome_diffs == []
    assert r.regression_warnings == []
    assert r.suite_diff is None


def test_regression_report_frozen():
    """RegressionReport 不可修改。"""
    r = RegressionReport(baseline_id="b", candidate_id="c", is_regression=False)
    with pytest.raises(FrozenInstanceError):
        r.is_regression = True  # type: ignore[misc]


def test_regression_report_with_diffs():
    """包含 diff 和 warning 的 RegressionReport。"""
    r = RegressionReport(
        baseline_id="baseline-v1",
        candidate_id="candidate-v2",
        is_regression=True,
        metric_diffs=[
            MetricDiff("tool_error_rate", 0.05, 0.12, 0.07, "worse"),
        ],
        finding_diffs=[
            FindingDiff("tool_use", 5, 8, 3, new_rule_ids=["r1"], resolved_rule_ids=[]),
        ],
        task_outcome_diffs=[
            TaskOutcomeDiff("case-1", "success", "failed", "new_failure"),
        ],
        regression_warnings=[
            RegressionWarning(
                "error_rate_spike", "high", "2x", "5%→12%", "Error rate spiked"
            ),
        ],
    )
    assert r.is_regression is True
    assert len(r.metric_diffs) == 1
    assert len(r.finding_diffs) == 1
    assert len(r.task_outcome_diffs) == 1
    assert len(r.regression_warnings) == 1


def test_regression_report_with_suite_diff():
    """包含 SuiteDiff 的 RegressionReport。"""
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
    assert r.suite_diff is not None
    assert r.suite_diff.task_success_rate_delta == -0.2


# ---------------------------------------------------------------------------
# JSON roundtrip
# ---------------------------------------------------------------------------


def test_regression_report_to_dict_roundtrip():
    """RegressionReport → dict 包含所有字段，JSON 序列化成功。"""
    r = RegressionReport(
        baseline_id="b1",
        candidate_id="c1",
        is_regression=False,
        metric_diffs=[],
        finding_diffs=[],
        task_outcome_diffs=[],
        regression_warnings=[],
    )
    result = regression_report_to_dict(r)
    assert result["baseline_id"] == "b1"
    assert result["candidate_id"] == "c1"
    assert result["is_regression"] is False
    assert result["metric_diffs"] == []
    assert "suite_diff" not in result  # 未传 suite_diff 时不出现该 key
    json.dumps(result)


def test_regression_report_to_dict_with_suite():
    """RegressionReport JSON 序列化包含 SuiteDiff。"""
    sd = SuiteDiff(
        suite_id="s1",
        baseline_task_success_rate=1.0,
        candidate_task_success_rate=0.8,
        task_success_rate_delta=-0.2,
        baseline_deterministic_pass_rate=1.0,
        candidate_deterministic_pass_rate=0.8,
        deterministic_pass_rate_delta=-0.2,
        baseline_total_cases=5,
        candidate_total_cases=5,
        new_failure_count=1,
        new_success_count=0,
    )
    r = RegressionReport(
        baseline_id="b1",
        candidate_id="c1",
        is_regression=True,
        suite_diff=sd,
    )
    result = regression_report_to_dict(r)
    assert result["suite_diff"] is not None
    assert result["suite_diff"]["suite_id"] == "s1"
    json.dumps(result)
