"""v3.5 P2: TranscriptPatternAnalyzer 测试。

覆盖 6 种 confusion pattern，每种 2-3 个场景。
"""

from __future__ import annotations

import pytest

from agent_tool_harness.analysis.transcript_pattern_analyzer import (
    TranscriptPatternAnalyzer,
)
from agent_tool_harness.core_contract import ExecutionTrace, ToolCall, ToolResult

# ---------------------------------------------------------------------------
# 辅助构造器
# ---------------------------------------------------------------------------


def _make_call(
    tool_name: str,
    arguments: dict | None = None,
    call_id: str = "",
    step: int = 0,
) -> ToolCall:
    """快速构造 ToolCall。"""
    cid = call_id or f"c{step}"
    return ToolCall(
        tool_name=tool_name,
        arguments=arguments or {},
        call_id=cid,
        timestamp=f"2026-05-17T00:00:{step:02d}Z",
    )


def _make_result(
    call_id: str,
    tool_name: str = "",
    status: str = "success",
    output: dict | None = None,
    error: str | None = None,
) -> ToolResult:
    """快速构造 ToolResult。"""
    return ToolResult(
        call_id=call_id,
        tool_name=tool_name,
        status=status,
        output=output or {},
        error=error,
    )


def _make_trace(
    calls: list[ToolCall] | None = None,
    results: list[ToolResult] | None = None,
    final_answer: str = "",
) -> ExecutionTrace:
    """快速构造 ExecutionTrace。"""
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
def analyzer() -> TranscriptPatternAnalyzer:
    return TranscriptPatternAnalyzer()


# ---------------------------------------------------------------------------
# 1. repeated_tool_retry_loop
# ---------------------------------------------------------------------------


class TestRepeatedRetry:
    def test_three_identical_calls_detected(self, analyzer):
        """同一 tool+args 连续 3 次 → 检测到。"""
        calls = [
            _make_call("search", {"q": "bug"}, step=1),
            _make_call("search", {"q": "bug"}, step=2),
            _make_call("search", {"q": "bug"}, step=3),
        ]
        trace = _make_trace(calls=calls)
        findings = analyzer._detect_repeated_retry(trace)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_type == "transcript.repeated_tool_retry_loop"
        assert f.severity == "high"
        assert f.rule_passed is False
        assert "search" in f.message
        assert "3" in f.message

    def test_four_identical_calls_single_finding(self, analyzer):
        """连续 4 次相同 → 1 个 finding，范围覆盖全部 4 次。"""
        calls = [
            _make_call("read", {"path": "/x"}, step=1),
            _make_call("read", {"path": "/x"}, step=2),
            _make_call("read", {"path": "/x"}, step=3),
            _make_call("read", {"path": "/x"}, step=4),
        ]
        trace = _make_trace(calls=calls)
        findings = analyzer._detect_repeated_retry(trace)
        assert len(findings) == 1
        assert "4" in findings[0].message

    def test_different_args_not_detected(self, analyzer):
        """同一 tool 但不同 args → 不检测。"""
        calls = [
            _make_call("search", {"q": "bug"}, step=1),
            _make_call("search", {"q": "bug"}, step=2),
            _make_call("search", {"q": "error"}, step=3),
        ]
        trace = _make_trace(calls=calls)
        findings = analyzer._detect_repeated_retry(trace)
        assert len(findings) == 0

    def test_less_than_three_calls(self, analyzer):
        """少于 3 次调用 → 不检测。"""
        trace = _make_trace(calls=[
            _make_call("search", {"q": "a"}, step=1),
            _make_call("search", {"q": "a"}, step=2),
        ])
        findings = analyzer._detect_repeated_retry(trace)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# 2. tool_switching_confusion
# ---------------------------------------------------------------------------


class TestToolSwitchingConfusion:
    def test_ab_alternation_detected(self, analyzer):
        """search → read → search → read → 检测为切换困惑。"""
        calls = [
            _make_call("search", {"q": "x"}, call_id="c1", step=1),
            _make_call("read", {"path": "/a"}, call_id="c2", step=2),
            _make_call("search", {"q": "y"}, call_id="c3", step=3),
            _make_call("read", {"path": "/b"}, call_id="c4", step=4),
        ]
        trace = _make_trace(calls=calls)
        findings = analyzer._detect_tool_switching_confusion(trace)
        assert len(findings) >= 1
        f = findings[0]
        assert f.rule_type == "transcript.tool_switching_confusion"
        assert f.severity == "medium"

    def test_abc_pattern_detected(self, analyzer):
        """A→B→C→A→B→C 三工具交替。"""
        calls = [
            _make_call("search", call_id="c1", step=1),
            _make_call("read", call_id="c2", step=2),
            _make_call("grep", call_id="c3", step=3),
            _make_call("search", call_id="c4", step=4),
            _make_call("read", call_id="c5", step=5),
            _make_call("grep", call_id="c6", step=6),
        ]
        trace = _make_trace(calls=calls)
        findings = analyzer._detect_tool_switching_confusion(trace)
        assert len(findings) >= 1

    def test_no_switching_normal_sequence(self, analyzer):
        """正常线性调用 → 不检测。"""
        calls = [
            _make_call("search", call_id="c1", step=1),
            _make_call("read", call_id="c2", step=2),
            _make_call("write", call_id="c3", step=3),
        ]
        trace = _make_trace(calls=calls)
        findings = analyzer._detect_tool_switching_confusion(trace)
        assert len(findings) == 0

    def test_less_than_four_calls(self, analyzer):
        """少于 4 次调用 → 不检测。"""
        trace = _make_trace(calls=[
            _make_call("search", call_id="c1", step=1),
            _make_call("read", call_id="c2", step=2),
            _make_call("search", call_id="c3", step=3),
        ])
        findings = analyzer._detect_tool_switching_confusion(trace)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# 3. invalid_arg_retry
# ---------------------------------------------------------------------------


class TestInvalidArgRetry:
    def test_single_char_change_detected(self, analyzer):
        """同一 tool，仅 query 参数改了一个字符 → 检测。"""
        calls = [
            _make_call("search", {"query": "find bugs"}, step=1),
            _make_call("search", {"query": "find bug"}, step=2),
        ]
        trace = _make_trace(calls=calls)
        findings = analyzer._detect_invalid_arg_retry(trace)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_type == "transcript.invalid_arg_retry"
        assert f.severity == "high"
        assert "search" in f.message

    def test_different_tools_not_detected(self, analyzer):
        """不同 tool → 不检测为 invalid arg retry。"""
        calls = [
            _make_call("search", {"q": "x"}, step=1),
            _make_call("read", {"q": "x"}, step=2),
        ]
        trace = _make_trace(calls=calls)
        findings = analyzer._detect_invalid_arg_retry(trace)
        assert len(findings) == 0

    def test_multiple_keys_changed_not_detected(self, analyzer):
        """多个 key 值都改变 → 相似度低 → 不检测。"""
        calls = [
            _make_call("search", {"q": "x", "limit": 5}, step=1),
            _make_call("search", {"q": "y", "limit": 50}, step=2),
        ]
        trace = _make_trace(calls=calls)
        findings = analyzer._detect_invalid_arg_retry(trace)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# 4. no_recovery_after_error
# ---------------------------------------------------------------------------


class TestNoRecoveryAfterError:
    def test_error_then_no_more_calls(self, analyzer):
        """error 后没有更多 tool call → 检测。"""
        calls = [
            _make_call("search", {"q": "x"}, call_id="c1", step=1),
        ]
        results = [
            _make_result("c1", tool_name="search", status="error", error="timeout"),
        ]
        trace = _make_trace(calls=calls, results=results)
        findings = analyzer._detect_no_recovery_after_error(trace)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_type == "transcript.no_recovery_after_error"
        assert f.severity == "high"

    def test_error_with_immediate_retry(self, analyzer):
        """error 后立刻重试同一 tool → 不检测（有恢复）。"""
        calls = [
            _make_call("search", {"q": "x"}, call_id="c1", step=1),
            _make_call("search", {"q": "x"}, call_id="c2", step=2),
        ]
        results = [
            _make_result("c1", tool_name="search", status="error", error="timeout"),
            _make_result("c2", tool_name="search", status="success", output={"data": "ok"}),
        ]
        trace = _make_trace(calls=calls, results=results)
        findings = analyzer._detect_no_recovery_after_error(trace)
        assert len(findings) == 0

    def test_success_result_not_detected(self, analyzer):
        """success 状态 → 不检测。"""
        calls = [
            _make_call("search", {"q": "x"}, call_id="c1", step=1),
        ]
        results = [
            _make_result("c1", tool_name="search", status="success", output={"data": "ok"}),
        ]
        trace = _make_trace(calls=calls, results=results)
        findings = analyzer._detect_no_recovery_after_error(trace)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# 5. final_answer_without_support
# ---------------------------------------------------------------------------


class TestFinalAnswerWithoutSupport:
    def test_no_tool_results_with_answer(self, analyzer):
        """有 final answer 但无 tool results → critical。"""
        trace = _make_trace(calls=[], results=[], final_answer="The root cause is a null pointer.")
        findings = analyzer._detect_final_answer_without_support(trace)
        assert len(findings) == 1
        f = findings[0]
        assert f.severity == "critical"
        assert f.rule_type == "transcript.final_answer_without_support"

    def test_answer_supported_by_output(self, analyzer):
        """final answer 内容全部在 tool output 中出现 → 不检测。"""
        results = [
            _make_result(
                "c1", tool_name="search",
                output={"data": "null pointer exception found in main module"},
            ),
        ]
        trace = _make_trace(
            calls=[_make_call("search", call_id="c1", step=1)],
            results=results,
            final_answer="The root cause is a null pointer exception.",
        )
        findings = analyzer._detect_final_answer_without_support(trace)
        assert len(findings) == 0

    def test_answer_with_unmatched_terms(self, analyzer):
        """final answer 包含大量 tool output 中不存在的词 → 检测。"""
        results = [
            _make_result("c1", tool_name="search", output={"data": "server started successfully"}),
        ]
        trace = _make_trace(
            calls=[_make_call("search", call_id="c1", step=1)],
            results=results,
            final_answer=(
                "The database connection failed because the authentication module "
                "encountered certificate verification problems during initialization"
            ),
        )
        findings = analyzer._detect_final_answer_without_support(trace)
        assert len(findings) == 1

    def test_empty_final_answer(self, analyzer):
        """空 final answer → 不检测。"""
        trace = _make_trace(calls=[], results=[], final_answer="")
        findings = analyzer._detect_final_answer_without_support(trace)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# 6. broad_search_loop
# ---------------------------------------------------------------------------


class TestBroadSearchLoop:
    def test_query_shortening_detected(self, analyzer):
        """query 越来越短 → 检测为搜索范围扩大。"""
        calls = [
            _make_call(
                "search",
                {"query": "null pointer exception in authentication module"},
                step=1,
            ),
            _make_call("search", {"query": "null pointer exception"}, step=2),
            _make_call("search", {"query": "error"}, step=3),
        ]
        trace = _make_trace(calls=calls)
        findings = analyzer._detect_broad_search_loop(trace)
        assert len(findings) == 1
        f = findings[0]
        assert f.rule_type == "transcript.broad_search_loop"
        assert f.severity == "medium"

    def test_limit_increasing_detected(self, analyzer):
        """limit 递增 → 检测。"""
        calls = [
            _make_call("list_files", {"limit": 5}, step=1),
            _make_call("list_files", {"limit": 10}, step=2),
            _make_call("list_files", {"limit": 50}, step=3),
        ]
        trace = _make_trace(calls=calls)
        findings = analyzer._detect_broad_search_loop(trace)
        assert len(findings) == 1

    def test_query_not_monotonic(self, analyzer):
        """query 长度非单调变化 → 不检测。"""
        calls = [
            _make_call("search", {"query": "short"}, step=1),
            _make_call("search", {"query": "much longer query here"}, step=2),
            _make_call("search", {"query": "x"}, step=3),
        ]
        trace = _make_trace(calls=calls)
        findings = analyzer._detect_broad_search_loop(trace)
        assert len(findings) == 0

    def test_less_than_three_calls(self, analyzer):
        """少于 3 次 → 不检测。"""
        calls = [
            _make_call("search", {"query": "big"}, step=1),
            _make_call("search", {"query": "sm"}, step=2),
        ]
        trace = _make_trace(calls=calls)
        findings = analyzer._detect_broad_search_loop(trace)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# 整合：analyze() 全量覆盖
# ---------------------------------------------------------------------------


class TestAnalyzeIntegration:
    def test_analyze_all_patterns_in_one_trace(self, analyzer):
        """一条 trace 中同时触发多种 pattern。"""
        calls = [
            _make_call("search", {"q": "x"}, call_id="c1", step=1),
            _make_call("search", {"q": "x"}, call_id="c2", step=2),
            _make_call("search", {"q": "x"}, call_id="c3", step=3),  # repeated_retry
            _make_call("read", {"path": "/a"}, call_id="c4", step=4),
            _make_call("search", {"q": "bug"}, call_id="c5", step=5),  # switching
            _make_call("read", {"path": "/b"}, call_id="c6", step=6),  # switching
        ]
        results = [
            _make_result("c1", tool_name="search", status="success", output={"data": "ok"}),
            _make_result("c2", tool_name="search", status="success", output={"data": "ok"}),
            _make_result("c3", tool_name="search", status="success", output={"data": "ok"}),
            _make_result("c4", tool_name="read", status="success", output={"data": "ok"}),
            _make_result("c5", tool_name="search", status="success", output={"data": "ok"}),
            _make_result("c6", tool_name="read", status="success", output={"data": "ok"}),
        ]
        trace = _make_trace(
            calls=calls,
            results=results,
            final_answer="found it",
        )
        findings = analyzer.analyze(trace)
        # 至少触发 repeated_retry 和 switching
        rule_types = {f.rule_type for f in findings}
        assert "transcript.repeated_tool_retry_loop" in rule_types
        assert "transcript.tool_switching_confusion" in rule_types
        # 所有 finding 都是 RuleFinding，category="transcript"
        for f in findings:
            assert f.category == "transcript"
            assert f.rule_passed is False

    def test_clean_trace_no_findings(self, analyzer):
        """完全正常的 trace → 无 finding。"""
        calls = [
            _make_call("search", {"q": "error"}, call_id="c1", step=1),
            _make_call("read", {"path": "/log"}, call_id="c2", step=2),
            _make_call("write", {"path": "/fix", "content": "patch"}, call_id="c3", step=3),
        ]
        results = [
            _make_result(
                "c1", tool_name="search", status="success",
                output={"results": ["log.txt"]},
            ),
            _make_result(
                "c2", tool_name="read", status="success",
                output={"content": "error details here"},
            ),
            _make_result(
                "c3", tool_name="write", status="success",
                output={"written": True},
            ),
        ]
        trace = _make_trace(
            calls=calls,
            results=results,
            final_answer="The error was found in log.txt and has been fixed.",
        )
        findings = analyzer.analyze(trace)
        assert len(findings) == 0
