"""EvidenceCollector / EvidenceRef / ToolImprovementBrief 测试。"""

from dataclasses import FrozenInstanceError

import pytest

from agent_tool_harness.core_contract import RuleFinding
from agent_tool_harness.portfolio.improvement_brief import (
    EvidenceCollector,
    EvidenceRef,
    ToolImprovementBrief,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_finding(
    finding_id: str = "f-1",
    severity: str = "warning",
    message: str = "",
    evidence_ref: str = "",
    rule_type: str = "",
) -> RuleFinding:
    return RuleFinding(
        finding_id=finding_id,
        severity=severity,
        category="rule",
        message=message,
        evidence_ref=evidence_ref,
        rule_type=rule_type,
        rule_passed=False,
    )


class _MockMetrics:
    """最小 ReportMetrics mock。"""

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            object.__setattr__(self, k, v)


class _MockTaskOutcome:
    """最小 TaskOutcome mock。"""

    def __init__(self, case_id: str, details: str = "", verifier_results=None):
        self.case_id = case_id
        self.details = details
        self.verifier_results = verifier_results or []


class _MockVerifierResult:
    """最小 VerifierResult mock。"""

    def __init__(self, details: str = ""):
        self.details = details


# ---------------------------------------------------------------------------
# EvidenceRef
# ---------------------------------------------------------------------------


class TestEvidenceRef:
    """EvidenceRef 数据类测试。"""

    def test_default_construction(self):
        ref = EvidenceRef()
        assert ref.finding_ids == []
        assert ref.metric_values == {}
        assert ref.task_outcome_ids == []
        assert ref.transcript_signal_types == []

    def test_full_construction(self):
        ref = EvidenceRef(
            finding_ids=["f-1", "f-2"],
            metric_values={"tool_error_rate": 0.4},
            task_outcome_ids=["case-a"],
            transcript_signal_types=["repeated_retry"],
        )
        assert len(ref.finding_ids) == 2
        assert ref.metric_values["tool_error_rate"] == 0.4
        assert "case-a" in ref.task_outcome_ids
        assert "repeated_retry" in ref.transcript_signal_types

    def test_is_immutable(self):
        ref = EvidenceRef(finding_ids=["f-1"])
        with pytest.raises(FrozenInstanceError):
            ref.finding_ids = ["f-2"]  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ToolImprovementBrief
# ---------------------------------------------------------------------------


class TestToolImprovementBrief:
    """ToolImprovementBrief 数据类测试。"""

    def test_full_construction(self):
        evidence = EvidenceRef(finding_ids=["f-1"])
        brief = ToolImprovementBrief(
            tool_name="doc.search",
            priority="high",
            category="response",
            evidence=evidence,
            current_state="响应过大，无分页",
            recommended_state="默认 concise + 分页",
            rationale="减少上下文浪费",
            effort_estimate="small",
        )
        assert brief.tool_name == "doc.search"
        assert brief.priority == "high"
        assert brief.category == "response"
        assert brief.evidence == evidence
        assert brief.effort_estimate == "small"

    def test_is_immutable(self):
        brief = ToolImprovementBrief(
            tool_name="search",
            priority="medium",
            category="ergonomics",
            evidence=EvidenceRef(),
            current_state="名称不明确",
            recommended_state="改名",
            rationale="提升可发现性",
            effort_estimate="small",
        )
        with pytest.raises(FrozenInstanceError):
            brief.priority = "low"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# EvidenceCollector - collect_for_tool
# ---------------------------------------------------------------------------


class TestEvidenceCollectorForTool:
    """单工具证据收集。"""

    def test_collect_finding_ids_by_evidence_ref(self):
        """evidence_ref 含 tool_name → 收集 finding_id。"""
        findings = [
            _make_finding("f-1", evidence_ref="tool:search"),
            _make_finding("f-2", evidence_ref="tool:read"),
            _make_finding("f-3", evidence_ref="tool:search:c1"),
        ]
        collector = EvidenceCollector()
        result = collector.collect_for_tool("search", findings=findings)
        assert "f-1" in result.finding_ids
        assert "f-3" in result.finding_ids
        assert "f-2" not in result.finding_ids

    def test_collect_finding_ids_by_message(self):
        """evidence_ref 不含但 message 含 tool_name → 收集。"""
        findings = [
            _make_finding("f-1", message="search 工具响应过大"),
            _make_finding("f-2", message="read 工具无结果"),
        ]
        collector = EvidenceCollector()
        result = collector.collect_for_tool("search", findings=findings)
        assert "f-1" in result.finding_ids
        assert "f-2" not in result.finding_ids

    def test_collect_metric_values(self):
        """提取工具相关指标值。"""
        metrics = _MockMetrics(
            tool_error_rate=0.25,
            finding_count_by_tool={"search": 3, "read": 1},
            response_size_chars_by_tool={"search": 5000},
            orphan_call_count=2,
            repeated_tool_call_count=1,
        )
        collector = EvidenceCollector()
        result = collector.collect_for_tool("search", metrics=metrics)
        assert result.metric_values["tool_error_rate"] == 0.25
        assert result.metric_values["finding_count"] == 3.0
        assert result.metric_values["response_chars"] == 5000.0
        assert result.metric_values["orphan_call_count"] == 2.0

    def test_collect_metric_values_none_metrics(self):
        """metrics=None → 空 dict。"""
        collector = EvidenceCollector()
        result = collector.collect_for_tool("search", metrics=None)
        assert result.metric_values == {}

    def test_collect_task_outcome_ids(self):
        """details 含 tool_name → 收集 case_id。"""
        outcomes = [
            _MockTaskOutcome("case-1", details="使用了 search 工具"),
            _MockTaskOutcome(
                "case-2",
                verifier_results=[
                    _MockVerifierResult(details="search 验证通过"),
                ],
            ),
            _MockTaskOutcome("case-3", details="仅使用 read"),
        ]
        collector = EvidenceCollector()
        result = collector.collect_for_tool("search", task_outcomes=outcomes)
        assert "case-1" in result.task_outcome_ids
        assert "case-2" in result.task_outcome_ids
        assert "case-3" not in result.task_outcome_ids

    def test_collect_transcript_signals(self):
        """evidence_ref 含 tool_name → 收集 rule_type。"""
        signals = [
            _make_finding(
                "ts-1",
                rule_type="repeated_retry",
                evidence_ref="tool:search",
            ),
            _make_finding(
                "ts-2",
                rule_type="arg_micro_tuning",
                message="search 多次微调查询参数",
            ),
            _make_finding(
                "ts-3",
                rule_type="response_bloat",
                evidence_ref="tool:read",
            ),
        ]
        collector = EvidenceCollector()
        result = collector.collect_for_tool(
            "search", transcript_signals=signals,
        )
        assert "repeated_retry" in result.transcript_signal_types
        assert "arg_micro_tuning" in result.transcript_signal_types
        assert "response_bloat" not in result.transcript_signal_types

    def test_empty_inputs_return_empty_evidence(self):
        """全部为空 → 空 EvidenceRef。"""
        collector = EvidenceCollector()
        result = collector.collect_for_tool("search")
        assert result.finding_ids == []
        assert result.metric_values == {}
        assert result.task_outcome_ids == []
        assert result.transcript_signal_types == []


# ---------------------------------------------------------------------------
# EvidenceCollector - collect_cross_tool
# ---------------------------------------------------------------------------


class TestEvidenceCollectorCrossTool:
    """跨工具证据收集。"""

    def test_collect_cross_tool_from_portfolio_findings(self):
        """从 PortfolioFinding 列表生成 evidence 引用。"""
        from agent_tool_harness.portfolio.portfolio_review import PortfolioFinding

        pf = [
            PortfolioFinding(
                check_name="namespacing_consistency",
                severity="warning",
                affected_tools=["search", "read"],
                description="命名不规范",
                suggestion="添加 namespace",
            ),
        ]
        collector = EvidenceCollector()
        result = collector.collect_cross_tool(portfolio_findings=pf)
        assert "portfolio:namespacing_consistency" in result.finding_ids

    def test_collect_cross_tool_metrics(self):
        """提取跨工具级别指标。"""
        metrics = _MockMetrics(
            tool_error_rate=0.3,
            tool_call_count=50,
            unique_tool_count=8,
            orphan_call_count=5,
            judge_finding_count=2,
        )
        collector = EvidenceCollector()
        result = collector.collect_cross_tool(metrics=metrics)
        assert result.metric_values["tool_error_rate"] == 0.3
        assert result.metric_values["tool_call_count"] == 50.0
        assert result.metric_values["unique_tool_count"] == 8.0

    def test_collect_cross_tool_empty_inputs(self):
        """空输入 → 空 EvidenceRef。"""
        collector = EvidenceCollector()
        result = collector.collect_cross_tool()
        assert result.finding_ids == []
        assert result.metric_values == {}
