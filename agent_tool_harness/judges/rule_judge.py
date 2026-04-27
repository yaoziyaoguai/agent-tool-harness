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
    """

    MUTATING_HINTS = {"modify", "write", "patch", "delete", "update", "create", "set"}

    def judge(self, case: EvalSpec, run: AgentRunResult) -> JudgeResult:
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
            return self._result(rule, expected in tool_names, f"must call tool: {expected}")
        if rule_type == "must_call_one_of":
            options = set(rule.get("tools", []))
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
        if "evidence" not in run.final_answer.lower():
            return False
        return any(
            response.get("response", {}).get("success")
            and response.get("response", {}).get("content", {}).get("evidence")
            for response in run.tool_responses
        )

    def _no_modify_before_evidence(self, run: AgentRunResult) -> bool:
        seen_evidence = False
        response_by_call = {
            response["call_id"]: response.get("response", {}) for response in run.tool_responses
        }
        for call in run.tool_calls:
            name = call["tool_name"].lower()
            tokens = set(name.replace("-", "_").split("_"))
            if tokens & self.MUTATING_HINTS and not seen_evidence:
                return False
            response = response_by_call.get(call["call_id"], {})
            content = response.get("content", {})
            if response.get("success") and content.get("evidence"):
                seen_evidence = True
        return True

    def _result(self, rule: dict[str, Any], passed: bool, message: str) -> RuleCheckResult:
        return RuleCheckResult(rule=rule, passed=passed, message=message)
