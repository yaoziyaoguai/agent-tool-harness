from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_tool_harness.config.eval_spec import EvalSpec


@dataclass
class EvalFinding:
    rule_id: str
    severity: str
    message: str
    suggestion: str


@dataclass
class EvalAuditResult:
    eval_id: str
    name: str
    scores: dict[str, int]
    runnable: bool
    findings: list[EvalFinding] = field(default_factory=list)

    @property
    def overall_score(self) -> float:
        if not self.scores:
            return 0.0
        return round(sum(self.scores.values()) / len(self.scores), 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "eval_id": self.eval_id,
            "name": self.name,
            "overall_score": self.overall_score,
            "scores": self.scores,
            "runnable": self.runnable,
            "findings": [finding.__dict__ for finding in self.findings],
        }


class EvalQualityAuditor:
    """审计 eval 是否能真实检验 Agent 工具使用能力。

    架构边界：
    - 负责判断 eval 的真实性、多步性、可验证性、fixture 完整性和 judge 是否过拟合。
    - 不运行 Agent，不执行工具，也不根据最终答案自评通过。
    - 对弱 eval 给出低分和转正建议，保护 eval harness 不被“看似通过”的题污染。

    扩展点：
    - 后续可以接入真实工单/trace 采样器。
    - 后续可以增加 LLM 作为辅助 reviewer，但当前规则保持可复现。
    """

    VALID_SPLITS = {"training", "held_out", "regression"}

    def audit(self, evals: list[EvalSpec]) -> dict[str, Any]:
        results = [self.audit_eval(case) for case in evals]
        return {
            "summary": {
                "eval_count": len(evals),
                "average_score": self._average(result.overall_score for result in results),
                "not_runnable": [result.eval_id for result in results if not result.runnable],
                "low_score_evals": [
                    result.eval_id for result in results if result.overall_score < 3.5
                ],
            },
            "evals": [result.to_dict() for result in results],
        }

    def audit_eval(self, case: EvalSpec) -> EvalAuditResult:
        findings: list[EvalFinding] = []
        scores = {
            "realism": self._score_realism(case, findings),
            "multi_step": self._score_multi_step(case, findings),
            "verifiability": self._score_verifiability(case, findings),
            "judge_flexibility": self._score_judge_flexibility(case, findings),
            "split_and_fixture": self._score_split_fixture(case, findings),
        }
        runnable = case.runnable and bool(case.initial_context) and bool(case.verifiable_outcome)
        if not runnable:
            findings.append(
                EvalFinding(
                    "fixture.not_runnable",
                    "high",
                    "eval 缺少可运行上下文或可验证结果，不能进入正式 tool-use eval。",
                    "补充 initial_context、fixture/evidence 和 verifiable_outcome 后再转正。",
                )
            )
        return EvalAuditResult(
            eval_id=case.id,
            name=case.name,
            scores=scores,
            runnable=runnable,
            findings=findings,
        )

    def _score_realism(self, case: EvalSpec, findings: list[EvalFinding]) -> int:
        score = 5
        prompt = case.user_prompt.lower()
        if case.realism_level not in {"real", "synthetic_realistic", "regression"}:
            score -= 2
            findings.append(
                EvalFinding(
                    "realism.weak_source",
                    "medium",
                    "realism_level 没有表明来自真实或近真实场景。",
                    "从工单、incident、trace、回归测试中抽取任务。",
                )
            )
        if (
            "please call" in prompt
            or "请调用" in prompt
            or ("调用" in prompt and "工具" in prompt)
        ):
            score -= 2
            findings.append(
                EvalFinding(
                    "realism.cheating_prompt",
                    "high",
                    "user_prompt 像在要求调用某工具，而不是真实用户问题。",
                    "把题面改成用户目标，不泄露工具名或调用路径。",
                )
            )
        if len(case.user_prompt) < 30:
            score -= 1
            findings.append(
                EvalFinding(
                    "realism.too_short",
                    "medium",
                    "user_prompt 太短，可能是过弱 sandbox。",
                    "加入症状、约束、已有观察或业务影响。",
                )
            )
        return max(score, 1)

    def _score_multi_step(self, case: EvalSpec, findings: list[EvalFinding]) -> int:
        score = 5
        required = case.expected_tool_behavior.get("required_tools", [])
        alternatives = case.expected_tool_behavior.get("tool_options", [])
        complexity = case.complexity.lower()
        if len(required) < 2 and not alternatives and complexity not in {"multi_step", "complex"}:
            score -= 2
            findings.append(
                EvalFinding(
                    "multi_step.too_simple",
                    "high",
                    "eval 不明显需要多步工具调用，难以检验 tool-use 策略。",
                    "设计需要先定位证据、再钻取 checkpoint/trace 的任务。",
                )
            )
        if case.expected_tool_behavior.get("required_order_strict", False):
            score -= 1
            findings.append(
                EvalFinding(
                    "multi_step.overfit_order",
                    "medium",
                    "expected_tool_behavior 过度约束唯一顺序，可能惩罚合理替代路径。",
                    "只要求关键证据工具，允许等价探索路径。",
                )
            )
        return max(score, 1)

    def _score_verifiability(self, case: EvalSpec, findings: list[EvalFinding]) -> int:
        score = 5
        if not case.verifiable_outcome:
            score -= 3
            findings.append(
                EvalFinding(
                    "verifiability.missing_outcome",
                    "high",
                    "缺少 verifiable_outcome，无法从证据判定成功。",
                    "声明 expected_root_cause、evidence_ids 或可机器检查字段。",
                )
            )
        if not case.success_criteria:
            score -= 1
            findings.append(
                EvalFinding(
                    "verifiability.missing_success_criteria",
                    "medium",
                    "缺少 success_criteria，报告无法解释通过原因。",
                    "写出最终结论、证据使用、禁止行为等准则。",
                )
            )
        rules = case.judge.get("rules", [])
        if not rules:
            score -= 2
            findings.append(
                EvalFinding(
                    "verifiability.missing_judge_rules",
                    "high",
                    "缺少 deterministic judge rules。",
                    "至少配置 must_call_tool 和 expected_root_cause_contains。",
                )
            )
        return max(score, 1)

    def _score_judge_flexibility(self, case: EvalSpec, findings: list[EvalFinding]) -> int:
        score = 5
        required = case.expected_tool_behavior.get("required_tools", [])
        if len(required) > 3 and not case.expected_tool_behavior.get("allowed_alternatives"):
            score -= 1
            findings.append(
                EvalFinding(
                    "judge.overfit_tools",
                    "medium",
                    "expected tools 可能过拟合唯一策略。",
                    "把硬性要求限制在关键证据工具，其他步骤用 criteria 表达。",
                )
            )
        if case.judge.get("strict_final_text"):
            score -= 2
            findings.append(
                EvalFinding(
                    "judge.strict_text",
                    "high",
                    "judge 依赖严格最终文本，容易错判同义正确答案。",
                    "使用 root_cause_contains、evidence ids 和 tool call 规则。",
                )
            )
        # 反 tautological 规则（P0 根因治理）：
        # 如果 judge.rules 只有一个 ``must_call_tool``，且这个工具就是 ``required_tools[0]``，
        # 等价于“调用了被指定的工具就算过”——在 mock replay + 候选自动生成的链路下，
        # 这条 eval 必然 PASS，无法证伪 Agent 真实能力。审计必须显式提示，避免“看似通过”。
        rules = case.judge.get("rules") or []
        if (
            len(rules) == 1
            and isinstance(rules[0], dict)
            and rules[0].get("type") == "must_call_tool"
            and required
            and rules[0].get("tool") == required[0]
        ):
            score -= 2
            findings.append(
                EvalFinding(
                    "judge.tautological_must_call_tool",
                    "high",
                    "judge 只校验“必须调用 expected_tool_behavior.required_tools[0]”，"
                    "在 mock replay 链路下结构性必过，不能证伪 Agent 真实能力。",
                    "补充 must_use_evidence、expected_root_cause_contains 等语义规则，"
                    "或要求多工具组合，避免 tautological eval。",
                )
            )
        return max(score, 1)

    def _score_split_fixture(self, case: EvalSpec, findings: list[EvalFinding]) -> int:
        score = 5
        if case.split not in self.VALID_SPLITS:
            score -= 2
            findings.append(
                EvalFinding(
                    "split.invalid",
                    "medium",
                    "split 不是 training/held_out/regression。",
                    "按用途设置 split，避免训练题污染 held-out 判断。",
                )
            )
        if not case.initial_context:
            score -= 2
            findings.append(
                EvalFinding(
                    "fixture.missing_initial_context",
                    "high",
                    "缺少 initial_context/fixture，无法复盘真实场景。",
                    "提供 trace_id、session_id、checkpoint_id 或可执行 fixture。",
                )
            )
        if case.missing_context:
            score -= 1
            findings.append(
                EvalFinding(
                    "fixture.missing_context_declared",
                    "medium",
                    f"eval 声明缺少上下文：{', '.join(case.missing_context)}。",
                    "补齐 missing_context 后将 runnable 改为 true。",
                )
            )
        return max(score, 1)

    def _average(self, values: Any) -> float:
        values = list(values)
        if not values:
            return 0.0
        return round(sum(values) / len(values), 2)
