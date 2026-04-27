from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.recorder.run_recorder import RunRecorder
from agent_tool_harness.signal_quality import UNKNOWN
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
    - 必须显式声明 ``SIGNAL_QUALITY``，把当前实现的信号质量等级披露给 EvalRunner，
      以便报告/metrics 明确告诉真实团队 PASS/FAIL 是否可作为评估依据。

    这个边界保证真实模型 adapter 和 replay adapter 可以互换；同时也防止
    “看起来通过”的 mock 路径被误读为“工具好用”。

    用户项目自定义入口：
    - 真实 OpenAI/Anthropic adapter 落地后应在子类上覆盖 ``SIGNAL_QUALITY`` 为
      ``signal_quality.REAL_AGENT``；任何不显式声明的 adapter 会以 ``UNKNOWN`` 显示。
    """

    # adapter 实现者必须显式声明信号质量等级。这里给 Protocol 一个默认值，是为了让
    # 类型检查能识别该属性，但生产代码里不应依赖默认值——见 ``signal_quality`` 模块。
    SIGNAL_QUALITY: str = UNKNOWN

    def run(
        self, case: EvalSpec, registry: ToolRegistry, recorder: RunRecorder
    ) -> AgentRunResult:
        ...
