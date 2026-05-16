"""P2: Deterministic verifiers 测试。

测试覆盖 6 种 verifier + 工厂函数：
- ContainsRequiredFacts: 全部匹配 / 部分匹配 / 零匹配 / case-insensitive / 空
- ForbiddenFactsAbsent: 无禁止事实 / 发现禁止事实 / 空
- ExactMatch: 精确匹配 / 不匹配 / 空白差异
- RegexMatch: 全部匹配 / 部分匹配 / 空 patterns
- JsonFieldMatch: 字段子集匹配 / 字段缺失 / 嵌套比较
- CompositeVerifier(all): 全部通过 / 一个失败
- CompositeVerifier(any): 一个通过
- build_verifiers_from_outcome: 正确数量 / 空 ExpectedOutcome

架构语义保护：
- 所有 verifier 为 deterministic——同一输入始终同一输出
- verifier 不修改 EvaluationResult.passed——它们是纯函数，只产出 VerifierResult
- 特殊字符、多行文本、中文内容都能正确处理
- CompositeVerifier 保留子结果——matched/missing 聚合自子 verifier
"""

from __future__ import annotations

import pytest

from agent_tool_harness.task_eval.eval_case import ExpectedOutcome
from agent_tool_harness.task_eval.verifiers import (
    CompositeVerifier,
    ContainsRequiredFacts,
    ExactMatch,
    ForbiddenFactsAbsent,
    JsonFieldMatch,
    RegexMatch,
    build_verifiers_from_outcome,
)

# ============================================================================
# ContainsRequiredFacts
# ============================================================================


class TestContainsRequiredFacts:
    def test_all_facts_matched(self):
        """全部 required_facts 匹配 → passed=True, matched=all。"""
        v = ContainsRequiredFacts(["root cause", "fix recommendation"])
        result = v.verify(
            "Root cause is network timeout. Fix recommendation: increase retry.",
            [],
        )
        assert result.passed is True
        assert result.matched == ["root cause", "fix recommendation"]
        assert result.missing == []

    def test_partial_match(self):
        """部分匹配 → passed=False, missing 有值。"""
        v = ContainsRequiredFacts(["root cause", "fix recommendation"])
        result = v.verify("Root cause is network timeout.", [])
        assert result.passed is False
        assert result.matched == ["root cause"]
        assert result.missing == ["fix recommendation"]

    def test_zero_match(self):
        """全部不匹配 → passed=False, missing=all。"""
        v = ContainsRequiredFacts(["root cause", "fix"])
        result = v.verify("Everything is fine.", [])
        assert result.passed is False
        assert result.matched == []
        assert result.missing == ["root cause", "fix"]

    def test_case_insensitive(self):
        """case-insensitive 匹配——"Root Cause" 匹配 "root cause"。"""
        v = ContainsRequiredFacts(["root cause"])
        result = v.verify("Root Cause identified.", [])
        assert result.passed is True
        assert result.matched == ["root cause"]

    def test_empty_required_facts(self):
        """空 required_facts → passed=True（无要求即通过）。"""
        v = ContainsRequiredFacts([])
        result = v.verify("any answer", [])
        assert result.passed is True
        assert result.matched == []
        assert result.missing == []

    def test_chinese_fact_matching(self):
        """中文事实匹配——天然 case-insensitive（中文无大小写）。"""
        v = ContainsRequiredFacts(["根本原因是网络超时"])
        result = v.verify("经过排查，根本原因是网络超时。建议增加重试机制。", [])
        assert result.passed is True
        assert result.matched == ["根本原因是网络超时"]


# ============================================================================
# ForbiddenFactsAbsent
# ============================================================================


class TestForbiddenFactsAbsent:
    def test_no_forbidden_facts_found(self):
        """answer 不含禁止事实 → passed=True。"""
        v = ForbiddenFactsAbsent(["restart production"])
        result = v.verify("Fix: increase timeout and retry.", [])
        assert result.passed is True
        assert result.missing == []

    def test_forbidden_fact_found(self):
        """answer 含禁止事实 → passed=False, missing=found。"""
        v = ForbiddenFactsAbsent(["restart production"])
        result = v.verify("We should restart production.", [])
        assert result.passed is False
        assert result.missing == ["restart production"]

    def test_empty_forbidden_facts(self):
        """空禁止列表 → passed=True。"""
        v = ForbiddenFactsAbsent([])
        result = v.verify("restart production now!", [])
        assert result.passed is True

    def test_forbidden_case_insensitive(self):
        """case-insensitive——"RESTART PRODUCTION" 匹配 "restart production"。"""
        v = ForbiddenFactsAbsent(["restart production"])
        result = v.verify("RESTART PRODUCTION NOW", [])
        assert result.passed is False
        assert result.missing == ["restart production"]


# ============================================================================
# ExactMatch
# ============================================================================


class TestExactMatch:
    def test_exact_match(self):
        """精确字符串匹配 → passed=True。"""
        v = ExactMatch("42")
        result = v.verify("42", [])
        assert result.passed is True
        assert result.matched == ["42"]

    def test_not_match(self):
        """不匹配 → passed=False。"""
        v = ExactMatch("42")
        result = v.verify("43", [])
        assert result.passed is False

    def test_strip_whitespace(self):
        """首尾空白差异 → passed=True（strip 后比较）。"""
        v = ExactMatch("answer")
        result = v.verify("  answer  ", [])
        assert result.passed is True

    def test_multiline_exact(self):
        """多行文本精确匹配。"""
        v = ExactMatch("line1\nline2")
        result = v.verify("line1\nline2", [])
        assert result.passed is True


# ============================================================================
# RegexMatch
# ============================================================================


class TestRegexMatch:
    def test_all_patterns_match(self):
        """全部 pattern 匹配 → passed=True。"""
        v = RegexMatch([r"\d+", r"error"])
        result = v.verify("error code: 500", [])
        assert result.passed is True
        assert len(result.matched) == 2

    def test_partial_match(self):
        """部分 pattern 不匹配 → passed=False。"""
        v = RegexMatch([r"\d+", r"timeout"])
        result = v.verify("error code: 500", [])
        assert result.passed is False
        assert len(result.matched) == 1
        assert len(result.missing) == 1

    def test_empty_patterns(self):
        """空 patterns → passed=True。"""
        v = RegexMatch([])
        result = v.verify("anything", [])
        assert result.passed is True

    def test_multiline_match(self):
        """多行文本正则匹配（DOTALL 模式）。"""
        v = RegexMatch([r"error.*timeout"])
        result = v.verify("error occurred\nnetwork timeout", [])
        assert result.passed is True


# ============================================================================
# JsonFieldMatch
# ============================================================================


class TestJsonFieldMatch:
    def test_field_subset_match(self):
        """expected 是 tool_output 的子集 → passed=True。"""
        v = JsonFieldMatch({"status": "ok"})
        result = v.verify(
            "",
            [{"status": "ok", "data": {"id": 1}}],
        )
        assert result.passed is True
        assert result.matched == ["status"]

    def test_field_missing(self):
        """expected 字段不在任何 tool_output → passed=False。"""
        v = JsonFieldMatch({"status": "ok"})
        result = v.verify("", [{"data": {"id": 1}}])
        assert result.passed is False
        assert result.missing == ["status"]

    def test_nested_dict_subset(self):
        """嵌套 dict 递归子集匹配。"""
        v = JsonFieldMatch({"result": {"status": "ok"}})
        result = v.verify(
            "",
            [{"result": {"status": "ok", "id": 1}}],
        )
        assert result.passed is True

    def test_nested_dict_not_subset(self):
        """嵌套 dict 不满足子集条件 → passed=False。"""
        v = JsonFieldMatch({"result": {"status": "ok"}})
        result = v.verify(
            "",
            [{"result": {"status": "error"}}],
        )
        assert result.passed is False

    def test_search_across_multiple_outputs(self):
        """在多个 tool_output 中搜索——任一匹配即通过。"""
        v = JsonFieldMatch({"key": "target"})
        result = v.verify(
            "",
            [
                {"other": "data"},
                {"key": "target", "extra": 1},
            ],
        )
        assert result.passed is True

    def test_empty_expected_fields(self):
        """空 expected_fields → passed=True。"""
        v = JsonFieldMatch({})
        result = v.verify("", [{"any": "data"}])
        assert result.passed is True

    def test_non_dict_output_skipped(self):
        """非 dict 的 tool_output 跳过，不 crash。"""
        v = JsonFieldMatch({"key": "val"})
        result = v.verify("", ["not a dict", 123, {"key": "val"}])
        assert result.passed is True

    def test_list_of_dicts_subset_match(self):
        """list 嵌套 dict 时递归子集匹配——expected dict 是 actual dict 的子集。"""
        v = JsonFieldMatch({"items": [{"name": "foo"}]})
        result = v.verify(
            "",
            [{"items": [{"name": "foo", "extra": "bar"}, {"other": "x"}]}],
        )
        assert result.passed is True

    def test_list_of_dicts_not_subset(self):
        """list 嵌套 dict 时 expected dict 不是任何 actual dict 的子集 → failed。"""
        v = JsonFieldMatch({"items": [{"name": "missing"}]})
        result = v.verify(
            "",
            [{"items": [{"name": "foo"}, {"name": "bar"}]}],
        )
        assert result.passed is False

    def test_nested_list_recursive_subset(self):
        """递归 list 嵌套——[[{"a": 1}]] 是 [[{"a": 1, "b": 2}]] 的子集。"""
        v = JsonFieldMatch({"data": [[{"a": 1}]]})
        result = v.verify(
            "",
            [{"data": [[{"a": 1, "b": 2}, {"c": 3}]]}],
        )
        assert result.passed is True


# ============================================================================
# CompositeVerifier
# ============================================================================


class TestCompositeVerifier:
    def test_all_mode_all_pass(self):
        """mode="all" + 全部子 verifier 通过 → passed=True。"""
        v = CompositeVerifier(
            [
                ContainsRequiredFacts(["fact"]),
                ForbiddenFactsAbsent(["bad"]),
            ],
            mode="all",
        )
        result = v.verify("fact is here", [])
        assert result.passed is True

    def test_all_mode_one_fails(self):
        """mode="all" + 一个子 verifier 失败 → passed=False。"""
        v = CompositeVerifier(
            [
                ContainsRequiredFacts(["fact"]),
                ForbiddenFactsAbsent(["bad"]),
            ],
            mode="all",
        )
        result = v.verify("fact is here but bad too", [])
        assert result.passed is False
        assert any("contains_required_facts" in result.details for _ in [1])

    def test_any_mode_one_passes(self):
        """mode="any" + 一个子 verifier 通过 → passed=True。"""
        v = CompositeVerifier(
            [
                ContainsRequiredFacts(["fact"]),
                ExactMatch("exact answer"),
            ],
            mode="any",
        )
        result = v.verify("fact is here", [])
        assert result.passed is True

    def test_any_mode_all_fail(self):
        """mode="any" + 全部失败 → passed=False。"""
        v = CompositeVerifier(
            [
                ContainsRequiredFacts(["fact"]),
                ExactMatch("exact"),
            ],
            mode="any",
        )
        result = v.verify("nothing matches", [])
        assert result.passed is False

    def test_preserves_sub_results(self):
        """CompositeVerifier 保留子 verifier 的 matched/missing 聚合。"""
        v = CompositeVerifier(
            [
                ContainsRequiredFacts(["fact A"]),
                ContainsRequiredFacts(["fact B"]),
            ],
            mode="all",
        )
        result = v.verify("fact A present", [])
        assert result.passed is False
        assert "fact A" in result.matched
        assert "fact B" in result.missing

    def test_empty_verifiers(self):
        """空 verifiers 列表 → passed=True（无约束即满足）。"""
        v = CompositeVerifier([], mode="all")
        result = v.verify("anything", [])
        assert result.passed is True

    def test_invalid_mode_raises(self):
        """非法 mode 值 raise ValueError。"""
        with pytest.raises(ValueError, match="mode"):
            CompositeVerifier([], mode="xor")

    def test_default_mode_is_all(self):
        """不传 mode 默认为 "all"。"""
        v = CompositeVerifier([
            ContainsRequiredFacts(["fact"]),
        ])
        result = v.verify("fact", [])
        assert result.passed is True


# ============================================================================
# build_verifiers_from_outcome
# ============================================================================


class TestBuildVerifiersFromOutcome:
    def test_build_from_full_outcome(self):
        """完整 ExpectedOutcome 构造全部 5 种 verifier。"""
        outcome = ExpectedOutcome(
            required_facts=["fact"],
            forbidden_facts=["bad"],
            expected_json_fields={"status": "ok"},
            exact_answer="42",
            regex_patterns=[r"\d+"],
        )
        verifiers = build_verifiers_from_outcome(outcome)
        assert len(verifiers) == 5

    def test_build_from_empty_outcome(self):
        """空 ExpectedOutcome → 空 verifier 列表。"""
        outcome = ExpectedOutcome()
        verifiers = build_verifiers_from_outcome(outcome)
        assert len(verifiers) == 0

    def test_build_ignores_human_notes(self):
        """human_notes 不生成 verifier（不参与自动验证）。"""
        outcome = ExpectedOutcome(human_notes="需人工确认")
        verifiers = build_verifiers_from_outcome(outcome)
        assert len(verifiers) == 0

    def test_build_partial_outcome(self):
        """仅有 required_facts + forbidden_facts → 2 verifiers。"""
        outcome = ExpectedOutcome(
            required_facts=["f1"],
            forbidden_facts=["b1"],
        )
        verifiers = build_verifiers_from_outcome(outcome)
        assert len(verifiers) == 2

    def test_build_from_non_outcome(self):
        """非 ExpectedOutcome 输入 → 空列表，不 crash。"""
        assert build_verifiers_from_outcome(None) == []
        assert build_verifiers_from_outcome("not an outcome") == []
