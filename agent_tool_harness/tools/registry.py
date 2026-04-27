from __future__ import annotations

from collections import Counter
from typing import Any

from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.tools.executor_base import ToolExecutionResult, ToolExecutor
from agent_tool_harness.tools.python_executor import PythonToolExecutor


class ToolRegistryError(ValueError):
    """工具注册/查找错误。

    这个异常表示“框架无法明确定位一个工具”，不是工具函数自身失败。Registry 的 public
    `get` 会抛出它，方便配置加载或测试尽早暴露问题；`execute` 会把它转换成
    ToolExecutionResult(success=false)，确保 Agent 调错工具时仍能写入 tool_responses.jsonl。
    """


class ToolRegistry:
    """工具注册表。

    架构边界：
    - 负责按 name/qualified_name 查找 ToolSpec，并把执行分发给对应 executor。
    - 不负责 Agent 决策，不负责审计工具设计，也不负责 judge。
    - 通过 executor 类型扩展执行能力，避免在 runner 里写死 Python/MCP/HTTP 逻辑。

    设计原则：
    - qualified_name 必须唯一，否则框架无法可靠执行，初始化时直接失败。
    - 简短 name 如果重复，不静默覆盖；必须用 namespace.name 调用。
    - execute 捕获查找错误并返回失败结果，是为了让 recorder 能留下真实误调用证据。
    """

    def __init__(self, tools: list[ToolSpec], executors: dict[str, ToolExecutor] | None = None):
        """建立工具索引。

        用户项目可以选择同名但不同 namespace 的工具；这种情况下 Registry 会保留这些工具，
        但禁止用短名调用，避免 Agent 或测试误以为短名能唯一指向某个实现。
        """

        self.tools = list(tools)
        name_counts = Counter(tool.name for tool in self.tools)
        qualified_counts = Counter(tool.qualified_name for tool in self.tools)
        duplicate_qualified = [
            name for name, count in qualified_counts.items() if count > 1
        ]
        if duplicate_qualified:
            raise ToolRegistryError(
                f"duplicate qualified tool names: {', '.join(sorted(duplicate_qualified))}"
            )
        self.ambiguous_names = {name for name, count in name_counts.items() if count > 1}
        self.by_name = {
            tool.name: tool for tool in self.tools if tool.name not in self.ambiguous_names
        }
        self.by_qualified_name = {tool.qualified_name: tool for tool in self.tools}
        self.executors: dict[str, ToolExecutor] = {"python": PythonToolExecutor()}
        if executors:
            self.executors.update(executors)

    def get(self, name: str) -> ToolSpec:
        """按短名或 qualified_name 查找工具。

        这里故意对歧义短名抛错，而不是选择第一个或最后一个。工具选择错误是 Agent eval
        里最重要的证据之一，Registry 不能制造“看起来可运行”的错误路径。
        """

        if name in self.ambiguous_names:
            matches = [
                tool.qualified_name for tool in self.tools if tool.name == name
            ]
            raise ToolRegistryError(
                f"ambiguous tool name '{name}', use one of: {', '.join(sorted(matches))}"
            )
        if name in self.by_name:
            return self.by_name[name]
        if name in self.by_qualified_name:
            return self.by_qualified_name[name]
        raise ToolRegistryError(f"unknown tool: {name}")

    def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult:
        """执行工具并把查找/执行问题都规范化为 ToolExecutionResult。

        Agent 调用未知工具或歧义短名时，这仍然是一条必须落盘的 tool_response；因此这里不把
        registry 错误继续抛给 runner，而是返回 success=false 和可行动的 next_action。
        """

        try:
            tool = self.get(name)
        except ToolRegistryError as exc:
            return ToolExecutionResult(
                success=False,
                content={
                    "summary": "Tool lookup failed.",
                    "evidence": [],
                    "next_action": "检查 tool_name 是否存在，或改用 namespace.name 消除歧义。",
                },
                error=str(exc),
                metadata={"tool": name, "error_type": "tool_registry"},
            )
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
