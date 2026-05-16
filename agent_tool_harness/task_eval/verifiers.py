"""Verifier Protocol + VerifierResult —— v3.2 确定性验证器接口。

架构边界
--------
- **负责**：定义 Verifier Protocol（可组合验证器的接口契约）和 VerifierResult
  （单个 verifier 的执行结果）。
- **不负责**：不实现具体 verifier 逻辑（P2 实现）、不调 LLM、
  不修改 EvaluationResult。

设计原则（来自 RFC 0003 Decision 3）：
- Verifier 是 Protocol，不是 ABC——不需要状态、不需要 lifecycle。
- 具体 verifier 只需实现 verify(answer_text, tool_outputs) -> VerifierResult。
- VerifierResult 保留 matched/missing 列表，方便报告展示每个事实/字段/pattern
  的匹配情况——不是为了做 NLP，而是为了让 reviewer 能快速定位缺失项。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class VerifierResult:
    """单次 verifier 执行的确定性结果。

    设计原则：
    - 所有字段为确定性值——同一输入始终同一输出
    - matched / missing 是事实列表（matched 的事实、missing 的事实），
      而非模糊评分——reviewer 可直接判断缺失了什么
    - details 是人类可读摘要（如 "matched 2/3 required facts"），
      用于 Markdown 报告展示
    """

    verifier_name: str
    """verifier 名称（如 "contains_required_facts"）。"""

    passed: bool
    """本次验证是否通过。"""

    matched: list[str] = field(default_factory=list)
    """匹配成功的事实/字段/pattern 列表。"""

    missing: list[str] = field(default_factory=list)
    """匹配失败的事实/字段/pattern 列表。"""

    details: str = ""
    """人类可读的判定摘要。"""


class Verifier(Protocol):
    """Verifier Protocol —— 确定性验证器的最小接口。

    架构边界：
    - **负责**：定义验证器的输入/输出契约。
    - **不负责**：不规定实现细节——具体 verifier 可以是类、函数、闭包，
      只要满足签名即可。
    - **为什么是 Protocol 而非 ABC**：Verifier 不需要状态管理、不需要
      lifecycle（setup/teardown）、不需要依赖注入。Protocol 提供最大灵活性。

    用法：
        class ContainsRequiredFacts:
            def __init__(self, required_facts: list[str]): ...
            def verify(self, answer_text: str, tool_outputs) -> VerifierResult: ...
    """

    def verify(
        self,
        answer_text: str,
        tool_outputs: list[dict[str, Any]],
    ) -> VerifierResult:
        """对 Agent 的最终答案执行确定性验证。

        Args:
            answer_text: 从 ExecutionTrace 提取的最终答案文本。
            tool_outputs: 所有 tool_result.output 的列表，供 JsonFieldMatch
                          等需要访问 tool output 的 verifier 使用。

        Returns:
            VerifierResult: 包含 passed/matched/missing/details 的结果。
        """
        ...
