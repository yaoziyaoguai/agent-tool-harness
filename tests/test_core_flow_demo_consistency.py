"""Core Flow 与旧路径一致性回归测试。

测试纪律：
- 使用 examples/knowledge_search 的真实配置（不 mock eval spec），确保旧路径
  PASS 的关键 eval 在 Core Flow 路径不会因为 tool_name 丢失等信息损失而 FAIL。
- 测试不涉及 IO（不调 CLI，不写磁盘），纯 import 链路。
- 测试不调用真实 LLM。
"""

from __future__ import annotations

from pathlib import Path

from agent_tool_harness.agent2harness_adapter import DemoAgent2HarnessAdapter
from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.config.loader import load_evals, load_tools
from agent_tool_harness.core_contract import ScenarioSpec
from agent_tool_harness.core_evaluation import CoreEvaluation
from agent_tool_harness.demo_core_bridge import execution_trace_to_evidence
from agent_tool_harness.signal_quality import TAUTOLOGICAL_REPLAY

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "examples" / "knowledge_search"


def _load_kb_scenario() -> tuple[ScenarioSpec, list, object]:
    """加载 kb_sso_session_loss_regression 场景及配套工具/eval spec。"""
    tools = load_tools(EXAMPLE_DIR / "tools.yaml")
    evals = load_evals(EXAMPLE_DIR / "evals.yaml")
    eval_spec = evals[0]
    assert eval_spec.id == "kb_sso_session_loss_regression"

    scenario = ScenarioSpec(
        scenario_id=eval_spec.id,
        goal=eval_spec.user_prompt,
        available_tools=[t.qualified_name for t in tools],
        success_criteria=eval_spec.success_criteria,
    )
    return scenario, tools, eval_spec


def test_kb_sso_evidence_from_required_tools_passes_in_core_flow():
    """Core Flow 路径：evidence_from_required_tools 规则必须 PASS。

    这是 P0 回归测试：修复前 ToolResult 缺少 tool_name，导致 roundtrip 后
    evidence_from_required_tools 误报 FAIL（cited evidence only from non-required
    tool(s) ['']）。修复后该规则必须通过。
    """
    scenario, tools, eval_spec = _load_kb_scenario()

    adapter = DemoAgent2HarnessAdapter(
        inner=MockReplayAdapter("good"),
        tool_specs=tools,
        eval_spec=eval_spec,
    )
    trace = adapter.run(scenario)

    # 验证 ExecutionTrace 中 ToolResult 携带 tool_name
    for r in trace.tool_results:
        assert r.tool_name, (
            f"ToolResult tool_name 不应为空（修复前就是这里丢了信息导致 "
            f"evidence_from_required_tools FAIL），实际 tool_name={r.tool_name!r}"
        )

    evidence = execution_trace_to_evidence(
        trace, signal_quality=TAUTOLOGICAL_REPLAY
    )

    eval_result = CoreEvaluation().evaluate(evidence, eval_spec)

    # 定位 evidence_from_required_tools 规则
    finding = next(
        (f for f in eval_result.findings
         if f.rule_type == "evidence_from_required_tools"),
        None,
    )
    assert finding is not None, "eval 必须包含 evidence_from_required_tools 规则"
    assert finding.rule_passed, (
        f"evidence_from_required_tools 必须 PASS，"
        f"实际 rule_passed={finding.rule_passed}，"
        f"message={finding.message}"
    )


def test_kb_sso_all_rules_pass_in_core_flow():
    """Core Flow 路径：全部 8 条规则必须 PASS。

    kb_sso_session_loss_regression 在旧路径全部 PASS，修复后 Core Flow 路径
    也必须全部 PASS——不允许任何因 roundtrip 信息损失导致的 FAIL。
    """
    scenario, tools, eval_spec = _load_kb_scenario()

    adapter = DemoAgent2HarnessAdapter(
        inner=MockReplayAdapter("good"),
        tool_specs=tools,
        eval_spec=eval_spec,
    )
    trace = adapter.run(scenario)
    evidence = execution_trace_to_evidence(
        trace, signal_quality=TAUTOLOGICAL_REPLAY
    )
    eval_result = CoreEvaluation().evaluate(evidence, eval_spec)

    failed = [f for f in eval_result.findings if not f.rule_passed]
    assert not failed, (
        f"全部规则必须 PASS，实际 {len(failed)} 条 FAIL:\n"
        + "\n".join(f"  - {f.rule_type}: {f.message}" for f in failed)
    )
    assert len(eval_result.findings) == 17, (
        f"预期 17 条规则（8 eval-level + 9 trace-level），实际 {len(eval_result.findings)} 条"
    )
    assert eval_result.passed is True
