"""v3.4 P2-P3: RegressionComparator 测试。

测试覆盖：
- _direction: better/worse/neutral 三态
- compute_metric_diffs: 指标对比、派生指标、稳定排序
- compute_finding_diffs: 按 category 对比、new/resolved rule_id
- _determine_change: 五态判定
- compute_task_outcome_diffs: 逐 case 状态变化
- compute_suite_diff: suite 级别对比
- compute_regression_warnings: 5 种警告检测
- RegressionComparator.compare: 编排集成
- 不修改输入（immutability 验证）
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from agent_tool_harness.regression.diff_schema import (
    RegressionThresholds,
)
from agent_tool_harness.regression.regression_comparator import (
    RegressionComparator,
    _compute_task_success_rate,
    _determine_change,
    _direction,
    compute_finding_diffs,
    compute_metric_diffs,
    compute_regression_warnings,
    compute_suite_diff,
    compute_task_outcome_diffs,
)
from agent_tool_harness.reports.report_insight import (
    GroupedFindings,
    ReportInsight,
    ReportInsightMetadata,
    ReportMetrics,
    ReportScorecard,
)
from agent_tool_harness.suite_eval.suite_result import SuiteResult
from agent_tool_harness.task_eval.task_evaluator import TaskOutcome

# ---------------------------------------------------------------------------
# helpers: 构造 ReportInsight mock
# ---------------------------------------------------------------------------


def _make_metrics(**overrides) -> ReportMetrics:
    """构造 ReportMetrics，未指定字段使用默认值。"""
    defaults: dict = {
        "tool_call_count": 10,
        "tool_success_count": 8,
        "tool_error_count": 2,
        "tool_error_rate": 0.2,
    }
    defaults.update(overrides)
    return ReportMetrics(**defaults)


def _make_scorecard(**overrides) -> ReportScorecard:
    """构造 ReportScorecard mock。"""
    defaults: dict = {
        "passed": True,
        "total_findings": 0,
        "errors": 0,
        "warnings": 0,
        "info": 0,
        "advisory_count": 0,
        "tools_called": 1,
        "tool_errors": 0,
    }
    defaults.update(overrides)
    return ReportScorecard(**defaults)


def _make_insight(
    metrics=None, grouped_findings=None, generated_at="2026-01-01T00:00:00Z"
) -> ReportInsight:
    """构造 ReportInsight mock。"""
    return ReportInsight(
        metrics=metrics or _make_metrics(),
        scorecard=_make_scorecard(),
        grouped_findings=grouped_findings or GroupedFindings(),
        metadata=ReportInsightMetadata(generated_at=generated_at),
    )


# ---------------------------------------------------------------------------
# _direction
# ---------------------------------------------------------------------------


class TestDirection:
    """_direction: 根据 metric 语义和 delta 映射 direction。"""

    def test_better_when_higher_positive_delta(self):
        """success_rate 上升 → better。"""
        assert _direction("task_success_rate", 0.1) == "better"
        assert _direction("tool_success_rate", 0.05) == "better"
        assert _direction("deterministic_pass_rate", 0.2) == "better"
        assert _direction("unique_tool_count", 3.0) == "better"

    def test_worse_when_higher_positive_delta(self):
        """error_rate 上升 → worse。"""
        assert _direction("tool_error_rate", 0.1) == "worse"
        assert _direction("tool_error_count", 2.0) == "worse"
        assert _direction("orphan_call_count", 1.0) == "worse"
        assert _direction("total_findings", 5.0) == "worse"

    def test_better_when_higher_negative_delta(self):
        """success_rate 下降 → worse。"""
        assert _direction("task_success_rate", -0.1) == "worse"

    def test_worse_when_higher_negative_delta(self):
        """error_rate 下降 → better。"""
        assert _direction("tool_error_rate", -0.1) == "better"

    def test_neutral_zero_delta(self):
        """delta=0.0 → neutral（无论 metric 语义）。"""
        assert _direction("tool_error_rate", 0.0) == "neutral"
        assert _direction("task_success_rate", 0.0) == "neutral"
        assert _direction("unknown_metric", 0.0) == "neutral"

    def test_unknown_metric_defaults_to_conservative(self):
        """未知 metric：正 delta → worse（保守），负 delta → better。"""
        assert _direction("unknown_xyz", 5.0) == "worse"
        assert _direction("unknown_xyz", -3.0) == "better"


# ---------------------------------------------------------------------------
# compute_metric_diffs
# ---------------------------------------------------------------------------


class TestComputeMetricDiffs:
    """compute_metric_diffs: baseline vs candidate 指标对比。"""

    def test_basic_metric_improved(self):
        """tool_error_rate 下降 → better。"""
        b = _make_metrics(tool_error_rate=0.2, tool_error_count=2)
        c = _make_metrics(tool_error_rate=0.05, tool_error_count=1)
        diffs = compute_metric_diffs(b, c)
        err_diff = next(d for d in diffs if d.metric_name == "Tool Error Rate")
        assert err_diff.direction == "better"
        assert err_diff.delta < 0

    def test_basic_metric_regressed(self):
        """tool_error_rate 上升 → worse。"""
        b = _make_metrics(tool_error_rate=0.05, tool_error_count=1)
        c = _make_metrics(tool_error_rate=0.2, tool_error_count=3)
        diffs = compute_metric_diffs(b, c)
        err_diff = next(d for d in diffs if d.metric_name == "Tool Error Rate")
        assert err_diff.direction == "worse"
        assert err_diff.delta > 0

    def test_basic_metric_unchanged(self):
        """指标完全相同 → neutral。"""
        b = _make_metrics(tool_error_rate=0.1)
        c = _make_metrics(tool_error_rate=0.1)
        diffs = compute_metric_diffs(b, c)
        err_diff = next(d for d in diffs if d.metric_name == "Tool Error Rate")
        assert err_diff.direction == "neutral"
        assert err_diff.delta == 0.0

    def test_stable_sorting(self):
        """结果按 metric_name 稳定排序。"""
        b = _make_metrics()
        c = _make_metrics()
        diffs = compute_metric_diffs(b, c)
        names = [d.metric_name for d in diffs]
        assert names == sorted(names)

    def test_all_9_core_metrics_present(self):
        """9 个核心指标全部出现在结果中。"""
        b = _make_metrics()
        c = _make_metrics()
        diffs = compute_metric_diffs(b, c)
        names = {d.metric_name for d in diffs}
        expected = {
            "Tool Error Rate",
            "Tool Error Count",
            "Tool Success Count",
            "Orphan Call Count",
            "Orphan Result Count",
            "Repeated Tool Call Count",
            "Unique Tool Count",
            "Total Tool Calls",
            "LLM Judge Findings",
        }
        assert expected.issubset(names)

    def test_derived_total_findings(self):
        """finding_count_by_severity 非空时生成 Total Findings diff。"""
        b = _make_metrics(
            finding_count_by_severity={"critical": 1, "high": 2, "medium": 1}
        )
        c = _make_metrics(
            finding_count_by_severity={"critical": 3, "high": 1, "low": 1}
        )
        diffs = compute_metric_diffs(b, c)
        total_diff = next(d for d in diffs if d.metric_name == "Total Findings")
        assert total_diff.baseline_value == 4  # 1+2+1
        assert total_diff.candidate_value == 5  # 3+1+1
        assert total_diff.delta == 1

    def test_derived_errors(self):
        """critical + high finding 生成 Errors diff。"""
        b = _make_metrics(
            finding_count_by_severity={"critical": 1, "high": 3}
        )
        c = _make_metrics(
            finding_count_by_severity={"critical": 2, "high": 4}
        )
        diffs = compute_metric_diffs(b, c)
        err_diff = next(
            d for d in diffs if d.metric_name == "Errors (critical+high)"
        )
        assert err_diff.baseline_value == 4
        assert err_diff.candidate_value == 6
        assert err_diff.delta == 2
        assert err_diff.direction == "worse"

    def test_derived_warnings(self):
        """medium + low finding 生成 Warnings diff。"""
        b = _make_metrics(
            finding_count_by_severity={"medium": 2, "low": 1}
        )
        c = _make_metrics(
            finding_count_by_severity={"medium": 1, "low": 0}
        )
        diffs = compute_metric_diffs(b, c)
        warn_diff = next(
            d for d in diffs if d.metric_name == "Warnings (medium+low)"
        )
        assert warn_diff.baseline_value == 3
        assert warn_diff.candidate_value == 1
        assert warn_diff.direction == "better"

    def test_empty_metrics(self):
        """全零 metrics 仍可正常对比。"""
        b = _make_metrics(tool_call_count=0, tool_success_count=0,
                          tool_error_count=0, tool_error_rate=0.0)
        c = _make_metrics(tool_call_count=0, tool_success_count=0,
                          tool_error_count=0, tool_error_rate=0.0)
        diffs = compute_metric_diffs(b, c)
        for d in diffs:
            assert d.direction == "neutral"
            assert d.delta == 0.0

    def test_input_not_modified(self):
        """compute_metric_diffs 不修改传入的 ReportMetrics。"""
        b = _make_metrics(tool_error_rate=0.1)
        c = _make_metrics(tool_error_rate=0.2)
        original_b_rate = b.tool_error_rate
        original_c_rate = c.tool_error_rate
        compute_metric_diffs(b, c)
        assert b.tool_error_rate == original_b_rate
        assert c.tool_error_rate == original_c_rate


# ---------------------------------------------------------------------------
# compute_finding_diffs
# ---------------------------------------------------------------------------


class TestComputeFindingDiffs:
    """compute_finding_diffs: finding 按 category 的数量变化对比。"""

    def test_new_finding_category(self):
        """candidate 新增 category。"""

        @dataclass
        class FakeFinding:
            rule_type: str

        b_findings = [FakeFinding(rule_type="tool_call")]
        c_findings = [
            FakeFinding(rule_type="tool_call"),
            FakeFinding(rule_type="tool_response"),
        ]
        b_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={"tool_call": b_findings}
            )
        )
        c_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={
                    "tool_call": c_findings[:1],
                    "tool_response": c_findings[1:],
                }
            )
        )
        diffs = compute_finding_diffs(b_insight, c_insight)
        resp_diff = next(d for d in diffs if d.category == "tool_response")
        assert resp_diff.baseline_count == 0
        assert resp_diff.candidate_count == 1
        assert resp_diff.delta == 1

    def test_resolved_finding_category(self):
        """baseline category 在 candidate 中消失。"""

        @dataclass
        class FakeFinding:
            rule_type: str

        b_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={"tool_call": [FakeFinding(rule_type="r1")]}
            )
        )
        c_insight = _make_insight(
            grouped_findings=GroupedFindings()
        )
        diffs = compute_finding_diffs(b_insight, c_insight)
        call_diff = next(d for d in diffs if d.category == "tool_call")
        assert call_diff.baseline_count == 1
        assert call_diff.candidate_count == 0
        assert call_diff.delta == -1

    def test_new_resolved_rule_ids(self):
        """new_rule_ids 和 resolved_rule_ids 追踪具体 rule 变化。"""

        @dataclass
        class FakeFinding:
            rule_type: str

        b_findings = [
            FakeFinding(rule_type="rule_a"),
            FakeFinding(rule_type="rule_b"),
        ]
        c_findings = [
            FakeFinding(rule_type="rule_a"),
            FakeFinding(rule_type="rule_c"),
        ]
        b_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={"test_cat": b_findings}
            )
        )
        c_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={"test_cat": c_findings}
            )
        )
        diffs = compute_finding_diffs(b_insight, c_insight)
        assert len(diffs) == 1
        d = diffs[0]
        assert d.new_rule_ids == ["rule_c"]
        assert d.resolved_rule_ids == ["rule_b"]

    def test_increased_severity_count(self):
        """类别内 finding 数量增加。"""

        @dataclass
        class FakeFinding:
            rule_type: str

        b_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={"tool_call": [FakeFinding(rule_type="r1")]}
            )
        )
        c_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={
                    "tool_call": [
                        FakeFinding(rule_type="r1"),
                        FakeFinding(rule_type="r2"),
                        FakeFinding(rule_type="r3"),
                    ]
                }
            )
        )
        diffs = compute_finding_diffs(b_insight, c_insight)
        d = diffs[0]
        assert d.baseline_count == 1
        assert d.candidate_count == 3
        assert d.delta == 2

    def test_decreased_severity_count(self):
        """类别内 finding 数量减少。"""

        @dataclass
        class FakeFinding:
            rule_type: str

        b_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={
                    "tool_call": [
                        FakeFinding(rule_type="r1"),
                        FakeFinding(rule_type="r2"),
                    ]
                }
            )
        )
        c_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={"tool_call": [FakeFinding(rule_type="r1")]}
            )
        )
        diffs = compute_finding_diffs(b_insight, c_insight)
        d = diffs[0]
        assert d.baseline_count == 2
        assert d.candidate_count == 1
        assert d.delta == -1

    def test_empty_baseline(self):
        """空 baseline finding。"""
        b_insight = _make_insight()
        c_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={"tool_call": [type("F", (), {"rule_type": "r1"})()]}
            )
        )
        diffs = compute_finding_diffs(b_insight, c_insight)
        assert len(diffs) == 1
        assert diffs[0].baseline_count == 0
        assert diffs[0].candidate_count == 1

    def test_empty_candidate(self):
        """空 candidate finding。"""
        b_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={"tool_call": [type("F", (), {"rule_type": "r1"})()]}
            )
        )
        c_insight = _make_insight()
        diffs = compute_finding_diffs(b_insight, c_insight)
        assert len(diffs) == 1
        assert diffs[0].baseline_count == 1
        assert diffs[0].candidate_count == 0

    def test_stable_sorting_by_category(self):
        """结果按 category 稳定排序。"""

        @dataclass
        class FakeFinding:
            rule_type: str

        b_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={
                    "zzz": [FakeFinding(rule_type="r1")],
                    "aaa": [FakeFinding(rule_type="r2")],
                }
            )
        )
        c_insight = _make_insight()
        diffs = compute_finding_diffs(b_insight, c_insight)
        cats = [d.category for d in diffs]
        assert cats == sorted(cats)

    def test_handles_findings_without_rule_type(self):
        """没有 rule_type 属性的 finding 也能正常处理。"""

        @dataclass
        class FakeFinding:
            pass

        b_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={"test": [FakeFinding()]}
            )
        )
        c_insight = _make_insight(
            grouped_findings=GroupedFindings(
                by_category={"test": [FakeFinding(), FakeFinding()]}
            )
        )
        diffs = compute_finding_diffs(b_insight, c_insight)
        assert len(diffs) == 1
        assert diffs[0].delta == 1


# ---------------------------------------------------------------------------
# _determine_change
# ---------------------------------------------------------------------------


class TestDetermineChange:
    """_determine_change: 五态判定逻辑。"""

    def test_new_failure_success_to_failed(self):
        assert _determine_change("success", "failed") == "new_failure"

    def test_new_success_failed_to_success(self):
        assert _determine_change("failed", "success") == "new_success"

    def test_unchanged_same_status(self):
        assert _determine_change("success", "success") == "unchanged"
        assert _determine_change("failed", "failed") == "unchanged"
        assert _determine_change("inconclusive", "inconclusive") == "unchanged"

    def test_new_inconclusive(self):
        """任意状态 → inconclusive。"""
        assert _determine_change("success", "inconclusive") == "new_inconclusive"
        assert _determine_change("failed", "inconclusive") == "new_inconclusive"

    def test_resolved_inconclusive(self):
        """inconclusive → success/failed。"""
        assert _determine_change("inconclusive", "success") == "resolved_inconclusive"
        assert _determine_change("inconclusive", "failed") == "resolved_inconclusive"

    def test_unknown_both(self):
        """两边都是 unknown → unchanged。"""
        assert _determine_change("unknown", "unknown") == "unchanged"

    def test_unknown_to_status(self):
        """unknown → 任意状态。"""
        # unknown → failed → new_failure（因为 candidate_status 是 failed）
        assert _determine_change("unknown", "failed") == "new_failure"
        # unknown → success → new_success
        assert _determine_change("unknown", "success") == "new_success"


# ---------------------------------------------------------------------------
# compute_task_outcome_diffs
# ---------------------------------------------------------------------------


class TestComputeTaskOutcomeDiffs:
    """compute_task_outcome_diffs: 逐 case 状态变化。"""

    def _make_task(self, case_id: str, status: str) -> TaskOutcome:
        return TaskOutcome(case_id=case_id, status=status)

    def test_basic_new_failure(self):
        """baseline success → candidate failed。"""
        baseline = [self._make_task("c1", "success")]
        candidate = [self._make_task("c1", "failed")]
        diffs = compute_task_outcome_diffs(baseline, candidate)
        assert len(diffs) == 1
        assert diffs[0].case_id == "c1"
        assert diffs[0].change == "new_failure"

    def test_basic_new_success(self):
        """baseline failed → candidate success。"""
        baseline = [self._make_task("c1", "failed")]
        candidate = [self._make_task("c1", "success")]
        diffs = compute_task_outcome_diffs(baseline, candidate)
        assert diffs[0].change == "new_success"

    def test_unchanged(self):
        baseline = [self._make_task("c1", "success")]
        candidate = [self._make_task("c1", "success")]
        diffs = compute_task_outcome_diffs(baseline, candidate)
        assert diffs[0].change == "unchanged"

    def test_mixed_changes(self):
        """混合了 new_failure、new_success、unchanged 的场景。"""
        baseline = [
            self._make_task("c1", "success"),
            self._make_task("c2", "failed"),
            self._make_task("c3", "success"),
        ]
        candidate = [
            self._make_task("c1", "failed"),   # new_failure
            self._make_task("c2", "success"),  # new_success
            self._make_task("c3", "success"),  # unchanged
        ]
        diffs = compute_task_outcome_diffs(baseline, candidate)
        by_id = {d.case_id: d.change for d in diffs}
        assert by_id["c1"] == "new_failure"
        assert by_id["c2"] == "new_success"
        assert by_id["c3"] == "unchanged"

    def test_empty_both(self):
        """两边都为空 → 空列表。"""
        diffs = compute_task_outcome_diffs([], [])
        assert diffs == []

    def test_empty_baseline(self):
        """空 baseline → 所有 candidate case 被标记为从 unknown 转换。"""
        candidate = [self._make_task("c1", "success")]
        diffs = compute_task_outcome_diffs(None, candidate)
        assert len(diffs) == 1
        assert diffs[0].baseline_status == "unknown"

    def test_empty_candidate(self):
        """空 candidate → 所有 baseline case 标记为 unknown。"""
        baseline = [self._make_task("c1", "success")]
        diffs = compute_task_outcome_diffs(baseline, None)
        assert len(diffs) == 1
        assert diffs[0].candidate_status == "unknown"

    def test_stable_sorting_by_case_id(self):
        """结果按 case_id 稳定排序。"""
        baseline = [
            self._make_task("z", "success"),
            self._make_task("a", "success"),
        ]
        candidate = [
            self._make_task("a", "success"),
            self._make_task("z", "success"),
        ]
        diffs = compute_task_outcome_diffs(baseline, candidate)
        assert [d.case_id for d in diffs] == ["a", "z"]

    def test_input_not_modified(self):
        """不修改传入的 TaskOutcome 列表。"""
        baseline = [self._make_task("c1", "success")]
        candidate = [self._make_task("c1", "failed")]
        compute_task_outcome_diffs(baseline, candidate)
        assert baseline[0].status == "success"
        assert candidate[0].status == "failed"

    def test_only_in_baseline(self):
        """仅在 baseline 中存在的 case。"""
        baseline = [self._make_task("c1", "success")]
        diffs = compute_task_outcome_diffs(baseline, [])
        assert diffs[0].baseline_status == "success"
        assert diffs[0].candidate_status == "unknown"

    def test_only_in_candidate(self):
        """仅在 candidate 中存在的 case。"""
        candidate = [self._make_task("c2", "failed")]
        diffs = compute_task_outcome_diffs([], candidate)
        assert diffs[0].baseline_status == "unknown"
        assert diffs[0].candidate_status == "failed"


# ---------------------------------------------------------------------------
# compute_suite_diff
# ---------------------------------------------------------------------------


class TestComputeSuiteDiff:
    """compute_suite_diff: suite 级别对比。"""

    def test_basic(self):
        b_suite = SuiteResult(
            suite_id="s1",
            total_cases=5,
            task_success_rate=0.8,
            deterministic_pass_rate=0.6,
        )
        c_suite = SuiteResult(
            suite_id="s1",
            total_cases=5,
            task_success_rate=0.6,
            deterministic_pass_rate=0.5,
        )
        diff = compute_suite_diff(b_suite, c_suite, [])
        assert diff is not None
        assert diff.suite_id == "s1"
        assert diff.task_success_rate_delta == pytest.approx(-0.2)
        assert diff.deterministic_pass_rate_delta == pytest.approx(-0.1)
        assert diff.baseline_total_cases == 5
        assert diff.candidate_total_cases == 5

    def test_with_task_outcome_diffs(self):
        """new_failure / new_success 计数从 task_outcome_diffs 统计。"""
        from agent_tool_harness.regression.diff_schema import TaskOutcomeDiff

        b_suite = SuiteResult(
            suite_id="s1",
            total_cases=4,
            task_success_rate=0.5,
            deterministic_pass_rate=0.5,
        )
        c_suite = SuiteResult(
            suite_id="s1",
            total_cases=4,
            task_success_rate=0.5,
            deterministic_pass_rate=0.5,
        )
        diffs = [
            TaskOutcomeDiff("c1", "success", "failed", "new_failure"),
            TaskOutcomeDiff("c2", "success", "failed", "new_failure"),
            TaskOutcomeDiff("c3", "failed", "success", "new_success"),
            TaskOutcomeDiff("c4", "success", "success", "unchanged"),
        ]
        result = compute_suite_diff(b_suite, c_suite, diffs)
        assert result.new_failure_count == 2
        assert result.new_success_count == 1

    def test_none_baseline_returns_none(self):
        c_suite = SuiteResult(suite_id="s1", total_cases=1,
                              task_success_rate=1.0, deterministic_pass_rate=1.0)
        result = compute_suite_diff(None, c_suite)
        assert result is None

    def test_none_candidate_returns_none(self):
        b_suite = SuiteResult(suite_id="s1", total_cases=1,
                              task_success_rate=1.0, deterministic_pass_rate=1.0)
        result = compute_suite_diff(b_suite, None)
        assert result is None


# ---------------------------------------------------------------------------
# compute_regression_warnings
# ---------------------------------------------------------------------------


class TestComputeRegressionWarnings:
    """compute_regression_warnings: 5 种回归警告检测。"""

    def test_new_task_failures(self):
        """new_failure 触发 critical 级别警告。"""
        from agent_tool_harness.regression.diff_schema import TaskOutcomeDiff

        diffs = [
            TaskOutcomeDiff("case-1", "success", "failed", "new_failure"),
            TaskOutcomeDiff("case-2", "failed", "success", "new_success"),
        ]
        warnings = compute_regression_warnings(
            metric_diffs=[],
            task_outcome_diffs=diffs,
            finding_diffs=[],
            thresholds=RegressionThresholds(),
            baseline_metrics=_make_metrics(),
            candidate_metrics=_make_metrics(),
        )
        assert len(warnings) >= 1
        ntf = next(w for w in warnings if w.warning_type == "new_task_failures")
        assert ntf.severity == "critical"
        assert "case-1" in ntf.actual

    def test_no_warning_when_no_new_failures(self):
        """没有 new_failure 时不产生 new_task_failures 警告。"""
        from agent_tool_harness.regression.diff_schema import TaskOutcomeDiff

        diffs = [TaskOutcomeDiff("c1", "success", "success", "unchanged")]
        warnings = compute_regression_warnings(
            metric_diffs=[],
            task_outcome_diffs=diffs,
            finding_diffs=[],
            thresholds=RegressionThresholds(),
            baseline_metrics=_make_metrics(),
            candidate_metrics=_make_metrics(),
        )
        ntf = [w for w in warnings if w.warning_type == "new_task_failures"]
        assert len(ntf) == 0

    def test_error_rate_spike(self):
        """tool_error_rate 超过阈值触发 high 警告。"""
        b = _make_metrics(tool_error_rate=0.05)
        c = _make_metrics(tool_error_rate=0.15)  # +200%，超过默认 100% 阈值
        warnings = compute_regression_warnings(
            metric_diffs=[],
            task_outcome_diffs=[],
            finding_diffs=[],
            thresholds=RegressionThresholds(error_rate_spike_pct=100.0),
            baseline_metrics=b,
            candidate_metrics=c,
        )
        spike = [w for w in warnings if w.warning_type == "error_rate_spike"]
        assert len(spike) == 1
        assert spike[0].severity == "high"

    def test_error_rate_spike_not_triggered_when_below_threshold(self):
        """未超过阈值不触发。"""
        b = _make_metrics(tool_error_rate=0.10)
        c = _make_metrics(tool_error_rate=0.12)  # +20%，未超过 100%
        warnings = compute_regression_warnings(
            metric_diffs=[],
            task_outcome_diffs=[],
            finding_diffs=[],
            thresholds=RegressionThresholds(error_rate_spike_pct=100.0),
            baseline_metrics=b,
            candidate_metrics=c,
        )
        spike = [w for w in warnings if w.warning_type == "error_rate_spike"]
        assert len(spike) == 0

    def test_error_rate_spike_baseline_zero_no_trigger(self):
        """baseline error_rate 为 0 时不触发（避免除零）。"""
        b = _make_metrics(tool_error_rate=0.0)
        c = _make_metrics(tool_error_rate=0.1)
        # baseline 为 0，函数内部的 `if b_error_rate > 0` 防止计算
        warnings = compute_regression_warnings(
            metric_diffs=[],
            task_outcome_diffs=[],
            finding_diffs=[],
            thresholds=RegressionThresholds(error_rate_spike_pct=100.0),
            baseline_metrics=b,
            candidate_metrics=c,
        )
        spike = [w for w in warnings if w.warning_type == "error_rate_spike"]
        assert len(spike) == 0

    def test_finding_explosion(self):
        """finding 总数增长超过阈值触发 high 警告。"""
        b = _make_metrics(
            finding_count_by_severity={"critical": 1, "high": 1}  # total=2
        )
        c = _make_metrics(
            finding_count_by_severity={"critical": 2, "high": 2, "medium": 1}  # total=5, +150%
        )
        warnings = compute_regression_warnings(
            metric_diffs=[],
            task_outcome_diffs=[],
            finding_diffs=[],
            thresholds=RegressionThresholds(finding_explosion_pct=50.0),
            baseline_metrics=b,
            candidate_metrics=c,
        )
        explosion = [w for w in warnings if w.warning_type == "finding_explosion"]
        assert len(explosion) == 1
        assert explosion[0].severity == "high"

    def test_finding_explosion_disabled_by_none(self):
        """finding_explosion_pct=None 禁用检测。"""
        b = _make_metrics(
            finding_count_by_severity={"critical": 1}
        )
        c = _make_metrics(
            finding_count_by_severity={"critical": 10}
        )
        warnings = compute_regression_warnings(
            metric_diffs=[],
            task_outcome_diffs=[],
            finding_diffs=[],
            thresholds=RegressionThresholds(finding_explosion_pct=None),
            baseline_metrics=b,
            candidate_metrics=c,
        )
        explosion = [w for w in warnings if w.warning_type == "finding_explosion"]
        assert len(explosion) == 0

    def test_new_tool_errors(self):
        """candidate 中出现全新的含 error 工具。"""
        b = _make_metrics(
            finding_count_by_tool={"tool_a": 1}
        )
        c = _make_metrics(
            finding_count_by_tool={"tool_a": 1, "tool_b": 2}
        )
        warnings = compute_regression_warnings(
            metric_diffs=[],
            task_outcome_diffs=[],
            finding_diffs=[],
            thresholds=RegressionThresholds(),
            baseline_metrics=b,
            candidate_metrics=c,
        )
        nte = [w for w in warnings if w.warning_type == "new_tool_errors"]
        assert len(nte) == 1
        assert nte[0].severity == "medium"
        assert "tool_b" in nte[0].actual

    def test_new_tool_errors_excludes_unknown(self):
        """(unknown) 工具被排除不产生警告。"""
        b = _make_metrics(finding_count_by_tool={})
        c = _make_metrics(finding_count_by_tool={"(unknown)": 1})
        warnings = compute_regression_warnings(
            metric_diffs=[],
            task_outcome_diffs=[],
            finding_diffs=[],
            thresholds=RegressionThresholds(),
            baseline_metrics=b,
            candidate_metrics=c,
        )
        nte = [w for w in warnings if w.warning_type == "new_tool_errors"]
        assert len(nte) == 0

    def test_task_success_drop(self):
        """task_success_rate 下降超过阈值。"""
        from agent_tool_harness.regression.diff_schema import TaskOutcomeDiff

        diffs = [
            TaskOutcomeDiff("c1", "success", "success", "unchanged"),
            TaskOutcomeDiff("c2", "success", "success", "unchanged"),
            TaskOutcomeDiff("c3", "success", "failed", "new_failure"),
            TaskOutcomeDiff("c4", "success", "failed", "new_failure"),
            TaskOutcomeDiff("c5", "success", "failed", "new_failure"),
        ]
        # baseline: 5 success → 100%, candidate: 2 success → 40%, drop 60pp
        warnings = compute_regression_warnings(
            metric_diffs=[],
            task_outcome_diffs=diffs,
            finding_diffs=[],
            thresholds=RegressionThresholds(task_success_drop_pp=10.0),
            baseline_metrics=_make_metrics(),
            candidate_metrics=_make_metrics(),
        )
        drop = [w for w in warnings if w.warning_type == "task_success_drop"]
        assert len(drop) == 1
        assert drop[0].severity == "critical"

    def test_task_success_drop_disabled_by_none(self):
        """task_success_drop_pp=None 禁用检测。"""
        from agent_tool_harness.regression.diff_schema import TaskOutcomeDiff

        diffs = [
            TaskOutcomeDiff("c1", "success", "failed", "new_failure"),
            TaskOutcomeDiff("c2", "success", "failed", "new_failure"),
        ]
        warnings = compute_regression_warnings(
            metric_diffs=[],
            task_outcome_diffs=diffs,
            finding_diffs=[],
            thresholds=RegressionThresholds(task_success_drop_pp=None),
            baseline_metrics=_make_metrics(),
            candidate_metrics=_make_metrics(),
        )
        drop = [w for w in warnings if w.warning_type == "task_success_drop"]
        assert len(drop) == 0

    def test_all_disabled_thresholds(self):
        """所有阈值设为 None → 不产生任何 warning。"""
        warnings = compute_regression_warnings(
            metric_diffs=[],
            task_outcome_diffs=[],
            finding_diffs=[],
            thresholds=RegressionThresholds(
                error_rate_spike_pct=None,
                finding_explosion_pct=None,
                task_success_drop_pp=None,
            ),
            baseline_metrics=_make_metrics(),
            candidate_metrics=_make_metrics(),
        )
        assert warnings == []


# ---------------------------------------------------------------------------
# _compute_task_success_rate
# ---------------------------------------------------------------------------


class TestComputeTaskSuccessRate:
    """_compute_task_success_rate: 从 TaskOutcomeDiff 估算成功率。"""

    def test_basic_baseline(self):
        from agent_tool_harness.regression.diff_schema import TaskOutcomeDiff

        diffs = [
            TaskOutcomeDiff("c1", "success", "success", "unchanged"),
            TaskOutcomeDiff("c2", "success", "failed", "new_failure"),
            TaskOutcomeDiff("c3", "failed", "failed", "unchanged"),
            TaskOutcomeDiff("c4", "success", "success", "unchanged"),
        ]
        # baseline: 3 success out of 4
        rate = _compute_task_success_rate(diffs, "baseline")
        assert rate == 0.75

    def test_candidate(self):
        from agent_tool_harness.regression.diff_schema import TaskOutcomeDiff

        diffs = [
            TaskOutcomeDiff("c1", "success", "success", "unchanged"),
            TaskOutcomeDiff("c2", "success", "failed", "new_failure"),
        ]
        # candidate: 1 success out of 2
        rate = _compute_task_success_rate(diffs, "candidate")
        assert rate == 0.5

    def test_empty_returns_none(self):
        assert _compute_task_success_rate([], "baseline") is None

    def test_all_unknown_returns_none(self):
        from agent_tool_harness.regression.diff_schema import TaskOutcomeDiff

        diffs = [TaskOutcomeDiff("c1", "unknown", "unknown", "unchanged")]
        assert _compute_task_success_rate(diffs, "baseline") is None


# ---------------------------------------------------------------------------
# RegressionComparator.compare (编排集成)
# ---------------------------------------------------------------------------


class TestRegressionComparatorCompare:
    """RegressionComparator.compare: 编排集成测试。"""

    def test_no_regression_when_identical(self):
        """相同报告对比 → 无回归。"""
        m = _make_metrics()
        insight = _make_insight(metrics=m)
        comparator = RegressionComparator()
        report = comparator.compare(insight, insight)
        assert report.is_regression is False
        assert report.regression_warnings == []

    def test_is_regression_true_when_new_failure(self):
        """出现 new_failure → is_regression=True。"""
        m = _make_metrics()
        b_insight = _make_insight(metrics=m)
        c_insight = _make_insight(metrics=m)
        comparator = RegressionComparator()
        report = comparator.compare(
            b_insight,
            c_insight,
            baseline_task_outcomes=[TaskOutcome(case_id="c1", status="success")],
            candidate_task_outcomes=[TaskOutcome(case_id="c1", status="failed")],
        )
        assert report.is_regression is True
        assert any(
            w.warning_type == "new_task_failures" for w in report.regression_warnings
        )

    def test_with_suite_diff(self):
        """传入 SuiteResult 时 Report 包含 suite_diff。"""
        m = _make_metrics()
        insight = _make_insight(metrics=m)
        b_suite = SuiteResult(
            suite_id="s1", total_cases=2,
            task_success_rate=1.0, deterministic_pass_rate=1.0,
        )
        c_suite = SuiteResult(
            suite_id="s1", total_cases=2,
            task_success_rate=0.5, deterministic_pass_rate=0.5,
        )
        comparator = RegressionComparator()
        report = comparator.compare(
            insight, insight,
            baseline_suite=b_suite,
            candidate_suite=c_suite,
        )
        assert report.suite_diff is not None
        assert report.suite_diff.suite_id == "s1"
        assert report.suite_diff.task_success_rate_delta == -0.5

    def test_without_suite_diff(self):
        """不传 SuiteResult → suite_diff 为 None。"""
        insight = _make_insight()
        comparator = RegressionComparator()
        report = comparator.compare(insight, insight)
        assert report.suite_diff is None

    def test_compare_does_not_modify_input(self):
        """compare() 不修改输入的 ReportInsight。"""
        m = _make_metrics(tool_error_rate=0.1)
        b_insight = _make_insight(metrics=m)
        c_insight = _make_insight(metrics=_make_metrics(tool_error_rate=0.3))
        original_rate = b_insight.metrics.tool_error_rate
        comparator = RegressionComparator()
        comparator.compare(b_insight, c_insight)
        assert b_insight.metrics.tool_error_rate == original_rate

    def test_custom_thresholds_applied(self):
        """自定义阈值生效。"""
        b = _make_metrics(tool_error_rate=0.10)
        c = _make_metrics(tool_error_rate=0.15)  # +50%
        insight_b = _make_insight(metrics=b)
        insight_c = _make_insight(metrics=c)
        # 默认 100% 阈值不触发
        default_comp = RegressionComparator()
        report_default = default_comp.compare(insight_b, insight_c)
        assert not any(
            w.warning_type == "error_rate_spike"
            for w in report_default.regression_warnings
        )
        # 自定义 30% 阈值触发
        strict_comp = RegressionComparator(
            thresholds=RegressionThresholds(error_rate_spike_pct=30.0)
        )
        report_strict = strict_comp.compare(insight_b, insight_c)
        assert any(
            w.warning_type == "error_rate_spike"
            for w in report_strict.regression_warnings
        )

    def test_baseline_candidate_id_from_metadata(self):
        """baseline_id / candidate_id 从 metadata.generated_at 提取。"""
        b_insight = _make_insight(
            metrics=_make_metrics(),
            generated_at="2026-01-01T00:00:00Z",
        )
        c_insight = _make_insight(
            metrics=_make_metrics(),
            generated_at="2026-02-01T00:00:00Z",
        )
        comparator = RegressionComparator()
        report = comparator.compare(b_insight, c_insight)
        assert report.baseline_id == "2026-01-01T00:00:00Z"
        assert report.candidate_id == "2026-02-01T00:00:00Z"

    def test_all_diffs_included(self):
        """完整 compare 包含所有 4 类 diff + warnings。"""
        b = _make_metrics(tool_call_count=5)
        c = _make_metrics(tool_call_count=10)

        @dataclass
        class FakeF:
            rule_type: str

        b_insight = _make_insight(
            metrics=b,
            grouped_findings=GroupedFindings(
                by_category={"tool_call": [FakeF(rule_type="r1")]}
            ),
        )
        c_insight = _make_insight(
            metrics=c,
            grouped_findings=GroupedFindings(
                by_category={
                    "tool_call": [FakeF(rule_type="r1"), FakeF(rule_type="r2")]
                }
            ),
        )
        comparator = RegressionComparator()
        report = comparator.compare(
            b_insight,
            c_insight,
            baseline_task_outcomes=[TaskOutcome(case_id="c1", status="success")],
            candidate_task_outcomes=[TaskOutcome(case_id="c1", status="failed")],
        )
        assert len(report.metric_diffs) > 0
        assert len(report.finding_diffs) > 0
        assert len(report.task_outcome_diffs) > 0
        assert len(report.regression_warnings) > 0
        assert report.is_regression is True
