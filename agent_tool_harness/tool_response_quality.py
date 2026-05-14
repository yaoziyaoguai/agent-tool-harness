"""Tool response quality inspection —— deterministic tool_result content hints.

架构边界
--------
- **负责**：消费 ExecutionTrace 的 tool_results，对 output / error 做确定性
  response quality 检查，产出 RuleFinding 列表。所有检查 zero-network, deterministic。
- **不负责**：不检查 tool spec 文档（那是 ToolSpecInspector 的事）、
  不检查 trace 结构不变量（那是 ToolUseInspector 的事）、
  不做 LLM 语义判断（faithfulness / missing fields for next call 等）、
  不自动修改 output、不调用 LLM。
- **为什么输入是 ExecutionTrace 而非仅 tool_results**：部分规则需要 tool_calls
  做配对查找（如确认 status=success 的调用预期有 output）。

当前规则集（6 条，2 ERROR + 4 WARNING，全部 deterministic）
--------------------------------------------------------------
ERROR（rule_passed=False 当违反 → 影响 EvaluationResult.passed）:
1. tool_response.success.output_present  — status=success 时 output 非空
2. tool_response.failure.error_present   — status=error 时 error 非空

WARNING（rule_passed=True，severity="medium"）:
3. tool_response.output.size_reasonable      — output 字符串化后不超阈值
4. tool_response.output.low_signal           — output 含可辨识内容
5. tool_response.error.actionable            — error message 提供可操作信息
6. tool_response.output.context_fields_present — output 含人类可读字段

明确 deferred:
- LLM semantic faithfulness / missing fields for next call
- truncation guidance detection（依赖特定 truncation 标记）
- concise/detailed mode detection
- automatic response rewriting
"""

from __future__ import annotations

import json

from agent_tool_harness.core_contract import ExecutionTrace, RuleFinding

# ---------------------------------------------------------------------------
# 启发式常量
# ---------------------------------------------------------------------------

# output 序列化后超过此长度视为过大（字符数）。
_OUTPUT_SIZE_WARNING_THRESHOLD = 100_000

# 低信号 output 值 —— 这些内容不提供可操作的上下文。
_LOW_SIGNAL_STRINGS = frozenset({"ok", "success", "done", "true", "false", "null", "none"})

# 低信号 output dict —— 仅包含 status-like 字段，不含实际数据。
_LOW_SIGNAL_DICT_KEYS = frozenset({"status", "success", "ok", "result", "message"})

# error 不可操作 —— 只返回这些内容时 Agent 无法知道如何修正。
_NON_ACTIONABLE_ERRORS = frozenset({
    "unknown", "error", "failed", "failure", "exception",
    "internal error", "internal server error", "bad request",
    "something went wrong", "an error occurred",
})

# 人类可读上下文字段 —— output 如果是 object/list of object 应至少含其一。
_CONTEXT_FIELD_NAMES = frozenset({
    "name", "title", "summary", "description", "message",
    "label", "text", "content", "body", "id", "key", "slug",
    "status", "type", "category", "created_at", "updated_at",
})


class ToolResponseQualityInspector:
    """对 ExecutionTrace 的 tool_results 做确定性 response quality 检查。

    ERROR 规则（success output missing / failure error missing）rule_passed=False，
    WARNING 规则 rule_passed=True。不依赖 LLM / 网络 / tool spec。
    """

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    def inspect(self, trace: ExecutionTrace) -> list[RuleFinding]:
        """运行全部 6 条确定性检查，返回 RuleFinding 列表。"""
        findings: list[RuleFinding] = []
        findings.extend(self._check_success_output_present(trace))
        findings.extend(self._check_failure_error_present(trace))
        findings.extend(self._check_output_size_reasonable(trace))
        findings.extend(self._check_output_low_signal(trace))
        findings.extend(self._check_error_actionable(trace))
        findings.extend(self._check_output_context_fields_present(trace))
        return findings

    # ------------------------------------------------------------------
    # Rule 1: tool_response.success.output_present (ERROR)
    # ------------------------------------------------------------------

    def _check_success_output_present(self, trace: ExecutionTrace) -> list[RuleFinding]:
        rule_type = "tool_response.success.output_present"
        success_results = [r for r in trace.tool_results if r.status == "success"]
        findings: list[RuleFinding] = []

        for result in success_results:
            output = result.output or {}
            is_empty = (
                output == {}
                or output == []
                or output == ""
                or output is None
            )
            if is_empty:
                findings.append(RuleFinding(
                    finding_id=f"{rule_type}::{result.call_id}",
                    severity="high",
                    category="rule",
                    message=f"status=success but output is empty (call_id={result.call_id})",
                    evidence_ref=f"tool_result:{result.call_id}",
                    rule_type=rule_type,
                    rule_passed=False,
                ))

        if not findings:
            findings.append(RuleFinding(
                finding_id=f"{rule_type}::all",
                severity="info",
                category="rule",
                message=(
                    "all success tool_results have non-empty output"
                    if success_results
                    else "no success tool_results to check"
                ),
                evidence_ref=f"tool_results[{len(trace.tool_results)} items]",
                rule_type=rule_type,
                rule_passed=True,
            ))

        return findings

    # ------------------------------------------------------------------
    # Rule 2: tool_response.failure.error_present (ERROR)
    # ------------------------------------------------------------------

    def _check_failure_error_present(self, trace: ExecutionTrace) -> list[RuleFinding]:
        rule_type = "tool_response.failure.error_present"
        error_results = [r for r in trace.tool_results if r.status == "error"]
        findings: list[RuleFinding] = []

        for result in error_results:
            if not result.error or not result.error.strip():
                findings.append(RuleFinding(
                    finding_id=f"{rule_type}::{result.call_id}",
                    severity="high",
                    category="rule",
                    message=f"status=error but error is empty (call_id={result.call_id})",
                    evidence_ref=f"tool_result:{result.call_id}",
                    rule_type=rule_type,
                    rule_passed=False,
                ))

        if not findings:
            findings.append(RuleFinding(
                finding_id=f"{rule_type}::all",
                severity="info",
                category="rule",
                message=(
                    "all error tool_results have non-empty error"
                    if error_results
                    else "no error tool_results to check"
                ),
                evidence_ref=f"tool_results[{len(trace.tool_results)} items]",
                rule_type=rule_type,
                rule_passed=True,
            ))

        return findings

    # ------------------------------------------------------------------
    # Rule 3: tool_response.output.size_reasonable (WARNING)
    # ------------------------------------------------------------------

    def _check_output_size_reasonable(
        self, trace: ExecutionTrace
    ) -> list[RuleFinding]:
        rule_type = "tool_response.output.size_reasonable"
        findings: list[RuleFinding] = []

        for result in trace.tool_results:
            output = result.output or {}
            try:
                serialized = json.dumps(output, default=str)
            except Exception:
                serialized = str(output)
            size = len(serialized)

            if size > _OUTPUT_SIZE_WARNING_THRESHOLD:
                findings.append(RuleFinding(
                    finding_id=f"{rule_type}::{result.call_id}",
                    severity="medium",
                    category="rule",
                    message=(
                        f"output size {size} chars exceeds threshold"
                        f" {_OUTPUT_SIZE_WARNING_THRESHOLD}"
                        f" (call_id={result.call_id})"
                    ),
                    evidence_ref=f"tool_result:{result.call_id}",
                    rule_type=rule_type,
                    rule_passed=True,
                ))

        if not findings:
            findings.append(RuleFinding(
                finding_id=f"{rule_type}::all",
                severity="info",
                category="rule",
                message="all tool_result outputs within size threshold",
                evidence_ref=f"tool_results[{len(trace.tool_results)} items]",
                rule_type=rule_type,
                rule_passed=True,
            ))

        return findings

    # ------------------------------------------------------------------
    # Rule 4: tool_response.output.low_signal (WARNING)
    # ------------------------------------------------------------------

    def _check_output_low_signal(self, trace: ExecutionTrace) -> list[RuleFinding]:
        rule_type = "tool_response.output.low_signal"
        findings: list[RuleFinding] = []

        for result in trace.tool_results:
            output = result.output or {}
            if self._is_low_signal(output):
                findings.append(RuleFinding(
                    finding_id=f"{rule_type}::{result.call_id}",
                    severity="medium",
                    category="rule",
                    message=(
                        f"output is low-signal: {json.dumps(output, default=str)[:120]}"
                        f" (call_id={result.call_id})"
                    ),
                    evidence_ref=f"tool_result:{result.call_id}",
                    rule_type=rule_type,
                    rule_passed=True,
                ))

        if not findings:
            findings.append(RuleFinding(
                finding_id=f"{rule_type}::all",
                severity="info",
                category="rule",
                message="all tool_result outputs have meaningful signal",
                evidence_ref=f"tool_results[{len(trace.tool_results)} items]",
                rule_type=rule_type,
                rule_passed=True,
            ))

        return findings

    @staticmethod
    def _is_low_signal(output: dict | list | str | None) -> bool:
        """判断 output 是否不包含可操作的上下文。"""
        if output is None:
            return True
        if isinstance(output, str):
            return output.lower().strip() in _LOW_SIGNAL_STRINGS or output.strip() == ""
        if isinstance(output, list):
            return len(output) == 0
        if isinstance(output, dict):
            if len(output) == 0:
                return True
            # dict 中仅有 status-like 字段 → 低信号
            keys = {k.lower() for k in output}
            if keys and keys <= _LOW_SIGNAL_DICT_KEYS:
                return True
        return False

    # ------------------------------------------------------------------
    # Rule 5: tool_response.error.actionable (WARNING)
    # ------------------------------------------------------------------

    def _check_error_actionable(self, trace: ExecutionTrace) -> list[RuleFinding]:
        rule_type = "tool_response.error.actionable"
        error_results = [r for r in trace.tool_results if r.status == "error"]
        findings: list[RuleFinding] = []

        for result in error_results:
            error_msg = (result.error or "").strip()
            if not error_msg:
                continue  # 由 failure.error_present 覆盖
            error_lower = error_msg.lower()
            is_non_actionable = (
                error_lower in _NON_ACTIONABLE_ERRORS
                or len(error_msg) < 10
            )
            if is_non_actionable:
                findings.append(RuleFinding(
                    finding_id=f"{rule_type}::{result.call_id}",
                    severity="medium",
                    category="rule",
                    message=(
                        f"error message is not actionable: '{error_msg[:100]}'"
                        f" (call_id={result.call_id})"
                    ),
                    evidence_ref=f"tool_result:{result.call_id}",
                    rule_type=rule_type,
                    rule_passed=True,
                ))

        if not findings:
            findings.append(RuleFinding(
                finding_id=f"{rule_type}::all",
                severity="info",
                category="rule",
                message=(
                    "all error messages are actionable"
                    if error_results
                    else "no error tool_results to check"
                ),
                evidence_ref=f"tool_results[{len(trace.tool_results)} items]",
                rule_type=rule_type,
                rule_passed=True,
            ))

        return findings

    # ------------------------------------------------------------------
    # Rule 6: tool_response.output.context_fields_present (WARNING)
    # ------------------------------------------------------------------

    def _check_output_context_fields_present(
        self, trace: ExecutionTrace
    ) -> list[RuleFinding]:
        rule_type = "tool_response.output.context_fields_present"
        findings: list[RuleFinding] = []

        for result in trace.tool_results:
            output = result.output or {}
            if not isinstance(output, dict) or len(output) == 0:
                continue
            if not self._has_context_fields(output):
                findings.append(RuleFinding(
                    finding_id=f"{rule_type}::{result.call_id}",
                    severity="medium",
                    category="rule",
                    message=(
                        f"output missing context fields"
                        f" (keys: {sorted(output.keys())})"
                        f" (call_id={result.call_id})"
                    ),
                    evidence_ref=f"tool_result:{result.call_id}",
                    rule_type=rule_type,
                    rule_passed=True,
                ))

        if not findings:
            findings.append(RuleFinding(
                finding_id=f"{rule_type}::all",
                severity="info",
                category="rule",
                message=(
                    "all object outputs have context fields"
                    if trace.tool_results
                    else "no tool_results to check"
                ),
                evidence_ref=f"tool_results[{len(trace.tool_results)} items]",
                rule_type=rule_type,
                rule_passed=True,
            ))

        return findings

    @staticmethod
    def _has_context_fields(output: dict) -> bool:
        """检查 output dict 或其内嵌 list 是否包含人类可读上下文字段。"""
        keys = {k.lower() for k in output}
        if keys & _CONTEXT_FIELD_NAMES:
            return True
        # 检查 list-typed 的值是否包含 context fields
        for value in output.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, dict):
                        item_keys = {k.lower() for k in item}
                        if item_keys & _CONTEXT_FIELD_NAMES:
                            return True
        return False
