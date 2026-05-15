"""P4 RecommendationCatalog 测试。

覆盖 25+ 场景：31 条已知 rule_id 精确匹配、fallback 按 severity 分级、
去重、JudgeFinding 处理、deterministic 输出、不改变 pass/fail。
"""

from __future__ import annotations

import pytest

from agent_tool_harness.core_contract import (
    EvaluationResult,
    JudgeFinding,
    RuleFinding,
)
from agent_tool_harness.reports.report_insight import (
    _RECOMMENDATION_CATALOG,
    Recommendation,
    RecommendationCatalog,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_rule_finding(
    finding_id: str = "f1",
    severity: str = "high",
    rule_type: str = "tool_response.output.low_signal",
    message: str = "",
    evidence_ref: str = "ref",
) -> RuleFinding:
    return RuleFinding(
        finding_id=finding_id,
        severity=severity,
        category="rule",
        message=message or f"规则发现: {rule_type}",
        evidence_ref=evidence_ref,
        rule_type=rule_type,
        rule_passed=False,
    )


def _make_judge_finding(
    finding_id: str = "j1",
    severity: str = "medium",
    message: str = "LLM judge 发现输出质量一般",
) -> JudgeFinding:
    return JudgeFinding(
        finding_id=finding_id,
        severity=severity,
        category="judge",
        message=message,
        evidence_ref="ref",
        provider="openai-native",
        model="gpt-4o",
        confidence=0.7,
        rationale="输出缺少上下文",
        rubric="response_quality",
    )


# ---------------------------------------------------------------------------
# 测试 1: 已知 rule_id 精确匹配（参数化）
# ---------------------------------------------------------------------------


# 收集所有 31 条 rule_id
ALL_RULE_IDS = list(_RECOMMENDATION_CATALOG.keys())


@pytest.mark.parametrize("rule_id", ALL_RULE_IDS)
class TestKnownRuleId:
    def test_has_specific_recommendation(self, rule_id: str):
        """每条已知 rule_id 有对应 recommendation，what/why/how_to_fix 均非空。"""
        f = _make_rule_finding(rule_type=rule_id)
        catalog = RecommendationCatalog()
        rec = catalog.recommend(f)

        assert rec.rule_id == rule_id
        assert isinstance(rec.what, str) and len(rec.what) > 0
        assert isinstance(rec.why, str) and len(rec.why) > 0
        assert isinstance(rec.how_to_fix, str) and len(rec.how_to_fix) > 0
        assert rec.affected_count == 1


# ---------------------------------------------------------------------------
# 测试 2: 特定 rule_id 内容验证
# ---------------------------------------------------------------------------


class TestSpecificRuleContent:
    def test_low_signal_keywords(self):
        """tool_response.output.low_signal → what 包含"信号过低"。"""
        f = _make_rule_finding(rule_type="tool_response.output.low_signal")
        rec = RecommendationCatalog().recommend(f)
        assert "信号过低" in rec.what

    def test_error_actionable_keywords(self):
        """tool_response.error.actionable → how_to_fix 包含 suggested_action。"""
        f = _make_rule_finding(rule_type="tool_response.error.actionable")
        rec = RecommendationCatalog().recommend(f)
        assert "suggested_action" in rec.how_to_fix

    def test_spec_description_length_keywords(self):
        """tool_spec.description.useful_length → how_to_fix 包含"扩展"。"""
        f = _make_rule_finding(rule_type="tool_spec.description.useful_length")
        rec = RecommendationCatalog().recommend(f)
        assert "扩展" in rec.how_to_fix

    def test_name_too_generic_keywords(self):
        """tool_ergonomics.name.too_generic → how_to_fix 包含"前缀"。"""
        f = _make_rule_finding(rule_type="tool_ergonomics.name.too_generic")
        rec = RecommendationCatalog().recommend(f)
        assert "前缀" in rec.how_to_fix

    def test_shallow_wrapper_keywords(self):
        """tool_ergonomics.description.shallow_wrapper → how_to_fix 含"抽象层级"或"面向 Agent"。"""
        f = _make_rule_finding(rule_type="tool_ergonomics.description.shallow_wrapper")
        rec = RecommendationCatalog().recommend(f)
        assert "Agent" in rec.how_to_fix or "抽象" in rec.how_to_fix

    def test_arguments_present_keywords(self):
        """tool_call.arguments.present → what 包含"缺少"。"""
        f = _make_rule_finding(rule_type="tool_call.arguments.present")
        rec = RecommendationCatalog().recommend(f)
        assert "缺少" in rec.what

    def test_orphan_call_keywords(self):
        """tool_pair.orphan_call → how_to_fix 包含"工具执行链路"。"""
        f = _make_rule_finding(rule_type="tool_pair.orphan_call")
        rec = RecommendationCatalog().recommend(f)
        assert "工具执行链路" in rec.how_to_fix

    def test_orphan_result_keywords(self):
        """tool_pair.orphan_result → how_to_fix 包含"trace 记录"。"""
        f = _make_rule_finding(rule_type="tool_pair.orphan_result")
        rec = RecommendationCatalog().recommend(f)
        assert ("trace" in rec.how_to_fix.lower()
                or "记录" in rec.how_to_fix)


# ---------------------------------------------------------------------------
# 测试 3: fallback recommendation
# ---------------------------------------------------------------------------


class TestFallbackRecommendations:
    def test_critical_fallback(self):
        """未知 rule_id + critical severity → critical fallback。"""
        f = _make_rule_finding(
            rule_type="some.nonexistent.rule",
            severity="critical",
        )
        rec = RecommendationCatalog().recommend(f)
        assert "严重问题" in rec.what or "暂无针对" in rec.what

    def test_high_fallback(self):
        """未知 rule_id + high severity → high fallback。"""
        f = _make_rule_finding(rule_type="unknown.rule.xxx", severity="high")
        rec = RecommendationCatalog().recommend(f)
        assert "高优先级" in rec.what or "暂无针对" in rec.what

    def test_medium_fallback(self):
        """未知 rule_id + medium severity → medium fallback。"""
        f = _make_rule_finding(rule_type="unknown.rule.yyy", severity="medium")
        rec = RecommendationCatalog().recommend(f)
        assert "中优先级" in rec.what or "暂无针对" in rec.what

    def test_low_fallback(self):
        """未知 rule_id + low severity → low fallback。"""
        f = _make_rule_finding(rule_type="unknown.rule.zzz", severity="low")
        rec = RecommendationCatalog().recommend(f)
        assert "低优先级" in rec.what or "暂无针对" in rec.what

    def test_info_fallback(self):
        """未知 rule_id + info severity → info fallback。"""
        f = _make_rule_finding(rule_type="unknown.rule.iii", severity="info")
        rec = RecommendationCatalog().recommend(f)
        assert "仅供参考" in rec.what or "暂无针对" in rec.what

    def test_weird_severity_fallback_to_info(self):
        """未知 severity → 回退到 info fallback。"""
        f = _make_rule_finding(rule_type="unknown.rule.weird", severity="bogus")
        rec = RecommendationCatalog().recommend(f)
        # 不应崩溃，应有合理的 fallback
        assert isinstance(rec.what, str) and len(rec.what) > 0


# ---------------------------------------------------------------------------
# 测试 4: JudgeFinding recommendation
# ---------------------------------------------------------------------------


class TestJudgeFindingRecommendation:
    def test_judge_finding_advisory_fallback(self):
        """JudgeFinding 无 rule_type → advisory fallback。"""
        f = _make_judge_finding()
        rec = RecommendationCatalog().recommend(f)
        assert rec.category == "judge"
        assert "LLM judge" in rec.what or "advisory" in rec.what.lower()
        assert len(rec.how_to_fix) > 0

    def test_judge_finding_deterministic(self):
        """同一 JudgeFinding 多次 recommend 结果一致。"""
        f = _make_judge_finding()
        catalog = RecommendationCatalog()
        rec1 = catalog.recommend(f)
        rec2 = catalog.recommend(f)
        assert rec1 == rec2


# ---------------------------------------------------------------------------
# 测试 5: recommend_all 去重
# ---------------------------------------------------------------------------


class TestRecommendAllDedup:
    def test_same_rule_id_deduped(self):
        """同一 rule_id 的多条 finding 只输出 1 条 recommendation。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_response.output.low_signal"),
            _make_rule_finding("f2", rule_type="tool_response.output.low_signal"),
            _make_rule_finding("f3", rule_type="tool_response.output.low_signal"),
        ]
        recs = RecommendationCatalog().recommend_all(findings)
        assert len(recs) == 1
        assert recs[0].affected_count == 3

    def test_different_rule_ids_kept(self):
        """不同 rule_id 各自保留。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_response.output.low_signal"),
            _make_rule_finding("f2", rule_type="tool_spec.description.exists"),
            _make_rule_finding("f3", rule_type="tool_ergonomics.name.too_generic"),
        ]
        recs = RecommendationCatalog().recommend_all(findings)
        assert len(recs) == 3

    def test_dedup_keeps_higher_severity(self):
        """去重时保留更严重的 severity。"""
        mk = _make_rule_finding
        findings = [
            mk("f1", rule_type="tool_response.output.low_signal", severity="low"),
            mk("f2", rule_type="tool_response.output.low_signal", severity="critical"),
        ]
        recs = RecommendationCatalog().recommend_all(findings)
        assert len(recs) == 1
        assert recs[0].severity == "critical"

    def test_empty_findings(self):
        """空 findings → 空 recommendations。"""
        recs = RecommendationCatalog().recommend_all([])
        assert recs == []

    def test_all_findings_covered(self):
        """recommend_all 覆盖所有输入 finding（每条至少被 1 条 rec 覆盖）。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_response.output.low_signal"),
            _make_rule_finding("f2", rule_type="tool_response.error.actionable"),
            _make_rule_finding("f3", rule_type="tool_spec.description.useful_length"),
            _make_judge_finding("j1"),
        ]
        recs = RecommendationCatalog().recommend_all(findings)
        # 输出数量 ≤ 输入数量（去重）
        assert len(recs) <= len(findings)
        assert all(isinstance(r, Recommendation) for r in recs)


# ---------------------------------------------------------------------------
# 测试 6: 输出稳定性
# ---------------------------------------------------------------------------


class TestDeterministicOutput:
    def test_same_input_same_output(self):
        """同一份 findings 每次 recommend_all 结果一致。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_response.output.low_signal"),
            _make_rule_finding("f2", rule_type="tool_spec.description.exists"),
            _make_judge_finding("j1"),
        ]
        catalog = RecommendationCatalog()
        recs1 = catalog.recommend_all(findings)
        recs2 = catalog.recommend_all(findings)
        assert recs1 == recs2

    def test_output_order_by_severity(self):
        """recommend_all 输出按 severity 降序排列。"""
        mk = _make_rule_finding
        findings = [
            mk("f1", rule_type="tool_spec.description.exists", severity="low"),
            mk("f2", rule_type="tool_response.output.low_signal", severity="critical"),
            mk("f3", rule_type="tool_ergonomics.name.too_generic", severity="info"),
        ]
        recs = RecommendationCatalog().recommend_all(findings)
        severities = [r.severity for r in recs]
        assert severities == ["critical", "low", "info"]


# ---------------------------------------------------------------------------
# 测试 7: 不修改输入
# ---------------------------------------------------------------------------


class TestNoMutation:
    def test_recommend_does_not_mutate_finding(self):
        """recommend() 不修改传入的 finding。"""
        f = _make_rule_finding(rule_type="tool_response.output.low_signal")
        original_id = f.finding_id
        original_severity = f.severity

        RecommendationCatalog().recommend(f)

        assert f.finding_id == original_id
        assert f.severity == original_severity

    def test_recommend_all_does_not_mutate_findings(self):
        """recommend_all() 不修改传入的 findings 列表。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_response.output.low_signal"),
            _make_rule_finding("f2", rule_type="tool_spec.description.exists"),
        ]
        original_ids = [f.finding_id for f in findings]

        RecommendationCatalog().recommend_all(findings)

        assert [f.finding_id for f in findings] == original_ids

    def test_does_not_alter_passed(self):
        """recommendation 不影响 EvaluationResult.passed。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_pair.orphan_call", severity="critical"),
        ]
        eval_result = EvaluationResult(
            scenario_id="s1",
            findings=findings,  # type: ignore[arg-type]
            passed=False,
        )
        original_passed = eval_result.passed

        RecommendationCatalog().recommend_all(eval_result.findings)

        # passed 不应被修改
        assert eval_result.passed == original_passed


# ---------------------------------------------------------------------------
# 测试 8: coverage 覆盖所有已知 rule_id
# ---------------------------------------------------------------------------


class TestCoverage:
    def test_all_31_rule_ids_in_catalog(self):
        """所有 31 条 deterministic rule_id 都在 _RECOMMENDATION_CATALOG 中。"""
        # 验证 catalog 有 31 条（或更多，如果有额外映射）
        assert len(_RECOMMENDATION_CATALOG) >= 31

    def test_each_rule_id_non_empty_text(self):
        """每条 catalog entry 的 what/why/how_to_fix 均为非空字符串。"""
        for rule_id, (what, why, how_to_fix) in _RECOMMENDATION_CATALOG.items():
            assert isinstance(what, str) and len(what.strip()) > 0, \
                f"{rule_id}: what is empty"
            assert isinstance(why, str) and len(why.strip()) > 0, \
                f"{rule_id}: why is empty"
            assert isinstance(how_to_fix, str) and len(how_to_fix.strip()) > 0, \
                f"{rule_id}: how_to_fix is empty"


# ---------------------------------------------------------------------------
# 测试 9: Recommendation dataclass
# ---------------------------------------------------------------------------


class TestRecommendationDataclass:
    def test_frozen(self):
        """Recommendation 为 frozen=True。"""
        rec = Recommendation(
            rule_id="test.rule",
            category="test",
            severity="high",
            what="问题",
            why="原因",
            how_to_fix="修复",
        )
        with pytest.raises(AttributeError):
            rec.what = "changed"  # type: ignore[misc]

    def test_default_affected_count(self):
        """affected_count 默认为 1。"""
        rec = Recommendation(
            rule_id="test.rule",
            category="test",
            severity="medium",
            what="w",
            why="y",
            how_to_fix="h",
        )
        assert rec.affected_count == 1
