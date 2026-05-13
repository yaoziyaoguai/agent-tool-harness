"""Runtime assembly 层 — Demo/Core 边界的第一道闸门。

提供两套装配函数：
1. 旧 AgentAdapter 装配（CLI 使用，保持向后兼容）
   - build_demo_runtime() → MockReplayAdapter
   - build_replay_runtime() → TranscriptReplayAdapter

2. Core Flow 装配
   - build_demo_core_flow() → DemoCoreFlowResult

架构边界：
- **负责**：把参数转成实例，隐藏具体类型。
- **不负责**：不实现真实 Agent、不读取 .env、不调用外部 API。
- **为什么 CLI 不应该直接硬编码 adapter 类型**：
  CLI 是 Core 的装配层，不应直接依赖 Demo 实现。
  通过 assembly 函数接入，让未来可以替换 adapter 而不修改 CLI 结构。
- **ReviewDecision 不在此层生成**：
  ReviewDecision 必须由人工 Reviewer 显式创建。assembly 只装配机器产出链路。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_tool_harness.agents.agent_adapter_base import AgentAdapter


@dataclass
class DemoCoreFlowResult:
    """一次 demo Core Flow 的完整产物。

    包含从 ScenarioSpec 到 ReportSummary 的所有 Core Contract 对象。
    这是纯数据——不包含 IO 引用、不包含 adapter 实例、不包含 file path。
    """

    trace: Any  # ExecutionTrace，避免顶层 import 用 Any
    evidence: Any  # Evidence
    eval_result: Any  # EvaluationResult
    signal_quality: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)


def build_demo_runtime(mock_path: str = "good") -> AgentAdapter:
    """装配当前 demo/mock runtime 的 AgentAdapter。

    当前实现：返回 MockReplayAdapter，按 good/bad 分支回放工具调用。
    signal_quality = tautological_replay。

    未来 Real Integration 必须：
    - 通过独立的 factory 函数接入（如 build_real_runtime）
    - 显式 opt-in（--live --confirm-i-have-real-key）
    - 不通过此函数混入 demo path
    """
    from agent_tool_harness.agents.mock_replay_adapter import (
        MockReplayAdapter,
    )

    return MockReplayAdapter(mock_path)


def build_replay_runtime(source_run: str | Path) -> AgentAdapter:
    """装配历史轨迹重放 runtime 的 AgentAdapter。

    当前实现：返回 TranscriptReplayAdapter，按历史 transcript 重放。
    signal_quality = recorded_trajectory。
    """
    from agent_tool_harness.agents.transcript_replay_adapter import (
        TranscriptReplayAdapter,
    )

    return TranscriptReplayAdapter(source_run)


# ---------------------------------------------------------------------------
# Core Flow 装配
# ---------------------------------------------------------------------------


def build_demo_core_flow(
    *,
    tool_specs: list[Any],
    eval_spec: Any,
    mock_path: str = "good",
    judge_provider: Any = None,
) -> DemoCoreFlowResult:
    """装配并运行一次完整的 demo Core Flow。

    这是 Agent2Harness 主流程的最小端到端入口：
    ScenarioSpec → DemoAgent2HarnessAdapter → ExecutionTrace
    → Evidence → CoreEvaluation → EvaluationResult → ReportSummary

    当前仅支持 demo/mock 材料——所有工具调用来自 MockReplayAdapter，
    signal_quality = tautological_replay。

    真实 Agent trace 应通过 TraceImportAdapter 导入，不走此函数。

    Args:
        tool_specs: ToolSpec 列表
        eval_spec: EvalSpec 实例
        mock_path: "good" 或 "bad"
        judge_provider: 可选 CoreJudgeProvider（如 FakeJudgeProvider），
            传入后 CoreEvaluation 将并列产出 RuleFinding + JudgeFinding

    Returns:
        DemoCoreFlowResult: 包含 trace, evidence, eval_result, signal_quality, metrics
    """
    from agent_tool_harness.agent2harness_adapter import DemoAgent2HarnessAdapter
    from agent_tool_harness.core_evaluation import CoreEvaluation
    from agent_tool_harness.demo_core_bridge import (
        build_report_summary,
        execution_trace_to_evidence,
    )

    # EvalSpec → ScenarioSpec
    scenario = _eval_to_scenario(eval_spec, tool_specs)

    # 装配旧 MockReplayAdapter（不改旧组件）
    inner = build_demo_runtime(mock_path)

    # 包装为 DemoAgent2HarnessAdapter
    wrapper = DemoAgent2HarnessAdapter(
        inner=inner,
        tool_specs=list(tool_specs),
        eval_spec=eval_spec,
    )

    # Step 1: ScenarioSpec → ExecutionTrace
    trace = wrapper.run(scenario)

    # Step 2: ExecutionTrace → Evidence
    evidence = execution_trace_to_evidence(
        trace, signal_quality=wrapper.SIGNAL_QUALITY
    )

    # Step 3: Evidence → EvaluationResult（通过 CoreEvaluation + RuleJudge）
    evaluation = CoreEvaluation(judge_provider=judge_provider)
    eval_result = evaluation.evaluate(evidence, eval_spec)

    # Step 4: metrics → ReportSummary
    metrics = {
        "total_evals": 1,
        "passed": 1 if eval_result.passed else 0,
        "failed": 0 if eval_result.passed else 1,
        "error_evals": 0,
        "signal_quality": wrapper.SIGNAL_QUALITY,
    }
    report_summary = build_report_summary(metrics)

    return DemoCoreFlowResult(
        trace=trace,
        evidence=evidence,
        eval_result=eval_result,
        signal_quality=wrapper.SIGNAL_QUALITY,
        metrics={
            "report_summary": report_summary,
            **metrics,
        },
    )


def build_demo_core_flow_batch(
    *,
    tool_specs: list[Any],
    eval_specs: list[Any],
    mock_path: str = "good",
    judge_provider: Any = None,
) -> dict[str, Any]:
    """装配并运行批量 demo Core Flow——一条命令跑多个 eval。

    这是 build_demo_core_flow() 的批量版本，供 CLI --core-flow 路径使用。
    为每个 eval_spec 独立运行 Core Flow，最后聚合 metrics 和一个 ReportSummary。

    Args:
        tool_specs: ToolSpec 列表
        eval_specs: EvalSpec 列表
        mock_path: "good" 或 "bad"
        judge_provider: 可选 CoreJudgeProvider，转发给每个 build_demo_core_flow() 调用

    Returns:
        dict 包含:
        - results: list[DemoCoreFlowResult] — 每个 eval 的 Core Flow 完整产物
        - report_summary: ReportSummary — 聚合统计
        - signal_quality: str
        - generated_at: str
    """
    from datetime import UTC, datetime

    from agent_tool_harness.core_contract import ReportSummary

    results: list[DemoCoreFlowResult] = []
    for eval_spec in eval_specs:
        result = build_demo_core_flow(
            tool_specs=tool_specs,
            eval_spec=eval_spec,
            mock_path=mock_path,
            judge_provider=judge_provider,
        )
        results.append(result)

    total = len(results)
    passed_count = sum(1 for r in results if r.eval_result.passed)
    failed_count = total - passed_count

    report_summary = ReportSummary(
        total_scenarios=total,
        passed=passed_count,
        failed=failed_count,
        errors=0,
        signal_quality=results[0].signal_quality if results else "",
        generated_at=datetime.now(UTC).isoformat(),
    )

    return {
        "results": results,
        "report_summary": report_summary,
        "signal_quality": report_summary.signal_quality,
        "generated_at": report_summary.generated_at,
    }


def _eval_to_scenario(eval_spec: Any, tool_specs: list[Any]) -> Any:
    """从 EvalSpec + ToolSpec 列表构造 ScenarioSpec。"""
    from agent_tool_harness.config.eval_spec import EvalSpec
    from agent_tool_harness.config.tool_spec import ToolSpec
    from agent_tool_harness.core_contract import ScenarioSpec

    available_tools = [t.qualified_name for t in tool_specs if isinstance(t, ToolSpec)]
    return ScenarioSpec(
        scenario_id=eval_spec.id if isinstance(eval_spec, EvalSpec) else str(eval_spec),
        goal=getattr(eval_spec, "user_prompt", ""),
        available_tools=available_tools,
        success_criteria=list(
            getattr(eval_spec, "success_criteria", []) or []
        ),
    )
