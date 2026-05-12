"""CoreEvaluation 测试 —— RuleJudge + JudgeProvider 聚合。

测试纪律：
- 所有测试零网络依赖
- 不读取 .env / os.environ
- 不调用真实 LLM
- JudgeFinding 不改变 EvaluationResult.passed
- 不生成 ReviewDecision
"""

from __future__ import annotations

import ast
from pathlib import Path

from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.core_contract import (
    EvaluationResult,
    Evidence,
    ExecutionTrace,
    Finding,
    JudgeFinding,
    RuleFinding,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.core_evaluation import CoreEvaluation
from agent_tool_harness.fake_judge import FakeJudgeProvider
from agent_tool_harness.judges.rule_judge import RuleJudge

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_evidence(scenario_id: str = "s1") -> Evidence:
    trace = ExecutionTrace(
        scenario_id=scenario_id,
        tool_calls=[
            ToolCall(tool_name="knowledge.search", arguments={"query": "test"}, call_id="c1"),
        ],
        tool_results=[
            ToolResult(
                call_id="c1",
                tool_name="knowledge.search",
                status="success",
                output={"data": "found"},
            ),
        ],
        final_answer="根据工具返回，测试通过。",
    )
    return Evidence(trace=trace, signal_quality="tautological_replay")


def _make_eval_spec() -> EvalSpec:
    return EvalSpec(
        id="s1",
        name="Test Scenario",
        category="integration",
        split="test",
        realism_level="mock",
        complexity="low",
        source="test",
        user_prompt="定位最近错误根因",
        initial_context={"query": "recent error"},
        verifiable_outcome={},
        success_criteria=["引用证据"],
        expected_tool_behavior={"required_tools": ["knowledge.search"]},
        judge={},
    )


class AlwaysPassJudge(RuleJudge):
    """注入测试用的 RuleJudge——对所有 case 返回 PASS。"""

    def judge(self, case, run_result):
        from agent_tool_harness.judges.rule_judge import JudgeResult, RuleCheckResult
        return JudgeResult(
            eval_id=case.id,
            passed=True,
            checks=[
                RuleCheckResult(
                    rule={"name": "forced_pass"},
                    passed=True,
                    message="forced pass",
                )
            ],
        )


class AlwaysFailJudge(RuleJudge):
    """注入测试用的 RuleJudge——对所有 case 返回 FAIL。"""

    def judge(self, case, run_result):
        from agent_tool_harness.judges.rule_judge import JudgeResult, RuleCheckResult
        return JudgeResult(
            eval_id=case.id,
            passed=False,
            checks=[
                RuleCheckResult(
                    rule={"name": "forced_fail"},
                    passed=False,
                    message="forced failure",
                )
            ],
        )


# ---------------------------------------------------------------------------
# 1. CoreEvaluation without judge_provider → backward compatible
# ---------------------------------------------------------------------------


def test_core_evaluation_without_judge_provider_backward_compatible():
    """不传 judge_provider 时，行为保持向后兼容。"""
    eval_result = CoreEvaluation().evaluate(_make_evidence(), _make_eval_spec())
    assert isinstance(eval_result, EvaluationResult)
    assert len(eval_result.findings) > 0
    # 全部是 RuleFinding
    for f in eval_result.findings:
        assert isinstance(f, RuleFinding), f"所有 finding 应为 RuleFinding，实际: {type(f)}"
    # 不包含 JudgeFinding
    judge_findings = [f for f in eval_result.findings if isinstance(f, JudgeFinding)]
    assert len(judge_findings) == 0


# ---------------------------------------------------------------------------
# 2. CoreEvaluation with FakeJudgeProvider → RuleFinding + JudgeFinding
# ---------------------------------------------------------------------------


def test_core_evaluation_with_fake_judge_provider():
    """传入 FakeJudgeProvider 时，findings 同时包含 RuleFinding 和 JudgeFinding。"""
    provider = FakeJudgeProvider(responses={"s1": {"rationale": "fake advisory"}})
    eval_result = CoreEvaluation(judge_provider=provider).evaluate(
        _make_evidence(), _make_eval_spec()
    )
    rule_findings = [f for f in eval_result.findings if isinstance(f, RuleFinding)]
    judge_findings = [f for f in eval_result.findings if isinstance(f, JudgeFinding)]

    assert len(rule_findings) >= 1, "至少有一条 RuleFinding"
    assert len(judge_findings) == 1, "应该恰好有一条 JudgeFinding"
    assert judge_findings[0].provider == "fake"
    assert judge_findings[0].model == "fake-model"


# ---------------------------------------------------------------------------
# 3. JudgeFinding does NOT change EvaluationResult.passed
# ---------------------------------------------------------------------------


def test_judge_finding_does_not_change_passed():
    """JudgeFinding 不改变 deterministic RuleJudge 的 passed 判定。"""
    # 注入 AlwaysFailJudge 确保 RuleJudge 对 EvalSpec 判 FAIL
    eval_result = CoreEvaluation(
        judge=AlwaysFailJudge(),
        judge_provider=FakeJudgeProvider(),
    ).evaluate(_make_evidence(), _make_eval_spec())

    assert not eval_result.passed, "passed 应仍由 RuleJudge 决定（FAIL）"
    assert any(isinstance(f, RuleFinding) for f in eval_result.findings)
    assert any(isinstance(f, JudgeFinding) for f in eval_result.findings)


def test_judge_finding_does_not_change_passed_to_fail():
    """即便 JudgeFinding 存在，已通过的结果不会被翻成失败。"""
    eval_result = CoreEvaluation(
        judge=AlwaysPassJudge(),
        judge_provider=FakeJudgeProvider(),
    ).evaluate(_make_evidence(), _make_eval_spec())

    assert eval_result.passed, "passed 应仍由 RuleJudge 决定（PASS）"
    assert any(isinstance(f, JudgeFinding) for f in eval_result.findings)


# ---------------------------------------------------------------------------
# 4. JudgeFinding does NOT generate ReviewDecision
# ---------------------------------------------------------------------------


def test_core_evaluation_does_not_generate_review_decision():
    """CoreEvaluation 不自动生成 ReviewDecision，无论是否有 judge_provider。"""
    eval_result = CoreEvaluation(
        judge_provider=FakeJudgeProvider(),
    ).evaluate(_make_evidence(), _make_eval_spec())

    assert not hasattr(eval_result, "decision")
    assert not hasattr(eval_result, "reviewer")
    assert not hasattr(eval_result, "to_review_decision")
    assert "ReviewDecision" not in type(eval_result).__name__


# ---------------------------------------------------------------------------
# 5. FakeJudgeProvider has no external API call (via CoreEvaluation)
# ---------------------------------------------------------------------------


def test_fake_judge_provider_no_external_call_in_core_evaluation():
    """FakeJudgeProvider 通过 CoreEvaluation 调用时仍不发起外部 API。"""
    import inspect

    source = inspect.getsource(CoreEvaluation.evaluate)
    eval_result = CoreEvaluation(
        judge_provider=FakeJudgeProvider(),
    ).evaluate(_make_evidence(), _make_eval_spec())

    assert len(eval_result.findings) > 0
    # CoreEvaluation.evaluate 源码中无网络调用
    assert "requests" not in source.lower()
    assert "httpx" not in source.lower()


# ---------------------------------------------------------------------------
# 6. CoreEvaluation does NOT read .env
# ---------------------------------------------------------------------------


def test_core_evaluation_does_not_read_dotenv():
    """CoreEvaluation 模块不 import dotenv，不调用 load_dotenv。"""
    path = Path("agent_tool_harness/core_evaluation.py")
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = node.module if isinstance(node, ast.ImportFrom) else ""
            for name in node.names:
                full = f"{module}.{name.name}" if module else name.name
                assert "dotenv" not in full, f"core_evaluation.py 不应 import dotenv，发现: {full}"
                assert "load_dotenv" not in full, (
                    f"core_evaluation.py 不应 import load_dotenv，发现: {full}"
                )


# ---------------------------------------------------------------------------
# 7. CoreEvaluation does NOT read os.environ
# ---------------------------------------------------------------------------


def test_core_evaluation_does_not_read_os_environ():
    """CoreEvaluation.evaluate 不读 os.environ。"""
    path = Path("agent_tool_harness/core_evaluation.py")
    source = path.read_text(encoding="utf-8")
    assert "os.environ" not in source, "core_evaluation.py 不应读取 os.environ"


# ---------------------------------------------------------------------------
# 8. CoreEvaluation does NOT import real provider
# ---------------------------------------------------------------------------


def test_core_evaluation_does_not_import_real_provider():
    """CoreEvaluation 模块不 import 真实 provider。"""
    path = Path("agent_tool_harness/core_evaluation.py")
    source = path.read_text(encoding="utf-8")
    forbidden = {
        "LiveAnthropicTransport",
        "AnthropicCompatibleJudgeProvider",
        "OpenAIJudgeProvider",
        "resolve_api_key",
    }
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for name in node.names:
                for token in forbidden:
                    assert token not in name.name, (
                        f"core_evaluation.py 不应 import {token}，发现: {name.name}"
                    )


# ---------------------------------------------------------------------------
# 9. RuleFinding and JudgeFinding boundaries are clear
# ---------------------------------------------------------------------------


def test_rule_and_judge_finding_boundaries():
    """RuleFinding 和 JudgeFinding 的 category / severity 边界清晰。"""
    eval_result = CoreEvaluation(
        judge_provider=FakeJudgeProvider(),
    ).evaluate(_make_evidence(), _make_eval_spec())

    for f in eval_result.findings:
        if isinstance(f, RuleFinding):
            assert f.category == "rule", f"RuleFinding category 应为 'rule'，实际: {f.category}"
        elif isinstance(f, JudgeFinding):
            assert f.category == "judge", f"JudgeFinding category 应为 'judge'，实际: {f.category}"
            assert f.provider == "fake"
            # JudgeFinding 不应有 rule 相关字段
            assert not hasattr(f, "rule_type")
            assert not hasattr(f, "rule_passed")
        else:
            raise AssertionError(f"未知 finding 类型: {type(f)}")


# ---------------------------------------------------------------------------
# 10. Multiple JudgeFindings are appended correctly
# ---------------------------------------------------------------------------


def test_multiple_judge_findings_appended():
    """如果 judge_provider 返回多个 JudgeFinding，全部追加到 findings。"""
    # 使用一个返回多个 finding 的 judge_provider
    class MultiJudgeProvider:
        name = "multi"
        mode = "fake"

        def evaluate(self, evidence: Evidence) -> list[JudgeFinding]:
            return [
                JudgeFinding(
                    finding_id="j1",
                    severity="info",
                    category="judge",
                    message="finding 1",
                    evidence_ref="ref1",
                    provider="multi",
                    rationale="first",
                    model="multi-model",
                ),
                JudgeFinding(
                    finding_id="j2",
                    severity="low",
                    category="judge",
                    message="finding 2",
                    evidence_ref="ref2",
                    provider="multi",
                    rationale="second",
                    model="multi-model",
                ),
            ]

    eval_result = CoreEvaluation(judge_provider=MultiJudgeProvider()).evaluate(
        _make_evidence(), _make_eval_spec()
    )
    judge_findings = [f for f in eval_result.findings if isinstance(f, JudgeFinding)]
    rule_findings = [f for f in eval_result.findings if isinstance(f, RuleFinding)]
    assert len(judge_findings) == 2
    assert len(rule_findings) >= 1


# ---------------------------------------------------------------------------
# 11. existing core flow tests still pass (sanity)
# ---------------------------------------------------------------------------


def test_core_evaluation_result_structure():
    """CoreEvaluation 产出的 EvaluationResult 结构完整性。"""
    eval_result = CoreEvaluation(
        judge_provider=FakeJudgeProvider(),
    ).evaluate(_make_evidence(), _make_eval_spec())

    assert eval_result.scenario_id == "s1"
    assert isinstance(eval_result.passed, bool)
    assert isinstance(eval_result.summary, str)
    assert isinstance(eval_result.findings, list)
    for f in eval_result.findings:
        assert isinstance(f, Finding)
        assert f.finding_id
        assert f.severity in ("critical", "high", "medium", "low", "info")
        assert f.category in ("rule", "judge")
        assert f.message
        assert f.evidence_ref
