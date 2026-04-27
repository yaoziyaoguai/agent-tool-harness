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

    replay 约束：
    - good path 从 eval.expected_tool_behavior.required_tools 推导工具序列。
    - bad path 优先使用 judge 里的 forbidden_first_tool，模拟“第一步就选错工具”。
    - 参数从 ToolSpec.input_schema 和 eval.initial_context 推导，不把 runtime_debug demo 工具名写死
      在核心框架里。
    """

    def __init__(self, path: str = "good"):
        if path not in {"good", "bad"}:
            raise ValueError("mock path must be 'good' or 'bad'")
        self.path = path

    def run(
        self, case: EvalSpec, registry: ToolRegistry, recorder: RunRecorder
    ) -> AgentRunResult:
        """执行一条可复现 replay。

        MockReplayAdapter 不是生产模型能力，它只生成 deterministic good/bad 路径，用来验证
        recorder、judge、diagnosis 是否真的看工具调用链路。
        """

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
        """按 eval 声明的 required_tools 生成成功路径。

        这里的“成功”不是模型智能，而是 replay 夹具：它按 eval 要求调用关键证据工具，并在
        final_answer 中引用 verifiable_outcome/evidence，方便 RuleJudge 验证正路径。
        """

        tool_calls: list[dict[str, Any]] = []
        tool_responses: list[dict[str, Any]] = []

        required_tools = list(case.expected_tool_behavior.get("required_tools", []))
        for tool_name in required_tools:
            call, response = self._call_tool(
                case,
                registry,
                recorder,
                tool_name,
                self._arguments_for_tool(tool_name, case, registry),
            )
            tool_calls.append(call)
            tool_responses.append(response)

        final_answer = self._good_final_answer(case, tool_responses)
        recorder.record_transcript(
            case.id,
            {"role": "assistant", "type": "final", "content": final_answer},
        )
        return AgentRunResult(case.id, final_answer, tool_calls, tool_responses)

    def _run_bad(
        self, case: EvalSpec, registry: ToolRegistry, recorder: RunRecorder
    ) -> AgentRunResult:
        """生成一个可解释的失败路径。

        bad path 的目标是验证 harness 能抓住错误工具选择，而不是模拟某个 demo 业务。它只调用
        一个从 eval judge 规则推导出的错误首工具，并给出不含正确 root cause/evidence 的结论。
        """

        tool_calls: list[dict[str, Any]] = []
        tool_responses: list[dict[str, Any]] = []

        wrong_tool = self._bad_first_tool(case, registry)
        call, response = self._call_tool(
            case,
            registry,
            recorder,
            wrong_tool,
            self._arguments_for_tool(wrong_tool, case, registry),
        )
        tool_calls.append(call)
        tool_responses.append(response)

        final_answer = (
            "Root cause: surface symptom. The first observation looked suspicious, so the "
            "problem is likely in the visible symptom rather than the causal event chain."
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
        """记录并执行一次 replay 工具调用。

        这里在 tool_call 中附带 side_effects/qualified_name，是为了让 RuleJudge 未来或当前规则
        可以基于工具契约判断“证据前是否修改”。如果工具查找失败，execute 仍会返回
        success=false，runner/recorder 能保留误调用证据。
        """

        call_id = recorder.next_call_id(case.id)
        tool_metadata = self._tool_metadata(tool_name, registry)
        call = {
            "call_id": call_id,
            "eval_id": case.id,
            "tool_name": tool_name,
            "arguments": arguments,
            **tool_metadata,
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

    def _arguments_for_tool(
        self, tool_name: str, case: EvalSpec, registry: ToolRegistry
    ) -> dict[str, Any]:
        """从 ToolSpec.input_schema 和 initial_context 推导 mock 参数。

        这是用户项目自定义入口：只要 tools.yaml 的 required 参数名能在 initial_context 中找到，
        replay 就能生成项目自己的工具调用，而不需要核心框架认识具体业务字段。
        """

        try:
            tool = registry.get(tool_name)
        except Exception:  # noqa: BLE001 - 未知工具也要让 execute 产生失败响应。
            return {}
        schema = tool.input_schema or {}
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        arguments: dict[str, Any] = {}
        for name in required:
            if name in case.initial_context:
                arguments[name] = case.initial_context[name]
            else:
                arguments[name] = self._placeholder_value(name, properties.get(name, {}))
        if "response_format" in properties:
            arguments.setdefault("response_format", "concise")
        return arguments

    def _bad_first_tool(self, case: EvalSpec, registry: ToolRegistry) -> str:
        """选择 bad path 的第一工具。

        优先读取 judge 的 forbidden_first_tool，因为这正是 eval 作者声明的错误首步；如果没有，
        则选择一个不在 required_tools 里的工具，仍然避免写死 demo 名称。
        """

        for rule in case.judge.get("rules", []):
            if rule.get("type") == "forbidden_first_tool" and rule.get("tool"):
                return str(rule["tool"])
        required = set(case.expected_tool_behavior.get("required_tools", []))
        for tool_name in registry.list_names():
            if tool_name not in required:
                return tool_name
        names = registry.list_names()
        return names[0] if names else "__missing_mock_tool__"

    def _good_final_answer(
        self, case: EvalSpec, tool_responses: list[dict[str, Any]]
    ) -> str:
        """构造 good path 的最终回答。

        RuleJudge 会检查 root cause 和 evidence 引用，所以这里从 eval/verifiable_outcome 和真实
        工具响应中抽取 evidence id，而不是写死 demo 里的 ev-17。
        """

        root_cause = case.verifiable_outcome.get("expected_root_cause") or "expected_root_cause"
        evidence_ids = self._evidence_ids(case, tool_responses)
        evidence_text = ", ".join(evidence_ids) if evidence_ids else "tool evidence"
        return (
            f"Root cause: {root_cause}. Evidence: {evidence_text}. "
            "Next action: follow the tool-provided next_action and fix the causal boundary."
        )

    def _evidence_ids(
        self, case: EvalSpec, tool_responses: list[dict[str, Any]]
    ) -> list[str]:
        ids = [str(item) for item in case.verifiable_outcome.get("evidence_ids", [])]
        for response in tool_responses:
            content = response.get("response", {}).get("content", {})
            for evidence in content.get("evidence", []):
                if isinstance(evidence, dict) and evidence.get("id"):
                    ids.append(str(evidence["id"]))
        return list(dict.fromkeys(ids))

    def _tool_metadata(self, tool_name: str, registry: ToolRegistry) -> dict[str, Any]:
        try:
            tool = registry.get(tool_name)
        except Exception:  # noqa: BLE001 - unknown tool metadata should not block recording.
            return {}
        return {
            "qualified_name": tool.qualified_name,
            "side_effects": tool.side_effects,
        }

    def _placeholder_value(self, name: str, schema: dict[str, Any]) -> Any:
        """为缺失上下文生成 deterministic 占位参数。

        占位值不是为了让真实 eval 变正确；它只是让 mock replay 可以把“缺上下文”暴露为工具
        返回或 judge 失败，而不是因为参数缺失直接没有 transcript。
        """

        if schema.get("default") is not None:
            return schema["default"]
        value_type = schema.get("type")
        if value_type == "integer":
            return 0
        if value_type == "number":
            return 0.0
        if value_type == "boolean":
            return False
        if value_type == "array":
            return []
        if value_type == "object":
            return {}
        return f"mock-{name}"
