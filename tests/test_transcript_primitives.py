"""v3.5 P1: Transcript 分析基础原语测试。

测试覆盖：
- normalize_args: 确定性签名、排序独立性、空 dict
- args_similarity: 完全相同、完全不同、部分键变化、空 dict
- sliding_window: 正常遍历、单元素、窗口大于列表
- consecutive_groups: 正常分组、不连续相同 key、空列表
- count_tool_switches: 无切换、有切换、window_size 截断
- find_repeated_sequences: A→B 交替、不重复、最小周期
- is_truncated: 各种截断标记
- extract_fields_usage: 正常、空、引用字段
"""

from __future__ import annotations

from agent_tool_harness.analysis.transcript_primitives import (
    args_similarity,
    consecutive_groups,
    count_tool_switches,
    extract_fields_usage,
    find_repeated_sequences,
    is_truncated,
    normalize_args,
    sliding_window,
)

# ---------------------------------------------------------------------------
# normalize_args
# ---------------------------------------------------------------------------


class TestNormalizeArgs:
    def test_basic(self):
        """简单 args。"""
        result = normalize_args({"query": "hello", "limit": 10})
        assert "hello" in result
        assert "limit" in result

    def test_deterministic(self):
        """相同内容两次调用结果一致。"""
        a = {"b": 1, "a": 2}
        b = {"a": 2, "b": 1}
        assert normalize_args(a) == normalize_args(b)

    def test_nested_dict_stable(self):
        """嵌套 dict 也能确定性序列化。"""
        a = {"x": {"deep": [1, 2, 3]}}
        b = {"x": {"deep": [1, 2, 3]}}
        assert normalize_args(a) == normalize_args(b)

    def test_empty(self):
        assert normalize_args({}) == "{}"

    def test_different_produces_different(self):
        """不同参数产生不同签名。"""
        sig1 = normalize_args({"q": "x"})
        sig2 = normalize_args({"q": "y"})
        assert sig1 != sig2


# ---------------------------------------------------------------------------
# args_similarity
# ---------------------------------------------------------------------------


class TestArgsSimilarity:
    def test_identical(self):
        assert args_similarity({"a": 1}, {"a": 1}) == 1.0

    def test_both_empty(self):
        assert args_similarity({}, {}) == 1.0

    def test_one_empty(self):
        assert args_similarity({}, {"a": 1}) == 0.0
        assert args_similarity({"a": 1}, {}) == 0.0

    def test_completely_different_keys(self):
        """键完全不同 → 很低的相似度。"""
        s = args_similarity({"a": 1}, {"b": 2})
        assert s == 0.0

    def test_partial_key_overlap(self):
        """部分键相同但值不同。"""
        s = args_similarity({"a": 1, "b": 2}, {"a": 1, "b": 99})
        # key_jaccard=1.0, value_similarity=0.5 → 0.5
        assert s == 0.5

    def test_one_value_changed(self):
        """一个值小幅变化 → value_similarity < 1。"""
        s = args_similarity(
            {"query": "find bugs", "limit": 10},
            {"query": "find bug", "limit": 10},
        )
        assert 0.0 < s < 1.0


# ---------------------------------------------------------------------------
# sliding_window
# ---------------------------------------------------------------------------


class TestSlidingWindow:
    def test_normal(self):
        result = list(sliding_window([1, 2, 3, 4], 3))
        assert result == [(1, 2, 3), (2, 3, 4)]

    def test_window_size_equals_list(self):
        result = list(sliding_window([1, 2, 3], 3))
        assert result == [(1, 2, 3)]

    def test_window_larger_than_list(self):
        result = list(sliding_window([1, 2], 3))
        assert result == []

    def test_single_element_window(self):
        result = list(sliding_window([1, 2, 3], 1))
        assert result == [(1,), (2,), (3,)]


# ---------------------------------------------------------------------------
# consecutive_groups
# ---------------------------------------------------------------------------


class TestConsecutiveGroups:
    def test_simple(self):
        result = consecutive_groups([1, 1, 2, 2, 2, 3], key=lambda x: x)
        assert result == [[1, 1], [2, 2, 2], [3]]

    def test_non_consecutive_same_key(self):
        """相同 key 但不连续的 → 分属不同组。"""
        result = consecutive_groups([1, 2, 1, 2], key=lambda x: x)
        assert result == [[1], [2], [1], [2]]

    def test_empty(self):
        assert consecutive_groups([], key=lambda x: x) == []

    def test_single_element(self):
        result = consecutive_groups([42], key=lambda x: x)
        assert result == [[42]]

    def test_with_tool_name_lambda(self):
        """模拟 tool_name 分组。"""
        items = [
            type("T", (), {"tool_name": "search"})(),
            type("T", (), {"tool_name": "search"})(),
            type("T", (), {"tool_name": "read"})(),
        ]
        result = consecutive_groups(items, key=lambda t: t.tool_name)
        assert len(result) == 2
        assert len(result[0]) == 2
        assert len(result[1]) == 1


# ---------------------------------------------------------------------------
# count_tool_switches
# ---------------------------------------------------------------------------


class TestCountToolSwitches:
    def test_no_switches(self):
        assert count_tool_switches(["a", "a", "a"]) == 0

    def test_with_switches(self):
        assert count_tool_switches(["a", "b", "a"]) == 2

    def test_single_call(self):
        assert count_tool_switches(["a"]) == 0

    def test_empty(self):
        assert count_tool_switches([]) == 0

    def test_with_window(self):
        """window_size 限制只计算最后 N 个。"""
        names = ["a", "a", "b", "c", "d"]
        assert count_tool_switches(names, window_size=3) == 2  # b→c, c→d


# ---------------------------------------------------------------------------
# find_repeated_sequences
# ---------------------------------------------------------------------------


class TestFindRepeatedSequences:
    def test_simple_alternation(self):
        """A→B→A→B 重复。"""
        result = find_repeated_sequences(["a", "b", "a", "b"])
        assert len(result) >= 1
        r = result[0]
        assert r["pattern"] == ["a", "b"]
        assert r["cycles"] == 2

    def test_no_repetition(self):
        assert find_repeated_sequences(["a", "b", "c", "d"]) == []

    def test_same_tool_repeated_not_switching(self):
        """同一工具 A→A→A 不算是 tool switching（pattern 内工具不同才计数）。"""
        result = find_repeated_sequences(["a", "a", "a", "a"])
        # 全是同一工具，不会匹配 switching pattern
        assert len(result) == 0

    def test_min_cycles(self):
        """min_cycles=3 时 2 cycles 不匹配。"""
        result = find_repeated_sequences(
            ["a", "b", "a", "b"], min_cycles=3
        )
        assert result == []

    def test_three_tool_pattern(self):
        """A→B→C→A→B→C。"""
        result = find_repeated_sequences(["a", "b", "c", "a", "b", "c"])
        assert len(result) >= 1
        assert result[0]["pattern"] == ["a", "b", "c"]
        assert result[0]["cycles"] == 2

    def test_longer_period_preferred(self):
        """更长的 pattern 应被检测到。"""
        result = find_repeated_sequences(["x", "y", "x", "y", "x", "y"],
                                          min_cycles=2)
        has_xy = any(r["pattern"] == ["x", "y"] for r in result)
        assert has_xy


# ---------------------------------------------------------------------------
# is_truncated
# ---------------------------------------------------------------------------


class TestIsTruncated:
    def test_ellipsis(self):
        assert is_truncated("some output...") is True

    def test_truncated_tag(self):
        assert is_truncated("result [truncated]") is True
        assert is_truncated("result (truncated)") is True

    def test_unicode_ellipsis(self):
        assert is_truncated("结果…") is True

    def test_normal_output(self):
        assert is_truncated("complete result") is False

    def test_empty(self):
        assert is_truncated("") is False


# ---------------------------------------------------------------------------
# extract_fields_usage
# ---------------------------------------------------------------------------


class TestExtractFieldsUsage:
    def test_normal(self):
        out = {"name": "doc", "content": "very long content here"}
        result = extract_fields_usage(out)
        assert result["total_chars"] > 0
        assert set(result["field_sizes"].keys()) == {"name", "content"}
        assert sum(result["field_ratios"].values()) == 1.0
        assert result["largest_field"] == "content"

    def test_empty(self):
        result = extract_fields_usage({})
        assert result["total_chars"] == 0
        assert result["largest_field"] is None

    def test_with_referenced_fields(self):
        out = {"a": "x" * 100, "b": "y", "c": "z" * 50}
        result = extract_fields_usage(out, referenced_fields={"a"})
        # unreferenced: b + c = 1 + 50 = 51 out of 151
        assert result["unreferenced_ratio"] > 0.0


# ---------------------------------------------------------------------------
# 整合：args 比较 + 窗口遍历
# ---------------------------------------------------------------------------


class TestIntegration:
    """P1 原语协同使用场景。"""

    def test_find_consecutive_same_args(self):
        """用 consecutive_groups + normalize_args 找出连续相同 args 的调用。"""
        calls = [
            type("C", (), {"tool_name": "s", "arguments": {"q": "x"}})(),
            type("C", (), {"tool_name": "s", "arguments": {"q": "x"}})(),
            type("C", (), {"tool_name": "s", "arguments": {"q": "x"}})(),
            type("C", (), {"tool_name": "s", "arguments": {"q": "y"}})(),
        ]
        groups = consecutive_groups(calls, key=lambda c: normalize_args(c.arguments))
        # 前 3 个相同 args → 一组，第 4 个不同 → 另一组
        assert len(groups) == 2
        assert len(groups[0]) == 3  # 连续 3 次相同 args
        assert len(groups[1]) == 1
