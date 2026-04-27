from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_tool_harness.config.tool_spec import ToolSpec


@dataclass
class ToolExecutionResult:
    """工具执行结果。

    success/content/error/metadata 是 recorder 和 judge 的公共证据结构。不同 executor
    可以返回不同 content，但不应改变这个外层协议。
    """

    success: bool
    content: dict[str, Any]
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "content": self.content,
            "error": self.error,
            "metadata": self.metadata,
        }


class ToolExecutor(Protocol):
    """executor 协议。

    架构边界：
    - 负责确定性执行某类工具。
    - 不负责选择工具，也不负责判断 Agent 是否成功。
    - 后续 MCP/HTTP/Shell executor 只需实现这个协议即可接入 ToolRegistry。
    """

    def execute(self, tool: ToolSpec, arguments: dict[str, Any]) -> ToolExecutionResult:
        ...
