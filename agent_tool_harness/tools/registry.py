from __future__ import annotations

from typing import Any

from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.tools.executor_base import ToolExecutionResult, ToolExecutor
from agent_tool_harness.tools.python_executor import PythonToolExecutor


class ToolRegistry:
    """工具注册表。

    架构边界：
    - 负责按 name/qualified_name 查找 ToolSpec，并把执行分发给对应 executor。
    - 不负责 Agent 决策，不负责审计工具设计，也不负责 judge。
    - 通过 executor 类型扩展执行能力，避免在 runner 里写死 Python/MCP/HTTP 逻辑。
    """

    def __init__(self, tools: list[ToolSpec], executors: dict[str, ToolExecutor] | None = None):
        self.tools = list(tools)
        self.by_name = {tool.name: tool for tool in self.tools}
        self.by_qualified_name = {tool.qualified_name: tool for tool in self.tools}
        self.executors: dict[str, ToolExecutor] = {"python": PythonToolExecutor()}
        if executors:
            self.executors.update(executors)

    def get(self, name: str) -> ToolSpec:
        if name in self.by_name:
            return self.by_name[name]
        if name in self.by_qualified_name:
            return self.by_qualified_name[name]
        raise KeyError(f"unknown tool: {name}")

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        tool = self.get(name)
        executor_type = str(tool.executor.get("type", "python"))
        executor = self.executors.get(executor_type)
        if executor is None:
            return ToolExecutionResult(
                success=False,
                content={
                    "summary": f"Unsupported executor type: {executor_type}",
                    "evidence": [],
                    "next_action": "注册对应 executor，或修改 tools.yaml executor.type。",
                },
                error=f"unsupported executor: {executor_type}",
                metadata={"tool": tool.name},
            )
        return executor.execute(tool, arguments)

    def list_names(self) -> list[str]:
        return [tool.name for tool in self.tools]
