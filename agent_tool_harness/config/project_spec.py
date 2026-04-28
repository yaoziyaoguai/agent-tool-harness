from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ProjectSpec:
    """用户项目的高层描述。

    架构边界：
    - 负责承载项目名、领域、证据源和领域分类等元数据。
    - 不负责解释工具如何执行，也不负责判断 eval 是否通过。
    - Runner 和报告层会读取这些信息来呈现上下文，但核心框架不会写死某个项目领域。
    """

    name: str
    domain: str
    description: str
    evidence_sources: list[dict[str, Any]] = field(default_factory=list)
    domain_taxonomy: dict[str, Any] = field(default_factory=dict)
    pricing: dict[str, Any] = field(default_factory=dict)
    budget: dict[str, Any] = field(default_factory=dict)
    source_path: Path | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any], source_path: Path | None = None) -> ProjectSpec:
        project = data.get("project", data)
        evidence_sources = data.get("evidence_sources", project.get("evidence_sources", []))
        # v1.8 第一项：从 project.yaml 顶层 / project 子段读取 pricing 与 budget。
        # 设计取舍：允许放在顶层 (data["pricing"]) 或 project 子段 (project["pricing"])，
        # 与 evidence_sources / domain_taxonomy 已有读取风格一致；不强制位置降低用户
        # 接入摩擦。pricing/budget 任一缺省都是 {}，不引入隐式默认价格——任何"看起
        # 来像真实账单"的数字都必须由用户显式声明，框架绝不编造。
        return cls(
            name=str(project.get("name", "")),
            domain=str(project.get("domain", "")),
            description=str(project.get("description", "")),
            evidence_sources=list(evidence_sources),
            domain_taxonomy=dict(
                data.get("domain_taxonomy", project.get("domain_taxonomy", {}))
            ),
            pricing=dict(data.get("pricing", project.get("pricing", {}))),
            budget=dict(data.get("budget", project.get("budget", {}))),
            source_path=source_path,
        )
