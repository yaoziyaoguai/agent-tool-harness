"""验证 signal_quality 边界披露真的写到了 metrics 与 report。

这一组测试不是单元覆盖率，而是“治理性测试”：它确保未来任何人改动 EvalRunner、
MockReplayAdapter 或 MarkdownReport 时，都不会无意中悄悄抹掉“当前是 mock replay”
这条对真实团队至关重要的能力边界声明。
"""

from __future__ import annotations

import json

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.loader import load_evals, load_project, load_tools
from agent_tool_harness.recorder.run_recorder import RunRecorder
from agent_tool_harness.runner.eval_runner import EvalRunner
from agent_tool_harness.signal_quality import (
    DESCRIPTIONS,
    REAL_AGENT,
    TAUTOLOGICAL_REPLAY,
    UNKNOWN,
    describe,
)
from agent_tool_harness.tools.registry import ToolRegistry


class _FakeRealAgentAdapter:
    """治理用 fake adapter：只为测试“真实 adapter 标签也会被透传”这一行为。

    它**不**调真实 LLM，也**不**生成有意义的 trajectory。它只是把 SIGNAL_QUALITY 设为
    ``REAL_AGENT`` 来证明 EvalRunner 透传逻辑工作，避免未来真实接入时被框架默默吞掉
    自报标签。这只是一个签名验证 fixture，不是模型 adapter 实现。
    """

    SIGNAL_QUALITY = REAL_AGENT

    def run(self, case: EvalSpec, registry: ToolRegistry, recorder: RunRecorder) -> AgentRunResult:
        # 写一条最终 transcript 让 runner 不抛异常；不调用任何工具。
        recorder.record_transcript(
            case.id,
            {"role": "assistant", "type": "final", "content": "fake real-agent answer"},
        )
        return AgentRunResult(case.id, "fake real-agent answer", [], [])


def test_mock_replay_adapter_declares_tautological_signal_quality():
    """MockReplayAdapter 必须显式声明 tautological_replay。

    这条断言锁死“当前 MVP 的 PASS 在结构上是必然的”这个事实，避免有人把 SIGNAL_QUALITY
    悄悄改成 real_agent 让 mock 看起来像真实评估。
    """

    assert MockReplayAdapter.SIGNAL_QUALITY == TAUTOLOGICAL_REPLAY


def test_runner_writes_signal_quality_into_metrics_and_report(tmp_path):
    """run 完成后 metrics.json 与 report.md 都必须显式写出 signal_quality。"""

    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")
    evals = load_evals("examples/runtime_debug/evals.yaml")

    EvalRunner().run(project, tools, evals, MockReplayAdapter("good"), tmp_path)

    metrics = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))
    report = (tmp_path / "report.md").read_text(encoding="utf-8")

    assert metrics["signal_quality"] == TAUTOLOGICAL_REPLAY
    assert metrics["signal_quality_note"] == DESCRIPTIONS[TAUTOLOGICAL_REPLAY]
    assert "Signal Quality" in report
    assert TAUTOLOGICAL_REPLAY in report
    # banner 必须真的出现，不是只渲染 level——这是给真实团队看的“别把 PASS 当真”警告。
    assert "MVP" in report
    assert "PASS/FAIL" in report


def test_runner_propagates_real_agent_label_when_adapter_declares_it(tmp_path):
    """真实 adapter 接入后，SIGNAL_QUALITY 必须被透传，而不是被 runner 强制覆盖。"""

    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")
    evals = load_evals("examples/runtime_debug/evals.yaml")

    EvalRunner().run(project, tools, evals, _FakeRealAgentAdapter(), tmp_path)
    metrics = json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))

    assert metrics["signal_quality"] == REAL_AGENT
    assert "agentic loop" in metrics["signal_quality_note"]


def test_describe_unknown_falls_back_safely():
    """unknown 等级不能让报告渲染失败。"""

    assert describe("not-a-real-level") == DESCRIPTIONS[UNKNOWN]
