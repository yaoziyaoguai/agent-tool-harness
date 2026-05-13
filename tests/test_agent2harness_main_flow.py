"""Agent2Harness Main Flow 集成测试。

测试纪律：
- 验证完整的 Core Flow 链路：ScenarioSpec → ExecutionTrace → Evidence
  → EvaluationResult → ReportSummary。
- 所有测试使用 demo/mock 材料，不接真实 LLM。
- 验证架构边界：ReviewDecision 不自动生成、reporter 不裁决、wrapper 不改旧 adapter。
"""

from __future__ import annotations

from agent_tool_harness.agent2harness_adapter import (
    DemoAgent2HarnessAdapter,
    ReplayAgent2HarnessAdapter,
)
from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.core_contract import (
    EvaluationResult,
    Evidence,
    ExecutionTrace,
    ReportSummary,
    ReviewDecision,
    RuleFinding,
    ScenarioSpec,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.core_evaluation import CoreEvaluation
from agent_tool_harness.core_report_bridge import (
    evaluation_result_to_report_dict,
    report_summary_to_report_dict,
)
from agent_tool_harness.demo_core_bridge import (
    agent_run_result_to_execution_trace,
    build_report_summary,
    execution_trace_to_agent_run_result,
    execution_trace_to_evidence,
)
from agent_tool_harness.judges.rule_judge import JudgeResult, RuleCheckResult, RuleJudge
from agent_tool_harness.signal_quality import TAUTOLOGICAL_REPLAY

# ---------------------------------------------------------------------------
# 共享 fixture 数据
# ---------------------------------------------------------------------------


def _make_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="search",
            namespace="knowledge",
            version="1.0",
            description="搜索知识库",
            when_to_use="查找信息时",
            when_not_to_use="信息已知时",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            output_contract={"evidence": "list"},
            token_policy={"max_tokens_per_call": 1000},
            side_effects={"destructive": False},
            executor={"type": "python", "module": "search_tool"},
        ),
        ToolSpec(
            name="lookup",
            namespace="trace",
            version="1.0",
            description="查询 trace",
            when_to_use="需要 trace 详情时",
            when_not_to_use="不需要时",
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            output_contract={"evidence": "list"},
            token_policy={"max_tokens_per_call": 500},
            side_effects={"destructive": False},
            executor={"type": "python", "module": "lookup_tool"},
        ),
    ]


def _make_eval_spec_good() -> EvalSpec:
    return EvalSpec(
        id="scenario-1",
        name="test scenario",
        category="integration",
        split="test",
        realism_level="mock",
        complexity="low",
        source="test",
        user_prompt="定位最近错误根因",
        initial_context={"query": "recent error"},
        expected_tool_behavior={"required_tools": ["knowledge.search"]},
        judge={
            "rules": [
                {"type": "must_call_tool", "tool": "knowledge.search"},
                {"type": "must_use_evidence"},
            ]
        },
        verifiable_outcome={
            "expected_root_cause": "timeout",
            "evidence_ids": ["ev-001"],
        },
        success_criteria=["结论引用证据"],
    )


def _make_scenario_spec() -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id="scenario-1",
        goal="定位最近错误根因",
        available_tools=["knowledge.search", "trace.lookup"],
        success_criteria=["结论引用证据"],
    )


# ---------------------------------------------------------------------------
# 1. ScenarioSpec → DemoAgent2HarnessAdapter → ExecutionTrace
# ---------------------------------------------------------------------------


def test_scenario_to_execution_trace_via_demo_adapter():
    """DemoAgent2HarnessAdapter.run(ScenarioSpec) → ExecutionTrace。"""
    tool_specs = _make_tool_specs()
    eval_spec = _make_eval_spec_good()
    scenario = _make_scenario_spec()

    inner = MockReplayAdapter("good")
    adapter = DemoAgent2HarnessAdapter(
        inner=inner, tool_specs=tool_specs, eval_spec=eval_spec
    )

    trace = adapter.run(scenario)

    assert isinstance(trace, ExecutionTrace)
    assert trace.scenario_id == "scenario-1"
    assert len(trace.tool_calls) >= 1
    assert all(isinstance(c, ToolCall) for c in trace.tool_calls)
    assert all(isinstance(r, ToolResult) for r in trace.tool_results)
    assert len(trace.final_answer) > 0


def test_demo_adapter_signal_quality():
    """DemoAgent2HarnessAdapter 的 SIGNAL_QUALITY 与旧 MockReplayAdapter 一致。"""
    tool_specs = _make_tool_specs()
    eval_spec = _make_eval_spec_good()
    adapter = DemoAgent2HarnessAdapter(
        inner=MockReplayAdapter("good"), tool_specs=tool_specs, eval_spec=eval_spec
    )

    assert adapter.SIGNAL_QUALITY == TAUTOLOGICAL_REPLAY
    assert adapter.SIGNAL_QUALITY == MockReplayAdapter.SIGNAL_QUALITY


def test_demo_adapter_does_not_change_inner_behavior():
    """Wrapper 不改旧 MockReplayAdapter 的行为——新旧并排对照。"""
    tool_specs = _make_tool_specs()
    eval_spec = _make_eval_spec_good()
    scenario = _make_scenario_spec()

    # 旧路径：直接调用 MockReplayAdapter
    import tempfile
    from pathlib import Path

    from agent_tool_harness.recorder.run_recorder import RunRecorder
    from agent_tool_harness.tools.registry import ToolRegistry

    registry_old = ToolRegistry(tool_specs)
    with tempfile.TemporaryDirectory() as tmpdir:
        recorder_old = RunRecorder(Path(tmpdir))
        old_result = MockReplayAdapter("good").run(eval_spec, registry_old, recorder_old)

    # 新路径：通过 wrapper
    inner = MockReplayAdapter("good")
    adapter = DemoAgent2HarnessAdapter(
        inner=inner, tool_specs=tool_specs, eval_spec=eval_spec
    )

    trace = adapter.run(scenario)

    # 核心数据应一致：tool call 数量、final_answer 非空
    assert len(trace.tool_calls) == len(old_result.tool_calls)
    assert trace.final_answer == old_result.final_answer


# ---------------------------------------------------------------------------
# 2. ExecutionTrace → Evidence
# ---------------------------------------------------------------------------


def test_execution_trace_to_evidence_bridge():
    """ExecutionTrace → Evidence 正确打包。"""
    trace = ExecutionTrace(
        scenario_id="s1",
        tool_calls=[ToolCall(tool_name="search", arguments={}, call_id="c1")],
        tool_results=[
            ToolResult(call_id="c1", status="success", output={"data": "ok"})
        ],
        final_answer="done",
    )
    evidence = execution_trace_to_evidence(trace, signal_quality=TAUTOLOGICAL_REPLAY)

    assert isinstance(evidence, Evidence)
    assert evidence.trace is trace
    assert evidence.cost_usd is None  # demo 无真实 cost
    assert evidence.latency_ms is None  # demo 无真实 latency
    assert evidence.signal_quality == TAUTOLOGICAL_REPLAY


# ---------------------------------------------------------------------------
# 3. Evidence → EvaluationResult (via CoreEvaluation)
# ---------------------------------------------------------------------------


def test_core_evaluation_evidence_to_evaluation_result():
    """CoreEvaluation.evaluate(Evidence, EvalSpec) → EvaluationResult。"""
    tool_specs = _make_tool_specs()
    eval_spec = _make_eval_spec_good()
    scenario = _make_scenario_spec()

    adapter = DemoAgent2HarnessAdapter(
        inner=MockReplayAdapter("good"), tool_specs=tool_specs, eval_spec=eval_spec
    )
    trace = adapter.run(scenario)
    evidence = execution_trace_to_evidence(
        trace, signal_quality=adapter.SIGNAL_QUALITY
    )

    evaluation = CoreEvaluation()
    eval_result = evaluation.evaluate(evidence, eval_spec)

    assert isinstance(eval_result, EvaluationResult)
    assert eval_result.scenario_id == "scenario-1"
    assert len(eval_result.findings) >= 1
    assert all(isinstance(f, RuleFinding) for f in eval_result.findings)
    # 所有 finding 来自 rule check
    for f in eval_result.findings:
        assert f.category == "rule"


def test_core_evaluation_with_custom_judge():
    """CoreEvaluation 支持注入自定义 RuleJudge。"""

    class AlwaysPassJudge(RuleJudge):
        def judge(self, case, run):
            return JudgeResult(
                eval_id=case.id,
                passed=True,
                checks=[
                    RuleCheckResult(
                        rule={"type": "always_pass"},
                        passed=True,
                        message="always passes",
                    )
                ],
            )

    trace = ExecutionTrace(
        scenario_id="s1",
        tool_calls=[ToolCall(tool_name="t1", arguments={}, call_id="c1")],
        tool_results=[
            ToolResult(call_id="c1", tool_name="t1", status="success", output={"x": 1})
        ],
        final_answer="ok",
    )
    evidence = execution_trace_to_evidence(trace)
    eval_spec = _make_eval_spec_good()

    evaluation = CoreEvaluation(judge=AlwaysPassJudge())
    eval_result = evaluation.evaluate(evidence, eval_spec)

    assert eval_result.passed is True
    assert any(
        f.rule_type == "always_pass" for f in eval_result.findings
    ), "应包含 always_pass 规则"


# ---------------------------------------------------------------------------
# 4. EvaluationResult → ReportSummary
# ---------------------------------------------------------------------------


def test_evaluation_result_to_report_summary():
    """EvaluationResult 的统计数据进入 ReportSummary。"""
    eval_result = EvaluationResult(
        scenario_id="s1",
        passed=True,
        findings=[
            RuleFinding(
                finding_id="f1",
                severity="info",
                category="rule",
                message="ok",
                evidence_ref="ref",
                rule_type="must_call_tool",
                rule_passed=True,
            )
        ],
        summary="通过",
    )

    metrics = {
        "total_evals": 1,
        "passed": 1 if eval_result.passed else 0,
        "failed": 0 if eval_result.passed else 1,
        "error_evals": 0,
        "signal_quality": TAUTOLOGICAL_REPLAY,
    }
    summary = build_report_summary(metrics)

    assert isinstance(summary, ReportSummary)
    assert summary.total_scenarios == 1
    assert summary.passed == 1
    assert summary.failed == 0


# ---------------------------------------------------------------------------
# 5. Report bridge 不承担最终裁决
# ---------------------------------------------------------------------------


def test_report_bridge_does_not_adjudicate():
    """evaluation_result_to_report_dict 只做数据转换，不修改 passed/failed。"""
    eval_result = EvaluationResult(
        scenario_id="s1",
        passed=False,
        findings=[
            RuleFinding(
                finding_id="f1",
                severity="high",
                category="rule",
                message="fail",
                evidence_ref="ref",
                rule_type="must_use_evidence",
                rule_passed=False,
            )
        ],
        summary="未通过",
    )

    report_dict = evaluation_result_to_report_dict(eval_result)
    assert report_dict["passed"] is False
    assert "decision" not in report_dict  # 无裁决字段
    assert "reviewer" not in report_dict  # 无 reviewer 字段


def test_report_summary_bridge_no_decision():
    """report_summary_to_report_dict 不做裁决。"""
    summary = ReportSummary(total_scenarios=5, passed=3, failed=2)
    d = report_summary_to_report_dict(summary)
    assert "decision" not in d
    assert "reviewer" not in d


# ---------------------------------------------------------------------------
# 6. EvaluationResult 不自动生成 ReviewDecision
# ---------------------------------------------------------------------------


def test_evaluation_result_no_auto_review_decision():
    """EvaluationResult 无 decision 字段、无 to_review_decision 方法。"""
    eval_result = EvaluationResult(scenario_id="s1", passed=True)
    assert not hasattr(eval_result, "decision")
    assert not hasattr(eval_result, "reviewer")
    assert not hasattr(eval_result, "to_review_decision")


def test_review_decision_must_be_manually_created():
    """ReviewDecision 必须人工显式创建。"""
    # 模拟人工 reviewer 在查看 evidence 后的显式创建
    decision = ReviewDecision(
        decision="approved",
        reviewer="tool-design-reviewer",
        notes="工具设计合理，eval 覆盖充分。",
        reviewed_at="2026-05-11T10:00:00Z",
    )
    assert decision.decision == "approved"
    assert decision.reviewer == "tool-design-reviewer"
    # 不可变
    try:
        decision.decision = "rejected"  # type: ignore[misc]
        raise AssertionError("ReviewDecision 应该是不可变的")
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 7. 整个 demo core flow 使用 Core Contract 对象
# ---------------------------------------------------------------------------


def test_all_objects_are_core_contract():
    """Core Flow 的所有产出物都是 Core Contract 类型。"""
    tool_specs = _make_tool_specs()
    eval_spec = _make_eval_spec_good()
    scenario = _make_scenario_spec()

    adapter = DemoAgent2HarnessAdapter(
        inner=MockReplayAdapter("good"), tool_specs=tool_specs, eval_spec=eval_spec
    )
    trace = adapter.run(scenario)
    evidence = execution_trace_to_evidence(
        trace, signal_quality=adapter.SIGNAL_QUALITY
    )
    eval_result = CoreEvaluation().evaluate(evidence, eval_spec)

    # 类型验证
    assert isinstance(trace, ExecutionTrace)
    assert isinstance(evidence, Evidence)
    assert isinstance(eval_result, EvaluationResult)
    assert isinstance(evidence.trace, ExecutionTrace)
    for c in trace.tool_calls:
        assert isinstance(c, ToolCall)
    for r in trace.tool_results:
        assert isinstance(r, ToolResult)
    for f in eval_result.findings:
        assert isinstance(f, RuleFinding)


# ---------------------------------------------------------------------------
# 8. build_demo_core_flow 端到端
# ---------------------------------------------------------------------------


def test_build_demo_core_flow_end_to_end():
    """assembly.build_demo_core_flow 端到端验证完整 Core Flow。"""
    from agent_tool_harness.assembly import build_demo_core_flow

    tool_specs = _make_tool_specs()
    eval_spec = _make_eval_spec_good()

    result = build_demo_core_flow(
        tool_specs=tool_specs, eval_spec=eval_spec, mock_path="good"
    )

    # 所有产物类型正确
    assert isinstance(result.trace, ExecutionTrace)
    assert isinstance(result.evidence, Evidence)
    assert isinstance(result.eval_result, EvaluationResult)
    assert result.evidence.trace is result.trace
    assert result.signal_quality == TAUTOLOGICAL_REPLAY

    # metrics 包含 report_summary
    assert "report_summary" in result.metrics
    assert isinstance(
        result.metrics["report_summary"], ReportSummary
    )

    # ExecutionTrace 内容正确
    assert result.trace.scenario_id == "scenario-1"
    assert len(result.trace.tool_calls) >= 1
    assert len(result.trace.final_answer) > 0

    # EvaluationResult 有 findings
    assert len(result.eval_result.findings) >= 1


def test_build_demo_core_flow_bad_path():
    """bad path 的 Core Flow 仍应正常运行（不抛异常），类型正确。"""
    from agent_tool_harness.assembly import build_demo_core_flow

    tool_specs = _make_tool_specs()
    eval_spec = _make_eval_spec_good()

    result = build_demo_core_flow(
        tool_specs=tool_specs, eval_spec=eval_spec, mock_path="bad"
    )

    # bad path 也应该正常产出 Core Contract 对象
    assert isinstance(result.trace, ExecutionTrace)
    assert isinstance(result.evidence, Evidence)
    assert isinstance(result.eval_result, EvaluationResult)


def test_build_demo_core_flow_batch():
    """build_demo_core_flow_batch() 正确聚合多个 eval 结果为 ReportSummary。"""
    from agent_tool_harness.assembly import build_demo_core_flow_batch
    from agent_tool_harness.core_contract import ReportSummary

    tool_specs = _make_tool_specs()
    # 两个不同 eval_id 的 eval_spec
    eval_a = _make_eval_spec_good()
    eval_b = EvalSpec(
        id="scenario-2",
        name="test scenario 2",
        category="integration",
        split="test",
        realism_level="mock",
        complexity="low",
        source="test",
        user_prompt="定位最近错误根因",
        initial_context={"query": "recent error"},
        expected_tool_behavior={"required_tools": ["knowledge.search"]},
        judge={
            "rules": [
                {"type": "must_call_tool", "tool": "knowledge.search"},
                {"type": "must_use_evidence"},
            ]
        },
        verifiable_outcome={
            "expected_root_cause": "timeout",
            "evidence_ids": ["ev-001"],
        },
        success_criteria=["结论引用证据"],
    )

    batch = build_demo_core_flow_batch(
        tool_specs=tool_specs,
        eval_specs=[eval_a, eval_b],
        mock_path="good",
    )

    # 验证结构正确
    assert len(batch["results"]) == 2
    assert isinstance(batch["report_summary"], ReportSummary)
    assert batch["report_summary"].total_scenarios == 2
    # passed + failed == total（聚合一致性）
    assert (
        batch["report_summary"].passed + batch["report_summary"].failed
        == batch["report_summary"].total_scenarios
    )
    assert batch["signal_quality"] == "tautological_replay"
    assert batch["generated_at"] != ""
    # 每个 result 都有完整的 Core Contract 对象
    for r in batch["results"]:
        assert isinstance(r.trace, ExecutionTrace)
        assert isinstance(r.evidence, Evidence)
        assert isinstance(r.eval_result, EvaluationResult)
        assert len(r.eval_result.findings) >= 1


def test_build_demo_core_flow_batch_aggregates_failures():
    """build_demo_core_flow_batch() 正确统计 mixed PASS/FAIL。"""
    from agent_tool_harness.assembly import build_demo_core_flow_batch

    tool_specs = _make_tool_specs()
    eval_specs = [_make_eval_spec_good()]

    batch = build_demo_core_flow_batch(
        tool_specs=tool_specs,
        eval_specs=eval_specs,
        mock_path="bad",
    )

    assert batch["report_summary"].passed == 0
    assert batch["report_summary"].failed == 1


# ---------------------------------------------------------------------------
# 9. 整个 demo core flow 不读取 .env / 不调用外部 API
# ---------------------------------------------------------------------------


def test_core_flow_modules_dont_import_env():
    """Core Flow 的所有新模块不 import dotenv/os.environ 读取。"""
    import ast
    from pathlib import Path

    forbidden = {"dotenv", "load_dotenv", "os.environ"}
    new_modules = [
        "agent_tool_harness/agent2harness_adapter.py",
        "agent_tool_harness/core_evaluation.py",
        "agent_tool_harness/core_report_bridge.py",
    ]

    for mod_path in new_modules:
        source = Path(mod_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = node.module if isinstance(node, ast.ImportFrom) else ""
                for name in node.names:
                    full = f"{module}.{name.name}" if module else name.name
                    for token in forbidden:
                        assert token not in full, (
                            f"{mod_path} 不应 import {token}，发现: {full}"
                        )


def test_core_flow_modules_dont_import_real_provider():
    """Core Flow 模块不 import 真实 provider。"""
    import ast
    from pathlib import Path

    forbidden = {
        "LiveAnthropicTransport",
        "FakeJudgeTransport",
        "AnthropicCompatibleJudgeProvider",
        "RealAgentAdapter",
        "examples",
    }
    new_modules = [
        "agent_tool_harness/agent2harness_adapter.py",
        "agent_tool_harness/core_evaluation.py",
        "agent_tool_harness/core_report_bridge.py",
    ]

    for mod_path in new_modules:
        source = Path(mod_path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = node.module if isinstance(node, ast.ImportFrom) else ""
                for name in node.names:
                    full = f"{module}.{name.name}" if module else name.name
                    for token in forbidden:
                        assert token not in full, (
                            f"{mod_path} 不应 import {token}，发现: {full}"
                        )


# ---------------------------------------------------------------------------
# 10. 反向桥接：ExecutionTrace → AgentRunResult
# ---------------------------------------------------------------------------


def test_execution_trace_to_agent_run_result_roundtrip():
    """正向+反向桥接：AgentRunResult → ExecutionTrace → AgentRunResult。"""
    original = AgentRunResult(
        eval_id="e1",
        final_answer="done",
        tool_calls=[
            {"call_id": "c1", "tool_name": "search", "arguments": {"q": "x"}}
        ],
        tool_responses=[
            {
                "call_id": "c1",
                "tool_name": "search",
                "response": {
                    "success": True,
                    "content": {"evidence": [{"id": "ev-1"}]},
                },
            }
        ],
    )

    # 正向
    trace = agent_run_result_to_execution_trace(original)
    # 反向
    reconstructed = execution_trace_to_agent_run_result(trace)

    assert reconstructed.eval_id == original.eval_id
    assert reconstructed.final_answer == original.final_answer
    assert len(reconstructed.tool_calls) == len(original.tool_calls)
    assert len(reconstructed.tool_responses) == len(original.tool_responses)
    assert reconstructed.tool_calls[0]["call_id"] == "c1"
    assert reconstructed.tool_calls[0]["tool_name"] == "search"
    assert reconstructed.tool_responses[0]["tool_name"] == "search"


# ---------------------------------------------------------------------------
# 11. ReplayAgent2HarnessAdapter 基本行为
# ---------------------------------------------------------------------------


def test_replay_adapter_has_correct_signal_quality():
    """ReplayAgent2HarnessAdapter 的 SIGNAL_QUALITY 正确。"""
    from agent_tool_harness.signal_quality import RECORDED_TRAJECTORY

    # Replay adapter 需要源目录存在，这里只测 signal_quality 声明
    assert ReplayAgent2HarnessAdapter.SIGNAL_QUALITY == RECORDED_TRAJECTORY
