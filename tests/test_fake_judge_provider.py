"""FakeJudgeProvider 测试 —— 验证 JudgeProvider 接口和架构边界。

测试纪律：
- FakeJudgeProvider 不调外部 API
- 默认不触发真实 provider
- JudgeFinding ≠ ReviewDecision
"""

from __future__ import annotations

from agent_tool_harness.core_contract import (
    EvaluationResult,
    Evidence,
    ExecutionTrace,
    JudgeFinding,
    ReportSummary,
    ReviewDecision,
    RuleFinding,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.fake_judge import FakeJudgeProvider

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_evidence(scenario_id: str = "s1") -> Evidence:
    trace = ExecutionTrace(
        scenario_id=scenario_id,
        tool_calls=[
            ToolCall(tool_name="search", arguments={"q": "test"}, call_id="c1"),
        ],
        tool_results=[
            ToolResult(call_id="c1", status="success", output={"data": "found"}),
        ],
        final_answer="根据工具返回，测试通过。",
    )
    return Evidence(trace=trace, signal_quality="tautological_replay")


# ---------------------------------------------------------------------------
# 1. FakeJudgeProvider does NOT call external API
# ---------------------------------------------------------------------------


def test_fake_judge_does_not_call_external_api():
    """FakeJudgeProvider.evaluate() 不发起任何网络请求。"""
    provider = FakeJudgeProvider()
    evidence = _make_evidence()
    findings = provider.evaluate(evidence)
    assert len(findings) == 1
    assert findings[0].provider == "fake"


# ---------------------------------------------------------------------------
# 2. FakeJudgeProvider accepts Evidence and outputs JudgeFinding
# ---------------------------------------------------------------------------


def test_fake_judge_accepts_evidence_outputs_judge_finding():
    """CoreJudgeProvider 契约：输入 Evidence，输出 list[JudgeFinding]。"""
    provider = FakeJudgeProvider()
    evidence = _make_evidence()
    findings = provider.evaluate(evidence)

    assert isinstance(findings, list)
    assert len(findings) == 1
    for f in findings:
        assert isinstance(f, JudgeFinding)
        assert f.finding_id
        assert f.severity
        assert f.category == "judge"
        assert f.provider == "fake"
        assert f.model == "fake-model"


# ---------------------------------------------------------------------------
# 3. FakeJudgeProvider uses preset responses when scenario_id matches
# ---------------------------------------------------------------------------


def test_fake_judge_uses_preset_responses():
    """预设 responses 覆盖默认值。"""
    provider = FakeJudgeProvider(
        responses={
            "s1": {
                "passed": False,
                "rationale": "工具调用参数缺失",
                "confidence": 0.6,
                "rubric": "参数完整性检查",
            }
        }
    )
    findings = provider.evaluate(_make_evidence("s1"))
    f = findings[0]
    assert f.rationale == "工具调用参数缺失"
    assert f.confidence == 0.6
    assert f.rubric == "参数完整性检查"


# ---------------------------------------------------------------------------
# 4. FakeJudgeProvider returns default when scenario_id not in responses
# ---------------------------------------------------------------------------


def test_fake_judge_defaults_when_scenario_not_in_responses():
    """未预设的 scenario_id 返回占位 finding。"""
    provider = FakeJudgeProvider(responses={"known": {"passed": False}})
    findings = provider.evaluate(_make_evidence("unknown"))
    assert len(findings) == 1
    assert findings[0].rationale == "fake judge advisory"


# ---------------------------------------------------------------------------
# 5. JudgeFinding ≠ ReviewDecision
# ---------------------------------------------------------------------------


def test_judge_finding_is_not_review_decision():
    """LLM judge 产出是 advisory，ReviewDecision 必须人工创建。"""
    provider = FakeJudgeProvider()
    evidence = _make_evidence()
    findings = provider.evaluate(evidence)

    for f in findings:
        assert not hasattr(f, "decision")
        assert not hasattr(f, "reviewer")
        assert not hasattr(f, "notes")

    # ReviewDecision 必须独立显式创建
    decision = ReviewDecision(
        decision="needs_revision",
        reviewer="human",
        notes="看了 judge finding，同意——需要改进工具参数。",
    )
    # 两者是完全不同的数据类型
    assert type(findings[0]) is not type(decision)


# ---------------------------------------------------------------------------
# 6. EvaluationResult can aggregate RuleFinding + JudgeFinding
# ---------------------------------------------------------------------------


def test_evaluation_result_aggregates_rule_and_judge_findings():
    """两种 finding 在 EvaluationResult 中并列存在。"""
    rule_finding = RuleFinding(
        finding_id="rf1",
        severity="medium",
        category="rule",
        message="must_call_tool 通过",
        evidence_ref="ref1",
        rule_type="must_call_tool",
        rule_passed=True,
    )

    judge_finding = JudgeFinding(
        finding_id="jf1",
        severity="info",
        category="judge",
        message="LLM 认为参数合理",
        evidence_ref="ref2",
        confidence=0.95,
        provider="fake",
        rationale="参数匹配预期",
        model="fake-model",
    )

    result = EvaluationResult(
        scenario_id="s1",
        findings=[rule_finding, judge_finding],
        passed=True,
        summary="规则和 LLM judge 都通过。",
    )
    assert len(result.findings) == 2
    assert isinstance(result.findings[0], RuleFinding)
    assert isinstance(result.findings[1], JudgeFinding)
    assert result.passed


# ---------------------------------------------------------------------------
# 7. reporter does NOT auto-adjudicate
# ---------------------------------------------------------------------------


def test_report_summary_does_not_adjudicate():
    """ReportSummary 只做统计，不做裁决。"""
    report = ReportSummary(
        total_scenarios=5, passed=4, failed=1, signal_quality="tautological_replay"
    )
    assert not hasattr(report, "decision")
    assert not hasattr(report, "reviewer")
    assert report.passed == 4
    assert report.failed == 1


# ---------------------------------------------------------------------------
# 8. FakeJudgeProvider conforms to CoreJudgeProvider Protocol
# ---------------------------------------------------------------------------


def test_fake_judge_conforms_to_core_judge_provider():
    """FakeJudgeProvider 满足 CoreJudgeProvider Protocol 结构。"""
    provider = FakeJudgeProvider()
    assert provider.name == "fake"
    assert provider.mode == "fake"
    assert callable(provider.evaluate)


# ---------------------------------------------------------------------------
# 9. real provider not triggered by default
# ---------------------------------------------------------------------------


def test_fake_judge_has_no_api_call_path():
    """FakeJudgeProvider 内部没有 resolve_api_key 调用路径。"""
    import inspect

    source = inspect.getsource(FakeJudgeProvider.evaluate).strip()
    # 不包含任何网络调用相关字符串
    assert "requests" not in source.lower()
    assert "httpx" not in source.lower()
    assert "http" not in source.lower()
    assert "api_key" not in source.lower()
    assert "resolve_api_key" not in source.lower()
    assert "os.environ" not in source
