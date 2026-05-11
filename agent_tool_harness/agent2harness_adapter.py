"""Agent2HarnessAdapter 的 demo 实现 —— 包装旧 demo/replay adapter。

架构边界
--------
- **负责**：把旧 MockReplayAdapter / TranscriptReplayAdapter 包装成
  Agent2HarnessAdapter Protocol 的实现，对外暴露 Core Contract 接口：
  ``run(ScenarioSpec) -> ExecutionTrace``。
- **不负责**：不修改旧 adapter 内部逻辑、不实现真实 Agent、不调 LLM。
- **为什么是 wrapper 而非直接改旧 adapter**：
  1. 旧 adapter 仍在生产链路（EvalRunner + CLI）中稳定工作，签名
     ``run(case, registry, recorder) -> AgentRunResult`` 被全量测试覆盖。
  2. Wrapper 让新旧两套接口并存——CLI 继续走旧路径，Core Flow 走新路径。
  3. 当旧 EvalRunner 迁移到 Core Flow 后，旧 adapter 可以安全退役。
- **为什么 demo 用假材料跑真实 Core Flow**：Demo 和 Real 共用同一套 Core Flow
  对象和契约。Demo 的 ExecutionTrace / Evidence / EvaluationResult 在结构上
  与未来 Real 的完全一致，差异仅在于 trace 的来源（mock replay vs LLM agentic loop）。
  这意味着今天在 demo 上验证的所有下游逻辑（judge / report / review），
  明天接真实 Agent 时不需要修改。

未来扩展点
----------
- 当旧 EvalRunner 退役后，本 wrapper 的内层 adapter 调用逻辑可内联简化
- RealAgentAdapter 将在未来轮次独立实现 Agent2HarnessAdapter Protocol，
  不经过本 wrapper
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.core_contract import ExecutionTrace, ScenarioSpec
from agent_tool_harness.demo_core_bridge import agent_run_result_to_execution_trace
from agent_tool_harness.recorder.run_recorder import RunRecorder
from agent_tool_harness.signal_quality import RECORDED_TRAJECTORY, TAUTOLOGICAL_REPLAY
from agent_tool_harness.tools.registry import ToolRegistry


class DemoAgent2HarnessAdapter:
    """包装 MockReplayAdapter，实现 Agent2HarnessAdapter Protocol。

    SIGNAL_QUALITY = tautological_replay —— good path 的"通过"是结构性必然，
    因为 adapter 直接读 eval 的期望并回放给 RuleJudge。任何看到这个标签的
    真实团队都应该理解：当前 PASS 不能解读为"工具对真实 Agent 好用"。
    """

    SIGNAL_QUALITY = TAUTOLOGICAL_REPLAY

    def __init__(
        self,
        inner,  # MockReplayAdapter
        tool_specs: list[ToolSpec],
        eval_spec: EvalSpec,
        *,
        recorder_dir: str | Path | None = None,
    ):
        """初始化 wrapper。

        inner: MockReplayAdapter 实例（已配置 good/bad path）
        tool_specs: ToolSpec 列表，用于构造 ToolRegistry
        eval_spec: 旧 EvalSpec，用于调用 inner.run()
        recorder_dir: 可选，RunRecorder 输出目录；默认 temp dir
        """
        self._inner = inner
        self._tool_specs = list(tool_specs)
        self._eval_spec = eval_spec
        self._recorder_dir = recorder_dir

    def run(self, scenario: ScenarioSpec) -> ExecutionTrace:
        """执行一条 demo replay，返回 Core Contract ExecutionTrace。

        内部流程：
        1. 用 tool_specs 构造 ToolRegistry
        2. 创建 RunRecorder（temp dir 或指定目录）
        3. 调用 inner.run(eval_spec, registry, recorder) → AgentRunResult
        4. 桥接 AgentRunResult → ExecutionTrace
        """
        registry = ToolRegistry(self._tool_specs)
        recorder = self._make_recorder()
        agent_result = self._inner.run(self._eval_spec, registry, recorder)
        return agent_run_result_to_execution_trace(
            agent_result, scenario_id=scenario.scenario_id
        )

    def _make_recorder(self) -> RunRecorder:
        if self._recorder_dir is not None:
            return RunRecorder(Path(self._recorder_dir))
        return RunRecorder(Path(tempfile.mkdtemp(prefix="demo-core-")))

    def run_raw(self) -> AgentRunResult:
        """直接返回旧 AgentRunResult，供 CoreEvaluation 用。

        这个方法暴露旧对象，让调用方可以同时获得 ExecutionTrace（通过 run()）
        和 AgentRunResult（通过本方法），避免 CoreEvaluation 需要做反向桥接。

        这是临时暴露——后续轮次 RuleJudge 适配 Core Contract 后移除。
        """
        registry = ToolRegistry(self._tool_specs)
        recorder = self._make_recorder()
        return self._inner.run(self._eval_spec, registry, recorder)


class ReplayAgent2HarnessAdapter:
    """包装 TranscriptReplayAdapter，实现 Agent2HarnessAdapter Protocol。

    SIGNAL_QUALITY = recorded_trajectory —— 比 tautological_replay 高，
    但仍不是 real_agent。历史 trajectory 不等于"当前模型对当前工具集还会做出同样选择"。
    """

    SIGNAL_QUALITY = RECORDED_TRAJECTORY

    def __init__(
        self,
        inner,  # TranscriptReplayAdapter
        tool_specs: list[ToolSpec],
        eval_spec: EvalSpec,
        *,
        recorder_dir: str | Path | None = None,
    ):
        self._inner = inner
        self._tool_specs = list(tool_specs)
        self._eval_spec = eval_spec
        self._recorder_dir = recorder_dir

    def run(self, scenario: ScenarioSpec) -> ExecutionTrace:
        """重放历史 trajectory，返回 Core Contract ExecutionTrace。"""
        registry = ToolRegistry(self._tool_specs)
        recorder = self._make_recorder()
        agent_result = self._inner.run(self._eval_spec, registry, recorder)
        return agent_run_result_to_execution_trace(
            agent_result, scenario_id=scenario.scenario_id
        )

    def _make_recorder(self) -> RunRecorder:
        if self._recorder_dir is not None:
            return RunRecorder(Path(self._recorder_dir))
        return RunRecorder(Path(tempfile.mkdtemp(prefix="replay-core-")))

    def run_raw(self) -> AgentRunResult:
        """直接返回旧 AgentRunResult。临时暴露，后续轮次移除。"""
        registry = ToolRegistry(self._tool_specs)
        recorder = self._make_recorder()
        return self._inner.run(self._eval_spec, registry, recorder)
