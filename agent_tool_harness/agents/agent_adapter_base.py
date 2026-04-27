from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.recorder.run_recorder import RunRecorder
from agent_tool_harness.tools.registry import ToolRegistry


@dataclass
class AgentRunResult:
    """一次 Agent replay/run 的摘要。

    详细证据不放在这里，而是由 RunRecorder 写入 transcript/tool_calls/tool_responses。
    """

    eval_id: str
    final_answer: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tool_responses: list[dict[str, Any]] = field(default_factory=list)


class AgentAdapter(Protocol):
    """Agent adapter 协议。

    架构边界：
    - 负责把 eval case 转成 Agent 行为和 tool calls。
    - 不负责执行工具细节；调用 ToolRegistry。
    - 不负责评判成败；RuleJudge 根据 recorder 证据判断。

    这个边界保证真实模型 adapter 和 replay adapter 可以互换。
    """

    def run(
        self, case: EvalSpec, registry: ToolRegistry, recorder: RunRecorder
    ) -> AgentRunResult:
        ...
