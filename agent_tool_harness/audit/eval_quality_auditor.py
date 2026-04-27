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
        # 顶层 warnings 字段（P0 治理，与 ToolDesignAuditor 对齐）：
        # 空 evals 时 audit_evals.json 不能"看起来通过"——必须把"零评估题"作为
        # 显式 warning 暴露给下游 CI / dashboard，否则真实团队会误以为 eval suite
        # 已建立。详见 ToolDesignAuditor 同名字段的注释。
        warnings: list[str] = []
        if not evals:
            warnings.append(
                "empty_input: evals list is empty; nothing to audit. "
                "请确认 evals.yaml 至少有一条真实评估题，否则 run/judge 永远无信号。"
            )
        return {
            "summary": {
                "eval_count": len(evals),
                "average_score": self._average(result.overall_score for result in results),
                "not_runnable": [result.eval_id for result in results if not result.runnable],
                "low_score_evals": [
                    result.eval_id for result in results if result.overall_score < 3.5
                ],
                "warnings": warnings,
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
        # runnable 不能只看字段是否存在（``bool({"x": ""})`` 是 True），否则用户写
        # ``initial_context: {trace_id: ""}`` 就能蒙混过关。这里要求 initial_context
        # 与 verifiable_outcome 至少有一个 substantive 值（非空字符串/非空容器），
        # 并且 verifiable_outcome 必须含可被 judge 校验的 expected_root_cause 或 evidence_ids。
        # 任意一项不满足都给出对应 high finding，让真实接入者按建议修而不是误以为可运行。
        runnable = case.runnable
        if not _has_substantive_value(case.initial_context):
            runnable = False
            findings.append(
                EvalFinding(
                    "fixture.empty_initial_context_values",
                    "high",
                    "initial_context 字段存在但所有值都为空，无法复盘真实场景。",
                    "至少给出 trace_id / session_id / checkpoint_id 等真实 fixture 值。",
                )
            )
        if not _has_substantive_value(case.verifiable_outcome):
            runnable = False
            findings.append(
                EvalFinding(
                    "verifiability.empty_verifiable_outcome_values",
                    "high",
                    "verifiable_outcome 字段存在但所有值都为空，judge 无从校验。",
                    "声明 expected_root_cause、evidence_ids 等可机器检查字段。",
                )
            )
        elif not _is_truthy(case.verifiable_outcome.get("expected_root_cause")) and not (
            case.verifiable_outcome.get("evidence_ids")
            or case.verifiable_outcome.get("evidence")
        ):
            runnable = False
            findings.append(
                EvalFinding(
                    "verifiability.missing_expected_root_cause",
                    "high",
                    "verifiable_outcome 缺少 expected_root_cause / evidence_ids，"
                    "judge 没有可校验目标。",
                    "至少补一条 expected_root_cause（非空）或 evidence_ids 列表。",
                )
            )
        if not _has_substantive_value(case.expected_tool_behavior):
            runnable = False
            findings.append(
                EvalFinding(
                    "multi_step.missing_expected_tool_behavior",
                    "high",
                    "expected_tool_behavior 字段存在但所有值都为空，无法描述工具调用预期。",
                    "至少声明 required_tools 或 tool_options，让 RuleJudge 能校验调用链。",
                )
            )
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
        # 作弊 prompt 启发式（P1 治理扩展）：
        #
        # 之前只钉 "please call" / "请调用" / ("调用" + "工具") 三种模式，真实坑：
        # 审核者写"使用 xxx 工具"、"use the xxx tool"、"call xxx" 等等价表达时
        # 仍能绕过，等于把工具名/调用动作泄露给 Agent。这里把判定收口到"动词 +
        # 工具/tool 名词"的词共现，覆盖中英最常见说法。
        # **不是 NLU**：仍然是 deterministic substring 启发式，不能替代真实
        # 语义检测；语义级写入 docs/ROADMAP.md 后续 LLM Reviewer。
        cheating_signals = (
            "please call",
            "please use",
            "call the ",
            "use the ",
            "invoke the ",
            "请调用",
            "请使用",
            "使用工具",
            ("调用", "工具"),
            ("使用", "工具"),
            ("call", "tool"),
            ("use", "tool"),
            ("invoke", "tool"),
        )
        is_cheating = False
        for signal in cheating_signals:
            if isinstance(signal, tuple):
                if all(token in prompt for token in signal):
                    is_cheating = True
                    break
            elif signal in prompt:
                is_cheating = True
                break
        if is_cheating:
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
        # 反 tautological 规则（P0 根因治理，本轮扩展）：
        #
        # 历史版本只钉"恰好 1 条 must_call_tool 且指向 required_tools[0]"，
        # 真实漏洞：审核者把候选 judge 扩成"对每个 required_tool 都加一条
        # must_call_tool"，例如 required_tools=[A,B,C] + 三条 must_call_tool(A/B/C)；
        # 在 MockReplayAdapter 反向回放 expected_tool_behavior 的链路下，仍然结构性
        # 必过，本质上是同一根因换种写法绕过 audit。本轮把判定收口到"是否存在
        # **任何**真正校验 Agent 行为的语义规则"——即 must_use_evidence /
        # expected_root_cause_contains / must_not_modify_before_evidence /
        # forbidden_first_tool / max_tool_calls 任意一条。如果一条都没有，且 judge
        # 仅由 must_call_tool / must_call_one_of 组成（这两条在 mock replay 下都
        # 是必过的），就报 tautological。
        rules = case.judge.get("rules") or []
        if rules and required:
            structural_only_types = {"must_call_tool", "must_call_one_of"}
            semantic_types = {
                "must_use_evidence",
                "expected_root_cause_contains",
                "must_not_modify_before_evidence",
                "forbidden_first_tool",
                "max_tool_calls",
            }
            rule_types = [
                rule.get("type") for rule in rules if isinstance(rule, dict)
            ]
            has_semantic = any(t in semantic_types for t in rule_types)
            only_structural = all(
                t in structural_only_types for t in rule_types if t is not None
            )
            # 收口条件：(a) 全部规则都是 must_call_tool / must_call_one_of；
            # (b) 没有任何一条带 Agent 行为语义校验。这样多 must_call_tool 覆盖
            # required_tools 的扩展写法也会被钉住。
            if only_structural and not has_semantic:
                score -= 2
                findings.append(
                    EvalFinding(
                        "judge.tautological_must_call_tool",
                        "high",
                        "judge 只配置了 must_call_tool / must_call_one_of 这类结构规则，"
                        "缺少 must_use_evidence / expected_root_cause_contains 等行为语义"
                        "校验；在 mock replay 链路下结构性必过，无法证伪 Agent 真实能力。",
                        "至少补一条语义规则（must_use_evidence、expected_root_cause_contains、"
                        "must_not_modify_before_evidence 等），避免 tautological eval。",
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


def _is_truthy(value: Any) -> bool:
    """判断单个 YAML 值是否“真有内容”。

    与 ``bool(value)`` 的区别：会把 ``"   "``（仅空白）也视为空，避免用户用空格
    伪造非空字符串。其它容器（dict/list）只要长度 > 0 就算 truthy；具体子项是否空
    交给 ``_has_substantive_value`` 递归检查。
    """

    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict | list | tuple | set):
        return len(value) > 0
    return bool(value)


def _has_substantive_value(container: Any) -> bool:
    """判断 mapping/list 是否至少包含一个 substantive 值。

    为什么需要：``bool({"trace_id": ""})`` 是 True，但语义上等同于空。runnable 检查
    必须穿透字段层只看实际值，否则用户写一个全空字典就能让 eval 显示"可运行"，
    跑出来的 artifact 会全是占位符——这是真实用户最容易踩的"看似配齐"的坑。
    """

    if isinstance(container, dict):
        return any(_has_substantive_value(v) for v in container.values())
    if isinstance(container, list | tuple | set):
        return any(_has_substantive_value(v) for v in container)
    return _is_truthy(container)
