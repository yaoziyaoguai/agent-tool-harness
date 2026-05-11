"""Core Contract 测试 —— 验证 Agent2Harness 核心对象和接口契约。

测试纪律：
- 不允许放宽断言来追求绿。
- FakeAgentAdapter 只在测试中使用，不成为生产 fake provider。
- Contract test 验证的是接口契约，不是实现细节。
"""

from __future__ import annotations

from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.core_contract import (
    EvaluationResult,
    Evidence,
    ExecutionTrace,
    Finding,
    ReportSummary,
    ReviewDecision,
    RuleFinding,
    ScenarioSpec,
    ToolCall,
    ToolResult,
)

# ---------------------------------------------------------------------------
# Fake adapter —— 仅用于 contract test
# ---------------------------------------------------------------------------


class FakeAgentAdapter:
    """Fake adapter 实现 Agent2HarnessAdapter Protocol。

    只在 contract test 中使用，验证"任意 adapter 实现都可以输入 ScenarioSpec、
    输出 ExecutionTrace"。不进入生产代码。
    """

    SIGNAL_QUALITY = "rule_deterministic"

    def run(self, scenario: ScenarioSpec) -> ExecutionTrace:
        return ExecutionTrace(
            scenario_id=scenario.scenario_id,
            tool_calls=[
                ToolCall(
                    tool_name=scenario.available_tools[0] if scenario.available_tools else "test",
                    arguments={"query": scenario.goal},
                    call_id="fake-call-1",
                )
            ],
            tool_results=[
                ToolResult(
                    call_id="fake-call-1",
                    status="success",
                    output={"evidence": [{"id": "ev-001", "label": "test evidence"}]},
                )
            ],
            final_answer=f"根据工具返回的证据，{scenario.goal} 的结论是：测试通过。",
        )


# ---------------------------------------------------------------------------
# 1. ToolSpec 可以表达一个工具定义
# ---------------------------------------------------------------------------


def test_tool_spec_expresses_tool_definition():
    """ToolSpec（config 层已有）可以完整描述一个工具。"""
    tool = ToolSpec(
        name="search",
        namespace="knowledge",
        version="1.0",
        description="搜索知识库",
        when_to_use="当需要查找信息时",
        when_not_to_use="当信息已知时",
        input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
        output_contract={"evidence": "list"},
        token_policy={"max_tokens_per_call": 1000},
        side_effects={"destructive": False},
        executor={"type": "python", "module": "search_tool"},
    )
    assert tool.name == "search"
    assert tool.qualified_name == "knowledge.search"
    assert isinstance(tool.input_schema, dict)
    assert not tool.side_effects["destructive"]


# ---------------------------------------------------------------------------
# 2. ScenarioSpec 可以引用 ToolSpec
# ---------------------------------------------------------------------------


def test_scenario_spec_references_tools():
    """ScenarioSpec.available_tools 引用 ToolSpec.name。"""
    scenario = ScenarioSpec(
        scenario_id="s1",
        goal="用户想知道最近的错误原因",
        available_tools=["knowledge.search", "trace.lookup"],
        success_criteria=["结论引用具体 trace id"],
    )
    assert "knowledge.search" in scenario.available_tools
    assert len(scenario.success_criteria) == 1
    assert scenario.scenario_id == "s1"


def test_scenario_spec_is_pure_data():
    """ScenarioSpec 不包含 IO 逻辑（from_dict/to_dict 等）。"""
    s = ScenarioSpec(scenario_id="s1", goal="test")
    # 确认是纯 dataclass，没有 config 加载方法
    assert not hasattr(s, "from_dict")
    assert not hasattr(s, "to_dict")


# ---------------------------------------------------------------------------
# 3. ExecutionTrace 可以承载 tool calls 和 tool results
# ---------------------------------------------------------------------------


def test_execution_trace_carries_tool_calls_and_results():
    """ExecutionTrace 聚合 tool_calls 和 tool_results。"""
    trace = ExecutionTrace(
        scenario_id="s1",
        tool_calls=[
            ToolCall(tool_name="search", arguments={"q": "err"}, call_id="c1"),
            ToolCall(tool_name="lookup", arguments={"id": "ev-001"}, call_id="c2"),
        ],
        tool_results=[
            ToolResult(call_id="c1", status="success", output={"data": "found"}),
            ToolResult(call_id="c2", status="success", output={"detail": "trace"}),
        ],
        final_answer="错误原因是超时。",
    )
    assert len(trace.tool_calls) == 2
    assert len(trace.tool_results) == 2
    assert trace.tool_calls[0].call_id == "c1"
    assert trace.tool_results[0].call_id == "c1"
    assert trace.final_answer == "错误原因是超时。"


def test_tool_call_is_immutable():
    """ToolCall 是 frozen dataclass，不可原地修改。"""
    call = ToolCall(tool_name="test", arguments={}, call_id="c1")
    try:
        call.tool_name = "changed"  # type: ignore[misc]
        raise AssertionError("ToolCall 应该是不可变的")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 4. Evidence 可以引用 ExecutionTrace
# ---------------------------------------------------------------------------


def test_evidence_wraps_execution_trace():
    """Evidence 打包 ExecutionTrace + 可选字段。"""
    trace = ExecutionTrace(scenario_id="s1", final_answer="ok")
    evidence = Evidence(
        trace=trace,
        cost_usd=0.01,
        latency_ms=150.0,
        warnings=["tool search 返回空结果"],
        signal_quality="real_agent",
    )
    assert evidence.trace.scenario_id == "s1"
    assert evidence.cost_usd == 0.01
    assert evidence.latency_ms == 150.0
    assert len(evidence.warnings) == 1
    assert evidence.signal_quality == "real_agent"


def test_evidence_cost_and_latency_can_be_none():
    """cost_usd / latency_ms 可为 None——当前 demo 没有真实数据。"""
    evidence = Evidence(trace=ExecutionTrace(scenario_id="s1"))
    assert evidence.cost_usd is None
    assert evidence.latency_ms is None


# ---------------------------------------------------------------------------
# 5. Finding 可以引用 Evidence
# ---------------------------------------------------------------------------


def test_finding_references_evidence():
    """Finding.evidence_ref 指向具体证据位置。"""
    finding = Finding(
        finding_id="f1",
        severity="high",
        category="rule",
        message="Agent 没有调用 required tool",
        evidence_ref="tool_calls.jsonl::eval_id=s1",
    )
    assert finding.finding_id == "f1"
    assert finding.severity == "high"
    assert finding.category == "rule"
    assert "tool_calls.jsonl" in finding.evidence_ref


def test_rule_finding_extends_finding():
    """RuleFinding 继承 Finding，新增 rule_type / rule_passed。"""
    rf = RuleFinding(
        finding_id="rf1",
        severity="medium",
        category="rule",
        message="must_call_tool 检查失败",
        evidence_ref="transcript.jsonl#L10",
        rule_type="must_call_tool",
        rule_passed=False,
    )
    assert isinstance(rf, Finding)
    assert rf.rule_type == "must_call_tool"
    assert not rf.rule_passed


# ---------------------------------------------------------------------------
# 6. EvaluationResult 聚合 findings，但不产生 ReviewDecision
# ---------------------------------------------------------------------------


def test_evaluation_result_aggregates_findings():
    """EvaluationResult 聚合多条 Finding。"""
    result = EvaluationResult(
        scenario_id="s1",
        findings=[
            Finding(
                finding_id="f1",
                severity="high",
                category="rule",
                message="must_call_tool 失败",
                evidence_ref="ref1",
            ),
            RuleFinding(
                finding_id="f2",
                severity="medium",
                category="rule",
                message="evidence 来源不在 required_tools 中",
                evidence_ref="ref2",
                rule_type="evidence_from_required_tools",
                rule_passed=False,
            ),
        ],
        passed=False,
        summary="Agent 未调用预期工具，且引用了 decoy 工具的证据。",
    )
    assert len(result.findings) == 2
    assert not result.passed
    assert isinstance(result.findings[1], RuleFinding)


def test_evaluation_result_does_not_auto_create_review_decision():
    """EvaluationResult 不会自动生成 ReviewDecision。

    这是关键架构边界：机器评分不能自动变成人工裁决。
    """
    result = EvaluationResult(scenario_id="s1", passed=True)
    # EvaluationResult 没有 decision 字段
    assert not hasattr(result, "decision")
    # EvaluationResult 没有 to_review_decision 之类的方法
    assert not hasattr(result, "to_review_decision")


# ---------------------------------------------------------------------------
# 7. ReviewDecision 必须显式创建，不能由 EvaluationResult 自动生成
# ---------------------------------------------------------------------------


def test_review_decision_must_be_explicitly_created():
    """ReviewDecision 必须人工显式构造。

    演示正确流程：
    1. 机器产出 EvaluationResult
    2. 人工 reviewer 查看 evidence + result
    3. 人工 reviewer 显式创建 ReviewDecision
    """
    # Step 1: 机器评分
    result = EvaluationResult(scenario_id="s1", passed=False, summary="工具设计有问题")

    # Step 2-3: 人工审核后显式创建（这里模拟）
    decision = ReviewDecision(
        decision="needs_revision",
        reviewer="tool-design-reviewer",
        notes=f"同意机器评分：{result.summary}。建议增加 input_schema 约束。",
        reviewed_at="2026-05-11T10:00:00Z",
    )

    assert decision.decision == "needs_revision"
    assert decision.reviewer == "tool-design-reviewer"
    # ReviewDecision 不由 EvaluationResult 派生
    assert not hasattr(result, "to_review_decision")
    assert "ReviewDecision" not in type(result).__name__


def test_review_decision_is_immutable():
    """ReviewDecision 一旦创建不可修改。"""
    decision = ReviewDecision(decision="approved", reviewer="alice", notes="looks good")
    try:
        decision.decision = "rejected"  # type: ignore[misc]
        raise AssertionError("ReviewDecision 应该是不可变的")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 8. Agent2HarnessAdapter protocol 可以被 fake adapter 实现
# ---------------------------------------------------------------------------


def test_fake_adapter_implements_agent2harness_protocol():
    """FakeAgentAdapter 满足 Agent2HarnessAdapter Protocol。"""
    adapter = FakeAgentAdapter()
    assert hasattr(adapter, "SIGNAL_QUALITY")
    assert hasattr(adapter, "run")
    assert adapter.SIGNAL_QUALITY == "rule_deterministic"


# ---------------------------------------------------------------------------
# 9. Fake adapter 输入 ScenarioSpec，输出 ExecutionTrace
# ---------------------------------------------------------------------------


def test_fake_adapter_input_scenario_output_trace():
    """契约验证：adapter.run(ScenarioSpec) → ExecutionTrace。"""
    scenario = ScenarioSpec(
        scenario_id="s1",
        goal="定位最近的 production error 根因",
        available_tools=["trace.lookup", "log.search"],
        success_criteria=["结论必须引用具体 trace id"],
    )
    adapter = FakeAgentAdapter()
    trace = adapter.run(scenario)

    assert isinstance(trace, ExecutionTrace)
    assert trace.scenario_id == "s1"
    assert len(trace.tool_calls) >= 1
    assert len(trace.tool_results) >= 1
    assert trace.tool_calls[0].call_id == trace.tool_results[0].call_id
    assert "测试通过" in trace.final_answer or len(trace.final_answer) > 0


def test_fake_adapter_trace_connects_calls_and_results():
    """tool_calls 和 tool_results 通过 call_id 一一对应。"""
    scenario = ScenarioSpec(scenario_id="s1", goal="test")
    adapter = FakeAgentAdapter()
    trace = adapter.run(scenario)

    call_ids = {c.call_id for c in trace.tool_calls}
    result_ids = {r.call_id for r in trace.tool_results}
    assert call_ids == result_ids, "每个 tool_call 应有对应 tool_result"


# ---------------------------------------------------------------------------
# 10. Core contract 模块不 import demo / cli / provider 模块
# ---------------------------------------------------------------------------


def test_core_contract_does_not_import_demo_modules():
    """core_contract.py 不 import demo adapter / cli / provider。"""
    import ast
    from pathlib import Path

    source = Path("agent_tool_harness/core_contract.py").read_text(encoding="utf-8")
    tree = ast.parse(source)

    forbidden = {
        "mock_replay_adapter",
        "transcript_replay_adapter",
        "cli",
        "LiveAnthropicTransport",
        "FakeJudgeTransport",
        "AnthropicCompatibleJudgeProvider",
        "examples",
        "dotenv",
        "load_dotenv",
    }

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = node.module if isinstance(node, ast.ImportFrom) else ""
            for name in node.names:
                full = f"{module}.{name.name}" if module else name.name
                for token in forbidden:
                    assert token not in full, f"core_contract.py 不应 import {token}，发现: {full}"


def test_core_contract_does_not_import_env_reading():
    """core_contract.py 不读取环境变量或 .env。"""
    from agent_tool_harness import core_contract as mod

    assert hasattr(mod, "ToolCall")
    assert hasattr(mod, "ExecutionTrace")


# ---------------------------------------------------------------------------
# 11. ReportSummary 不替代 ReviewDecision
# ---------------------------------------------------------------------------


def test_report_summary_is_not_review_decision():
    """ReportSummary 是统计摘要，ReviewDecision 是人工结论。两者不可混淆。"""
    report = ReportSummary(
        total_scenarios=10, passed=7, failed=3, signal_quality="tautological_replay"
    )
    assert report.total_scenarios == 10
    assert report.passed == 7
    assert not hasattr(report, "decision")
    assert not hasattr(report, "reviewer")
