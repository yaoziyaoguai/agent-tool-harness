from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    """工具契约 spec。

    架构边界：
    - 负责描述一个工具暴露给 Agent 的契约，包括何时使用、输入输出、token 策略和副作用。
    - 不负责真正调用工具；执行由 ToolExecutor 处理。
    - 不负责判断设计好坏；审计由 ToolDesignAuditor 处理。

    这样拆是为了把“契约描述”和“运行时实现”分开，后续可替换为 MCP/HTTP/Shell executor。
    """

    name: str
    namespace: str
    version: str
    description: str
    when_to_use: str
    when_not_to_use: str
    input_schema: dict[str, Any]
    output_contract: dict[str, Any]
    token_policy: dict[str, Any]
    side_effects: dict[str, Any]
    executor: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None

    @property
    def qualified_name(self) -> str:
        return f"{self.namespace}.{self.name}" if self.namespace else self.name

    @classmethod
    def from_dict(cls, data: dict[str, Any], source_path: Path | None = None) -> ToolSpec:
        known = {
            "name",
            "namespace",
            "version",
            "description",
            "when_to_use",
            "when_not_to_use",
            "input_schema",
            "output_contract",
            "token_policy",
            "side_effects",
            "executor",
        }
        metadata = {key: value for key, value in data.items() if key not in known}
        executor = dict(data.get("executor", {}))
        if source_path is not None:
            executor.setdefault("__base_dir", str(source_path.parent))
        return cls(
            name=str(data.get("name", "")),
            namespace=str(data.get("namespace", "")),
            version=str(data.get("version", "")),
            description=str(data.get("description", "")),
            when_to_use=str(data.get("when_to_use", "")),
            when_not_to_use=str(data.get("when_not_to_use", "")),
            input_schema=dict(data.get("input_schema", {})),
            output_contract=dict(data.get("output_contract", {})),
            token_policy=dict(data.get("token_policy", {})),
            side_effects=dict(data.get("side_effects", {})),
            executor=executor,
            metadata=metadata,
            source_path=source_path,
        )

    def to_dict(self) -> dict[str, Any]:
        data = {
            "name": self.name,
            "namespace": self.namespace,
            "version": self.version,
            "description": self.description,
            "when_to_use": self.when_to_use,
            "when_not_to_use": self.when_not_to_use,
            "input_schema": self.input_schema,
            "output_contract": self.output_contract,
            "token_policy": self.token_policy,
            "side_effects": self.side_effects,
            "executor": {k: v for k, v in self.executor.items() if not k.startswith("__")},
        }
        data.update(self.metadata)
        return data
