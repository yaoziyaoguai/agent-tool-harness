"""v3.5 P2: TranscriptPatternAnalyzer —— Agent 困惑模式分析。

识别 6 种确定性 confusion pattern，产出 RuleFinding (category="transcript")。
所有检测为纯函数，不调 LLM，不依赖网络。

架构边界
--------
- **负责**：消费 ExecutionTrace，检测 6 种 confusion pattern，产出 RuleFinding。
- **不负责**：不做 context efficiency 分析（那是 ContextEfficiencyAnalyzer 的事）、
  不生成报告（P4）、不修改 trace。
"""

from __future__ import annotations

import json
import re

from agent_tool_harness.analysis.transcript_primitives import (
    consecutive_groups,
    find_repeated_sequences,
    normalize_args,
)
from agent_tool_harness.core_contract import ExecutionTrace, RuleFinding

# ---------------------------------------------------------------------------
# stopwords 列表 —— 用于 final_answer_without_support 的文本匹配
# ---------------------------------------------------------------------------

_STOPWORDS: set[str] = {
    "the", "and", "for", "from", "that", "this", "with", "have", "been",
    "were", "their", "they", "will", "would", "could", "should", "about",
    "also", "after", "before", "which", "there", "these", "those", "then",
    "than", "into", "over", "under", "more", "some", "such", "only",
    "other", "each", "every", "both", "just", "because", "through",
    "between", "since", "without", "within", "along", "among",
}

# 搜索相关的 args key 名 —— 用于 broad_search_loop 检测
_SEARCH_PARAM_KEYS: set[str] = {
    "query", "q", "search", "text", "keyword", "keywords", "question",
    "prompt", "input", "term", "terms", "pattern", "expression", "expr",
}

# 分页/范围相关参数 —— 用于 broad_search_loop 的单调递增检测
_RANGE_PARAM_KEYS: set[str] = {
    "limit", "page", "offset", "max_results", "top", "size", "count",
    "window", "range", "max_tokens", "max_length",
}


# ---------------------------------------------------------------------------
# TranscriptPatternAnalyzer
# ---------------------------------------------------------------------------


class TranscriptPatternAnalyzer:
    """消费 ExecutionTrace，识别 6 种 Agent 困惑模式。

    用法::

        analyzer = TranscriptPatternAnalyzer()
        findings = analyzer.analyze(trace)
        for f in findings:
            print(f"[{f.severity}] {f.message}")
    """

    def analyze(self, trace: ExecutionTrace) -> list[RuleFinding]:
        """执行全部 6 种 pattern 检测，返回 RuleFinding 列表。"""
        findings: list[RuleFinding] = []
        findings.extend(self._detect_repeated_retry(trace))
        findings.extend(self._detect_tool_switching_confusion(trace))
        findings.extend(self._detect_invalid_arg_retry(trace))
        findings.extend(self._detect_no_recovery_after_error(trace))
        findings.extend(self._detect_final_answer_without_support(trace))
        findings.extend(self._detect_broad_search_loop(trace))
        return findings

    # -------------------------------------------------------------------
    # 1. repeated_tool_retry_loop (high)
    # -------------------------------------------------------------------

    def _detect_repeated_retry(
        self, trace: ExecutionTrace
    ) -> list[RuleFinding]:
        """检测同一 tool+args 连续 ≥ 3 次调用的死循环模式。

        使用 normalize_args 生成确定性签名，然后 consecutive_groups
        按 (tool_name, args_signature) 分组，长度 ≥ 3 的组即为重复重试。
        """
        findings: list[RuleFinding] = []
        calls = trace.tool_calls
        if len(calls) < 3:
            return findings

        # 按 (tool_name, args_sig) 连续分组
        groups = consecutive_groups(
            calls,
            key=lambda c: (c.tool_name, normalize_args(c.arguments)),
        )

        idx = 0  # 追踪在原序列中的位置
        for grp in groups:
            count = len(grp)
            if count >= 3:
                # 找到起始 step 号（1-indexed）
                start_step = idx + 1
                end_step = idx + count
                findings.append(
                    RuleFinding(
                        finding_id=f"transcript.repeated_retry-{len(findings)+1}",
                        severity="high",
                        category="transcript",
                        rule_type="transcript.repeated_tool_retry_loop",
                        rule_passed=False,
                        message=(
                            f"'{grp[0].tool_name}' 连续调用 {count} 次，"
                            f"参数完全相同 (steps {start_step}-{end_step})"
                        ),
                        evidence_ref=f"tool_calls[{idx}:{idx + count}]",
                    )
                )
            idx += count

        return findings

    # -------------------------------------------------------------------
    # 2. tool_switching_confusion (medium)
    # -------------------------------------------------------------------

    def _detect_tool_switching_confusion(
        self, trace: ExecutionTrace
    ) -> list[RuleFinding]:
        """检测工具间来回切换的困惑模式 (A→B→A→B...)。

        使用 find_repeated_sequences 查找重复的 tool_name 模式，
        period=2 检测 A↔B 交替，period=3 检测 A→B→C→A→B→C。
        """
        findings: list[RuleFinding] = []
        tool_names = [c.tool_name for c in trace.tool_calls]
        if len(tool_names) < 4:
            return findings

        # 使用 P1 原语查找重复序列
        seqs = find_repeated_sequences(tool_names, min_period=2, min_cycles=2)
        for seq in seqs:
            pattern_str = " ↔ ".join(seq["pattern"])
            findings.append(
                RuleFinding(
                    finding_id=f"transcript.switching-{len(findings)+1}",
                    severity="medium",
                    category="transcript",
                    rule_type="transcript.tool_switching_confusion",
                    rule_passed=False,
                    message=(
                        f"工具切换困惑: {pattern_str} 模式重复 "
                        f"{seq['cycles']} 次 (steps {seq['start_idx']+1}-{seq['end_idx']})"
                    ),
                    evidence_ref=(
                        f"tool_calls[{seq['start_idx']}:{seq['end_idx']}]"
                    ),
                )
            )

        return findings

    # -------------------------------------------------------------------
    # 3. invalid_arg_retry (high)
    # -------------------------------------------------------------------

    def _detect_invalid_arg_retry(
        self, trace: ExecutionTrace
    ) -> list[RuleFinding]:
        """检测参数微调式重试：同一 tool 连续调用但只改了一个参数值。

        检测条件：同一 tool_name、键集合完全相同、恰好 1 个 key 的值变化。
        """
        findings: list[RuleFinding] = []
        calls = trace.tool_calls
        if len(calls) < 2:
            return findings

        i = 0
        while i < len(calls) - 1:
            a = calls[i]
            b = calls[i + 1]
            if a.tool_name != b.tool_name:
                i += 1
                continue

            # 键集合必须完全相同
            if set(a.arguments.keys()) != set(b.arguments.keys()):
                i += 1
                continue

            # 找出值发生变化的 key
            changed_keys = [
                k for k in a.arguments
                if json.dumps(a.arguments[k], sort_keys=True, ensure_ascii=False)
                != json.dumps(b.arguments[k], sort_keys=True, ensure_ascii=False)
            ]

            # 恰好 1 个 key 的值发生变化 → 微调重试
            if len(changed_keys) == 1:
                findings.append(
                    RuleFinding(
                        finding_id=f"transcript.invalid_arg-{len(findings)+1}",
                        severity="high",
                        category="transcript",
                        rule_type="transcript.invalid_arg_retry",
                        rule_passed=False,
                        message=(
                            f"'{a.tool_name}' 在 steps {i+1}-{i+2} 之间仅微调参数 "
                            f"'{changed_keys[0]}'"
                        ),
                        evidence_ref=f"tool_calls[{i}:{i+2}]",
                    )
                )
                i += 2  # 跳过已检测对
            else:
                i += 1

        return findings

    # -------------------------------------------------------------------
    # 4. no_recovery_after_error (high)
    # -------------------------------------------------------------------

    def _detect_no_recovery_after_error(
        self, trace: ExecutionTrace
    ) -> list[RuleFinding]:
        """检测错误后无恢复：tool result status="error" 后 ≤ 2 steps 内无重试。

        对每个 error result，检查之后是否还有 tool call。
        如果没有或间隔 > 2 步，标记为无恢复。
        """
        findings: list[RuleFinding] = []
        calls = trace.tool_calls
        results = trace.tool_results
        if not results:
            return findings

        # 构建 call_id → call index 映射
        call_id_to_idx: dict[str, int] = {}
        for idx, c in enumerate(calls):
            call_id_to_idx[c.call_id] = idx

        total_calls = len(calls)

        for r in results:
            if r.status != "error":
                continue

            error_call_idx = call_id_to_idx.get(r.call_id)
            if error_call_idx is None:
                continue

            # 检查之后是否还有 tool call，以及是否有同 tool 重试
            remaining = total_calls - error_call_idx - 1
            if remaining == 0:
                recovery = "轨迹结束，未重试"
            else:
                # 检查后续 steps 中是否有同 tool 重试
                check_window = min(remaining, 2)
                next_calls = calls[
                    error_call_idx + 1:error_call_idx + 1 + check_window
                ]
                if any(c.tool_name == r.tool_name for c in next_calls):
                    continue  # 有重试，跳过
                if remaining == 1:
                    recovery = "仅剩 1 步且非重试"
                else:
                    recovery = (
                        f"接下来 {check_window} 步内未重试 "
                        f"(steps {error_call_idx+2}-{error_call_idx+1+check_window})"
                    )

            findings.append(
                RuleFinding(
                    finding_id=f"transcript.no_recovery-{len(findings)+1}",
                    severity="high",
                    category="transcript",
                    rule_type="transcript.no_recovery_after_error",
                    rule_passed=False,
                    message=(
                        f"'{r.tool_name}' (call_id={r.call_id}) "
                        f"返回 error 后未恢复 —— {recovery}"
                    ),
                    evidence_ref=(
                        f"tool_results[call_id={r.call_id}], "
                        f"tool_calls[{error_call_idx}:]"
                    ),
                )
            )

        return findings

    # -------------------------------------------------------------------
    # 5. final_answer_without_support (critical)
    # -------------------------------------------------------------------

    def _detect_final_answer_without_support(
        self, trace: ExecutionTrace
    ) -> list[RuleFinding]:
        """检测最终答案缺乏工具输出支撑（潜在幻觉）。

        提取 final_answer 中的内容词（≥ 4 字符，过滤 stopwords），
        检查其中有多少出现在 tool_result output 中。
        匹配率 < 30% 时标记为缺乏支撑。
        """
        findings: list[RuleFinding] = []
        final = trace.final_answer
        if not final or not final.strip():
            return findings

        results = trace.tool_results
        if not results:
            # 没有任何工具调用却有 final answer → 无支撑
            findings.append(
                RuleFinding(
                    finding_id=f"transcript.no_support-{len(findings)+1}",
                    severity="critical",
                    category="transcript",
                    rule_type="transcript.final_answer_without_support",
                    rule_passed=False,
                    message="final answer 存在但没有任何 tool_result 可支撑",
                    evidence_ref="final_answer",
                )
            )
            return findings

        # 提取内容词（≥ 4 字符，非 stopwords）
        words = re.findall(r"[a-zA-Z]{4,}", final.lower())
        content_words = [w for w in words if w not in _STOPWORDS]
        if not content_words:
            return findings

        # 构建所有 tool output 的全文（小写）
        all_output_text = " ".join(
            json.dumps(r.output, ensure_ascii=False).lower()
            for r in results
        )

        # 计数匹配
        matched = sum(1 for w in content_words if w in all_output_text)
        ratio = matched / len(content_words)

        if ratio < 0.3:
            unique_words = list(dict.fromkeys(content_words))  # 去重保序
            unmatched = [w for w in unique_words if w not in all_output_text][:5]
            findings.append(
                RuleFinding(
                    finding_id=f"transcript.no_support-{len(findings)+1}",
                    severity="critical",
                    category="transcript",
                    rule_type="transcript.final_answer_without_support",
                    rule_passed=False,
                    message=(
                        f"final answer 中 {len(content_words)} 个内容词仅 "
                        f"{matched} 个 ({ratio:.0%}) 出现在 tool output 中，"
                        f"未匹配示例: {', '.join(unmatched)}"
                    ),
                    evidence_ref="final_answer vs tool_results[*].output",
                )
            )

        return findings

    # -------------------------------------------------------------------
    # 6. broad_search_loop (medium)
    # -------------------------------------------------------------------

    def _detect_broad_search_loop(
        self, trace: ExecutionTrace
    ) -> list[RuleFinding]:
        """检测搜索范围逐渐扩大的 fallback 模式。

        同一 tool 连续调用时，如果 query 参数越来越短（更泛化），
        或 limit/offset 参数递增（一次取更多），标记为搜索范围扩大。
        需要 ≥ 3 次连续调用才触发检测。
        """
        findings: list[RuleFinding] = []
        calls = trace.tool_calls
        if len(calls) < 3:
            return findings

        # 按 tool_name 连续分组
        groups = consecutive_groups(calls, key=lambda c: c.tool_name)

        idx = 0
        for grp in groups:
            count = len(grp)
            if count < 3:
                idx += count
                continue

            # 检查搜索参数是否单调扩大
            signal = self._check_broadening(grp)
            if signal:
                findings.append(
                    RuleFinding(
                        finding_id=f"transcript.broad_search-{len(findings)+1}",
                        severity="medium",
                        category="transcript",
                        rule_type="transcript.broad_search_loop",
                        rule_passed=False,
                        message=(
                            f"'{grp[0].tool_name}' 连续调用 {count} 次，"
                            f"搜索范围逐步扩大 (steps {idx+1}-{idx+count}): {signal}"
                        ),
                        evidence_ref=f"tool_calls[{idx}:{idx + count}]",
                    )
                )
            idx += count

        return findings

    def _check_broadening(self, calls: list) -> str | None:
        """检查连续调用中搜索参数是否单调扩大。

        Returns:
            描述信号的中文文本，无信号时返回 None。
        """
        # 提取搜索相关参数
        for key in _SEARCH_PARAM_KEYS:
            queries = []
            for c in calls:
                val = c.arguments.get(key)
                if isinstance(val, str):
                    queries.append(val)

            if len(queries) >= 3:
                # 检查 query 长度是否单调递减（越来越短 = 越来越泛）
                lengths = [len(q) for q in queries]
                if self._is_monotonic_decreasing(lengths) and lengths[0] > lengths[-1]:
                    return (
                        f"'{key}' 参数从 {lengths[0]} 字符缩短到 "
                        f"{lengths[-1]} 字符"
                    )

        # 检查分页参数是否单调递增
        for key in _RANGE_PARAM_KEYS:
            values = []
            for c in calls:
                val = c.arguments.get(key)
                if isinstance(val, (int, float)):
                    values.append(val)

            if len(values) >= 3:
                if self._is_monotonic_increasing(values) and values[0] < values[-1]:
                    return (
                        f"'{key}' 参数从 {values[0]} 递增到 {values[-1]}"
                    )

        return None

    @staticmethod
    def _is_monotonic_decreasing(seq: list) -> bool:
        """非严格单调递减（每个元素 ≤ 前一个）。"""
        for i in range(len(seq) - 1):
            if seq[i + 1] > seq[i]:
                return False
        return True

    @staticmethod
    def _is_monotonic_increasing(seq: list) -> bool:
        """非严格单调递增（每个元素 ≥ 前一个）。"""
        for i in range(len(seq) - 1):
            if seq[i + 1] < seq[i]:
                return False
        return True
