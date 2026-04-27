from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.tools.executor_base import ToolExecutionResult


class PythonToolExecutor:
    """执行本地 Python demo/user 工具。

    架构边界：
    - 只负责根据 tools.yaml executor 配置导入函数并调用。
    - 不负责 Agent 工具选择；MockReplayAdapter 或未来真实模型 adapter 决定调用顺序。
    - 不负责 judge；执行结果只作为 recorder/judge/analyzer 的证据。

    为什么这样拆：
    Python executor 是 MVP 的最小可运行 executor。未来 MCP、HTTP、Shell executor 可以并行
    实现同一个 ToolExecutor 协议，而不影响 runner/judge/report。
    """

    def execute(self, tool: ToolSpec, arguments: dict[str, Any]) -> ToolExecutionResult:
        try:
            function = self._load_function(tool)
            content = self._call(function, arguments)
            if not isinstance(content, dict):
                content = {"value": content}
            return ToolExecutionResult(
                success=True,
                content=content,
                metadata={"executor": "python", "function": function.__name__},
            )
        except Exception as exc:  # noqa: BLE001 - 工具错误必须被记录为证据，而不是吞掉。
            return ToolExecutionResult(
                success=False,
                content={
                    "summary": "Python tool execution failed.",
                    "evidence": [],
                    "next_action": "检查 executor 配置、参数 schema 和工具函数异常。",
                },
                error=str(exc),
                metadata={"traceback": traceback.format_exc(limit=5)},
            )

    def _load_function(self, tool: ToolSpec) -> Callable[..., Any]:
        config = tool.executor
        function_name = config.get("function")
        if not function_name:
            raise ValueError(f"python executor for {tool.name} requires function")

        if config.get("path"):
            module = self._load_module_from_path(tool, str(config["path"]))
        elif config.get("module"):
            module = importlib.import_module(str(config["module"]))
        else:
            raise ValueError(f"python executor for {tool.name} requires path or module")

        function = getattr(module, str(function_name), None)
        if function is None or not callable(function):
            raise ValueError(f"function not found or not callable: {function_name}")
        return function

    def _load_module_from_path(self, tool: ToolSpec, configured_path: str):
        base_dir = Path(str(tool.executor.get("__base_dir", ".")))
        path = Path(configured_path)
        if not path.is_absolute():
            path = base_dir / path
        if not path.exists():
            raise FileNotFoundError(path)
        module_name = f"_ath_user_tool_{path.stem}_{abs(hash(path))}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load module from {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
        return module

    def _call(self, function: Callable[..., Any], arguments: dict[str, Any]) -> Any:
        signature = inspect.signature(function)
        if len(signature.parameters) == 1:
            first = next(iter(signature.parameters.values()))
            if first.kind in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }:
                return function(arguments)
        return function(**arguments)
