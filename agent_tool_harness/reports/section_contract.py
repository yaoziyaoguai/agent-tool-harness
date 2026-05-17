"""Report section contract —— 统一报告段的最小边界。

架构意图
--------
报告组合器只应该理解“一个 section 能渲染 Markdown，也可选提供 JSON”，不应该
知道 TaskOutcome、SuiteResult、RegressionReport、PortfolioFinding 等业务对象
的内部结构。各业务模块通过 adapter 把自己的对象隐藏在 ``ReportSection`` 后面，
从而保持高内聚、低耦合和 Information Hiding。

本模块不负责具体业务渲染，也不修改输入对象；它只提供稳定排序、Markdown 拼接和
JSON 聚合这三个通用动作。
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RenderedSection:
    """一个已渲染报告段。

    ``markdown`` 是可直接插入报告的文本；``json_data`` 是可选的结构化视图。
    两者都由领域模块生成，composer 不解释其业务含义。
    """

    markdown: str = ""
    json_data: Any = None


@dataclass(frozen=True)
class ReportSection:
    """报告段 contract。

    ``section_id`` 是稳定 JSON key；``title`` 是人类可读标题；``priority`` 控制
    多 section 组合顺序；``render`` 延迟执行，避免 composer 持有业务对象细节。
    """

    section_id: str
    title: str
    render: Callable[[], RenderedSection]
    priority: int = 100
    metadata: dict[str, Any] = field(default_factory=dict)


def ordered_sections(sections: Iterable[ReportSection]) -> list[ReportSection]:
    """按 priority + section_id 稳定排序。

    调用方传入顺序不应影响最终报告结构；稳定排序让测试和 artifact diff 更可靠。
    """

    return sorted(sections, key=lambda section: (section.priority, section.section_id))


def render_sections_markdown(sections: Iterable[ReportSection]) -> str:
    """渲染一组 section 的 Markdown。

    空 section 会被跳过；返回值末尾保持一个换行，方便插入主报告。
    """

    parts: list[str] = []
    for section in ordered_sections(sections):
        rendered = section.render()
        markdown = rendered.markdown.strip()
        if markdown:
            parts.append(markdown)
    return "\n\n".join(parts) + ("\n" if parts else "")


def sections_to_json_dict(sections: Iterable[ReportSection]) -> dict[str, Any]:
    """聚合 section JSON 视图。

    ``None`` 表示该 section 无结构化 JSON 输出，会被跳过；其他假值（如空 dict/list）
    仍保留，避免丢失“明确为空”的业务语义。
    """

    payload: dict[str, Any] = {}
    for section in ordered_sections(sections):
        rendered = section.render()
        if rendered.json_data is not None:
            payload[section.section_id] = rendered.json_data
    return payload
