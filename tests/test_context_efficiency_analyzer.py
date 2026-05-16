"""v3.5 P3: ContextEfficiencyAnalyzer 测试。

覆盖 5 种 context inefficiency pattern，每种 2-3 个场景。
"""

from __future__ import annotations

import pytest

from agent_tool_harness.analysis.context_efficiency_analyzer import (
    ContextEfficiencyAnalyzer,
)
from agent_tool_harness.core_contract import ExecutionTrace, ToolCall, ToolResult

# ---------------------------------------------------------------------------
# 辅助构造器
# ---------------------------------------------------------------------------


def _make_call(
    tool_name: str,
    arguments: dict | None = None,
    call_id: str = "",
) -> ToolCall:
    return ToolCall(
        tool_name=tool_name,
        arguments=arguments or {},
        call_id=call_id or tool_name,
    )


def _make_result(
    call_id: str,
    tool_name: str = "",
    status: str = "success",
    output: dict | None = None,
    error: str | None = None,
) -> ToolResult:
    return ToolResult(
        call_id=call_id,
        tool_name=tool_name or call_id,
        status=status,
        output=output or {},
        error=error,
    )


def _make_trace(
    calls: list[ToolCall] | None = None,
    results: list[ToolResult] | None = None,
    final_answer: str = "",
) -> ExecutionTrace:
    return ExecutionTrace(
        scenario_id="test",
        tool_calls=calls or [],
        tool_results=results or [],
        messages=[],
        final_answer=final_answer,
    )


# ---------------------------------------------------------------------------
# Analyzer fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def analyzer() -> ContextEfficiencyAnalyzer:
    return ContextEfficiencyAnalyzer()


# ---------------------------------------------------------------------------
# 1. response_bloat
# ---------------------------------------------------------------------------


class TestResponseBloat:
    def test_bloat_detected(self, analyzer):
        """一个 result 远超 median × 10。"""
        results = [
            _make_result("c1", tool_name="search", output={"data": "short"}),
            _make_result("c2", tool_name="search", output={"data": "short"}),
            _make_result(
                "c3", tool_name="search",
                output={"data": "x" * 500},
            ),  # 远超 median
        ]
        # median ≈ 15 chars, c3 = ~507 chars >> median × 10
        trace = _make_trace(results=results)
        findings = analyzer._detect_response_bloat(trace)
        assert len(findings) >= 1
        f = findings[0]
        assert f.rule_type == "context.response_bloat"
        assert f.severity == "high"
        assert f.category == "context"

    def test_normal_variation_not_detected(self, analyzer):
        """正常波动 → 不检测。"""
        results = [
            _make_result("c1", tool_name="search", output={"data": "abc"}),
            _make_result("c2", tool_name="search", output={"data": "defghij"}),
            _make_result("c3", tool_name="search", output={"data": "klmnop"}),
        ]
        trace = _make_trace(results=results)
        findings = analyzer._detect_response_bloat(trace)
        assert len(findings) == 0

    def test_insufficient_data_skipped(self, analyzer):
        """只有 1 次调用 → 跳过（无法计算 median）。"""
        results = [
            _make_result("c1", tool_name="search", output={"data": "x" * 5000}),
        ]
        trace = _make_trace(results=results)
        findings = analyzer._detect_response_bloat(trace)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# 2. missing_pagination
# ---------------------------------------------------------------------------


class TestMissingPagination:
    def test_large_list_no_pagination(self, analyzer):
        """返回 ≥ 20 项但 args 无分页参数。"""
        calls = [
            _make_call("list_items", {"filter": "all"}, call_id="c1"),
        ]
        results = [
            _make_result(
                "c1", tool_name="list_items",
                output={"items": list(range(25))},
            ),
        ]
        trace = _make_trace(calls=calls, results=results)
        findings = analyzer._detect_missing_pagination(trace)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_type == "context.missing_pagination"
        assert "25" in f.message

    def test_large_list_with_pagination_not_detected(self, analyzer):
        """有分页参数 → 不检测。"""
        calls = [
            _make_call("list_items", {"limit": 20, "offset": 0}, call_id="c1"),
        ]
        results = [
            _make_result(
                "c1", tool_name="list_items",
                output={"items": list(range(25))},
            ),
        ]
        trace = _make_trace(calls=calls, results=results)
        findings = analyzer._detect_missing_pagination(trace)
        assert len(findings) == 0

    def test_small_list_not_detected(self, analyzer):
        """list < 20 项 → 不检测。"""
        calls = [
            _make_call("list_items", {}, call_id="c1"),
        ]
        results = [
            _make_result("c1", tool_name="list_items", output={"items": list(range(5))}),
        ]
        trace = _make_trace(calls=calls, results=results)
        findings = analyzer._detect_missing_pagination(trace)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# 3. missing_concise_mode
# ---------------------------------------------------------------------------


class TestMissingConciseMode:
    def test_many_fields_no_summary(self, analyzer):
        """≥ 5 个字段但无简洁标记 → 检测。"""
        results = [
            _make_result(
                "c1", tool_name="get_report",
                output={
                    "full_content": "x" * 100,
                    "metadata": "y",
                    "raw_data": "z" * 50,
                    "timestamps": [],
                    "logs": "a" * 30,
                },
            ),
        ]
        trace = _make_trace(results=results)
        findings = analyzer._detect_missing_concise_mode(trace)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_type == "context.missing_concise_mode"

    def test_has_summary_field_not_detected(self, analyzer):
        """有 summary 字段 → 不检测。"""
        results = [
            _make_result(
                "c1", tool_name="get_report",
                output={
                    "summary": "brief",
                    "full_content": "x" * 100,
                    "metadata": "y",
                    "raw_data": "z" * 50,
                    "timestamps": [],
                },
            ),
        ]
        trace = _make_trace(results=results)
        findings = analyzer._detect_missing_concise_mode(trace)
        assert len(findings) == 0

    def test_few_fields_not_detected(self, analyzer):
        """< 5 个字段 → 不检测。"""
        results = [
            _make_result(
                "c1", tool_name="get_status",
                output={"status": "ok", "code": 200},
            ),
        ]
        trace = _make_trace(results=results)
        findings = analyzer._detect_missing_concise_mode(trace)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# 4. low_value_large_fields
# ---------------------------------------------------------------------------


class TestLowValueLargeFields:
    def test_large_field_unreferenced(self, analyzer):
        """大字段未被后续引用。"""
        calls = [
            _make_call("search", {"q": "error"}, call_id="c1"),
            _make_call("read", {"path": "/log"}, call_id="c2"),
        ]
        results = [
            _make_result(
                "c1", tool_name="search",
                output={
                    "summary": "found error",
                    "raw_dump": "x" * 1000,  # 占比最大
                },
            ),
        ]
        trace = _make_trace(
            calls=calls, results=results,
            final_answer="Found error in the logs, reading it now.",
        )
        findings = analyzer._detect_low_value_large_fields(trace)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_type == "context.low_value_large_fields"
        assert "raw_dump" in f.message

    def test_large_field_referenced_not_detected(self, analyzer):
        """大字段被后续引用 → 不检测。"""
        calls = [
            _make_call("search", {"q": "error"}, call_id="c1"),
            _make_call("analyze", {"input": "raw_dump data"}, call_id="c2"),
        ]
        results = [
            _make_result(
                "c1", tool_name="search",
                output={
                    "summary": "found",
                    "raw_dump": "x" * 1000,
                },
            ),
        ]
        trace = _make_trace(
            calls=calls, results=results,
            final_answer="Analyzing the raw_dump now.",
        )
        findings = analyzer._detect_low_value_large_fields(trace)
        assert len(findings) == 0

    def test_balanced_fields_not_detected(self, analyzer):
        """字段占比均匀 → 不检测。"""
        results = [
            _make_result(
                "c1", tool_name="search",
                output={"field_a": "x" * 50, "field_b": "y" * 50},
            ),
        ]
        trace = _make_trace(results=results)
        findings = analyzer._detect_low_value_large_fields(trace)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# 5. truncation_without_hint
# ---------------------------------------------------------------------------


class TestTruncationWithoutHint:
    def test_truncated_no_hint(self, analyzer):
        """截断但无延续提示 → 检测。"""
        results = [
            _make_result(
                "c1", tool_name="search",
                output={"results": "some output..."},
            ),
        ]
        trace = _make_trace(results=results)
        findings = analyzer._detect_truncation_without_hint(trace)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_type == "context.truncation_without_hint"
        assert f.severity == "high"

    def test_truncated_with_cursor_not_detected(self, analyzer):
        """截断但有 next_cursor → 不检测。"""
        results = [
            _make_result(
                "c1", tool_name="search",
                output={
                    "results": "partial data...",
                    "next_cursor": "abc123",
                },
            ),
        ]
        trace = _make_trace(results=results)
        findings = analyzer._detect_truncation_without_hint(trace)
        assert len(findings) == 0

    def test_normal_output_not_detected(self, analyzer):
        """非截断输出 → 不检测。"""
        results = [
            _make_result(
                "c1", tool_name="search",
                output={"results": "complete result here"},
            ),
        ]
        trace = _make_trace(results=results)
        findings = analyzer._detect_truncation_without_hint(trace)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# 整合：analyze() 全量覆盖
# ---------------------------------------------------------------------------


class TestAnalyzeIntegration:
    def test_multiple_patterns_in_one_trace(self, analyzer):
        """一条 trace 触发多种 inefficiency pattern。"""
        calls = [
            _make_call("list_items", {"filter": "all"}, call_id="c1"),
        ]
        results = [
            _make_result(
                "c1", tool_name="list_items",
                output={
                    "items": list(range(30)),
                    "raw_blob": "x" * 2000,
                    "field_a": "a",
                    "field_b": "b",
                    "field_c": "c",
                    "field_d": "d",
                    "field_e": "e",
                },
            ),
        ]
        trace = _make_trace(
            calls=calls, results=results,
            final_answer="Items retrieved.",
        )
        findings = analyzer.analyze(trace)
        rule_types = {f.rule_type for f in findings}
        # 应触发 missing_pagination + missing_concise_mode + low_value_large_fields
        assert "context.missing_pagination" in rule_types
        assert "context.missing_concise_mode" in rule_types
        # 所有 finding 的 category 都是 "context"
        for f in findings:
            assert f.category == "context"
            assert f.rule_passed is False

    def test_clean_trace_no_findings(self, analyzer):
        """完全正常的 trace → 无 finding。"""
        calls = [
            _make_call("search", {"q": "error", "limit": 10}, call_id="c1"),
            _make_call("read", {"path": "/log"}, call_id="c2"),
        ]
        results = [
            _make_result(
                "c1", tool_name="search",
                output={"results": ["log.txt"], "summary": "1 match"},
            ),
            _make_result(
                "c2", tool_name="read",
                output={"content": "Error: disk full"},
            ),
        ]
        trace = _make_trace(
            calls=calls, results=results,
            final_answer="The error is a disk full issue in log.txt.",
        )
        findings = analyzer.analyze(trace)
        assert len(findings) == 0
