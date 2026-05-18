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

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

PRIORITY_TASK_OUTCOME = 20
"""Task-level section：紧跟 Core Flow 摘要之后。"""

PRIORITY_SUITE_RESULT = 30
"""Suite 聚合 section：排在 task-level 结果之后。"""

PRIORITY_REGRESSION = 40
"""Regression 对比 section：排在 task/suite 事实之后。"""

PRIORITY_ANALYSIS = 50
"""Transcript/context analysis section：排在回归对比之后。"""

PRIORITY_PORTFOLIO = 60
"""Portfolio review / improvement brief section：当前 v3.6 最后一个业务段。"""

PRIORITY_DEFAULT = 100
"""未知或未来 section 的默认优先级，避免抢占既有 v3.1-v3.6 顺序。"""


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

    priority 约定
    ---------------
    当前 v3.1-v3.6 的业务段使用 20/30/40/50/60 这组有间隔的 band：
    task → suite → regression → analysis → portfolio。新增 section 应优先使用
    本模块的 ``PRIORITY_*`` 常量，只有确有插队需求时才在相邻 band 之间取值。
    ``PRIORITY_DEFAULT`` 用于未来未知 section，保证不会意外改变既有报告顺序。
    """

    section_id: str
    title: str
    render: Callable[[], RenderedSection]
    priority: int = PRIORITY_DEFAULT
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SectionRenderResult:
    """一次 section composition 的完整结果。

    设计意图：Markdown 与 JSON 是同一组 ``RenderedSection`` 的两个视图，应该在
    同一次 composition 中从同一次 ``section.render()`` 结果派生，避免 renderer
    有成本或计数副作用时被重复调用。
    """

    markdown: str
    json_data: dict[str, Any]


def compose_sections(sections: Iterable[ReportSection]) -> SectionRenderResult:
    """一次性渲染 section，并同时产出 Markdown 与 JSON 视图。

    本函数不缓存到 ``ReportSection`` 上，也不修改业务输入对象；它只在当前调用栈
    中复用已渲染结果，避免隐藏状态和跨测试污染。
    """

    rendered_sections = [
        (section, section.render()) for section in ordered_sections(sections)
    ]
    return SectionRenderResult(
        markdown=_markdown_from_rendered_sections(rendered_sections),
        json_data=_json_from_rendered_sections(rendered_sections),
    )


def ordered_sections(sections: Iterable[ReportSection]) -> list[ReportSection]:
    """按 priority + section_id 稳定排序。

    调用方传入顺序不应影响最终报告结构；稳定排序让测试和 artifact diff 更可靠。
    """

    return sorted(sections, key=lambda section: (section.priority, section.section_id))


def render_sections_markdown(sections: Iterable[ReportSection]) -> str:
    """渲染一组 section 的 Markdown。

    空 section 会被跳过；返回值末尾保持一个换行，方便插入主报告。
    """

    return compose_sections(sections).markdown


def sections_to_json_dict(sections: Iterable[ReportSection]) -> dict[str, Any]:
    """聚合 section JSON 视图。

    ``None`` 表示该 section 无结构化 JSON 输出，会被跳过；其他假值（如空 dict/list）
    仍保留，避免丢失“明确为空”的业务语义。
    """

    return compose_sections(sections).json_data


def _markdown_from_rendered_sections(
    rendered_sections: Sequence[tuple[ReportSection, RenderedSection]],
) -> str:
    parts: list[str] = []
    for _section, rendered in rendered_sections:
        markdown = rendered.markdown.strip()
        if markdown:
            parts.append(markdown)
    return "\n\n".join(parts) + ("\n" if parts else "")


def _json_from_rendered_sections(
    rendered_sections: Sequence[tuple[ReportSection, RenderedSection]],
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for section, rendered in rendered_sections:
        if rendered.json_data is not None:
            payload[section.section_id] = rendered.json_data
    return payload
