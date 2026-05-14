"""Tool-use quality LLM judge —— fake/deterministic implementation.

架构边界
--------
- **负责**：消费 ExecutionTrace + ToolSpec，利用 rubric 定义产出 rubric-aware
  JudgeFinding。所有分析基于 deterministic heuristics，不调真实 LLM。
- **不负责**：不调外部 API、不读 .env、不生成 ReviewDecision、不改变 passed。
- **为什么是 fake**：Phase 2 要求先做 fake-testable 的 judge skeleton，
  后续接入真实 LLM judge provider 时只需替换 transport，接口不变。
- **与 FakeJudgeProvider 的关系**：FakeJudgeProvider 是通用 fake judge skeleton
  （预置 responses 模式），ToolUseQualityJudge 是专门对 tool-use quality
  rubric 的 fake judge，用简单启发式替代 LLM 语义判断。
"""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher

from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.core_contract import Evidence, JudgeFinding
from agent_tool_harness.tool_use_quality_rubric import (
    RUBRIC_FINAL_ANSWER_FAITHFULNESS,
    RUBRIC_FREQUENTLY_CHAINED_TOOLS,
    RUBRIC_MISSING_DOMAIN_TOOL,
    RUBRIC_MISSING_FIELDS_FOR_NEXT_CALL,
    RUBRIC_TOOL_CHOICE_REASONABLENESS,
    RUBRIC_TOOL_TOO_LOW_LEVEL,
)

# ---------------------------------------------------------------------------
# Heuristic constants
# ---------------------------------------------------------------------------

_SHALLOW_WRAPPER_PHRASES: tuple[str, ...] = (
    "api wrapper", "raw endpoint", "crud operation", "database operation",
    "http request", "raw sql", "rest endpoint", "graphql query",
    "api call", "direct wrapper",
)

_CONTEXT_FIELD_NAMES: frozenset = frozenset({
    "name", "title", "label", "description", "summary",
    "username", "email", "full_name", "display_name",
})

_NAME_SIMILARITY_THRESHOLD = 0.75
_CHAINED_PAIR_MIN_OCCURRENCES = 2


class ToolUseQualityJudge:
    """Fake tool-use quality judge using rubric definitions.

    对每个 rubric 维度用 deterministic heuristic 产生一条 JudgeFinding。
    每条 finding 标出对应的 rubric dimension_id，rationale 描述启发式发现。
    所有 finding 均为 advisory only，severity="info"，不影响 passed。

    Usage:
        judge = ToolUseQualityJudge(tool_specs=[...])
        findings = judge.evaluate(evidence)
    """

    name = "tool-use-quality-judge"
    mode = "fake"

    def __init__(self, tool_specs: list[ToolSpec] | None = None) -> None:
        self._tool_specs: list[ToolSpec] = list(tool_specs) if tool_specs else []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(self, evidence: Evidence) -> list[JudgeFinding]:
        trace = evidence.trace
        specs = self._tool_specs

        checks = [
            self._check_tool_choice_reasonableness(trace, specs),
            self._check_tool_too_low_level(specs),
            self._check_frequently_chained_tools(trace),
            self._check_missing_domain_tool(trace, specs),
            self._check_missing_fields_for_next_call(trace),
            self._check_final_answer_faithfulness(trace),
        ]
        return [f for f in checks if f is not None]

    # ------------------------------------------------------------------
    # D4: tool_choice_reasonableness
    # ------------------------------------------------------------------

    def _check_tool_choice_reasonableness(
        self, trace, specs: list[ToolSpec]
    ) -> JudgeFinding | None:
        """检查已调用工具名与可用工具名之间的相似度重叠。

        如果某次调用使用了一个名字与另一可用工具高度相似的工具，
        agent 可能被命名混淆误导——值得人类 reviewer 关注。
        """
        called_names = [tc.tool_name for tc in trace.tool_calls]
        spec_names = [s.name for s in specs]

        overlaps: list[str] = []
        for cn in set(called_names):
            for sn in set(spec_names):
                if cn == sn:
                    continue
                sim = SequenceMatcher(None, cn.lower(), sn.lower()).ratio()
                if sim >= _NAME_SIMILARITY_THRESHOLD:
                    overlaps.append(f"'{cn}' vs '{sn}' (sim={sim:.2f})")

        if not overlaps:
            return self._pass_finding(
                RUBRIC_TOOL_CHOICE_REASONABLENESS,
                "No confusing name overlaps detected between called and available tools.",
            )

        return JudgeFinding(
            finding_id="tqj-tool-choice-0",
            severity="info",
            category="judge",
            message=(
                f"Possible tool name confusion: {len(overlaps)} overlapping pair(s)"
                f" — {'; '.join(overlaps[:5])}"
            ),
            evidence_ref="trace.tool_calls[*].tool_name",
            confidence=None,
            rubric=RUBRIC_TOOL_CHOICE_REASONABLENESS.rubric_text,
            provider="tool-use-quality-judge",
            rationale=(
                f"Fake heuristic: SequenceMatcher similarity >= {_NAME_SIMILARITY_THRESHOLD}"
                f" between called and available tool names."
                f" Overlaps found: {'; '.join(overlaps[:5])}."
                f" These may indicate tool description overlap that confuses the agent."
            ),
            model="fake-heuristic",
        )

    # ------------------------------------------------------------------
    # D4: tool_too_low_level
    # ------------------------------------------------------------------

    def _check_tool_too_low_level(
        self, specs: list[ToolSpec]
    ) -> JudgeFinding | None:
        """检查工具描述是否暴露了低层实现细节。"""
        low_level: list[str] = []
        for s in specs:
            desc_lower = (s.description or "").lower()
            for phrase in _SHALLOW_WRAPPER_PHRASES:
                if phrase in desc_lower:
                    low_level.append(f"'{s.name}' contains '{phrase}'")
                    break

        if not low_level:
            return self._pass_finding(
                RUBRIC_TOOL_TOO_LOW_LEVEL,
                "No tool descriptions signal low-level wrapper concerns.",
            )

        return JudgeFinding(
            finding_id="tqj-too-low-0",
            severity="info",
            category="judge",
            message=(
                f"{len(low_level)} tool(s) may be too low-level: {'; '.join(low_level[:5])}"
            ),
            evidence_ref="ToolSpec[*].description",
            confidence=None,
            rubric=RUBRIC_TOOL_TOO_LOW_LEVEL.rubric_text,
            provider="tool-use-quality-judge",
            rationale=(
                f"Fake heuristic: description contains one of {_SHALLOW_WRAPPER_PHRASES}."
                f" Matched: {'; '.join(low_level[:5])}."
                f" Low-level tools force the agent to compose primitive steps"
                f" instead of calling a single domain action."
            ),
            model="fake-heuristic",
        )

    # ------------------------------------------------------------------
    # D4: frequently_chained_tools
    # ------------------------------------------------------------------

    def _check_frequently_chained_tools(self, trace) -> JudgeFinding | None:
        """检测 trace 中重复出现的连续工具调用对。"""
        if len(trace.tool_calls) < 2:
            return self._pass_finding(
                RUBRIC_FREQUENTLY_CHAINED_TOOLS,
                "Fewer than 2 tool calls — no chain patterns to analyze.",
            )

        names = [tc.tool_name for tc in trace.tool_calls]
        pair_counts: Counter = Counter()
        for i in range(len(names) - 1):
            pair_counts[("→".join(names[i:i + 2]),)] += 1

        repeated = [
            f"'{p[0]}' ({c}x)"
            for p, c in pair_counts.most_common()
            if c >= _CHAINED_PAIR_MIN_OCCURRENCES
        ]

        if not repeated:
            return self._pass_finding(
                RUBRIC_FREQUENTLY_CHAINED_TOOLS,
                "No repeated tool-call pairs detected in trace.",
            )

        return JudgeFinding(
            finding_id="tqj-chained-0",
            severity="info",
            category="judge",
            message=(
                f"{len(repeated)} tool pair(s) appear repeatedly: {'; '.join(repeated[:5])}"
            ),
            evidence_ref="trace.tool_calls[*].tool_name",
            confidence=None,
            rubric=RUBRIC_FREQUENTLY_CHAINED_TOOLS.rubric_text,
            provider="tool-use-quality-judge",
            rationale=(
                f"Fake heuristic: consecutive tool-call pairs appearing"
                f" >= {_CHAINED_PAIR_MIN_OCCURRENCES} times."
                f" Repeated chains: {'; '.join(repeated[:5])}."
                f" These may be candidates for a consolidated higher-level tool."
            ),
            model="fake-heuristic",
        )

    # ------------------------------------------------------------------
    # D4: missing_domain_tool
    # ------------------------------------------------------------------

    def _check_missing_domain_tool(
        self, trace, specs: list[ToolSpec]
    ) -> JudgeFinding | None:
        """检查 tool inventory 是否缺少高层领域工具。

        启发式：如果 trace 中使用了 3+ 个不同工具且没有明显的领域级聚合工具，
        提示可能存在 domain tool gap。
        """
        if not specs:
            return self._pass_finding(
                RUBRIC_MISSING_DOMAIN_TOOL,
                "No tool specs provided — cannot evaluate domain coverage.",
            )

        distinct_called = len({tc.tool_name for tc in trace.tool_calls})
        if distinct_called < 3:
            return self._pass_finding(
                RUBRIC_MISSING_DOMAIN_TOOL,
                f"Only {distinct_called} distinct tool(s) called —"
                f" too few to suggest missing domain tool.",
            )

        # 按 namespace 分组看是否有碎片
        ns_groups: dict[str, list[str]] = {}
        for s in specs:
            ns = s.namespace or ""
            ns_groups.setdefault(ns, []).append(s.name)

        fragmented_ns = [
            f"'{ns}' ({len(tools)} tools: {', '.join(tools[:4])})"
            for ns, tools in sorted(ns_groups.items())
            if len(tools) >= 3
        ]

        if not fragmented_ns:
            return self._pass_finding(
                RUBRIC_MISSING_DOMAIN_TOOL,
                "No namespace has 3+ tools — no obvious domain tool gap.",
            )

        return JudgeFinding(
            finding_id="tqj-missing-domain-0",
            severity="info",
            category="judge",
            message=(
                f"Potential missing domain tool: {len(fragmented_ns)} namespace(s)"
                f" with 3+ tools — {'; '.join(fragmented_ns[:3])}"
            ),
            evidence_ref="ToolSpec[*].namespace, trace.tool_calls[*].tool_name",
            confidence=None,
            rubric=RUBRIC_MISSING_DOMAIN_TOOL.rubric_text,
            provider="tool-use-quality-judge",
            rationale=(
                f"Fake heuristic: namespaces with >= 3 tools ({distinct_called}"
                f" distinct tools called) may signal fragmentation."
                f" Fragmented namespaces: {'; '.join(fragmented_ns[:3])}."
                f" Consider a higher-level domain tool to reduce agent orchestration steps."
            ),
            model="fake-heuristic",
        )

    # ------------------------------------------------------------------
    # D5: missing_fields_for_next_call
    # ------------------------------------------------------------------

    def _check_missing_fields_for_next_call(self, trace) -> JudgeFinding | None:
        """检查 tool_result 输出是否缺少 agent 下一步调用需要的字段。

        核心启发式：如果输出中包含 ID 类字段但缺少 name/title 类字段，
        agent 可能需要额外调用来翻译 ID 为人可读名称。
        """
        gaps: list[str] = []
        for tr in trace.tool_results:
            if not isinstance(tr.output, dict) or not tr.output:
                continue
            keys = set(tr.output.keys())
            has_ids = any(k == "id" or k.endswith("_id") for k in keys)
            has_context = bool(keys & _CONTEXT_FIELD_NAMES)
            if has_ids and not has_context:
                gaps.append(
                    f"call_id={tr.call_id}: keys={sorted(keys)}"
                    f" (has IDs but no context fields)"
                )

        if not gaps:
            return self._pass_finding(
                RUBRIC_MISSING_FIELDS_FOR_NEXT_CALL,
                "All tool_result outputs contain context fields alongside IDs.",
            )

        return JudgeFinding(
            finding_id="tqj-missing-fields-0",
            severity="info",
            category="judge",
            message=(
                f"{len(gaps)} tool_result(s) return IDs without context fields"
                f" (name/title/label) — agent may need extra calls."
            ),
            evidence_ref="trace.tool_results[*].output",
            confidence=None,
            rubric=RUBRIC_MISSING_FIELDS_FOR_NEXT_CALL.rubric_text,
            provider="tool-use-quality-judge",
            rationale=(
                f"Fake heuristic: output contains id/_id but none of"
                f" {sorted(_CONTEXT_FIELD_NAMES)}."
                f" Gaps: {'; '.join(gaps[:5])}."
                f" Agent may need a follow-up call to resolve IDs to readable names."
            ),
            model="fake-heuristic",
        )

    # ------------------------------------------------------------------
    # D5: final_answer_faithfulness
    # ------------------------------------------------------------------

    def _check_final_answer_faithfulness(self, trace) -> JudgeFinding | None:
        """检查 final_answer 是否忠实基于 tool_results 数据。

        启发式（非常有限——这是 LLM judge 才做得到的分析）：
        - 如果 final_answer 为空，flag 为需审查。
        - 如果 final_answer 长度过短（<20 chars）且 tool_results 有数据，flag。
        """
        if not trace.final_answer.strip():
            return JudgeFinding(
                finding_id="tqj-faithfulness-0",
                severity="info",
                category="judge",
                message="final_answer is empty — cannot verify faithfulness to tool results.",
                evidence_ref="trace.final_answer",
                confidence=None,
                rubric=RUBRIC_FINAL_ANSWER_FAITHFULNESS.rubric_text,
                provider="tool-use-quality-judge",
                rationale=(
                    "Fake heuristic: final_answer is empty or whitespace-only."
                    " Cannot determine whether answer is grounded in tool_results."
                    " Human review recommended."
                ),
                model="fake-heuristic",
            )

        result_keys: set[str] = set()
        for tr in trace.tool_results:
            if isinstance(tr.output, dict):
                result_keys.update(tr.output.keys())
            if tr.error:
                result_keys.add(f"error:{type(tr.error).__name__}")

        if len(trace.final_answer.strip()) < 20:
            return JudgeFinding(
                finding_id="tqj-faithfulness-0",
                severity="info",
                category="judge",
                message=(
                    "final_answer is very short (<20 chars) —"
                    " may omit data from tool results."
                ),
                evidence_ref="trace.final_answer",
                confidence=None,
                rubric=RUBRIC_FINAL_ANSWER_FAITHFULNESS.rubric_text,
                provider="tool-use-quality-judge",
                rationale=(
                    "Fake heuristic: final_answer length < 20 chars."
                    " Short answers often omit context from tool_results."
                    " Human review recommended to verify grounding."
                ),
                model="fake-heuristic",
            )

        return self._pass_finding(
            RUBRIC_FINAL_ANSWER_FAITHFULNESS,
            f"final_answer present ({len(trace.final_answer)} chars)."
            f" Deterministic faithfulness check not possible — human review recommended.",
        )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def _pass_finding(rubric, message: str) -> JudgeFinding:
        """构建"无明显问题"的占位 JudgeFinding。"""
        return JudgeFinding(
            finding_id=f"tqj-{rubric.dimension_id.replace('_', '-')}-pass",
            severity="info",
            category="judge",
            message=f"PASS: {message}",
            evidence_ref="n/a",
            confidence=None,
            rubric=rubric.rubric_text,
            provider="tool-use-quality-judge",
            rationale=message,
            model="fake-heuristic",
        )
