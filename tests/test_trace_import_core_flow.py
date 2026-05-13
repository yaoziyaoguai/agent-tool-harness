"""Trace Import → Core Flow 端到端测试。

验证唯一接入路径的完整闭环：
TraceImportAdapter → ExecutionTrace → Evidence → CoreEvaluation → EvaluationResult → Report

架构边界:
- 所有测试 zero-network, deterministic.
- 不读取 .env, 不调用外部 API.
- ReviewDecision 不由机器自动生成.
- JudgeFinding 为 advisory only，不改变 passed.
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.core_contract import (
    EvaluationResult,
    Evidence,
    ExecutionTrace,
    ReviewDecision,
    RuleFinding,
)
from agent_tool_harness.core_evaluation import CoreEvaluation
from agent_tool_harness.core_report_bridge import (
    evaluation_result_to_report_dict,
    report_summary_to_report_dict,
)
from agent_tool_harness.demo_core_bridge import build_report_summary
from agent_tool_harness.fake_judge import FakeJudgeProvider
from agent_tool_harness.trace_import import SimpleMappingConfig, TraceImportAdapter

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _native_trace_json(tmp_path: Path, scenario_id: str = "test-001") -> Path:
    """写入 native 格式的 trace JSON 文件并返回路径。"""
    trace = {
        "scenario_id": scenario_id,
        "tool_calls": [
            {
                "call_id": "c1",
                "tool_name": "knowledge.search",
                "arguments": {"query": "SSO session loss", "limit": 5},
            },
            {
                "call_id": "c2",
                "tool_name": "trace.lookup",
                "arguments": {"trace_id": "abc123"},
            },
        ],
        "tool_results": [
            {
                "call_id": "c1",
                "tool_name": "knowledge.search",
                "status": "success",
                "output": {"articles": [{"id": "1", "title": "SSO Fix"}]},
                "error": None,
            },
            {
                "call_id": "c2",
                "tool_name": "trace.lookup",
                "status": "success",
                "output": {"trace": {"id": "abc123", "status": "resolved"}},
                "error": None,
            },
        ],
        "final_answer": "Root cause: SSO misconfiguration in session storage layer.",
        "messages": [],
    }
    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace))
    return path


def _simple_mapping_trace_json(tmp_path: Path, scenario_id: str = "test-001") -> Path:
    """写入非标准格式的 trace JSON 文件并返回路径。"""
    trace = {
        "scenario": scenario_id,
        "calls": [
            {"id": "c1", "name": "knowledge.search", "args": {"query": "test"}},
        ],
        "results": [
            {
                "id": "c1",
                "name": "knowledge.search",
                "status": "ok",
                "result": {"found": True},
            },
        ],
        "answer": "All good.",
    }
    path = tmp_path / "trace_nonstandard.json"
    path.write_text(json.dumps(trace))
    return path


def _simple_mapping_config() -> SimpleMappingConfig:
    return SimpleMappingConfig(
        scenario_id_path="scenario",
        tool_calls_path="calls",
        tool_results_path="results",
        tool_call_id_field="id",
        tool_call_name_field="name",
        tool_result_call_id_field="id",
        tool_result_name_field="name",
        final_answer_path="answer",
        tool_call_arguments_field="args",
        tool_result_status_field="status",
        tool_result_output_field="result",
    )


def _eval_spec_must_call_search() -> EvalSpec:
    return EvalSpec(
        id="test-001",
        name="test scenario",
        category="integration",
        split="test",
        realism_level="mock",
        complexity="low",
        source="test",
        user_prompt="Find root cause of SSO issue",
        initial_context={},
        verifiable_outcome={},
        success_criteria=["must_call_tool:knowledge.search"],
        expected_tool_behavior={"required_tools": ["knowledge.search"]},
        judge={
            "rules": [{"type": "must_call_tool", "tool": "knowledge.search"}],
        },
    )


def _eval_spec_nonexistent_tool() -> EvalSpec:
    return EvalSpec(
        id="test-001",
        name="test scenario",
        category="integration",
        split="test",
        realism_level="mock",
        complexity="low",
        source="test",
        user_prompt="test",
        initial_context={},
        verifiable_outcome={},
        success_criteria=["must_call_tool:nonexistent.tool"],
        expected_tool_behavior={"required_tools": ["nonexistent.tool"]},
        judge={
            "rules": [{"type": "must_call_tool", "tool": "nonexistent.tool"}],
        },
    )


# ---------------------------------------------------------------------------
# native trace import → CoreEvaluation → Report
# ---------------------------------------------------------------------------


class TestNativeTraceImportCoreFlow:
    """Native mode trace import 经 CoreEvaluation 到 Report 的端到端测试。"""

    def test_full_chain_produces_passed_evaluation(self, tmp_path):
        """native trace 导入后 RuleJudge 判定 passed。"""
        trace_path = _native_trace_json(tmp_path)
        adapter = TraceImportAdapter(mode="native")
        trace = adapter.import_file(trace_path)

        assert isinstance(trace, ExecutionTrace)
        assert trace.scenario_id == "test-001"
        assert len(trace.tool_calls) == 2
        assert len(trace.tool_results) == 2

        evidence = adapter.to_evidence(trace)
        assert isinstance(evidence, Evidence)

        eval_spec = _eval_spec_must_call_search()
        evaluation = CoreEvaluation()
        result = evaluation.evaluate(evidence, eval_spec)

        assert isinstance(result, EvaluationResult)
        assert result.passed is True
        assert len(result.findings) >= 1

    def test_native_trace_missing_required_tool_fails(self, tmp_path):
        """native trace 缺少必须工具时 RuleJudge 判定 failed。"""
        trace_path = _native_trace_json(tmp_path)
        adapter = TraceImportAdapter(mode="native")
        trace = adapter.import_file(trace_path)
        evidence = adapter.to_evidence(trace)

        eval_spec = _eval_spec_nonexistent_tool()
        result = CoreEvaluation().evaluate(evidence, eval_spec)
        assert result.passed is False

    def test_native_trace_evidence_survives_report(self, tmp_path):
        """Evidence 经 evaluation 后可成功生成 report dict。"""
        trace_path = _native_trace_json(tmp_path)
        adapter = TraceImportAdapter(mode="native")
        trace = adapter.import_file(trace_path)
        evidence = adapter.to_evidence(trace)

        result = CoreEvaluation().evaluate(evidence, _eval_spec_must_call_search())

        report_dict = evaluation_result_to_report_dict(result)
        assert report_dict["passed"] is True

        metrics = {
            "total_evals": 1,
            "passed": 1,
            "failed": 0,
            "error_evals": 0,
            "signal_quality": "recorded_trajectory",
        }
        summary = build_report_summary(metrics)
        summary_dict = report_summary_to_report_dict(summary)
        assert summary_dict["total_scenarios"] == 1
        assert summary_dict["passed"] == 1

    def test_trace_final_answer_preserved_in_evidence(self, tmp_path):
        """trace 的 final_answer 正确保留在 Evidence 中。"""
        trace_path = _native_trace_json(tmp_path)
        adapter = TraceImportAdapter(mode="native")
        trace = adapter.import_file(trace_path)
        evidence = adapter.to_evidence(trace)

        assert "root cause" in evidence.trace.final_answer.lower()


# ---------------------------------------------------------------------------
# simple mapping trace import → CoreEvaluation → Report
# ---------------------------------------------------------------------------


class TestSimpleMappingTraceImportCoreFlow:
    """Simple mapping mode trace import 经 CoreEvaluation 到 Report 的端到端测试。"""

    def test_full_chain_simple_mapping_produces_evaluation(self, tmp_path):
        """simple mapping 导入后 RuleJudge 正常判定。"""
        trace_path = _simple_mapping_trace_json(tmp_path)
        mapping = _simple_mapping_config()
        adapter = TraceImportAdapter(mode="simple_mapping", mapping=mapping)
        trace = adapter.import_file(trace_path)

        assert isinstance(trace, ExecutionTrace)
        assert trace.scenario_id == "test-001"
        assert len(trace.tool_calls) == 1

        evidence = adapter.to_evidence(trace)
        result = CoreEvaluation().evaluate(evidence, _eval_spec_must_call_search())

        assert isinstance(result, EvaluationResult)
        assert result.passed is True

    def test_simple_mapping_evidence_survives_report(self, tmp_path):
        """simple mapping Evidence 经 evaluation 后可成功生成 report dict。"""
        trace_path = _simple_mapping_trace_json(tmp_path)
        mapping = _simple_mapping_config()
        adapter = TraceImportAdapter(mode="simple_mapping", mapping=mapping)
        trace = adapter.import_file(trace_path)
        evidence = adapter.to_evidence(trace)

        result = CoreEvaluation().evaluate(evidence, _eval_spec_must_call_search())
        report_dict = evaluation_result_to_report_dict(result)
        assert report_dict["passed"] is True


# ---------------------------------------------------------------------------
# JudgeFinding advisory only
# ---------------------------------------------------------------------------


class TestJudgeFindingAdvisory:
    """JudgeFinding 不改变 passed——passed 始终由 RuleJudge 决定。"""

    def test_judge_finding_does_not_change_passed(self, tmp_path):
        """即使有 JudgeFinding，passed 仍由 RuleJudge 决定。"""
        trace_path = _native_trace_json(tmp_path)
        adapter = TraceImportAdapter(mode="native")
        trace = adapter.import_file(trace_path)
        evidence = adapter.to_evidence(trace)

        fake_judge = FakeJudgeProvider(
            responses={"test-001": {"rationale": "advisory note from judge"}}
        )
        evaluation = CoreEvaluation(judge_provider=fake_judge)
        result = evaluation.evaluate(evidence, _eval_spec_must_call_search())

        # RuleJudge 决定 passed
        assert result.passed is True

    def test_judge_finding_present_but_rule_finding_unchanged(self, tmp_path):
        """RuleFinding 不被 JudgeFinding 覆盖。"""
        trace_path = _native_trace_json(tmp_path)
        adapter = TraceImportAdapter(mode="native")
        trace = adapter.import_file(trace_path)
        evidence = adapter.to_evidence(trace)

        fake_judge = FakeJudgeProvider(
            responses={"test-001": {"rationale": "semantic concern"}}
        )
        evaluation = CoreEvaluation(judge_provider=fake_judge)
        result = evaluation.evaluate(evidence, _eval_spec_must_call_search())

        # RuleFinding 仍存在（排除 JudgeFinding）
        rule_findings = [f for f in result.findings if isinstance(f, RuleFinding)]
        assert len(rule_findings) >= 1
        for f in rule_findings:
            assert hasattr(f, "rule_type")


# ---------------------------------------------------------------------------
# ReviewDecision boundary
# ---------------------------------------------------------------------------


class TestReviewDecisionBoundary:
    """ReviewDecision 不由机器自动生成。"""

    def test_evaluation_result_does_not_auto_generate_review_decision(self, tmp_path):
        """EvaluationResult 不包含自动生成的 ReviewDecision。"""
        trace_path = _native_trace_json(tmp_path)
        adapter = TraceImportAdapter(mode="native")
        trace = adapter.import_file(trace_path)
        evidence = adapter.to_evidence(trace)

        result = CoreEvaluation().evaluate(evidence, _eval_spec_must_call_search())

        # EvaluationResult 没有 review_decision 字段
        assert not hasattr(result, "review_decision")

    def test_review_decision_must_be_created_explicitly(self):
        """ReviewDecision 只能通过显式构造创建。"""
        decision = ReviewDecision(
            decision="approved",
            reviewer="human-tester",
            notes="Manual review passed.",
        )
        assert decision.reviewer == "human-tester"
        assert decision.decision == "approved"


# ---------------------------------------------------------------------------
# Imported evidence → Report 集成
# ---------------------------------------------------------------------------


class TestImportedEvidenceReport:
    """验证导入的 Evidence 可完整进入 Report 链路。"""

    def test_native_evidence_to_report_roundtrip(self, tmp_path):
        """native trace Evidence 完整通过 evaluation → report 链路。"""
        trace_path = _native_trace_json(tmp_path)
        adapter = TraceImportAdapter(mode="native")
        evidence = adapter.to_evidence(adapter.import_file(trace_path))

        result = CoreEvaluation().evaluate(evidence, _eval_spec_must_call_search())
        report = evaluation_result_to_report_dict(result)

        assert report["passed"] is True
        assert "findings" in report

    def test_simple_mapping_evidence_to_report_roundtrip(self, tmp_path):
        """simple mapping trace Evidence 完整通过 evaluation → report 链路。"""
        trace_path = _simple_mapping_trace_json(tmp_path)
        adapter = TraceImportAdapter(
            mode="simple_mapping", mapping=_simple_mapping_config()
        )
        evidence = adapter.to_evidence(adapter.import_file(trace_path))

        result = CoreEvaluation().evaluate(evidence, _eval_spec_must_call_search())
        report = evaluation_result_to_report_dict(result)

        assert report["passed"] is True

    def test_signal_quality_preserved_in_evidence(self, tmp_path):
        """signal_quality 在 Evidence 中正确保留。"""
        trace_path = _native_trace_json(tmp_path)
        adapter = TraceImportAdapter(mode="native")
        evidence = adapter.to_evidence(adapter.import_file(trace_path))

        # Evidence 携带 signal_quality
        assert hasattr(evidence, "signal_quality")
        assert evidence.signal_quality == "recorded_trajectory"
