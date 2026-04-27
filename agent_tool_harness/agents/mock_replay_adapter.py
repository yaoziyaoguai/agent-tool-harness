from __future__ import annotations

from typing import Any

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.recorder.run_recorder import RunRecorder
from agent_tool_harness.tools.registry import ToolRegistry


class MockReplayAdapter:
    """可复现的 replay adapter。

    架构边界：
    - 只模拟 Agent 的 tool-use 路径，不调用真实 LLM。
    - 通过 good/bad 两条路径验证 harness 是否真的看 transcript 和 tool_calls。
    - 不写死用户业务逻辑到框架核心；它只按 eval 的 initial_context 填参数，demo 语义在
      examples/runtime_debug/demo_tools.py 中。

    当前 MVP 先用 MockReplayAdapter，是为了让 audit/record/judge/diagnose/report 闭环可测。
    未来真实 OpenAI/Anthropic adapter 应保持同样的 recorder 写入协议。
    """

    def __init__(self, path: str = "good"):
        if path not in {"good", "bad"}:
            raise ValueError("mock path must be 'good' or 'bad'")
        self.path = path

    def run(
        self, case: EvalSpec, registry: ToolRegistry, recorder: RunRecorder
    ) -> AgentRunResult:
        recorder.record_transcript(
            case.id,
            {
                "role": "user",
                "type": "message",
                "content": case.user_prompt,
                "metadata": {"initial_context": case.initial_context},
            },
        )
        recorder.record_transcript(
            case.id,
            {
                "role": "assistant",
                "type": "message",
                "content": "我会先查看可用证据，再给出根因判断。",
            },
        )
        if self.path == "good":
            return self._run_good(case, registry, recorder)
        return self._run_bad(case, registry, recorder)

    def _run_good(
        self, case: EvalSpec, registry: ToolRegistry, recorder: RunRecorder
    ) -> AgentRunResult:
        tool_calls: list[dict[str, Any]] = []
        tool_responses: list[dict[str, Any]] = []

        trace_args = {
            "trace_id": case.initial_context.get("trace_id", "trace-demo-001"),
            "focus": "input_boundary",
            "response_format": "concise",
        }
        call, response = self._call_tool(
            case, registry, recorder, "runtime_trace_event_chain", trace_args
        )
        tool_calls.append(call)
        tool_responses.append(response)

        checkpoint_args = {
            "checkpoint_id": case.initial_context.get("checkpoint_id", "ckpt-input-17"),
            "response_format": "concise",
        }
        call, response = self._call_tool(
            case, registry, recorder, "runtime_inspect_checkpoint", checkpoint_args
        )
        tool_calls.append(call)
        tool_responses.append(response)

        final_answer = (
            "Root cause: input_boundary mismatch. Evidence: trace event ev-17 shows the "
            "runtime accepted a TUI payload after the checkpoint boundary, and checkpoint "
            "ckpt-input-17 confirms the stale input buffer. Next action: fix boundary validation."
        )
        recorder.record_transcript(
            case.id,
            {"role": "assistant", "type": "final", "content": final_answer},
        )
        return AgentRunResult(case.id, final_answer, tool_calls, tool_responses)

    def _run_bad(
        self, case: EvalSpec, registry: ToolRegistry, recorder: RunRecorder
    ) -> AgentRunResult:
        tool_calls: list[dict[str, Any]] = []
        tool_responses: list[dict[str, Any]] = []

        snapshot_args = {
            "session_id": case.initial_context.get("session_id", "session-demo-001"),
            "response_format": "concise",
        }
        call, response = self._call_tool(
            case, registry, recorder, "tui_inspect_snapshot", snapshot_args
        )
        tool_calls.append(call)
        tool_responses.append(response)

        final_answer = (
            "Root cause: UI rendering issue. The snapshot looks inconsistent, so the problem "
            "is likely a stale terminal render."
        )
        recorder.record_transcript(
            case.id,
            {"role": "assistant", "type": "final", "content": final_answer},
        )
        return AgentRunResult(case.id, final_answer, tool_calls, tool_responses)

    def _call_tool(
        self,
        case: EvalSpec,
        registry: ToolRegistry,
        recorder: RunRecorder,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        call_id = recorder.next_call_id(case.id)
        call = {
            "call_id": call_id,
            "eval_id": case.id,
            "tool_name": tool_name,
            "arguments": arguments,
        }
        recorder.record_tool_call(call)
        recorder.record_transcript(
            case.id,
            {
                "role": "assistant",
                "type": "tool_call",
                "call_id": call_id,
                "tool_name": tool_name,
                "arguments": arguments,
            },
        )

        result = registry.execute(tool_name, arguments)
        response = {
            "call_id": call_id,
            "eval_id": case.id,
            "tool_name": tool_name,
            "response": result.to_dict(),
        }
        recorder.record_tool_response(response)
        recorder.record_transcript(
            case.id,
            {
                "role": "tool",
                "type": "tool_response",
                "call_id": call_id,
                "tool_name": tool_name,
                "content": result.to_dict(),
            },
        )
        return call, response
