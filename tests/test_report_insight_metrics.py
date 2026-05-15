"""P1 MetricsCollector 测试。

覆盖 15+ 场景：空 trace、正常 trace、错误、孤立调用/返回、重复调用、
响应大小、token 估算、finding 分桶、除零保护、边界条件。
"""

from __future__ import annotations

import json

import pytest

from agent_tool_harness.core_contract import (
    EvaluationResult,
    ExecutionTrace,
    Finding,
    JudgeFinding,
    RuleFinding,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.reports.report_insight import MetricsCollector, ReportMetrics

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_tool_call(
    tool_name: str = "search",
    arguments: dict | None = None,
    call_id: str = "c1",
) -> ToolCall:
    return ToolCall(
        tool_name=tool_name,
        arguments=arguments or {"query": "test"},
        call_id=call_id,
    )


def _make_tool_result(
    call_id: str = "c1",
    tool_name: str = "search",
    status: str = "success",
    output: dict | None = None,
    error: str | None = None,
) -> ToolResult:
    return ToolResult(
        call_id=call_id,
        tool_name=tool_name,
        status=status,
        output=output or {"result": "ok"},
        error=error,
    )


def _make_rule_finding(
    finding_id: str = "tool_response.output.low_signal::search",
    severity: str = "high",
    rule_type: str = "tool_response.output.low_signal",
    rule_passed: bool = False,
    message: str = "",
    evidence_ref: str = "tool_calls.jsonl::call_id=c1",
) -> RuleFinding:
    return RuleFinding(
        finding_id=finding_id,
        severity=severity,
        category="rule",
        message=message or "工具 'search' 输出信号过低",
        evidence_ref=evidence_ref,
        rule_type=rule_type,
        rule_passed=rule_passed,
    )


def _make_judge_finding(
    finding_id: str = "judge_001",
    severity: str = "medium",
    message: str = "LLM judge 认为输出质量一般",
) -> JudgeFinding:
    return JudgeFinding(
        finding_id=finding_id,
        severity=severity,
        category="judge",
        message=message,
        evidence_ref="tool_calls.jsonl::call_id=c1",
        provider="openai-native",
        model="gpt-4o",
        confidence=0.7,
        rationale="输出缺少上下文信息",
        rubric="response_quality",
    )


# ---------------------------------------------------------------------------
# 测试 1: 空 trace
# ---------------------------------------------------------------------------


class TestEmptyTrace:
    def test_all_counts_zero(self):
        """空 trace（无 tool_calls，无 tool_results）→ 所有 count 为 0，rate 为 0.0。"""
        trace = ExecutionTrace(scenario_id="s1")
        eval_result = EvaluationResult(scenario_id="s1")

        collector = MetricsCollector()
        m = collector.collect(trace, eval_result)

        assert m.tool_call_count == 0
        assert m.tool_result_count == 0
        assert m.unique_tool_count == 0
        assert m.tool_success_count == 0
        assert m.tool_error_count == 0
        assert m.tool_error_rate == 0.0
        assert m.orphan_call_count == 0
        assert m.orphan_result_count == 0
        assert m.repeated_tool_call_count == 0
        assert m.response_size_chars_total == 0
        assert m.response_size_chars_by_tool == {}
        assert m.estimated_response_tokens_total == 0
        assert m.finding_count_by_severity == {}
        assert m.finding_count_by_category == {}
        assert m.finding_count_by_tool == {}
        assert m.judge_finding_count == 0

    def test_frozen_dataclass(self):
        """ReportMetrics 为 frozen=True，不可原地修改。"""
        m = ReportMetrics()
        with pytest.raises(AttributeError):
            m.tool_call_count = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 测试 2: 正常 trace
# ---------------------------------------------------------------------------


class TestNormalTrace:
    def test_all_success(self):
        """正常 trace：3 calls，3 results，全部 success。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[
                _make_tool_call("search", {"q": "a"}, "c1"),
                _make_tool_call("read", {"path": "f"}, "c2"),
                _make_tool_call("write", {"path": "f", "content": "x"}, "c3"),
            ],
            tool_results=[
                _make_tool_result("c1", "search", "success"),
                _make_tool_result("c2", "read", "success"),
                _make_tool_result("c3", "write", "success"),
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        collector = MetricsCollector()
        m = collector.collect(trace, eval_result)

        assert m.tool_call_count == 3
        assert m.tool_result_count == 3
        assert m.unique_tool_count == 3
        assert m.tool_success_count == 3
        assert m.tool_error_count == 0
        assert m.tool_error_rate == 0.0
        assert m.orphan_call_count == 0
        assert m.orphan_result_count == 0


# ---------------------------------------------------------------------------
# 测试 3: 含 error 的 trace
# ---------------------------------------------------------------------------


class TestErrorTrace:
    def test_mixed_success_error(self):
        """含 error 的 trace → tool_error_count>0, tool_error_rate>0。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[
                _make_tool_call("search", call_id="c1"),
                _make_tool_call("read", call_id="c2"),
                _make_tool_call("write", call_id="c3"),
                _make_tool_call("delete", call_id="c4"),
            ],
            tool_results=[
                _make_tool_result("c1", "search", "success"),
                _make_tool_result("c2", "read", "error", error="not found"),
                _make_tool_result("c3", "write", "success"),
                _make_tool_result("c4", "delete", "error", error="permission denied"),
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.tool_call_count == 4
        assert m.tool_success_count == 2
        assert m.tool_error_count == 2
        assert m.tool_error_rate == 0.5
        # tool_success_count 只看 status，不检查 output
        # 即使 output 为空字典，status=="success" 即计入


# ---------------------------------------------------------------------------
# 测试 4: 孤立调用
# ---------------------------------------------------------------------------


class TestOrphanCall:
    def test_call_without_result(self):
        """call 无对应 result → orphan_call_count>0。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[
                _make_tool_call("search", call_id="c1"),
                _make_tool_call("read", call_id="c2"),
                _make_tool_call("write", call_id="c3"),
            ],
            tool_results=[
                _make_tool_result("c1", "search", "success"),
                # c2, c3 无 result
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.tool_call_count == 3
        assert m.tool_result_count == 1
        assert m.orphan_call_count == 2  # c2, c3
        assert m.orphan_result_count == 0


# ---------------------------------------------------------------------------
# 测试 5: 孤立返回
# ---------------------------------------------------------------------------


class TestOrphanResult:
    def test_result_without_call(self):
        """result 无对应 call → orphan_result_count>0。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[
                _make_tool_call("search", call_id="c1"),
            ],
            tool_results=[
                _make_tool_result("c1", "search", "success"),
                _make_tool_result("c2", "read", "success"),  # 无对应 call
                _make_tool_result("c3", "write", "success"),  # 无对应 call
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.orphan_call_count == 0
        assert m.orphan_result_count == 2  # c2, c3


# ---------------------------------------------------------------------------
# 测试 6: 重复调用
# ---------------------------------------------------------------------------


class TestRepeatedToolCall:
    def test_identical_args_repeated(self):
        """相同 tool_name + 相同 arguments 出现多次 → 计入重复。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[
                _make_tool_call("search", {"q": "x"}, "c1"),
                _make_tool_call("search", {"q": "x"}, "c2"),  # 重复
                _make_tool_call("search", {"q": "x"}, "c3"),  # 重复
                _make_tool_call("search", {"q": "y"}, "c4"),  # 不同参数
            ],
            tool_results=[
                _make_tool_result("c1", "search"),
                _make_tool_result("c2", "search"),
                _make_tool_result("c3", "search"),
                _make_tool_result("c4", "search"),
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        # search+"q=x" 出现 3 次 → 计数 3
        assert m.repeated_tool_call_count == 3

    def test_no_repeats(self):
        """无重复调用 → repeated_tool_call_count=0。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[
                _make_tool_call("search", {"q": "a"}, "c1"),
                _make_tool_call("read", {"path": "f"}, "c2"),
            ],
            tool_results=[
                _make_tool_result("c1", "search"),
                _make_tool_result("c2", "read"),
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)
        assert m.repeated_tool_call_count == 0

    def test_nested_args_stable_serialization(self):
        """嵌套 dict/list 参数的重复检测：json.dumps(sort_keys=True) 保证稳定。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[
                _make_tool_call(
                    "search",
                    {"filters": [{"field": "name", "op": "eq"}], "limit": 10},
                    "c1",
                ),
                _make_tool_call(
                    "search",
                    {"limit": 10, "filters": [{"op": "eq", "field": "name"}]},
                    "c2",
                ),
            ],
            tool_results=[
                _make_tool_result("c1", "search"),
                _make_tool_result("c2", "search"),
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)
        # sort_keys=True 让不同 key 顺序的等价 dict 被检测为重复
        assert m.repeated_tool_call_count == 2


# ---------------------------------------------------------------------------
# 测试 7: response_size_chars_total
# ---------------------------------------------------------------------------


class TestResponseSize:
    def test_chars_total(self):
        """response_size_chars_total 应为所有 tool_result.output 的 JSON 长度之和。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[
                _make_tool_call("s", call_id="c1"),
                _make_tool_call("r", call_id="c2"),
            ],
            tool_results=[
                _make_tool_result("c1", "s", output={"a": 1, "b": 2}),
                _make_tool_result("c2", "r", output={"data": "hello"}),
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        expected = len(json.dumps({"a": 1, "b": 2})) + len(
            json.dumps({"data": "hello"})
        )
        assert m.response_size_chars_total == expected

    def test_unserializable_output_fallback(self):
        """包含不可 JSON 序列化对象的 output → 退避为 str()。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[_make_tool_call("s", call_id="c1")],
            tool_results=[
                ToolResult(
                    call_id="c1",
                    tool_name="s",
                    status="success",
                    # 包含 bytes，json.dumps 会抛 TypeError
                    output={"data": b"binary"},  # type: ignore[dict-item]
                )
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)
        # 不应抛异常
        assert m.response_size_chars_total > 0


# ---------------------------------------------------------------------------
# 测试 8: response_size_chars_by_tool
# ---------------------------------------------------------------------------


class TestResponseSizeByTool:
    def test_grouped_by_tool(self):
        """response_size_chars_by_tool 按 tool_name 分组正确。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[
                _make_tool_call("search", call_id="c1"),
                _make_tool_call("search", call_id="c2"),
                _make_tool_call("read", call_id="c3"),
            ],
            tool_results=[
                _make_tool_result("c1", "search", output={"r": "a"}),
                _make_tool_result("c2", "search", output={"r": "bb"}),
                _make_tool_result("c3", "read", output={"data": "ccc"}),
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert "search" in m.response_size_chars_by_tool
        assert "read" in m.response_size_chars_by_tool
        # 各 tool 的 value 之和应等于 total
        assert sum(m.response_size_chars_by_tool.values()) == m.response_size_chars_total


# ---------------------------------------------------------------------------
# 测试 9: estimated_response_tokens_total
# ---------------------------------------------------------------------------


class TestTokenEstimate:
    def test_chars_div_4(self):
        """estimated_response_tokens_total = response_size_chars_total // 4。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[_make_tool_call("s", call_id="c1")],
            tool_results=[
                _make_tool_result("c1", "s", output={"data": "x" * 100})
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.estimated_response_tokens_total == m.response_size_chars_total // 4


# ---------------------------------------------------------------------------
# 测试 10: finding_count_by_severity
# ---------------------------------------------------------------------------


class TestFindingCountBySeverity:
    def test_mixed_severity(self):
        """finding_count_by_severity 统计正确。"""
        findings = [
            _make_rule_finding("f1", severity="critical"),
            _make_rule_finding("f2", severity="high"),
            _make_rule_finding("f3", severity="high"),
            _make_rule_finding("f4", severity="medium"),
            _make_rule_finding("f5", severity="low"),
            _make_rule_finding("f6", severity="info"),
        ]
        eval_result = EvaluationResult(
            scenario_id="s1", findings=findings  # type: ignore[arg-type]
        )
        trace = ExecutionTrace(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.finding_count_by_severity == {
            "critical": 1,
            "high": 2,
            "medium": 1,
            "low": 1,
            "info": 1,
        }

    def test_empty_findings(self):
        """eval_result.findings 为空 → 所有 finding_count_* 为空 dict。"""
        trace = ExecutionTrace(scenario_id="s1")
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.finding_count_by_severity == {}
        assert m.finding_count_by_category == {}
        assert m.finding_count_by_tool == {}
        assert m.judge_finding_count == 0


# ---------------------------------------------------------------------------
# 测试 11: finding_count_by_category（含 rule_id prefix 子类别）
# ---------------------------------------------------------------------------


class TestFindingCountByCategory:
    def test_rule_prefix_subcategories(self):
        """Rule finding 按 rule_type prefix 分子类别。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_response.output.low_signal"),
            _make_rule_finding("f2", rule_type="tool_response.error.actionable"),
            _make_rule_finding("f3", rule_type="tool_response.output.size_reasonable"),
            _make_rule_finding("f4", rule_type="tool_spec.description.exists"),
            _make_rule_finding("f5", rule_type="tool_spec.description.useful_length"),
        ]
        eval_result = EvaluationResult(
            scenario_id="s1", findings=findings  # type: ignore[arg-type]
        )
        trace = ExecutionTrace(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.finding_count_by_category["tool_response"] == 3
        assert m.finding_count_by_category["tool_spec"] == 2

    def test_judge_category(self):
        """JudgeFinding → category="judge"。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_spec.description.exists"),
            _make_judge_finding("f2"),
            _make_judge_finding("f3"),
        ]
        eval_result = EvaluationResult(
            scenario_id="s1", findings=findings  # type: ignore[arg-type]
        )
        trace = ExecutionTrace(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.finding_count_by_category["tool_spec"] == 1
        assert m.finding_count_by_category["judge"] == 2

    def test_rule_without_prefix_fallback(self):
        """rule_type 无 dot → 整个 rule_type 作为 category。"""
        f = RuleFinding(
            finding_id="f1",
            severity="high",
            category="rule",
            message="test",
            evidence_ref="ref",
            rule_type="some_flat_rule",
        )
        eval_result = EvaluationResult(
            scenario_id="s1", findings=[f]  # type: ignore[arg-type]
        )
        trace = ExecutionTrace(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.finding_count_by_category["some_flat_rule"] == 1

    def test_rule_without_rule_type_fallback(self):
        """rule_type 为空字符串 → 归入 "rule" category。"""
        f = RuleFinding(
            finding_id="f1",
            severity="medium",
            category="rule",
            message="test",
            evidence_ref="ref",
            rule_type="",
        )
        eval_result = EvaluationResult(
            scenario_id="s1", findings=[f]  # type: ignore[arg-type]
        )
        trace = ExecutionTrace(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.finding_count_by_category["rule"] == 1

    def test_audit_signal_defensive_buckets(self):
        """category="audit" 或 "signal" → 防御性分桶。"""
        f_audit = Finding(
            finding_id="f1",
            severity="low",
            category="audit",
            message="audit note",
            evidence_ref="ref",
        )
        f_signal = Finding(
            finding_id="f2",
            severity="info",
            category="signal",
            message="signal note",
            evidence_ref="ref",
        )
        eval_result = EvaluationResult(
            scenario_id="s1", findings=[f_audit, f_signal]
        )
        trace = ExecutionTrace(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.finding_count_by_category["audit"] == 1
        assert m.finding_count_by_category["signal"] == 1


# ---------------------------------------------------------------------------
# 测试 12: finding_count_by_tool
# ---------------------------------------------------------------------------


class TestFindingCountByTool:
    def test_from_finding_id_with_double_colon(self):
        """finding_id 格式 rule_type::tool_name → 提取 tool_name。"""
        f = _make_rule_finding(
            finding_id="tool_response.output.low_signal::search_documents",
            rule_type="tool_response.output.low_signal",
        )
        eval_result = EvaluationResult(
            scenario_id="s1", findings=[f]  # type: ignore[arg-type]
        )
        trace = ExecutionTrace(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.finding_count_by_tool["search_documents"] == 1

    def test_from_evidence_ref_call_id(self):
        """finding_id 无 tool_name → 从 evidence_ref 提取。"""
        f = _make_rule_finding(
            finding_id="tool_response.output.low_signal",
            evidence_ref="tool_calls.jsonl::call_id=read_file_001",
            rule_type="tool_response.output.low_signal",
        )
        eval_result = EvaluationResult(
            scenario_id="s1", findings=[f]  # type: ignore[arg-type]
        )
        trace = ExecutionTrace(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.finding_count_by_tool["read_file"] == 1

    def test_from_message_quoted_tool_name(self):
        """从 message 中单引号包裹的工具名提取。"""
        f = _make_rule_finding(
            finding_id="tool_response.output.low_signal",
            evidence_ref="ref",
            message="工具 'write_file' 的输出信号过低",
            rule_type="tool_response.output.low_signal",
        )
        eval_result = EvaluationResult(
            scenario_id="s1", findings=[f]  # type: ignore[arg-type]
        )
        trace = ExecutionTrace(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.finding_count_by_tool["write_file"] == 1

    def test_unknown_fallback(self):
        """所有策略都无法提取 → "(unknown)"。"""
        f = _make_rule_finding(
            finding_id="some_generic_id",
            evidence_ref="some_ref",
            message="no tool name here",
            rule_type="tool_response.output.low_signal",
        )
        eval_result = EvaluationResult(
            scenario_id="s1", findings=[f]  # type: ignore[arg-type]
        )
        trace = ExecutionTrace(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.finding_count_by_tool["(unknown)"] == 1

    def test_multiple_tools_aggregated(self):
        """多个 finding 按 tool_name 正确聚合。"""
        findings = [
            _make_rule_finding(
                finding_id="f1::search", rule_type="tool_response.output.low_signal"
            ),
            _make_rule_finding(
                finding_id="f2::search", rule_type="tool_response.error.actionable"
            ),
            _make_rule_finding(
                finding_id="f3::read", rule_type="tool_spec.description.exists"
            ),
        ]
        eval_result = EvaluationResult(
            scenario_id="s1", findings=findings  # type: ignore[arg-type]
        )
        trace = ExecutionTrace(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.finding_count_by_tool["search"] == 2
        assert m.finding_count_by_tool["read"] == 1


# ---------------------------------------------------------------------------
# 测试 13: judge_finding_count
# ---------------------------------------------------------------------------


class TestJudgeFindingCount:
    def test_judge_count(self):
        """judge_finding_count = category=="judge" 的 finding 数。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_spec.description.exists"),
            _make_rule_finding("f2", rule_type="tool_response.output.low_signal"),
            _make_judge_finding("f3"),
        ]
        eval_result = EvaluationResult(
            scenario_id="s1", findings=findings  # type: ignore[arg-type]
        )
        trace = ExecutionTrace(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.judge_finding_count == 1

    def test_no_judge_findings(self):
        """全部为 rule finding → judge_finding_count=0。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_spec.description.exists"),
            _make_rule_finding("f2", rule_type="tool_response.output.low_signal"),
        ]
        eval_result = EvaluationResult(
            scenario_id="s1", findings=findings  # type: ignore[arg-type]
        )
        trace = ExecutionTrace(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)
        assert m.judge_finding_count == 0


# ---------------------------------------------------------------------------
# 测试 14: tool_error_rate 除零保护
# ---------------------------------------------------------------------------


class TestErrorRateDivideByZero:
    def test_zero_calls_zero_rate(self):
        """tool_call_count=0 → tool_error_rate=0.0（除零保护）。"""
        trace = ExecutionTrace(scenario_id="s1")
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert m.tool_call_count == 0
        assert m.tool_error_rate == 0.0

    def test_correct_rate_calculation(self):
        """正常错误率计算：2 error / 4 calls = 0.5。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[
                _make_tool_call("s", call_id="c1"),
                _make_tool_call("s", call_id="c2"),
                _make_tool_call("s", call_id="c3"),
                _make_tool_call("s", call_id="c4"),
            ],
            tool_results=[
                _make_tool_result("c1", "s", "error"),
                _make_tool_result("c2", "s", "success"),
                _make_tool_result("c3", "s", "error"),
                _make_tool_result("c4", "s", "success"),
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)
        assert m.tool_error_rate == 0.5


# ---------------------------------------------------------------------------
# 测试 15: tool_name 为空字符串 → "(unknown)" bucket
# ---------------------------------------------------------------------------


class TestEmptyToolName:
    def test_empty_tool_name_in_response_size(self):
        """tool_name 为空字符串 → response_size_chars_by_tool 归入 "(unknown)"。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[_make_tool_call("", call_id="c1")],
            tool_results=[
                ToolResult(
                    call_id="c1",
                    tool_name="",
                    status="success",
                    output={"data": "test"},
                )
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)

        assert "(unknown)" in m.response_size_chars_by_tool
        assert m.response_size_chars_by_tool["(unknown)"] > 0

    def test_empty_tool_name_in_unique_count(self):
        """空字符串 tool_name 也计入 unique_tool_count。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[
                _make_tool_call("search", call_id="c1"),
                _make_tool_call("", call_id="c2"),
            ],
            tool_results=[
                _make_tool_result("c1", "search"),
                _make_tool_result("c2", ""),
            ],
        )
        eval_result = EvaluationResult(scenario_id="s1")

        m = MetricsCollector().collect(trace, eval_result)
        assert m.unique_tool_count == 2  # "search" + ""


# ---------------------------------------------------------------------------
# 回归测试：现有对象不被修改
# ---------------------------------------------------------------------------


class TestImmutabilityOfInputs:
    def test_trace_not_modified(self):
        """MetricsCollector.collect() 不修改传入的 trace。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_calls=[_make_tool_call("search", call_id="c1")],
            tool_results=[_make_tool_result("c1", "search")],
        )
        original_call_count = len(trace.tool_calls)
        original_result_count = len(trace.tool_results)

        eval_result = EvaluationResult(scenario_id="s1")
        MetricsCollector().collect(trace, eval_result)

        assert len(trace.tool_calls) == original_call_count
        assert len(trace.tool_results) == original_result_count

    def test_eval_result_not_modified(self):
        """MetricsCollector.collect() 不修改传入的 eval_result。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_response.output.low_signal")
        ]
        eval_result = EvaluationResult(
            scenario_id="s1", findings=findings  # type: ignore[arg-type]
        )
        original_finding_count = len(eval_result.findings)

        trace = ExecutionTrace(scenario_id="s1")
        MetricsCollector().collect(trace, eval_result)

        assert len(eval_result.findings) == original_finding_count
