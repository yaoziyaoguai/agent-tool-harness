"""P3 ReportScorecard 测试。

覆盖 ~15 场景：空数据、passed 透传、severity 分桶、top_issue_categories 排序、
top_affected_tools 排序/排除 "(unknown)"、immutability、不修改输入。
"""

from __future__ import annotations

import pytest

from agent_tool_harness.core_contract import EvaluationResult, RuleFinding
from agent_tool_harness.reports.report_insight import (
    GroupedFindings,
    ReportMetrics,
    ReportScorecard,
    make_scorecard,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mk_metrics(**overrides) -> ReportMetrics:
    """创建 ReportMetrics，零值默认，按需覆盖。"""
    defaults: dict = {
        "tool_call_count": 0,
        "tool_result_count": 0,
        "unique_tool_count": 0,
        "tool_success_count": 0,
        "tool_error_count": 0,
        "tool_error_rate": 0.0,
        "orphan_call_count": 0,
        "orphan_result_count": 0,
        "repeated_tool_call_count": 0,
        "response_size_chars_total": 0,
        "response_size_chars_by_tool": {},
        "estimated_response_tokens_total": 0,
        "finding_count_by_severity": {},
        "finding_count_by_category": {},
        "finding_count_by_tool": {},
        "judge_finding_count": 0,
    }
    defaults.update(overrides)
    return ReportMetrics(**defaults)


def _mk_groups(**overrides) -> GroupedFindings:
    """创建 GroupedFindings，空分组默认，按需覆盖。"""
    defaults: dict = {
        "by_severity": {},
        "by_category": {},
        "by_tool": {},
        "by_rule_id_prefix": {},
    }
    defaults.update(overrides)
    return GroupedFindings(**defaults)


def _mk_finding(
    finding_id: str = "f1",
    severity: str = "high",
    rule_type: str = "tool_call.arguments.present",
) -> RuleFinding:
    return RuleFinding(
        finding_id=finding_id,
        severity=severity,
        category="rule",
        message=f"规则发现: {rule_type}",
        evidence_ref="ref",
        rule_type=rule_type,
        rule_passed=False,
    )


# ---------------------------------------------------------------------------
# 测试: 空数据
# ---------------------------------------------------------------------------


class TestEmptyData:
    def test_empty_metrics_empty_groups(self):
        """空指标 + 空分组 → 全零 scorecard。"""
        sc = make_scorecard(_mk_metrics(), _mk_groups(), passed=True)
        assert sc.passed is True
        assert sc.total_findings == 0
        assert sc.errors == 0
        assert sc.warnings == 0
        assert sc.info == 0
        assert sc.advisory_count == 0
        assert sc.tools_called == 0
        assert sc.tool_errors == 0
        assert sc.top_issue_categories == []
        assert sc.top_affected_tools == []

    def test_empty_metrics_passed_false(self):
        """passed=False 正确透传。"""
        sc = make_scorecard(_mk_metrics(), _mk_groups(), passed=False)
        assert sc.passed is False


# ---------------------------------------------------------------------------
# 测试: severity 分桶
# ---------------------------------------------------------------------------


class TestSeverityBuckets:
    def test_total_findings_sums_all_severities(self):
        """total_findings = 各 severity 之和。"""
        m = _mk_metrics(finding_count_by_severity={
            "critical": 1, "high": 3, "medium": 5, "low": 7, "info": 2,
        })
        sc = make_scorecard(m, _mk_groups(), passed=True)
        assert sc.total_findings == 18

    def test_errors_critical_plus_high(self):
        """errors = critical + high。"""
        m = _mk_metrics(finding_count_by_severity={
            "critical": 2, "high": 4, "medium": 1, "low": 0, "info": 0,
        })
        sc = make_scorecard(m, _mk_groups(), passed=True)
        assert sc.errors == 6

    def test_warnings_medium_plus_low(self):
        """warnings = medium + low。"""
        m = _mk_metrics(finding_count_by_severity={
            "critical": 0, "high": 0, "medium": 3, "low": 2, "info": 0,
        })
        sc = make_scorecard(m, _mk_groups(), passed=True)
        assert sc.warnings == 5

    def test_info_count(self):
        """info 单独计数。"""
        m = _mk_metrics(finding_count_by_severity={
            "critical": 0, "high": 0, "medium": 0, "low": 0, "info": 7,
        })
        sc = make_scorecard(m, _mk_groups(), passed=True)
        assert sc.info == 7

    def test_missing_severity_keys_default_zero(self):
        """缺失的 severity key 默认 0。"""
        m = _mk_metrics(finding_count_by_severity={"high": 1})
        sc = make_scorecard(m, _mk_groups(), passed=True)
        assert sc.total_findings == 1
        assert sc.errors == 1
        assert sc.warnings == 0
        assert sc.info == 0


# ---------------------------------------------------------------------------
# 测试: 透传字段
# ---------------------------------------------------------------------------


class TestPassthrough:
    def test_advisory_count_from_metrics(self):
        """advisory_count 从 metrics.judge_finding_count 透传。"""
        m = _mk_metrics(judge_finding_count=3)
        sc = make_scorecard(m, _mk_groups(), passed=True)
        assert sc.advisory_count == 3

    def test_tools_called_from_metrics(self):
        """tools_called 从 metrics.unique_tool_count 透传。"""
        m = _mk_metrics(unique_tool_count=5)
        sc = make_scorecard(m, _mk_groups(), passed=True)
        assert sc.tools_called == 5

    def test_tool_errors_from_metrics(self):
        """tool_errors 从 metrics.tool_error_count 透传。"""
        m = _mk_metrics(tool_error_count=2)
        sc = make_scorecard(m, _mk_groups(), passed=True)
        assert sc.tool_errors == 2


# ---------------------------------------------------------------------------
# 测试: top_issue_categories
# ---------------------------------------------------------------------------


class TestTopIssueCategories:
    def test_descending_by_count(self):
        """top_issue_categories 按 finding count 降序。"""
        g = _mk_groups(by_category={
            "tool_call": [_mk_finding("f1"), _mk_finding("f2"), _mk_finding("f3")],
            "tool_spec": [_mk_finding("f4"), _mk_finding("f5")],
            "tool_response": [_mk_finding("f6")],
        })
        sc = make_scorecard(_mk_metrics(), g, passed=True)
        assert sc.top_issue_categories == ["tool_call", "tool_spec", "tool_response"]

    def test_limit_five(self):
        """最多返回前 5 个类别。"""
        g = _mk_groups(by_category={
            f"cat_{i}": [_mk_finding(f"f{i}")] for i in range(10)
        })
        sc = make_scorecard(_mk_metrics(), g, passed=True)
        assert len(sc.top_issue_categories) == 5

    def test_tie_stable_by_name(self):
        """同 count 时按类别名字母序稳定排列。"""
        g = _mk_groups(by_category={
            "b_tool": [_mk_finding("f1")],
            "a_tool": [_mk_finding("f2")],
            "c_tool": [_mk_finding("f3")],
        })
        sc = make_scorecard(_mk_metrics(), g, passed=True)
        assert sc.top_issue_categories == ["a_tool", "b_tool", "c_tool"]

    def test_empty_categories(self):
        """无分组时返回空列表。"""
        sc = make_scorecard(_mk_metrics(), _mk_groups(), passed=True)
        assert sc.top_issue_categories == []


# ---------------------------------------------------------------------------
# 测试: top_affected_tools
# ---------------------------------------------------------------------------


class TestTopAffectedTools:
    def test_descending_by_count(self):
        """top_affected_tools 按 finding count 降序。"""
        m = _mk_metrics(finding_count_by_tool={
            "search_file": 5,
            "read_file": 3,
            "grep": 1,
        })
        sc = make_scorecard(m, _mk_groups(), passed=True)
        assert sc.top_affected_tools == ["search_file", "read_file", "grep"]

    def test_limit_five(self):
        """最多返回前 5 个。"""
        m = _mk_metrics(finding_count_by_tool={
            f"tool_{i}": i + 1 for i in range(10)
        })
        sc = make_scorecard(m, _mk_groups(), passed=True)
        assert len(sc.top_affected_tools) == 5

    def test_excludes_unknown(self):
        """排除 "(unknown)" 工具。"""
        m = _mk_metrics(finding_count_by_tool={
            "search_file": 5,
            "(unknown)": 99,
            "read_file": 3,
        })
        sc = make_scorecard(m, _mk_groups(), passed=True)
        assert "(unknown)" not in sc.top_affected_tools
        assert sc.top_affected_tools == ["search_file", "read_file"]

    def test_tie_stable_by_name(self):
        """同 count 时按工具名字母序稳定排列。"""
        m = _mk_metrics(finding_count_by_tool={
            "b_tool": 1,
            "a_tool": 1,
            "c_tool": 1,
        })
        sc = make_scorecard(m, _mk_groups(), passed=True)
        assert sc.top_affected_tools == ["a_tool", "b_tool", "c_tool"]

    def test_all_unknown_returns_empty(self):
        """全部为 "(unknown)" 时返回空列表。"""
        m = _mk_metrics(finding_count_by_tool={"(unknown)": 10})
        sc = make_scorecard(m, _mk_groups(), passed=True)
        assert sc.top_affected_tools == []


# ---------------------------------------------------------------------------
# 测试: immutability
# ---------------------------------------------------------------------------


class TestFrozen:
    def test_scorecard_is_frozen(self):
        """ReportScorecard 为 frozen=True。"""
        sc = make_scorecard(_mk_metrics(), _mk_groups(), passed=True)
        with pytest.raises(AttributeError):
            sc.passed = False  # type: ignore[misc]

    def test_defaults(self):
        """top_issue_categories 和 top_affected_tools 默认空列表。"""
        sc = ReportScorecard(
            passed=True,
            total_findings=0,
            errors=0,
            warnings=0,
            info=0,
            advisory_count=0,
            tools_called=0,
            tool_errors=0,
        )
        assert sc.top_issue_categories == []
        assert sc.top_affected_tools == []


# ---------------------------------------------------------------------------
# 测试: 不修改输入
# ---------------------------------------------------------------------------


class TestNoMutation:
    def test_make_scorecard_does_not_mutate_metrics(self):
        """make_scorecard 不修改传入的 metrics。"""
        m = _mk_metrics(
            unique_tool_count=3,
            finding_count_by_severity={"high": 2},
        )
        original_uc = m.unique_tool_count
        original_sev = dict(m.finding_count_by_severity)

        make_scorecard(m, _mk_groups(), passed=True)

        assert m.unique_tool_count == original_uc
        assert dict(m.finding_count_by_severity) == original_sev

    def test_make_scorecard_does_not_mutate_groups(self):
        """make_scorecard 不修改传入的 groups。"""
        g = _mk_groups(by_category={"tool_call": [_mk_finding("f1")]})
        original_keys = list(g.by_category.keys())

        make_scorecard(_mk_metrics(), g, passed=True)

        assert list(g.by_category.keys()) == original_keys

    def test_does_not_alter_passed(self):
        """make_scorecard 不影响 EvaluationResult.passed。"""
        findings = [_mk_finding("f1", severity="critical")]
        eval_result = EvaluationResult(
            scenario_id="s1",
            findings=findings,  # type: ignore[arg-type]
            passed=False,
        )
        original_passed = eval_result.passed

        # 这里只测 make_scorecard 本身不变异外部数据
        m = _mk_metrics(finding_count_by_severity={"critical": 1})
        g = _mk_groups()
        make_scorecard(m, g, passed=eval_result.passed)

        assert eval_result.passed == original_passed


# ---------------------------------------------------------------------------
# 测试: 确定性
# ---------------------------------------------------------------------------


class TestDeterministic:
    def test_same_input_same_output(self):
        """相同输入多次调用结果一致。"""
        m = _mk_metrics(
            finding_count_by_severity={
                "critical": 1, "high": 2, "medium": 3, "low": 1, "info": 0,
            },
            finding_count_by_tool={"read_file": 3, "grep": 2},
            judge_finding_count=1,
            unique_tool_count=4,
            tool_error_count=0,
        )
        g = _mk_groups(by_category={
            "tool_response": [_mk_finding("f1")],
            "tool_call": [_mk_finding("f2"), _mk_finding("f3")],
        })
        sc1 = make_scorecard(m, g, passed=True)
        sc2 = make_scorecard(m, g, passed=True)
        assert sc1 == sc2
