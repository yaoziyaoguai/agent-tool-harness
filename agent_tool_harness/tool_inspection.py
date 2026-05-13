"""Tool-use correctness inspection —— trace-level 确定性不变量检查。

架构边界
--------
- **负责**：消费 ExecutionTrace，对 tool_calls / tool_results 做确定性结构检查，
  产出 RuleFinding 列表。所有检查 zero-network, deterministic。
- **不负责**：不消费 EvalSpec（那是 RuleJudge 的职责）、不做 LLM 语义判断、
  不生成 ReviewDecision、不修改 trace。
- **为什么独立于 TraceImportAdapter**：TraceImportAdapter 在 import 时做
  validation（throw error），本模块在 import 后做 invariant check（produce finding）。
- **为什么独立于 RuleJudge**：RuleJudge 消费 EvalSpec 做 eval-level 规则检查
  （must_call_tool 等），本模块做 trace-level 结构不变量检查，不依赖 EvalSpec。

当前规则集（9 条，全部 deterministic，全部产出 RuleFinding）
--------------------------------------------------------------
1. tool_call.call_id.duplicate    — tool_calls 中 call_id 重复
2. tool_result.call_id.duplicate  — tool_results 中 call_id 重复
3. tool_pair.orphan_call          — tool_call 无对应 tool_result
4. tool_pair.orphan_result        — tool_result 无对应 tool_call
5. tool_call.arguments.present    — arguments 字段存在（非 None）
6. tool_call.arguments.is_object  — arguments 类型为 dict
7. tool_call.tool_name.non_empty  — tool_call 的 tool_name 非空字符串
8. tool_result.tool_name.non_empty — tool_result 的 tool_name 非空字符串
9. tool_result.status.valid       — status 为 "success" 或 "error"
"""

from __future__ import annotations

from collections import Counter

from agent_tool_harness.core_contract import ExecutionTrace, RuleFinding


class ToolUseInspector:
    """对 ExecutionTrace 做 trace-level 确定性不变量检查，产出 RuleFinding 列表。

    所有检查不依赖 EvalSpec、不依赖网络、不依赖 LLM。
    每条规则无论通过与否都产出 RuleFinding——通过时 rule_passed=True，
    违规时 rule_passed=False 并附带具体违规信息。
    """

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    def inspect(self, trace: ExecutionTrace) -> list[RuleFinding]:
        """运行全部 9 条确定性检查，返回 RuleFinding 列表。"""
        return [
            self._check_call_id_duplicate(trace),
            self._check_result_call_id_duplicate(trace),
            self._check_orphan_call(trace),
            self._check_orphan_result(trace),
            self._check_arguments_present(trace),
            self._check_arguments_is_object(trace),
            self._check_call_tool_name_non_empty(trace),
            self._check_result_tool_name_non_empty(trace),
            self._check_result_status_valid(trace),
        ]

    # ------------------------------------------------------------------
    # Rule 1: tool_call.call_id.duplicate
    # ------------------------------------------------------------------

    def _check_call_id_duplicate(self, trace: ExecutionTrace) -> RuleFinding:
        rule_id = "tool_call.call_id.duplicate"
        call_ids = [tc.call_id for tc in trace.tool_calls]
        duplicates = {cid for cid, count in Counter(call_ids).items() if count > 1}

        if duplicates:
            return RuleFinding(
                finding_id=rule_id,
                severity="high",
                category="rule",
                message=f"重复的 tool_call call_id: {sorted(duplicates)}",
                evidence_ref=f"tool_calls[{len(trace.tool_calls)} items]",
                rule_type=rule_id,
                rule_passed=False,
            )

        return RuleFinding(
            finding_id=rule_id,
            severity="info",
            category="rule",
            message="所有 tool_call call_id 唯一",
            evidence_ref=f"tool_calls[{len(trace.tool_calls)} items]",
            rule_type=rule_id,
            rule_passed=True,
        )

    # ------------------------------------------------------------------
    # Rule 2: tool_result.call_id.duplicate
    # ------------------------------------------------------------------

    def _check_result_call_id_duplicate(self, trace: ExecutionTrace) -> RuleFinding:
        rule_id = "tool_result.call_id.duplicate"
        result_ids = [tr.call_id for tr in trace.tool_results]
        duplicates = {rid for rid, count in Counter(result_ids).items() if count > 1}

        if duplicates:
            return RuleFinding(
                finding_id=rule_id,
                severity="high",
                category="rule",
                message=f"重复的 tool_result call_id: {sorted(duplicates)}",
                evidence_ref=f"tool_results[{len(trace.tool_results)} items]",
                rule_type=rule_id,
                rule_passed=False,
            )

        return RuleFinding(
            finding_id=rule_id,
            severity="info",
            category="rule",
            message="所有 tool_result call_id 唯一",
            evidence_ref=f"tool_results[{len(trace.tool_results)} items]",
            rule_type=rule_id,
            rule_passed=True,
        )

    # ------------------------------------------------------------------
    # Rule 3: tool_pair.orphan_call
    # ------------------------------------------------------------------

    def _check_orphan_call(self, trace: ExecutionTrace) -> RuleFinding:
        rule_id = "tool_pair.orphan_call"
        result_ids = {tr.call_id for tr in trace.tool_results}
        orphans = [tc.call_id for tc in trace.tool_calls if tc.call_id not in result_ids]

        if orphans:
            return RuleFinding(
                finding_id=rule_id,
                severity="high",
                category="rule",
                message=f"tool_call 缺少对应 tool_result: {orphans}",
                evidence_ref=f"orphan call_ids: {orphans}",
                rule_type=rule_id,
                rule_passed=False,
            )

        return RuleFinding(
            finding_id=rule_id,
            severity="info",
            category="rule",
            message="所有 tool_call 都有对应 tool_result",
            evidence_ref=(
                f"tool_calls[{len(trace.tool_calls)}]"
                f" ↔ tool_results[{len(trace.tool_results)}]"
            ),
            rule_type=rule_id,
            rule_passed=True,
        )

    # ------------------------------------------------------------------
    # Rule 4: tool_pair.orphan_result
    # ------------------------------------------------------------------

    def _check_orphan_result(self, trace: ExecutionTrace) -> RuleFinding:
        rule_id = "tool_pair.orphan_result"
        call_ids = {tc.call_id for tc in trace.tool_calls}
        orphans = [tr.call_id for tr in trace.tool_results if tr.call_id not in call_ids]

        if orphans:
            return RuleFinding(
                finding_id=rule_id,
                severity="high",
                category="rule",
                message=f"tool_result 缺少对应 tool_call: {orphans}",
                evidence_ref=f"orphan call_ids: {orphans}",
                rule_type=rule_id,
                rule_passed=False,
            )

        return RuleFinding(
            finding_id=rule_id,
            severity="info",
            category="rule",
            message="所有 tool_result 都有对应 tool_call",
            evidence_ref=(
                f"tool_results[{len(trace.tool_results)}]"
                f" ↔ tool_calls[{len(trace.tool_calls)}]"
            ),
            rule_type=rule_id,
            rule_passed=True,
        )

    # ------------------------------------------------------------------
    # Rule 5: tool_call.arguments.present
    # ------------------------------------------------------------------

    def _check_arguments_present(self, trace: ExecutionTrace) -> RuleFinding:
        rule_id = "tool_call.arguments.present"
        missing = [
            tc.call_id for tc in trace.tool_calls if tc.arguments is None
        ]

        if missing:
            return RuleFinding(
                finding_id=rule_id,
                severity="critical",
                category="rule",
                message=f"tool_call arguments 为 None: {missing}",
                evidence_ref=f"call_ids with missing arguments: {missing}",
                rule_type=rule_id,
                rule_passed=False,
            )

        return RuleFinding(
            finding_id=rule_id,
            severity="info",
            category="rule",
            message="所有 tool_call arguments 字段存在",
            evidence_ref=f"tool_calls[{len(trace.tool_calls)} items]",
            rule_type=rule_id,
            rule_passed=True,
        )

    # ------------------------------------------------------------------
    # Rule 6: tool_call.arguments.is_object
    # ------------------------------------------------------------------

    def _check_arguments_is_object(self, trace: ExecutionTrace) -> RuleFinding:
        rule_id = "tool_call.arguments.is_object"
        non_dict = [
            tc.call_id
            for tc in trace.tool_calls
            if tc.arguments is not None and not isinstance(tc.arguments, dict)
        ]

        if non_dict:
            return RuleFinding(
                finding_id=rule_id,
                severity="critical",
                category="rule",
                message=f"tool_call arguments 不是 dict: {non_dict}",
                evidence_ref=f"call_ids with non-dict arguments: {non_dict}",
                rule_type=rule_id,
                rule_passed=False,
            )

        return RuleFinding(
            finding_id=rule_id,
            severity="info",
            category="rule",
            message="所有 tool_call arguments 为 dict",
            evidence_ref=f"tool_calls[{len(trace.tool_calls)} items]",
            rule_type=rule_id,
            rule_passed=True,
        )

    # ------------------------------------------------------------------
    # Rule 7: tool_call.tool_name.non_empty
    # ------------------------------------------------------------------

    def _check_call_tool_name_non_empty(self, trace: ExecutionTrace) -> RuleFinding:
        rule_id = "tool_call.tool_name.non_empty"
        empty = [
            tc.call_id
            for tc in trace.tool_calls
            if not isinstance(tc.tool_name, str) or tc.tool_name.strip() == ""
        ]

        if empty:
            return RuleFinding(
                finding_id=rule_id,
                severity="critical",
                category="rule",
                message=f"tool_call tool_name 为空: {empty}",
                evidence_ref=f"call_ids with empty tool_name: {empty}",
                rule_type=rule_id,
                rule_passed=False,
            )

        return RuleFinding(
            finding_id=rule_id,
            severity="info",
            category="rule",
            message="所有 tool_call tool_name 非空",
            evidence_ref=f"tool_calls[{len(trace.tool_calls)} items]",
            rule_type=rule_id,
            rule_passed=True,
        )

    # ------------------------------------------------------------------
    # Rule 8: tool_result.tool_name.non_empty
    # ------------------------------------------------------------------

    def _check_result_tool_name_non_empty(self, trace: ExecutionTrace) -> RuleFinding:
        rule_id = "tool_result.tool_name.non_empty"
        empty = [
            tr.call_id
            for tr in trace.tool_results
            if not isinstance(tr.tool_name, str) or tr.tool_name.strip() == ""
        ]

        if empty:
            return RuleFinding(
                finding_id=rule_id,
                severity="medium",
                category="rule",
                message=f"tool_result tool_name 为空: {empty}",
                evidence_ref=f"call_ids with empty tool_name: {empty}",
                rule_type=rule_id,
                rule_passed=False,
            )

        return RuleFinding(
            finding_id=rule_id,
            severity="info",
            category="rule",
            message="所有 tool_result tool_name 非空",
            evidence_ref=f"tool_results[{len(trace.tool_results)} items]",
            rule_type=rule_id,
            rule_passed=True,
        )

    # ------------------------------------------------------------------
    # Rule 9: tool_result.status.valid
    # ------------------------------------------------------------------

    def _check_result_status_valid(self, trace: ExecutionTrace) -> RuleFinding:
        rule_id = "tool_result.status.valid"
        invalid = [
            (tr.call_id, tr.status)
            for tr in trace.tool_results
            if tr.status not in ("success", "error")
        ]

        if invalid:
            return RuleFinding(
                finding_id=rule_id,
                severity="medium",
                category="rule",
                message=f"tool_result status 无效: {invalid}",
                evidence_ref=f"invalid statuses: {invalid}",
                rule_type=rule_id,
                rule_passed=False,
            )

        return RuleFinding(
            finding_id=rule_id,
            severity="info",
            category="rule",
            message="所有 tool_result status 为 success 或 error",
            evidence_ref=f"tool_results[{len(trace.tool_results)} items]",
            rule_type=rule_id,
            rule_passed=True,
        )
