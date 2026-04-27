from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.project_spec import ProjectSpec
from agent_tool_harness.config.tool_spec import ToolSpec


class ConfigError(ValueError):
    """配置错误。

    loader 只做“能否被框架理解”的基础检查，复杂质量判断交给 audit 模块。
    """


def _read_yaml(path: str | Path) -> dict[str, Any]:
    yaml_path = Path(path)
    if not yaml_path.exists():
        raise ConfigError(f"YAML file does not exist: {yaml_path}")
    with yaml_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"YAML root must be a mapping: {yaml_path}")
    return data


def load_project(path: str | Path) -> ProjectSpec:
    """加载 project.yaml。

    这个函数不解释 evidence source 的业务含义，只保留结构化字段供报告和生成器使用。
    """

    yaml_path = Path(path)
    data = _read_yaml(yaml_path)
    project = ProjectSpec.from_dict(data, source_path=yaml_path)
    if not project.name:
        raise ConfigError("project.name is required")
    return project


def load_tools(path: str | Path) -> list[ToolSpec]:
    """加载 tools.yaml。

    只要求 name 存在，其他缺失项留给 ToolDesignAuditor 给出可解释的低分和建议。
    """

    yaml_path = Path(path)
    data = _read_yaml(yaml_path)
    raw_tools = data.get("tools", data if isinstance(data, list) else [])
    if not isinstance(raw_tools, list):
        raise ConfigError("tools.yaml must contain a 'tools' list")
    tools = [ToolSpec.from_dict(item, source_path=yaml_path) for item in raw_tools]
    missing = [index for index, tool in enumerate(tools) if not tool.name]
    if missing:
        raise ConfigError(f"tool.name is required for entries: {missing}")
    return tools


def load_evals(path: str | Path) -> list[EvalSpec]:
    """加载 evals.yaml。

    Eval 的强弱、是否 runnable、judge 是否合理由 EvalQualityAuditor 判断。
    """

    yaml_path = Path(path)
    data = _read_yaml(yaml_path)
    raw_evals = data.get("evals", data if isinstance(data, list) else [])
    if not isinstance(raw_evals, list):
        raise ConfigError("evals.yaml must contain an 'evals' list")
    evals = [EvalSpec.from_dict(item, source_path=yaml_path) for item in raw_evals]
    missing = [index for index, case in enumerate(evals) if not case.id]
    if missing:
        raise ConfigError(f"eval.id is required for entries: {missing}")
    return evals
