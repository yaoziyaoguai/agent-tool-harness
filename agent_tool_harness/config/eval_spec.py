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
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            category=str(data.get("category", "")),
            split=str(data.get("split", "")),
            realism_level=str(data.get("realism_level", "")),
            complexity=str(data.get("complexity", "")),
            source=str(data.get("source", "")),
            user_prompt=str(data.get("user_prompt", "")),
            initial_context=dict(data.get("initial_context", {})),
            verifiable_outcome=dict(data.get("verifiable_outcome", {})),
            success_criteria=list(data.get("success_criteria", [])),
            expected_tool_behavior=dict(data.get("expected_tool_behavior", {})),
            judge=dict(data.get("judge", {})),
            runnable=bool(data.get("runnable", True)),
            missing_context=list(data.get("missing_context", [])),
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
