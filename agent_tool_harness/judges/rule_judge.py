from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.config.eval_spec import EvalSpec


@dataclass
class RuleCheckResult:
    rule: dict[str, Any]
    passed: bool
    message: str


@dataclass
class JudgeResult:
    eval_id: str
    passed: bool
    checks: list[RuleCheckResult] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "eval_id": self.eval_id,
            "passed": self.passed,
            "checks": [
                {"rule": check.rule, "passed": check.passed, "message": check.message}
                for check in self.checks
            ],
        }


class RuleJudge:
    """确定性规则 judge。

    架构边界：
    - 只根据 transcript 派生的 tool_calls、tool_responses 和 final_answer 判定。
    - 不信任 Agent 自评，不执行工具，也不做 LLM 语义打分。
    - 支持小而明确的规则，确保 bad path 能被判失败、good path 能被判成功。

    扩展点：
    - 后续可并列加入 LLM Judge，但 deterministic 规则仍应作为底线证据。

    判断原则：
    - 先看工具调用事实，再看最终回答文本。
    - 规则失败要返回可读 message，供 diagnosis/report 指向具体失败点。
    - 新规则应该保持 deterministic，避免把当前 MVP 变成模型自评框架。

    基础防误判：
    - expected_root_cause_contains 的期望文本不能为空，避免 Python 空字符串包含关系导致永真。
    - must_use_evidence 不只检查单词 evidence，还要求最终回答引用工具返回的 evidence id/label。
    - must_not_modify_before_evidence 优先读取 tool_call.side_effects，再退回工具名启发式。
    """

    MUTATING_HINTS = {"modify", "write", "patch", "delete", "update", "create", "set"}

    def judge(self, case: EvalSpec, run: AgentRunResult) -> JudgeResult:
        """对单条 eval run 做确定性判定。

        judge 不读取磁盘文件，而是消费 adapter/run 阶段已经结构化好的结果。磁盘上的
        artifacts 是同一事实的持久化副本，用于人工复盘和 CI 留证。
        """

        rules = list(case.judge.get("rules", []))
        checks = [self._check(rule, case, run) for rule in rules]
        passed = all(check.passed for check in checks) if checks else False
        if not checks:
            checks.append(
                RuleCheckResult(
                    rule={"type": "missing_rules"},
                    passed=False,
                    message="eval 没有配置 judge.rules，不能判定通过。",
                )
            )
        return JudgeResult(eval_id=case.id, passed=passed, checks=checks)

    def _check(self, rule: dict[str, Any], case: EvalSpec, run: AgentRunResult) -> RuleCheckResult:
        rule_type = rule.get("type")
        tool_names = [call["tool_name"] for call in run.tool_calls]
        if rule_type == "must_call_tool":
            expected = str(rule.get("tool", ""))
            if not expected:
                return self._result(rule, False, "must_call_tool requires non-empty tool")
            return self._result(rule, expected in tool_names, f"must call tool: {expected}")
        if rule_type == "must_call_one_of":
            options = set(rule.get("tools", []))
            if not options:
                return self._result(rule, False, "must_call_one_of requires non-empty tools")
            return self._result(
                rule,
                bool(options & set(tool_names)),
                f"must call one of: {sorted(options)}",
            )
        if rule_type == "forbidden_first_tool":
            forbidden = str(rule.get("tool", ""))
            first = tool_names[0] if tool_names else ""
            return self._result(
                rule,
                first != forbidden,
                f"first tool must not be {forbidden}; actual first={first or '<none>'}",
            )
        if rule_type == "max_tool_calls":
            limit = int(rule.get("value", rule.get("max", 0)))
            return self._result(
                rule,
                len(tool_names) <= limit,
                f"tool call count {len(tool_names)} <= {limit}",
            )
        if rule_type == "expected_root_cause_contains":
            expected = str(rule.get("text", case.verifiable_outcome.get("expected_root_cause", "")))
            if not expected.strip():
                return self._result(
                    rule,
                    False,
                    "expected_root_cause_contains requires non-empty text",
                )
            return self._result(
                rule,
                expected.lower() in run.final_answer.lower(),
                f"final answer contains root cause text: {expected}",
            )
        if rule_type == "must_use_evidence":
            return self._result(rule, self._uses_evidence(run), "final answer must cite evidence")
        if rule_type == "must_not_modify_before_evidence":
            return self._result(
                rule,
                self._no_modify_before_evidence(run),
                "no mutating tool before successful evidence response",
            )
        return RuleCheckResult(rule=rule, passed=False, message=f"unknown rule type: {rule_type}")

    def _uses_evidence(self, run: AgentRunResult) -> bool:
        """检查最终回答是否真的把工具 evidence 纳入结论。

        加固版本（P1 根因治理）——必须满足全部条件，缺一不可：
        1. 最终回答提及 evidence/证据相关词（中英）：``evidence`` / ``证据``。
        2. 至少有一次 ``tool_responses`` 返回了非空 evidence id/label。
        3. 最终回答包含其中至少一个 evidence id/label/technical_id。

        为什么不再放行"只写 evidence/based on/shows 这类词"的答案：那等于让任何
        模板化回答都通过 judge，无法证伪。本方法仍然是 deterministic 启发式，
        **不是 LLM Judge**——它只能验证"回答确实引用了工具返回的具体标识"，
        不能保证语义正确。语义级 grounding 需要后续 LLM Judge 或 evidence matcher，
        已写入 ``docs/ROADMAP.md``。

        排错提示：如果 good path 莫名 FAIL，先检查 ``tool_responses.jsonl`` 是否真的
        有 evidence id；再检查 ``transcript.jsonl`` 中 final answer 是否引用了那个 id。
        """

        final_answer_lower = run.final_answer.lower()
        if "evidence" not in final_answer_lower and "证据" not in run.final_answer:
            return False
        references = self._evidence_references(run)
        if not references:
            return False
        return any(reference.lower() in final_answer_lower for reference in references)

    def _no_modify_before_evidence(self, run: AgentRunResult) -> bool:
        """防止 Agent 在拿到证据前调用疑似修改类工具。

        当前通过工具名 token 做轻量判断，适合 MVP 的 deterministic rule。未来如果引入
        destructive metadata，应从 ToolSpec.side_effects 做更严格判断。
        """

        seen_evidence = False
        response_by_call = {
            response["call_id"]: response.get("response", {}) for response in run.tool_responses
        }
        for call in run.tool_calls:
            name = call["tool_name"].lower()
            tokens = set(name.replace("-", "_").split("_"))
            side_effects = call.get("side_effects") or {}
            is_mutating = bool(side_effects.get("destructive")) or bool(
                tokens & self.MUTATING_HINTS
            )
            if is_mutating and not seen_evidence:
                return False
            response = response_by_call.get(call["call_id"], {})
            content = response.get("content", {})
            if response.get("success") and content.get("evidence"):
                seen_evidence = True
        return True

    def _evidence_references(self, run: AgentRunResult) -> list[str]:
        """抽取可被最终回答引用的 evidence 标识。

        当前支持 evidence.id、evidence.label 和 content.technical_id。这样 judge 可以用稳定 ID
        判定“回答确实引用工具证据”，但仍保留未来升级成更完整 evidence matcher 的空间。
        """

        references: list[str] = []
        for response in run.tool_responses:
            payload = response.get("response", {})
            if not payload.get("success"):
                continue
            content = payload.get("content", {})
            if content.get("technical_id"):
                references.append(str(content["technical_id"]))
            for evidence in content.get("evidence", []):
                if not isinstance(evidence, dict):
                    continue
                for key in ("id", "label"):
                    if evidence.get(key):
                        references.append(str(evidence[key]))
        return [item for item in dict.fromkeys(references) if item]

    def _result(self, rule: dict[str, Any], passed: bool, message: str) -> RuleCheckResult:
        return RuleCheckResult(rule=rule, passed=passed, message=message)
