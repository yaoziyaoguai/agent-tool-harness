"""v3.5 P3: ContextEfficiencyAnalyzer —— 上下文效率分析。

识别 5 种确定性 context inefficiency pattern，产出 RuleFinding (category="context")。
所有检测为纯函数，不调 LLM，不依赖网络。

架构边界
--------
- **负责**：消费 ExecutionTrace，检测 5 种 inefficiency pattern，产出 RuleFinding。
- **不负责**：不做 transcript confusion 分析（那是 TranscriptPatternAnalyzer 的事）、
  不生成报告（P4）、不修改 trace。
"""

from __future__ import annotations

import json
from typing import Any

from agent_tool_harness.analysis.transcript_primitives import (
    _PAGINATION_PARAMS,
    extract_fields_usage,
    is_truncated,
)
from agent_tool_harness.core_contract import ExecutionTrace, RuleFinding

# 常见隐式引用字段 —— low_value_large_fields 中这些字段名视为"总被引用"
# 因为这些是通用容器字段名，Agent 无需逐字引用其名称
_IMPLICITLY_REFERENCED_FIELDS: set[str] = {
    "result", "results", "data", "output", "content", "items", "records",
    "entries", "response", "body", "message", "text", "value", "payload",
    "return", "answer", "list", "array", "collection",
}

# ---------------------------------------------------------------------------
# 简洁模式标记 —— missing_concise_mode 检测用
# ---------------------------------------------------------------------------

_CONCISE_FIELD_MARKERS: set[str] = {
    "summary", "abstract", "brief", "short", "preview",
    "description", "title", "name", "id", "key",
}

# 截断后应有的延续提示 —— truncation_without_hint 检测用
_CONTINUATION_HINT_KEYS: set[str] = {
    "next_cursor", "cursor", "continuation_token", "next_token",
    "has_more", "more", "next_page", "next", "offset", "page_token",
    "next_page_token", "pagination",
}


# ---------------------------------------------------------------------------
# ContextEfficiencyAnalyzer
# ---------------------------------------------------------------------------


class ContextEfficiencyAnalyzer:
    """消费 ExecutionTrace，识别 5 种上下文效率问题。

    用法::

        analyzer = ContextEfficiencyAnalyzer()
        findings = analyzer.analyze(trace)
        for f in findings:
            print(f"[{f.severity}] {f.message}")
    """

    def analyze(self, trace: ExecutionTrace) -> list[RuleFinding]:
        """执行全部 5 种 inefficiency pattern 检测。"""
        findings: list[RuleFinding] = []
        findings.extend(self._detect_response_bloat(trace))
        findings.extend(self._detect_missing_pagination(trace))
        findings.extend(self._detect_missing_concise_mode(trace))
        findings.extend(self._detect_low_value_large_fields(trace))
        findings.extend(self._detect_truncation_without_hint(trace))
        return findings

    # -------------------------------------------------------------------
    # 辅助：按 tool_name 分组计算 median
    # -------------------------------------------------------------------

    @staticmethod
    def _compute_median_sizes(
        results: list,
    ) -> dict[str, float]:
        """按 tool_name 分组计算各 tool 的 median output 字符数。

        Returns:
            {tool_name: median_char_count}，仅包含 ≥ 2 次调用的 tool。
        """
        sizes_by_tool: dict[str, list[int]] = {}
        for r in results:
            sizes_by_tool.setdefault(r.tool_name, []).append(
                len(json.dumps(r.output, ensure_ascii=False))
            )

        medians: dict[str, float] = {}
        for tool, sizes in sizes_by_tool.items():
            if len(sizes) >= 2:
                s = sorted(sizes)
                mid = len(s) // 2
                medians[tool] = (s[mid] + s[~mid]) / 2  # median for even/odd
        return medians

    # -------------------------------------------------------------------
    # 1. response_bloat (high)
    # -------------------------------------------------------------------

    def _detect_response_bloat(
        self, trace: ExecutionTrace
    ) -> list[RuleFinding]:
        """检测单个 tool result output 异常膨胀（> median × 10）。

        RFC Decision 4: median 由同名 tool 在本次 trace 中计算；
        只有 1 次调用则跳过。
        """
        findings: list[RuleFinding] = []
        results = trace.tool_results
        if len(results) < 2:
            return findings

        medians = self._compute_median_sizes(results)

        for r in results:
            if r.tool_name not in medians:
                continue  # 该 tool 调用次数不足，跳过

            char_count = len(json.dumps(r.output, ensure_ascii=False))
            median = medians[r.tool_name]
            if median <= 0:
                continue

            ratio = char_count / median
            if ratio > 10:
                findings.append(
                    RuleFinding(
                        finding_id=f"context.bloat-{len(findings)+1}",
                        severity="high",
                        category="context",
                        rule_type="context.response_bloat",
                        rule_passed=False,
                        message=(
                            f"'{r.tool_name}' (call_id={r.call_id}) "
                            f"返回 {char_count} 字符，为 median ({median:.0f}) "
                            f"的 {ratio:.0f}x"
                        ),
                        evidence_ref=f"tool_results[call_id={r.call_id}]",
                    )
                )

        return findings

    # -------------------------------------------------------------------
    # 2. missing_pagination (high)
    # -------------------------------------------------------------------

    def _detect_missing_pagination(
        self, trace: ExecutionTrace
    ) -> list[RuleFinding]:
        """检测大量数据返回但缺少分页参数。

        当一个 tool_result 的 output 中包含 ≥ 20 项的 list 时，
        检查对应 tool call 的 args 是否包含分页参数。
        """
        findings: list[RuleFinding] = []
        calls = trace.tool_calls

        # call_id → call 映射
        call_map: dict[str, Any] = {c.call_id: c for c in calls}

        for r in trace.tool_results:
            # 找到 output 中最大的 list
            max_list_len = 0
            list_key = ""
            for key, val in r.output.items():
                if isinstance(val, list):
                    if len(val) > max_list_len:
                        max_list_len = len(val)
                        list_key = key

            if max_list_len < 20:
                continue

            # 检查对应 tool call 是否有分页参数
            call = call_map.get(r.call_id)
            if call is None:
                continue

            has_pagination = any(
                p in call.arguments
                for p in _PAGINATION_PARAMS
            )
            if has_pagination:
                continue

            findings.append(
                RuleFinding(
                    finding_id=f"context.pagination-{len(findings)+1}",
                    severity="high",
                    category="context",
                    rule_type="context.missing_pagination",
                    rule_passed=False,
                    message=(
                        f"'{r.tool_name}' (call_id={r.call_id}) "
                        f"返回 {max_list_len} 条 '{list_key}' 但未传分页参数"
                    ),
                    evidence_ref=f"tool_results[call_id={r.call_id}]",
                )
            )

        return findings

    # -------------------------------------------------------------------
    # 3. missing_concise_mode (medium)
    # -------------------------------------------------------------------

    def _detect_missing_concise_mode(
        self, trace: ExecutionTrace
    ) -> list[RuleFinding]:
        """检测 output 字段过多但缺少简洁模式标记。

        output 包含 ≥ 5 个 field，且没有任何 summary/abstract 等简洁标记。
        """
        findings: list[RuleFinding] = []
        for r in trace.tool_results:
            if not r.output:
                continue
            if len(r.output) < 5:
                continue

            # 检查是否已有简洁标记
            output_keys_lower = {k.lower() for k in r.output.keys()}
            has_concise = bool(output_keys_lower & _CONCISE_FIELD_MARKERS)
            if has_concise:
                continue

            # 计算 output 的字符分布
            usage = extract_fields_usage(r.output)
            findings.append(
                RuleFinding(
                    finding_id=f"context.concise-{len(findings)+1}",
                    severity="medium",
                    category="context",
                    rule_type="context.missing_concise_mode",
                    rule_passed=False,
                    message=(
                        f"'{r.tool_name}' (call_id={r.call_id}) "
                        f"返回 {len(r.output)} 个字段 ({usage['total_chars']} 字符) "
                        f"但无简洁标记，最大字段为 '{usage['largest_field']}'"
                    ),
                    evidence_ref=f"tool_results[call_id={r.call_id}]",
                )
            )

        return findings

    # -------------------------------------------------------------------
    # 4. low_value_large_fields (medium)
    # -------------------------------------------------------------------

    def _detect_low_value_large_fields(
        self, trace: ExecutionTrace
    ) -> list[RuleFinding]:
        """检测输出中某个字段占比过大但后续未被引用。

        使用 extract_fields_usage 找出最大字段，检查其 key 名是否在
        后续 tool call args 或 final_answer 中出现。
        """
        findings: list[RuleFinding] = []
        calls = trace.tool_calls

        # call_id → 在 calls 中的 index
        call_index: dict[str, int] = {}
        for idx, c in enumerate(calls):
            call_index[c.call_id] = idx

        # 收集所有后续文本（tool args + final answer）用于"引用检测"
        subsequent_text_parts: list[str] = [trace.final_answer]

        for r in trace.tool_results:
            usage = extract_fields_usage(r.output)
            if usage["total_chars"] == 0:
                continue
            if usage["largest_field"] is None:
                continue

            largest = usage["largest_field"]
            ratio = usage["field_ratios"].get(largest, 0.0)

            # 仅 flag 多字段输出中占比 > 50% 的字段
            # 单字段输出天然占 100%，是合理的
            if len(r.output) < 2:
                continue
            if ratio <= 0.5:
                continue

            # 检查该 field key 是否在后续被引用
            r_idx = call_index.get(r.call_id)
            if r_idx is not None:
                # 收集后续 tool call 的 args 文本
                for later_call in calls[r_idx + 1:]:
                    subsequent_text_parts.append(
                        json.dumps(later_call.arguments, ensure_ascii=False)
                    )

            all_subsequent = " ".join(subsequent_text_parts).lower()
            # 字段名在后续文本中出现，或者是通用容器字段 → 视为已引用
            is_referenced = (
                largest.lower() in all_subsequent
                or largest.lower() in _IMPLICITLY_REFERENCED_FIELDS
            )

            if not is_referenced:
                findings.append(
                    RuleFinding(
                        finding_id=f"context.low_value-{len(findings)+1}",
                        severity="medium",
                        category="context",
                        rule_type="context.low_value_large_fields",
                        rule_passed=False,
                        message=(
                            f"'{r.tool_name}' (call_id={r.call_id}) "
                            f"字段 '{largest}' 占 {ratio:.0%} 字符 "
                            f"但后续未被引用"
                        ),
                        evidence_ref=f"tool_results[call_id={r.call_id}]",
                    )
                )

        return findings

    # -------------------------------------------------------------------
    # 5. truncation_without_hint (high)
    # -------------------------------------------------------------------

    def _detect_truncation_without_hint(
        self, trace: ExecutionTrace
    ) -> list[RuleFinding]:
        """检测输出被截断但缺少延续提示。

        使用 is_truncated 检测截断标记，然后检查 output 中是否包含
        next_cursor/continuation_token/has_more 等延续提示。
        """
        findings: list[RuleFinding] = []
        for r in trace.tool_results:
            # 检查 output 中是否有任何字符串值被截断
            truncated = False
            for val in r.output.values():
                if isinstance(val, str) and is_truncated(val):
                    truncated = True
                    break
            # 也检查 error 文本
            if r.error and is_truncated(r.error):
                truncated = True
            if not truncated:
                continue

            # 检查是否有延续提示
            has_hint = False
            for k in r.output:
                if k.lower() in _CONTINUATION_HINT_KEYS:
                    has_hint = True
                    break
            # 也检查 error 字段
            if r.error:
                for hint_key in _CONTINUATION_HINT_KEYS:
                    if hint_key in r.error.lower():
                        has_hint = True
                        break

            if has_hint:
                continue

            findings.append(
                RuleFinding(
                    finding_id=f"context.truncation-{len(findings)+1}",
                    severity="high",
                    category="context",
                    rule_type="context.truncation_without_hint",
                    rule_passed=False,
                    message=(
                        f"'{r.tool_name}' (call_id={r.call_id}) "
                        f"返回被截断但缺少延续提示 (cursor/next_page 等)"
                    ),
                    evidence_ref=f"tool_results[call_id={r.call_id}]",
                )
            )

        return findings
