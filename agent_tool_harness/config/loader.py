from __future__ import annotations

from collections import Counter
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


def _read_yaml(path: str | Path) -> Any:
    """读取 YAML 并保留 root 类型。

    loader 是用户接入 harness 的第一道边界。这里不强制 root 必须是 mapping，是因为
    tools/evals 在实践中常见两种写法：`tools: [...]` 和直接 `[...]`。具体命令是否接受
    list root 由 load_tools/load_evals 决定；project.yaml 仍要求 mapping。
    """

    yaml_path = Path(path)
    if not yaml_path.exists():
        raise ConfigError(f"YAML file does not exist: {yaml_path}")
    with yaml_path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    return data


def load_project(path: str | Path) -> ProjectSpec:
    """加载 project.yaml。

    这个函数不解释 evidence source 的业务含义，只保留结构化字段供报告和生成器使用。
    """

    yaml_path = Path(path)
    data = _read_yaml(yaml_path)
    if not isinstance(data, dict):
        raise ConfigError(f"project.yaml root must be a mapping: {yaml_path}")
    project = ProjectSpec.from_dict(data, source_path=yaml_path)
    if not project.name:
        raise ConfigError("project.name is required")
    return project


def load_tools(path: str | Path) -> list[ToolSpec]:
    """加载 tools.yaml。

    只要求 name 存在，其他缺失项留给 ToolDesignAuditor 给出可解释的低分和建议。
    这里额外校验 root 只能是 mapping 或 list，是为了把用户配置错误收口成 ConfigError，
    避免真实接入时暴露 `.get()` 这类框架内部实现细节。
    """

    yaml_path = Path(path)
    data = _read_yaml(yaml_path)
    if isinstance(data, list):
        raw_tools = data
    elif isinstance(data, dict):
        raw_tools = data.get("tools", [])
    else:
        raise ConfigError(f"tools.yaml root must be a mapping or list: {yaml_path}")
    if not isinstance(raw_tools, list):
        raise ConfigError("tools.yaml must contain a 'tools' list")
    tools = []
    for index, item in enumerate(raw_tools):
        if not isinstance(item, dict):
            raise ConfigError(f"tools[{index}] must be a mapping in {yaml_path}")
        try:
            tools.append(ToolSpec.from_dict(item, source_path=yaml_path))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"invalid tools[{index}] in {yaml_path}: {exc}") from exc
    missing = [index for index, tool in enumerate(tools) if not tool.name]
    if missing:
        raise ConfigError(f"tool.name is required for entries: {missing}")
    return tools


def load_evals(path: str | Path) -> list[EvalSpec]:
    """加载 evals.yaml。

    Eval 的强弱、是否 runnable、judge 是否合理由 EvalQualityAuditor 判断。
    loader 只负责保证 runner 能获得稳定结构；如果 root 本身不是 mapping/list，
    后续 artifacts 将没有可信 eval id，所以这里选择在运行前明确失败。
    """

    yaml_path = Path(path)
    data = _read_yaml(yaml_path)
    if isinstance(data, list):
        raw_evals = data
    elif isinstance(data, dict):
        raw_evals = data.get("evals", [])
    else:
        raise ConfigError(f"evals.yaml root must be a mapping or list: {yaml_path}")
    if not isinstance(raw_evals, list):
        raise ConfigError("evals.yaml must contain an 'evals' list")
    evals = []
    for index, item in enumerate(raw_evals):
        if not isinstance(item, dict):
            raise ConfigError(f"evals[{index}] must be a mapping in {yaml_path}")
        try:
            evals.append(EvalSpec.from_dict(item, source_path=yaml_path))
        except (TypeError, ValueError) as exc:
            raise ConfigError(f"invalid evals[{index}] in {yaml_path}: {exc}") from exc
    missing = [index for index, case in enumerate(evals) if not case.id]
    if missing:
        raise ConfigError(f"eval.id is required for entries: {missing}")
    duplicate_ids = sorted(
        eval_id for eval_id, count in Counter(case.id for case in evals).items() if count > 1
    )
    if duplicate_ids:
        raise ConfigError(f"eval.id must be unique, duplicates: {', '.join(duplicate_ids)}")
    return evals
