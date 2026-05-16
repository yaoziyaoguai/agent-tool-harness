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


# ============================================================================
# P2: 5 种确定性 verifier + CompositeVerifier
# ============================================================================


class ContainsRequiredFacts:
    """验证 answer 是否包含所有 required_facts（case-insensitive 子串匹配）。

    设计原则（RFC 0003 Decision 2）：
    - 用简单子串匹配，不引入 NLP 依赖
    - case-insensitive：fact.lower() in answer_text.lower()
    - 空 required_facts → passed=True（无要求即通过，不报 inconclusive——
      inconclusive 由 TaskEvaluator 在无任何 verifier 时单独判定）
    """

    def __init__(self, required_facts: list[str]) -> None:
        self.required_facts = list(required_facts)

    def verify(
        self, answer_text: str, tool_outputs: list[dict[str, Any]]
    ) -> VerifierResult:
        answer_lower = answer_text.lower()
        matched = [f for f in self.required_facts if f.lower() in answer_lower]
        missing = [f for f in self.required_facts if f.lower() not in answer_lower]
        total = len(self.required_facts)
        return VerifierResult(
            verifier_name="contains_required_facts",
            passed=len(missing) == 0,
            matched=matched,
            missing=missing,
            details=f"matched {len(matched)}/{total} required facts",
        )


class ForbiddenFactsAbsent:
    """验证 answer 是否不含任何 forbidden_facts（case-insensitive 子串匹配）。

    设计原则：
    - "missing" 字段在语义上复用于存放"发现到的禁止事实"——对于 reviewer，
      "missing=[]" 表示没有不该出现的内容，语义更直观。
    - 空 forbidden_facts → passed=True（没有禁止项即通过）。
    """

    def __init__(self, forbidden_facts: list[str]) -> None:
        self.forbidden_facts = list(forbidden_facts)

    def verify(
        self, answer_text: str, tool_outputs: list[dict[str, Any]]
    ) -> VerifierResult:
        answer_lower = answer_text.lower()
        found = [f for f in self.forbidden_facts if f.lower() in answer_lower]
        return VerifierResult(
            verifier_name="forbidden_facts_absent",
            passed=len(found) == 0,
            matched=[],
            missing=found,
            details=(
                f"found {len(found)} forbidden facts"
                if found
                else "no forbidden facts found"
            ),
        )


class JsonFieldMatch:
    """验证 tool_outputs 中是否存在 expected_fields 的递归子集。

    匹配逻辑：在所有 tool_output 中搜索，找到任一 output 的 dict 子集
    包含所有 expected_fields 即通过。

    设计原则：
    - 递归比较：嵌套 dict 也做子集匹配
    - 列表按值成员比较（顺序无关）
    - 空 expected_fields → passed=True
    """

    def __init__(self, expected_fields: dict[str, Any]) -> None:
        self.expected_fields = dict(expected_fields)

    def verify(
        self, answer_text: str, tool_outputs: list[dict[str, Any]]
    ) -> VerifierResult:
        if not self.expected_fields:
            return VerifierResult(
                verifier_name="json_field_match",
                passed=True,
                matched=[],
                missing=[],
                details="no expected fields to match",
            )

        for i, output in enumerate(tool_outputs):
            if not isinstance(output, dict):
                continue
            if self._is_subset(self.expected_fields, output):
                matched_keys = list(self.expected_fields.keys())
                return VerifierResult(
                    verifier_name="json_field_match",
                    passed=True,
                    matched=matched_keys,
                    missing=[],
                    details=f"all expected fields matched in tool_output[{i}]",
                )

        missing_keys = list(self.expected_fields.keys())
        return VerifierResult(
            verifier_name="json_field_match",
            passed=False,
            matched=[],
            missing=missing_keys,
            details=f"no tool_output matched all expected fields "
            f"(searched {len(tool_outputs)} outputs)",
        )

    @staticmethod
    def _is_subset(expected: dict[str, Any], actual: dict[str, Any]) -> bool:
        """递归检查 expected 是否为 actual 的 dict 子集。

        dict 递归子集匹配；list 逐元素递归匹配（顺序无关）；其他类型 == 比较。
        """
        for key, expected_val in expected.items():
            if key not in actual:
                return False
            actual_val = actual[key]
            if isinstance(expected_val, dict) and isinstance(actual_val, dict):
                if not JsonFieldMatch._is_subset(expected_val, actual_val):
                    return False
            elif isinstance(expected_val, list) and isinstance(actual_val, list):
                if not JsonFieldMatch._list_is_subset(expected_val, actual_val):
                    return False
            elif expected_val != actual_val:
                return False
        return True

    @staticmethod
    def _list_is_subset(expected_list: list, actual_list: list) -> bool:
        """检查 expected_list 每个元素是否为 actual_list 某元素的子集。

        dict 元素递归子集匹配；list 元素递归列表子集匹配；
        其他类型用 == 比较。
        """
        for expected_item in expected_list:
            found = False
            for actual_item in actual_list:
                if isinstance(expected_item, dict) and isinstance(actual_item, dict):
                    if JsonFieldMatch._is_subset(expected_item, actual_item):
                        found = True
                        break
                elif isinstance(expected_item, list) and isinstance(actual_item, list):
                    if JsonFieldMatch._list_is_subset(expected_item, actual_item):
                        found = True
                        break
                elif expected_item == actual_item:
                    found = True
                    break
            if not found:
                return False
        return True


class ExactMatch:
    """验证 answer_text 是否精确等于 expected 字符串（strip 后比较）。

    设计原则：
    - strip() 消除首尾空白差异，避免空格/换行导致的误判
    - expected 在 __init__ 时 strip 一次，避免每次 verify 重复
    """

    def __init__(self, expected: str) -> None:
        self.expected = expected.strip()

    def verify(
        self, answer_text: str, tool_outputs: list[dict[str, Any]]
    ) -> VerifierResult:
        passed = answer_text.strip() == self.expected
        return VerifierResult(
            verifier_name="exact_match",
            passed=passed,
            matched=[self.expected] if passed else [],
            missing=[] if passed else [self.expected],
            details=(
                "exact match"
                if passed
                else f"expected '{self.expected[:50]}...'"
                if len(self.expected) > 50
                else f"expected '{self.expected}'"
            ),
        )


class RegexMatch:
    """验证 answer_text 是否匹配所有 regex patterns。

    设计原则：
    - 用 re.search（非 re.fullmatch）——pattern 可以出现在文本任意位置
    - re.DOTALL：. 匹配换行符，适配多行 answer
    - 空 patterns → passed=True
    """

    def __init__(self, patterns: list[str]) -> None:
        import re

        self.patterns = [re.compile(p, re.DOTALL) for p in patterns]

    def verify(
        self, answer_text: str, tool_outputs: list[dict[str, Any]]
    ) -> VerifierResult:
        if not self.patterns:
            return VerifierResult(
                verifier_name="regex_match",
                passed=True,
                matched=[],
                missing=[],
                details="no patterns to match",
            )

        matched = [p.pattern for p in self.patterns if p.search(answer_text)]
        missing = [p.pattern for p in self.patterns if not p.search(answer_text)]
        return VerifierResult(
            verifier_name="regex_match",
            passed=len(missing) == 0,
            matched=matched,
            missing=missing,
            details=f"matched {len(matched)}/{len(self.patterns)} patterns",
        )


class CompositeVerifier:
    """组合多个子 verifier，按 mode 聚合结果。

    设计原则（RFC 0003 Decision 3 + CompositeVerifier 组合语义）：
    - mode="all"（默认）：AND 语义——所有子 verifier 通过才算通过。
      适用 required_facts + json_field_match 等严格组合。
    - mode="any"：OR 语义——任一子 verifier 通过即通过。
      适用多种可接受答案路径（如英文或中文答案均可）。
      必须显式配置 mode="any"——防止误用。
    - 无论哪种 mode，composite result 保留所有子 verifier 的独立结果，
      方便报告展示每项的通过/失败详情。
    - 空 verifiers 列表 → passed=True（无约束即满足）。
    """

    def __init__(self, verifiers: list, mode: str = "all") -> None:
        if mode not in ("all", "any"):
            raise ValueError(
                f"CompositeVerifier mode 必须是 'all' 或 'any'，当前值: {mode!r}"
            )
        self.verifiers = list(verifiers)
        self.mode = mode

    def verify(
        self, answer_text: str, tool_outputs: list[dict[str, Any]]
    ) -> VerifierResult:
        if not self.verifiers:
            return VerifierResult(
                verifier_name="composite",
                passed=True,
                matched=[],
                missing=[],
                details="no sub-verifiers",
            )

        results = [v.verify(answer_text, tool_outputs) for v in self.verifiers]
        if self.mode == "all":
            passed = all(r.passed for r in results)
        else:
            passed = any(r.passed for r in results)

        all_matched: list[str] = []
        all_missing: list[str] = []
        sub_details: list[str] = []
        for r in results:
            all_matched.extend(r.matched)
            all_missing.extend(r.missing)
            status = "PASS" if r.passed else "FAIL"
            sub_details.append(f"{r.verifier_name}: {status}")

        return VerifierResult(
            verifier_name="composite",
            passed=passed,
            matched=all_matched,
            missing=all_missing,
            details=f"mode={self.mode}; " + "; ".join(sub_details),
        )


# ============================================================================
# 工厂函数
# ============================================================================


def build_verifiers_from_outcome(
    expected_outcome,
) -> list:
    """从 ExpectedOutcome 构造 verifier 列表。

    映射规则（按 ExpectedOutcome 字段顺序）：
    - required_facts 非空 → ContainsRequiredFacts
    - forbidden_facts 非空 → ForbiddenFactsAbsent
    - expected_json_fields 非空 → JsonFieldMatch
    - exact_answer 非 None → ExactMatch
    - regex_patterns 非空 → RegexMatch

    注意：
    - human_notes 不参与自动验证——不生成 verifier
    - 返回空列表表示 ExpectedOutcome 没有任何自动验证条件，
      TaskEvaluator 应产出 status=inconclusive
    - 这个函数不引入 LLM 依赖、不调 LLM
    """
    from agent_tool_harness.task_eval.eval_case import ExpectedOutcome

    if not isinstance(expected_outcome, ExpectedOutcome):
        return []

    verifiers: list = []

    if expected_outcome.required_facts:
        verifiers.append(ContainsRequiredFacts(expected_outcome.required_facts))

    if expected_outcome.forbidden_facts:
        verifiers.append(ForbiddenFactsAbsent(expected_outcome.forbidden_facts))

    if expected_outcome.expected_json_fields:
        verifiers.append(JsonFieldMatch(expected_outcome.expected_json_fields))

    if expected_outcome.exact_answer is not None:
        verifiers.append(ExactMatch(expected_outcome.exact_answer))

    if expected_outcome.regex_patterns:
        verifiers.append(RegexMatch(expected_outcome.regex_patterns))

    return verifiers
