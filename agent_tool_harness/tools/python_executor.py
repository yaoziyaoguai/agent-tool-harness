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

    执行约束：
    - 调用用户函数前先做最小 JSON Schema 校验，避免明显错误参数触发副作用。
    - 单参数函数会按参数名智能绑定；`args/arguments/payload` 仍接收整个 dict，普通
      `query`/`trace_id` 这类参数则接收对应值。
    - 任何异常都会转成 ToolExecutionResult(success=false)，让 recorder 能保留失败证据。
    """

    def execute(self, tool: ToolSpec, arguments: dict[str, Any]) -> ToolExecutionResult:
        """执行一个 Python 工具。

        这个 public 方法是 ToolRegistry 调用 executor 的统一入口。它不决定 Agent 是否选对
        工具，也不判定 eval 是否通过；它只负责“尽量确定性地调用用户函数并返回证据结构”。
        """

        try:
            validation_error = self._validate_arguments(tool, arguments)
            if validation_error:
                return ToolExecutionResult(
                    success=False,
                    content={
                        "summary": "Tool arguments failed input_schema validation.",
                        "evidence": [],
                        "next_action": "根据 tools.yaml input_schema 修正参数后重试。",
                    },
                    error=validation_error,
                    metadata={"executor": "python", "tool": tool.name},
                )
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
        """根据 ToolSpec.executor 导入用户函数。

        path 相对 tools.yaml 所在目录解析，这是用户项目自定义工具的主要入口。这里不缓存模块，
        目的是让测试和本地 demo 在短生命周期进程里更容易复现当前文件内容。
        """

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
        """把 arguments 绑定到用户函数。

        早期 demo 工具使用 `def tool(args)` 接收整包参数；真实项目更常见的是
        `def search(query: str)`。这里同时支持两种风格，避免 executor 把单字段工具误传成
        dict，造成用户函数看似执行但语义错误。
        """

        signature = inspect.signature(function)
        positional_params = [
            param
            for param in signature.parameters.values()
            if param.kind
            in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }
        ]
        if len(signature.parameters) == 1 and positional_params:
            first = positional_params[0]
            if first.kind in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
            }:
                if first.name in {"args", "arguments", "payload"}:
                    return function(arguments)
                if first.name in arguments:
                    return function(arguments[first.name])
                return function(arguments)
        return function(**arguments)

    def _validate_arguments(self, tool: ToolSpec, arguments: dict[str, Any]) -> str | None:
        """执行 MVP 范围内的轻量 schema 校验。

        这里不是完整 JSON Schema 引擎，只覆盖 required、properties.type 和 enum 三类最容易
        导致误调用的契约。保持轻量是为了不引入新依赖；未来需要完整校验时可以替换为
        jsonschema，但外层 ToolExecutionResult 协议不应改变。
        """

        schema = tool.input_schema or {}
        required = schema.get("required", [])
        for name in required:
            if name not in arguments:
                return f"missing required argument: {name}"
        properties = schema.get("properties", {})
        for name, value in arguments.items():
            spec = properties.get(name)
            if not isinstance(spec, dict):
                continue
            allowed = spec.get("enum")
            if allowed is not None and value not in allowed:
                return f"argument {name} must be one of {allowed}, got {value!r}"
            expected_type = spec.get("type")
            if expected_type and not self._matches_json_type(value, str(expected_type)):
                return f"argument {name} must be {expected_type}, got {type(value).__name__}"
        return None

    def _matches_json_type(self, value: Any, expected_type: str) -> bool:
        """把常见 JSON Schema type 映射到 Python 类型。

        bool 在 Python 里是 int 的子类，因此 integer/number 要显式排除 bool，避免
        `True` 被误当成数字参数通过。
        """

        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "number":
            return isinstance(value, int | float) and not isinstance(value, bool)
        if expected_type == "boolean":
            return isinstance(value, bool)
        if expected_type == "object":
            return isinstance(value, dict)
        if expected_type == "array":
            return isinstance(value, list)
        return True
