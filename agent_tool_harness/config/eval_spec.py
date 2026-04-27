from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class EvalSpec:
    """一条 Agent tool-use eval case。

    架构边界：
    - 负责表达用户任务、上下文、可验证结果、期望工具行为和 judge 规则。
    - 不负责生成 replay，也不负责执行工具；这些由 adapter/runner 负责。
    - 不把“最终回答是否看起来对”当成唯一证据，而是为 transcript 级判断提供规则。
    """

    id: str
    name: str
    category: str
    split: str
    realism_level: str
    complexity: str
    source: str
    user_prompt: str
    initial_context: dict[str, Any]
    verifiable_outcome: dict[str, Any]
    success_criteria: list[str]
    expected_tool_behavior: dict[str, Any]
    judge: dict[str, Any]
    runnable: bool = True
    missing_context: list[str] = field(default_factory=list)
    source_path: Path | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], source_path: Path | None = None) -> EvalSpec:
        """从 YAML mapping 构造 EvalSpec。

        这里做轻量类型归一化，而不做质量审计。比如 `success_criteria` 必须仍是 list，
        `initial_context` 必须仍是 mapping；如果用户写错类型，loader 会把这里的 ValueError
        包装成带文件位置的 ConfigError。这样能在接入阶段尽早发现配置问题，而不是让 runner
        生成混乱 artifacts。
        """

        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            category=str(data.get("category", "")),
            split=str(data.get("split", "")),
            realism_level=str(data.get("realism_level", "")),
            complexity=str(data.get("complexity", "")),
            source=str(data.get("source", "")),
            user_prompt=str(data.get("user_prompt", "")),
            initial_context=_mapping_field(data, "initial_context"),
            verifiable_outcome=_mapping_field(data, "verifiable_outcome"),
            success_criteria=_list_field(data, "success_criteria"),
            expected_tool_behavior=_mapping_field(data, "expected_tool_behavior"),
            judge=_mapping_field(data, "judge"),
            runnable=_bool_field(data, "runnable", default=True),
            missing_context=_list_field(data, "missing_context"),
            source_path=source_path,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "split": self.split,
            "realism_level": self.realism_level,
            "complexity": self.complexity,
            "source": self.source,
            "user_prompt": self.user_prompt,
            "initial_context": self.initial_context,
            "verifiable_outcome": self.verifiable_outcome,
            "success_criteria": self.success_criteria,
            "expected_tool_behavior": self.expected_tool_behavior,
            "judge": self.judge,
            "runnable": self.runnable,
            "missing_context": self.missing_context,
        }


def _mapping_field(data: dict[str, Any], name: str) -> dict[str, Any]:
    """读取 mapping 字段。

    Eval 配置里的上下文、可验证结果和 judge 都是结构化契约。字符串或列表不应被偷偷转换成
    dict，否则后续 auditor/runner 会基于错误结构生成误导性 artifacts。
    """

    value = data.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a mapping")
    return dict(value)


def _list_field(data: dict[str, Any], name: str) -> list[Any]:
    """读取 list 字段，避免把字符串拆成字符列表。

    YAML 用户很容易把 `success_criteria: "..."` 写成字符串。这里选择报错而不是宽松转换，
    因为 eval 质量和报告解释依赖明确的多条 criteria。
    """

    value = data.get(name, [])
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    return list(value)


def _bool_field(data: dict[str, Any], name: str, *, default: bool) -> bool:
    """读取 boolean 字段。

    YAML 原生 bool 会直接保留；对被引号包住的 `"false"`/`"true"` 做兼容，是为了减少真实
    用户配置迁移时的踩坑。但无法识别的字符串会报错，避免 `"nope"` 被 Python bool 规则当真。
    """

    value = data.get(name, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "yes", "1"}:
            return True
        if normalized in {"false", "no", "0"}:
            return False
    raise ValueError(f"{name} must be a boolean")
