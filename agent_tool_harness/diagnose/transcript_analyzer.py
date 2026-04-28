from __future__ import annotations

from typing import Any

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.judges.rule_judge import JudgeResult

# 严重度等级，按可读性约束在三档。这里不引入 enum，是为了让 JSON artifact 字段保持
# 字符串可读，方便下游 CI/grep；新增等级请同步 docs/ARTIFACTS.md。
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_INFO = "info"

# Failure attribution 的四个 category，对齐 Anthropic *Writing effective tools for agents*
# 提到的四类失败来源；每条 finding 必须落到其中一个，方便报告聚合“到底是工具设计问题、
# eval 定义问题、Agent 工具选择问题，还是 runtime/工具执行问题”。
CATEGORY_TOOL_DESIGN = "tool_design"
CATEGORY_EVAL_DEFINITION = "eval_definition"
CATEGORY_AGENT_TOOL_CHOICE = "agent_tool_choice"
CATEGORY_RUNTIME = "runtime"

CATEGORY_LABELS = {
    CATEGORY_TOOL_DESIGN: "工具设计问题（tool_design）",
    CATEGORY_EVAL_DEFINITION: "eval 定义问题（eval_definition）",
    CATEGORY_AGENT_TOOL_CHOICE: "Agent 工具选择不当（agent_tool_choice）",
    CATEGORY_RUNTIME: "运行时/工具执行异常（runtime）",
}


class TranscriptAnalyzer:
    """从 raw artifacts 派生 failure attribution。

    架构边界：
    - 负责把 ``transcript.jsonl`` / ``tool_calls.jsonl`` / ``tool_responses.jsonl`` /
      ``judge_results.json`` / ``audit_tools.json`` / ``audit_evals.json`` 中的事实
      重新组织成可读的失败归因（findings + root cause hypothesis + 建议）。
    - **不重新执行工具，不替代 RuleJudge，也不调用 LLM。** 所有归因都是
      deterministic 启发式：能回答“是什么 / 为什么重要 / 看哪里 / 怎么改”，
      但不能回答“真实根因是不是这个”——后者需要人去看 raw artifacts 决定。

    为什么要这样拆：
    - 真实 Agent 团队最大的痛点是“PASS/FAIL 之外，到底改工具、改 eval 还是改 Agent
      prompt？” 当前 RuleJudge 只会说“某条规则没过”；analyzer 把规则失败 + audit
      finding + tool response 状态 + runner 异常这四股事实交叉关联，给出方向性提示。
    - 借鉴 LangSmith / LangGraph 的 trace tags、OpenTelemetry 的 span attributes、
      Anthropic 文章的工具评估方法论与 G-Eval 风格 rubric——但**不引入任何依赖**，
      所有结构都用纯 dict + str，方便未来真正接入 LLM Judge 时无缝替换 evidence_refs
      指向的 raw artifact。

    用户项目自定义入口：
    - 用户通过 ``ToolSpec.side_effects`` / ``output_contract`` / ``EvalSpec.judge.rules``
      /  ``EvalSpec.expected_tool_behavior.required_tools`` 等配置间接影响归因；
      analyzer 不暴露用户级配置点。

    扩展点（仅 ROADMAP，不在本轮实现）：
    - 调用顺序图（call graph）；
    - 真实 trajectory 节选（带 transcript 行号）；
    - LLM-based root cause confirmation（与 deterministic finding 并列，不替代）。

    诊断结果的稳定性：
    - 旧字段 ``issues`` / ``failed_rules`` / ``summary`` / ``tool_sequence`` /
      ``missing_required_tools`` / ``first_tool`` 全部保留，避免破坏既有 artifact 消费者。
    - 新字段 ``findings`` / ``category_summary`` / ``root_cause_hypothesis`` /
      ``suggested_fixes`` / ``what_to_check_next`` 是本轮新增。
    """

    def analyze(
        self,
        case: EvalSpec,
        run: AgentRunResult,
        judge: JudgeResult,
        *,
        audit_eval_findings: list[dict[str, Any]] | None = None,
        audit_tool_findings: dict[str, list[dict[str, Any]]] | None = None,
    ) -> dict[str, Any]:
        """归因一条 eval run 的失败/成功现场。

        - ``audit_eval_findings``：本 eval 在 ``audit_evals.json`` 中的 findings 列表。
          为空表示 audit 没给出 finding 或调用方没传——不会让 analyzer 崩，但归因
          中将看不到 ``weak_eval_definition`` 类。
        - ``audit_tool_findings``：``audit_tools.json`` 中“qualified_name → findings”
          映射；用于判断 required_tools 中是否有低分工具，触发 ``audit_signal_low``。

        诊断不会读磁盘；它只消费已经在内存里的运行/审计事实，确保单测可复用。
        """

        tool_names = [call["tool_name"] for call in run.tool_calls]
        required = list(case.expected_tool_behavior.get("required_tools", []))
        missing = [tool for tool in required if tool not in tool_names]

        findings: list[dict[str, Any]] = []
        # 顺序很重要：runtime 类先算（它们会让其他归因失去意义），再算 audit-driven，
        # 最后算 Agent 工具选择类。这样报告读者从上到下天然按"先看链路通不通，再看
        # 设计/定义层，最后看 Agent 行为层"的顺序排查。
        runtime_findings = self._runtime_findings(case, run, judge)
        findings.extend(runtime_findings)
        skip_finding = self._skipped_finding(judge)
        if skip_finding:
            findings.append(skip_finding)
        findings.extend(self._tool_error_findings(case, run))
        findings.extend(self._audit_findings(case, audit_eval_findings, audit_tool_findings))
        findings.extend(self._candidate_not_reviewed_finding(case))
        # Agent 工具选择类：runtime/skipped 的 eval 不再归因 Agent 行为，因为它根本
        # 没机会真实选工具——硬塞 missing_required_tool 反而会误导读者。
        if not runtime_findings and not skip_finding:
            findings.extend(
                self._agent_choice_findings(case, run, judge, tool_names, required, missing)
            )

        # 旧字段计算（保持向后兼容；测试 test_eval_runner_artifacts 依赖这些）。
        issues = self._legacy_issues(findings)
        failed_rules = [check.message for check in judge.checks if not check.passed]
        category_summary = self._category_summary(findings)
        root_cause_hypothesis = self._root_cause_hypothesis(
            judge.passed, findings, category_summary
        )
        suggested_fixes = self._dedupe(
            [f["suggested_fix"] for f in findings if f.get("suggested_fix")]
        )
        what_to_check_next = self._what_to_check_next(findings, judge.passed)

        return {
            "eval_id": case.id,
            "passed": judge.passed,
            "first_tool": tool_names[0] if tool_names else None,
            "tool_sequence": tool_names,
            "missing_required_tools": missing,
            "issues": issues,
            "failed_rules": failed_rules,
            "summary": self._summary(judge.passed, findings),
            "findings": findings,
            "category_summary": category_summary,
            "root_cause_hypothesis": root_cause_hypothesis,
            "suggested_fixes": suggested_fixes,
            "what_to_check_next": what_to_check_next,
            "diagnosis_kind": "deterministic_heuristic",
        }

    # ------------------------------------------------------------------ runtime
    def _runtime_findings(
        self, case: EvalSpec, run: AgentRunResult, judge: JudgeResult
    ) -> list[dict[str, Any]]:
        """把 runner 级伪规则翻成 runtime 类 finding。

        runner 在 adapter 抛错 / registry 初始化失败时会塞入 ``adapter_execution_failed``
        / ``tool_registry_initialization_failed`` 伪规则；analyzer 把它们升级成结构化
        finding，让报告/CI 能识别"这是链路异常而不是 Agent 选错工具"。
        """

        out: list[dict[str, Any]] = []
        for check in judge.checks:
            rule_type = (check.rule or {}).get("type")
            if rule_type in {"adapter_execution_failed", "tool_registry_initialization_failed"}:
                out.append(
                    {
                        "type": "runtime_error",
                        "severity": SEVERITY_HIGH,
                        "category": CATEGORY_RUNTIME,
                        "evidence_refs": [
                            f"judge_results.json#checks[type={rule_type}]",
                            f"transcript.jsonl#eval_id={case.id} type=runner_error",
                        ],
                        "why_it_matters": (
                            "Agent 没机会真实选工具：链路在 adapter 或 ToolRegistry 阶段就失败了。"
                            "如果不先修这个，后续所有归因都不可信。"
                        ),
                        "suggested_fix": (
                            "查看 transcript.jsonl 中 runner_error 事件的 traceback，"
                            "定位 adapter / registry / executor 的真实异常并修复；"
                            "不要靠改测试或调弱 audit 绕过 runtime 错误。"
                        ),
                        "related_tool_or_eval": case.id,
                    }
                )
        return out

    def _skipped_finding(self, judge: JudgeResult) -> dict[str, Any] | None:
        """audit 判 not_runnable 时的归因。

        skipped 不是 Agent 错——而是 eval 写得不够完整。把它归到 eval_definition 而非
        agent_tool_choice，避免读者去改 prompt/工具。
        """

        for check in judge.checks:
            if (check.rule or {}).get("type") == "eval_not_runnable":
                return {
                    "type": "skipped_non_runnable",
                    "severity": SEVERITY_INFO,
                    "category": CATEGORY_EVAL_DEFINITION,
                    "evidence_refs": [
                        "audit_evals.json#runnable=false",
                        "transcript.jsonl#type=runner_skip",
                    ],
                    "why_it_matters": (
                        "EvalQualityAuditor 把这条 eval 判为不可运行，runner 跳过执行；"
                        "本次 PASS/FAIL 不能反映 Agent 能力，需要先补 eval 定义。"
                    ),
                    "suggested_fix": (
                        "看 audit_evals.json 中该 eval 的 findings，按 next-step 补齐 "
                        "initial_context / verifiable_outcome / expected_tool_behavior 等字段，"
                        "再重新运行；详见 docs/ONBOARDING.md 候选审核流程。"
                    ),
                    "related_tool_or_eval": None,
                }
        return None

    def _tool_error_findings(
        self, case: EvalSpec, run: AgentRunResult
    ) -> list[dict[str, Any]]:
        """识别工具自身返回 ``success=false`` 的失败。

        这类失败常被读者误读为"Agent 没用对工具"，实际是工具实现/参数 schema/外部依赖
        异常。把它和 ``agent_tool_choice`` 区分开能直接告诉用户"先去看工具实现"。
        """

        out: list[dict[str, Any]] = []
        for response in run.tool_responses:
            payload = response.get("response") or {}
            if payload.get("success") is False:
                tool_name = response.get("tool_name", "<unknown>")
                call_id = response.get("call_id", "<unknown>")
                error = (payload.get("error") or {})
                err_msg = error.get("message") if isinstance(error, dict) else str(error)
                out.append(
                    {
                        "type": "tool_error",
                        "severity": SEVERITY_HIGH,
                        "category": CATEGORY_RUNTIME,
                        "evidence_refs": [
                            f"tool_responses.jsonl#call_id={call_id} success=false",
                            f"tool_calls.jsonl#call_id={call_id} tool_name={tool_name}",
                        ],
                        "why_it_matters": (
                            f"工具 `{tool_name}` 返回 success=false（"
                            f"{err_msg or 'no error message'}），Agent 无法基于真实证据继续；"
                            "判断 PASS/FAIL 之前必须先确认工具实现/参数/依赖是否健康。"
                        ),
                        "suggested_fix": (
                            f"在 tool_responses.jsonl 中按 call_id={call_id} 找到完整 error 字段，"
                            "回到工具实现或上游依赖修复；如果是参数 schema 问题，"
                            "同步更新 tools.yaml 的 input_schema。"
                        ),
                        "related_tool_or_eval": tool_name,
                    }
                )
        return out

    # ------------------------------------------------------------------ audit
    def _audit_findings(
        self,
        case: EvalSpec,
        audit_eval_findings: list[dict[str, Any]] | None,
        audit_tool_findings: dict[str, list[dict[str, Any]]] | None,
    ) -> list[dict[str, Any]]:
        """从 audit 结果派生 weak_eval_definition / audit_signal_low。

        weak_eval_definition：当 eval 仍 runnable 但 audit_evals 给出 high finding
        时，把"eval 本身可能写得不够稳"以 medium severity 提醒；不直接改判 PASS/FAIL，
        只让读者知道 eval 评分弱。

        audit_signal_low：当本 eval 的 required_tools 中存在 audit_tools 低分工具时，
        提示"工具契约本身也可能误导 Agent"——这是 Anthropic 文章里"先改工具，再调
        Agent"的核心建议。
        """

        out: list[dict[str, Any]] = []
        for finding in audit_eval_findings or []:
            if finding.get("severity") == "high":
                rule_id = finding.get("rule_id", "<unknown>")
                out.append(
                    {
                        "type": "weak_eval_definition",
                        "severity": SEVERITY_MEDIUM,
                        "category": CATEGORY_EVAL_DEFINITION,
                        "evidence_refs": [f"audit_evals.json#eval_id={case.id} rule_id={rule_id}"],
                        "why_it_matters": (
                            f"EvalQualityAuditor 给出 high finding `{rule_id}`："
                            f"{finding.get('message', '')} —— 当前 eval 即使 runnable，"
                            "判定信号也偏弱。"
                        ),
                        "suggested_fix": finding.get("suggestion")
                        or "按 audit_evals.json 中该 finding 的 suggestion 修订 eval 定义。",
                        "related_tool_or_eval": case.id,
                    }
                )

        required = list(case.expected_tool_behavior.get("required_tools", []))
        tool_findings = audit_tool_findings or {}
        for tool_name in required:
            findings_for_tool = tool_findings.get(tool_name) or []
            high_findings = [f for f in findings_for_tool if f.get("severity") == "high"]
            if high_findings:
                rule_ids = ", ".join(f.get("rule_id", "<unknown>") for f in high_findings[:3])
                out.append(
                    {
                        "type": "audit_signal_low",
                        "severity": SEVERITY_MEDIUM,
                        "category": CATEGORY_TOOL_DESIGN,
                        "evidence_refs": [
                            f"audit_tools.json#tool={tool_name} findings=[{rule_ids}]",
                        ],
                        "why_it_matters": (
                            f"required_tool `{tool_name}` 被 ToolDesignAuditor 标出 high "
                            f"finding（{rule_ids}）。即使 Agent 调对了工具，工具契约本身"
                            "也可能误导未来真实 Agent；先改工具往往收益最大。"
                        ),
                        "suggested_fix": (
                            f"查看 audit_tools.json 中 `{tool_name}` 的 findings.suggestion，"
                            "按 Anthropic *Writing effective tools for agents* 的五维原则"
                            "调整工具设计后再补 eval。"
                        ),
                        "related_tool_or_eval": tool_name,
                    }
                )
        return out

    def _candidate_not_reviewed_finding(self, case: EvalSpec) -> list[dict[str, Any]]:
        """检测 ``generated_from_*`` 来源的 eval 是否未经审核就进入正式 evals.yaml。

        ``EvalSpec`` 不保留候选阶段的 ``review_status`` 字段，所以这里靠 ``case.source``
        启发式识别——`from_tools` / `from_tests` 默认写入 ``source = "generated_from_*"``。
        如果用户把候选直接 copy 到 evals.yaml 而没改 source，这条 finding 会立刻提醒。
        不依赖任何 demo-specific 命名。
        """

        if not case.source.startswith("generated_from_"):
            return []
        return [
            {
                "type": "candidate_not_reviewed",
                "severity": SEVERITY_MEDIUM,
                "category": CATEGORY_EVAL_DEFINITION,
                "evidence_refs": [f"evals.yaml#id={case.id} source={case.source}"],
                "why_it_matters": (
                    "这条 eval 的 source 仍是 `generated_from_*`，疑似从候选直接复制到正式 "
                    "evals.yaml 而未走审核流程；候选 judge 默认是 tautological "
                    "must_call_tool，会让 mock replay 结构性 PASS。"
                ),
                "suggested_fix": (
                    "回到 docs/ARCHITECTURE.md 的『候选 eval 审核流程』，补 fixture / 替换"
                    " judge 规则后再修改 source 为 `hand_authored_*` 或真实工单标识。"
                ),
                "related_tool_or_eval": case.id,
            }
        ]

    # ------------------------------------------------------------------ agent
    def _agent_choice_findings(
        self,
        case: EvalSpec,
        run: AgentRunResult,
        judge: JudgeResult,
        tool_names: list[str],
        required: list[str],
        missing: list[str],
    ) -> list[dict[str, Any]]:
        """Agent 工具选择类归因。

        包括 missing_required_tool / forbidden_first_tool / wrong_first_tool /
        no_evidence_grounding / redundant_tool_calls。每条都带 evidence_refs 指向具体
        judge.check 或 tool_calls.jsonl 行。
        """

        out: list[dict[str, Any]] = []
        forbidden_hits: list[str] = []
        for check in judge.checks:
            rule = check.rule or {}
            if check.passed:
                continue
            rule_type = rule.get("type")
            if rule_type == "forbidden_first_tool":
                tool = str(rule.get("tool", ""))
                forbidden_hits.append(tool)
                out.append(
                    {
                        "type": "forbidden_first_tool",
                        "severity": SEVERITY_HIGH,
                        "category": CATEGORY_AGENT_TOOL_CHOICE,
                        "evidence_refs": [
                            f"judge_results.json#checks[type=forbidden_first_tool tool={tool}]",
                            f"tool_calls.jsonl#eval_id={case.id} index=0",
                        ],
                        "why_it_matters": (
                            f"Agent 第一步调用了被 eval 显式禁止的工具 `{tool}`，"
                            "意味着工具描述/prompt 引导了错误入口；"
                            "这条 eval 设计上正是为了暴露这类反模式。"
                        ),
                        "suggested_fix": (
                            f"检查 tools.yaml 中 `{tool}` 的 description / when_not_to_use，"
                            "确认是否对 Agent 暗示了它能解决本任务；同步检查 prompt"
                            "是否把它列为入口。"
                        ),
                        "related_tool_or_eval": tool,
                    }
                )
            elif rule_type == "max_tool_calls":
                limit = rule.get("value", rule.get("max", 0))
                out.append(
                    {
                        "type": "redundant_tool_calls",
                        "severity": SEVERITY_MEDIUM,
                        "category": CATEGORY_AGENT_TOOL_CHOICE,
                        "evidence_refs": [
                            f"judge_results.json#checks[type=max_tool_calls limit={limit}]",
                            f"tool_calls.jsonl#eval_id={case.id} count={len(tool_names)}",
                        ],
                        "why_it_matters": (
                            f"Agent 调用次数 {len(tool_names)} 超过预算 {limit}：可能是工具返回"
                            "信息密度不够，或 Agent 在重复探索；token/latency 都会被吃掉。"
                        ),
                        "suggested_fix": (
                            "在 tool_calls.jsonl 中按时间识别冗余/重复调用；考虑提升工具返回"
                            "的 evidence 密度、加 next_action 提示，或在 prompt 中收紧策略。"
                        ),
                        "related_tool_or_eval": case.id,
                    }
                )
            elif rule_type == "must_use_evidence":
                # v1.0 候选 A 增强：把"工具是否真的返回了 evidence"显式区分进 payload。
                # 两种子场景修复方向完全不同：
                #   - tool_responses_had_evidence=False → 修工具 output_contract，
                #     让它真返回 evidence；
                #   - tool_responses_had_evidence=True  → 修 prompt / Agent 策略，
                #     让它真的引用 evidence id。
                # 不在 message 文本里塞这个区分（report 一致按结构化字段读，避免 string 解析）。
                from agent_tool_harness.judges.rule_judge import RuleJudge

                ref_to_tools = RuleJudge()._evidence_reference_to_tools(run)
                tool_responses_had_evidence = bool(ref_to_tools)
                out.append(
                    {
                        "type": "no_evidence_grounding",
                        "severity": SEVERITY_HIGH,
                        "category": CATEGORY_AGENT_TOOL_CHOICE,
                        "evidence_refs": [
                            "judge_results.json#checks[type=must_use_evidence]",
                            f"tool_responses.jsonl#eval_id={case.id}",
                        ],
                        "tool_responses_had_evidence": tool_responses_had_evidence,
                        "available_evidence_refs": sorted(ref_to_tools.keys()),
                        "why_it_matters": (
                            "最终回答没有引用工具返回的 evidence id/label——结论可能是"
                            "Agent 自己脑补，或工具根本没返回 evidence。"
                            "这是 Anthropic 文章中『工具必须返回 meaningful context』的反例。"
                        ),
                        "suggested_fix": (
                            "查 tool_responses.jsonl：(a) 工具是否真的返回了 evidence 列表？"
                            "若否，改进工具 output_contract.required_fields；"
                            "(b) 若有 evidence 但 final_answer 没引用，改 prompt 让 Agent"
                            "强制把 evidence id 写进结论。"
                        ),
                        "related_tool_or_eval": case.id,
                    }
                )

        for tool in missing:
            out.append(
                {
                    "type": "missing_required_tool",
                    "severity": SEVERITY_HIGH,
                    "category": CATEGORY_AGENT_TOOL_CHOICE,
                    "evidence_refs": [
                        f"judge_results.json#checks[type=must_call_tool tool={tool}]",
                        f"tool_calls.jsonl#eval_id={case.id} (no call to {tool})",
                    ],
                    "why_it_matters": (
                        f"required_tool `{tool}` 没被调用，证据链断裂；"
                        "可能是 Agent 没意识到该工具相关，也可能是工具描述没强调适用场景。"
                    ),
                    "suggested_fix": (
                        f"查看 tools.yaml 中 `{tool}` 的 description / when_to_use，"
                        "确认对 Agent 暗示是否清晰；如果工具确实关键，可以在 prompt 或"
                        "上一步工具的 next_action 中显式建议它。"
                    ),
                    "related_tool_or_eval": tool,
                }
            )

        # wrong_first_tool 只在 forbidden_first_tool 没命中、且 required[0] 与实际首工具
        # 不一致时触发；避免和 forbidden_first_tool 重复给出建议。
        if (
            required
            and tool_names
            and tool_names[0] != required[0]
            and tool_names[0] not in forbidden_hits
        ):
            actual = tool_names[0]
            expected = required[0]
            out.append(
                {
                    "type": "wrong_first_tool",
                    "severity": SEVERITY_MEDIUM,
                    "category": CATEGORY_AGENT_TOOL_CHOICE,
                    "evidence_refs": [
                        f"tool_calls.jsonl#eval_id={case.id} index=0 actual={actual}",
                        f"evals.yaml#id={case.id} required_tools[0]={expected}",
                    ],
                    "why_it_matters": (
                        f"Agent 第一步选择了 `{actual}`，而 eval 期望优先用 `{expected}`"
                        "收集证据；顺序错误虽未必失败，但反映工具描述的诱导力。"
                    ),
                    "suggested_fix": (
                        f"对比 tools.yaml 中 `{actual}` 和 `{expected}` 的 description /"
                        "when_to_use；如果两者职责接近，考虑合并或加 when_not_to_use 边界。"
                    ),
                    "related_tool_or_eval": expected,
                }
            )

        # redundant_tool_calls 也覆盖"同一工具被连续调用 ≥2 次"的退化场景，即使 max_tool_calls
        # 没失败也提示。这是 LangSmith trajectory 复盘里常见的 Agent 退路。
        if not any(f["type"] == "redundant_tool_calls" for f in out):
            for i in range(1, len(tool_names)):
                if tool_names[i] == tool_names[i - 1]:
                    out.append(
                        {
                            "type": "redundant_tool_calls",
                            "severity": SEVERITY_MEDIUM,
                            "category": CATEGORY_AGENT_TOOL_CHOICE,
                            "evidence_refs": [
                                f"tool_calls.jsonl#eval_id={case.id} consecutive={tool_names[i]}",
                            ],
                            "why_it_matters": (
                                f"工具 `{tool_names[i]}` 被连续调用至少两次，可能是 Agent 在"
                                "无新信息情况下重试；token/latency 浪费。"
                            ),
                            "suggested_fix": (
                                "检查工具返回是否对 Agent 表达了进展；考虑加 next_action 或"
                                "对失败请求返回 retryable=false 与具体修复建议。"
                            ),
                            "related_tool_or_eval": tool_names[i],
                        }
                    )
                    break

        # v1.0 第一项：deterministic decoy evidence grounding 检测。
        # 触发条件（必须全部满足，避免与 missing_required_tool / no_evidence_grounding 重复）：
        # - eval 声明了 ``required_tools``；
        # - final_answer 实际引用了至少一个 evidence id/label（短串过滤同 RuleJudge）；
        # - 但被引用的 evidence 来源工具**全部不在** required_tools。
        # 它解决的真实风险：Agent 调了诱饵工具 + 把诱饵 evidence id 写进 final_answer，
        # 此时 must_use_evidence 仍会通过，但实际 evidence 链路是错的。本 finding
        # 永远附带 evidence_refs 指向具体诱饵工具，方便排错。**这不是 LLM Judge**，
        # 仍是 deterministic 启发式；语义级 grounding 等真实 LLM judge（v1.0 后续）。
        if required:
            decoy_finding = self._evidence_grounded_in_decoy_finding(case, run, required)
            if decoy_finding:
                out.append(decoy_finding)
        return out

    def _evidence_grounded_in_decoy_finding(
        self,
        case: EvalSpec,
        run: AgentRunResult,
        required: list[str],
    ) -> dict[str, Any] | None:
        """构造 evidence_grounded_in_decoy_tool finding（若触发）。

        通过反向索引 evidence id/label → tool_name；筛出 final_answer 实际引用的
        ref，再看其来源工具集是否与 required_tools 完全不相交。
        """

        from agent_tool_harness.judges.rule_judge import RuleJudge

        # 复用 RuleJudge 的反向索引避免逻辑漂移；analyzer 与 judge 必须用同一套
        # "什么是合法 evidence ref"的定义，否则 judge 通过 / analyzer 又报 finding
        # 会让真实用户产生信任危机。
        ref_to_tools = RuleJudge()._evidence_reference_to_tools(run)
        if not ref_to_tools:
            return None
        final_answer_lower = run.final_answer.lower()
        cited_tools: set[str] = set()
        cited_refs: list[str] = []
        for reference, tools in ref_to_tools.items():
            if reference.lower() in final_answer_lower:
                cited_refs.append(reference)
                cited_tools.update(tools)
        if not cited_refs:
            return None
        required_set = set(required)
        if cited_tools & required_set:
            return None
        return {
            "type": "evidence_grounded_in_decoy_tool",
            "severity": SEVERITY_HIGH,
            "category": CATEGORY_AGENT_TOOL_CHOICE,
            "evidence_refs": [
                f"tool_responses.jsonl#eval_id={case.id} tools={sorted(cited_tools)}",
                f"transcript.jsonl#eval_id={case.id} final_answer cites {cited_refs}",
                f"evals.yaml#id={case.id} required_tools={sorted(required_set)}",
            ],
            # v1.0 候选 A 增强：结构化字段，让 report.md 能直接渲染"引用了什么 / 来自什么 /
            # 应该来自什么"，避免读者去解析 evidence_refs 字符串。
            "cited_refs": sorted(cited_refs),
            "cited_tools": sorted(cited_tools),
            "required_tools": sorted(required_set),
            "why_it_matters": (
                f"final_answer 引用的 evidence 全部来自非 required 工具 "
                f"{sorted(cited_tools)}，required_tools={sorted(required_set)}。"
                "这是 deterministic anti-decoy 信号：Agent 可能调了诱饵工具收 evidence，"
                "再把诱饵 evidence id 写进结论；must_use_evidence 仍会通过，但 evidence "
                "来源不对。这是当前 deterministic 启发式能识别的最强 decoy 信号；语义级"
                "grounding 仍等真实 LLM judge（v1.0 后续）。"
            ),
            "suggested_fix": (
                "1) 在 evals.yaml 的 judge.rules 加 ``evidence_from_required_tools``，"
                "把 deterministic anti-decoy 升为硬约束；"
                f"2) 检查 tools.yaml 中诱饵工具 {sorted(cited_tools)} 的 description / "
                "when_to_use 是否对 Agent 暗示能解决本任务；"
                "3) 复盘 tool_calls.jsonl，确认 Agent 路径选择失败的真实根因。"
            ),
            "related_tool_or_eval": case.id,
        }

    # ------------------------------------------------------------------ derive
    def _legacy_issues(self, findings: list[dict[str, Any]]) -> list[dict[str, str]]:
        """把新 findings 折叠回旧 ``issues`` 字段，保持向后兼容。

        旧字段只含 ``type`` + ``message``；测试 test_eval_runner_artifacts 等仍按旧 schema
        断言。这里不做语义削弱，只是在 raw artifact 中同时保留两种视图。
        """

        out: list[dict[str, str]] = []
        # 兼容老 type：missing_evidence / wrong_first_tool / missing_required_tool
        type_map = {
            "no_evidence_grounding": ("missing_evidence", "最终结论没有引用工具 evidence"),
            "wrong_first_tool": ("wrong_first_tool", "第一步工具选择错误"),
            "missing_required_tool": ("missing_required_tool", "缺少关键工具调用"),
            "forbidden_first_tool": ("forbidden_first_tool", "第一步触发禁忌工具"),
        }
        for finding in findings:
            ftype = finding.get("type")
            if ftype in type_map:
                legacy_type, prefix = type_map[ftype]
                related = finding.get("related_tool_or_eval") or ""
                msg = f"{prefix}：{related}".strip("：")
                out.append({"type": legacy_type, "message": msg})
        return out

    def _category_summary(self, findings: list[dict[str, Any]]) -> dict[str, int]:
        """统计每个 category 的 finding 数量；供报告聚合渲染。"""

        summary = {key: 0 for key in CATEGORY_LABELS}
        for finding in findings:
            cat = finding.get("category")
            if cat in summary:
                summary[cat] += 1
        return summary

    def _root_cause_hypothesis(
        self,
        passed: bool,
        findings: list[dict[str, Any]],
        category_summary: dict[str, int],
    ) -> str:
        """基于 finding 主导 category 派生方向性根因假设。

        **这是启发式假设，不是真实根因。** 报告中会同时显式声明这一点；用户必须回到
        raw artifacts 验证。"""

        if passed and not findings:
            return (
                "PASS：Agent 按 expected_tool_behavior 调用了关键工具并引用了 evidence。"
                "注意：信号质量受顶部 signal_quality 限制；deterministic heuristic 不能"
                "替代真实 LLM agentic loop 评估。"
            )
        if not findings:
            return (
                "FAIL 但 deterministic heuristic 未识别结构性问题；请直接看 "
                "judge_results.json 的 failed checks 与 tool_responses.jsonl。"
            )
        # runtime 永远优先：链路异常时其他归因都不可信。
        if category_summary.get(CATEGORY_RUNTIME, 0) > 0:
            return (
                "假设：runtime / 工具执行链路异常。先去 transcript.jsonl / tool_responses.jsonl"
                "确认 adapter / registry / 工具实现的 traceback；其他归因在链路修好之前不可信。"
            )
        dominant = max(category_summary.items(), key=lambda kv: kv[1])
        if dominant[1] == 0:
            return "FAIL 但无主导 category；请回到 raw artifacts 复盘。"
        category, _ = dominant
        return (
            f"假设：主要问题在 {CATEGORY_LABELS.get(category, category)}。"
            "这是 deterministic heuristic 派生的方向性结论，不是真实根因——"
            "请按下方 evidence_refs 回到 raw artifacts 验证。"
        )

    def _what_to_check_next(
        self, findings: list[dict[str, Any]], passed: bool
    ) -> list[str]:
        """聚合所有 finding 的 evidence_refs，生成"先看哪、后看哪"的去重清单。"""

        if passed and not findings:
            return [
                "复盘 tool_calls.jsonl / tool_responses.jsonl，确认调用顺序与 evidence 真实；",
                "若想增强信号，请等待真实 LLM adapter（详见 docs/ROADMAP.md 信号质量章节）。",
            ]
        refs: list[str] = []
        for finding in findings:
            for ref in finding.get("evidence_refs", []):
                refs.append(ref)
        return self._dedupe(refs)

    def _summary(self, passed: bool, findings: list[dict[str, Any]]) -> str:
        """生成兼容旧 ``summary`` 字段的中文一句话。"""

        if passed and not findings:
            return "Agent 使用关键工具并基于 evidence 给出了可验证结论。"
        if not findings:
            return "Judge 判失败，但 deterministic heuristic 没发现额外结构性问题。"
        return "；".join(
            f"[{f['severity']}/{f['category']}] {f['type']}"
            for f in findings
        )

    def _dedupe(self, items: list[str]) -> list[str]:
        """保序去重；用 dict.fromkeys 比 set 更稳定。"""

        return list(dict.fromkeys(item for item in items if item))
