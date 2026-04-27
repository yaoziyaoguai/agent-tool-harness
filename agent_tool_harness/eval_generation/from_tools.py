from __future__ import annotations

import re
from typing import Any

from agent_tool_harness.config.project_spec import ProjectSpec
from agent_tool_harness.config.tool_spec import ToolSpec


class FromToolsGenerator:
    """从 tools.yaml 生成 eval candidate。

    架构边界（这一层负责什么、不负责什么）：
    - **负责**：根据工具契约生成"可能值得测"的用户任务候选；为每条候选挂上**默认
      就含语义校验**的 judge 占位，避免审核者不修就转正得到 tautological eval。
    - **负责**：当工具自身契约缺关键字段（when_to_use / when_not_to_use /
      output_contract / evidence / next_action / response_format）时，把候选明确标
      ``review_status="needs_review"`` + ``runnable=False``，并把缺哪几项写进
      ``missing_context`` / ``review_notes``——而不是糊一份"看起来可运行"的假 eval。
    - **不负责**：直接写正式 evals.yaml（promoter 才做）；做语义级 LLM 评审；
      自动改 prompt；判断 fixture 是否真实。

    用户项目自定义入口：
    - ``ToolSpec.metadata["eval_generation"]`` 是工具作者给 generator 的 hint。
      支持字段：``id`` / ``name`` / ``category`` / ``user_prompt`` / ``fixture`` /
      ``expected_root_cause`` / ``evidence`` / ``required_tools`` /
      ``forbidden_first_tool`` / ``complexity`` / ``success_criteria``。
    - hint 字段全部可选，且**不会绕过**反作弊检查（user_prompt 仍会被剥工具名 +
      cheating signal 检测；为空时回退到通用模板）。

    如何通过 artifacts 查问题：
    - 看 ``runs/<dir>/eval_candidates.from_tools.yaml`` 顶层 ``warnings`` 字段判断
      整批候选的质量风险（empty_input / all_unrunnable / cheating_prompt_suspect 等）。
    - 单条候选的 ``review_notes`` 是 checklist：缺什么、为什么仍是候选、转正前必须补
      什么；它会跟随候选进 promote 输出，便于审核痕迹一直可追溯。
    - 单条候选的 ``review_status`` 取值约束：``"candidate"``（默认，可补字段后转
      ``"accepted"``）或 ``"needs_review"``（工具契约缺关键字段，必须先修工具）。
      promoter 只搬运 ``"accepted"`` + ``runnable=true`` 的候选，所以 ``"needs_review"``
      / ``"candidate"`` / ``"rejected"`` 都会被自然过滤。

    哪些只是 MVP / mock / demo：
    - judge 默认规则集合已尽量减少 tautological 风险，但**仍是 deterministic 模板**，
      不是真根因检验。审核者必须按 ``review_notes`` 替换/补充语义规则，并用真实
      fixture 验证。
    - 不做 LLM 自动改 prompt、不接 issue tracker、不读 Python 工具源码——这些都属
      ``docs/ROADMAP.md`` 后续路线。

    候选转正流程（与 docs/ARCHITECTURE.md / docs/ONBOARDING.md 同步）：
        candidate -> 人工补 fixture/initial_context/expected_root_cause ->
        把 review_status 改成 "accepted" -> promote-evals 机械搬运 ->
        audit-evals 验证 runnable=true & 无 high finding -> 合入正式 evals.yaml。
    """

    # 工具契约缺这些字段就算"spec 不完整"——候选会被强制标 needs_review + runnable=false。
    # 选这几条而不是全部字段，是为了把"会让 Agent 真实走错"的最小集合钉死：
    # - when_to_use / when_not_to_use 直接决定 Agent 何时该选 / 不该选；
    # - output_contract.required_fields 决定 RuleJudge 能否做 must_use_evidence；
    # - input_schema.properties 至少要有 response_format 这种 token 控制开关，
    #   否则候选 eval 跑起来 Agent 没有可对齐的输入约束。
    # 这一组**不读 Python 源码**，仅做 structural 检查；语义级缺陷仍走 ToolDesignAuditor。
    _CRITICAL_SPEC_GAPS = (
        "missing_when_to_use",
        "missing_when_not_to_use",
        "missing_output_contract",
        "missing_evidence_in_output_contract",
        "missing_response_format",
    )

    # 提示文本里出现这几个动词 + "工具/tool" 共现就视为"作弊式"prompt：
    # 它把"调用某工具"暴露给 Agent，等于直接给答案。这里仅作为最终兜底 scrub
    # 检查；主要去工具名工作仍由 _remove_tool_name 完成。
    # 与 audit/eval_quality_auditor.realism.cheating_prompt 的检测口径保持一致，
    # 但**不**复用其 import——审计与生成解耦，让两边各自演进。
    _CHEATING_TOKEN_PAIRS = (
        ("call", "tool"),
        ("use", "tool"),
        ("invoke", "tool"),
        ("调用", "工具"),
        ("使用", "工具"),
    )
    _CHEATING_PHRASES = (
        "please call",
        "please use",
        "请调用",
        "请使用",
        "使用工具",
    )

    def generate(self, project: ProjectSpec, tools: list[ToolSpec]) -> list[dict[str, Any]]:
        """对一组 ToolSpec 逐个生成候选 eval。

        遍历语义：每个工具产出**恰好一条**候选，便于审核者按行 review、按行修。
        生成顺序与 tools 输入顺序一致；候选 id 默认带数字前缀 + 工具名，避免重排时混淆。
        """

        candidates = []
        for index, tool in enumerate(tools, start=1):
            hint = dict(tool.metadata.get("eval_generation", {}))
            prompt = hint.get("user_prompt") or self._prompt_from_tool(project, tool)
            prompt = self._remove_tool_name(prompt, tool)
            prompt = self._scrub_cheating_signals(prompt)

            spec_gaps = self._spec_completeness_gaps(tool)
            missing_context: list[str] = list(spec_gaps)
            if not hint.get("fixture"):
                missing_context.append("fixture")
            if not hint.get("expected_root_cause"):
                missing_context.append("expected_root_cause")

            # runnable / review_status 的二元决策：
            # - 工具契约本身就缺关键字段（spec_gaps 非空）→ ``needs_review``，且
            #   runnable=False；提醒接入者"先改工具，不要在弱契约上补 eval"。
            # - 仅缺 hint 层 fixture / expected_root_cause → 仍是 ``candidate``，
            #   runnable=False，但走"补 hint → review_status=accepted → promote"的常规路径。
            # - 都齐 → ``candidate`` + runnable=True，等待审核者把 review_status
            #   改成 ``accepted`` 后再 promote。
            review_status = "needs_review" if spec_gaps else "candidate"
            runnable = not missing_context

            required_tools = hint.get("required_tools") or [tool.name]
            forbidden_first = hint.get("forbidden_first_tool")
            expected_root_cause = hint.get("expected_root_cause", "")
            complexity = hint.get("complexity", "multi_step")

            candidate = {
                "id": hint.get("id", f"candidate_from_tool_{index:03d}_{tool.name}"),
                "name": hint.get("name", f"Candidate from {tool.namespace}.{tool.name}"),
                "category": hint.get("category", "tool_contract_candidate"),
                "split": "training",
                "realism_level": "synthetic_realistic",
                "complexity": complexity,
                "source": "generated_from_tools",
                "user_prompt": prompt,
                "initial_context": hint.get("fixture", {}),
                "verifiable_outcome": self._build_verifiable_outcome(hint),
                "success_criteria": hint.get(
                    "success_criteria",
                    self._default_success_criteria(),
                ),
                "expected_tool_behavior": {
                    "required_tools": required_tools,
                    "notes": "候选只要求关键证据工具，不强制唯一调用路径。",
                },
                "judge": {
                    "rules": self._default_judge_rules(
                        tool=tool,
                        required_tools=required_tools,
                        expected_root_cause=expected_root_cause,
                        forbidden_first=forbidden_first,
                    ),
                },
                "runnable": runnable,
                "missing_context": missing_context,
                "difficulty": self._difficulty(complexity),
                "review_status": review_status,
                "review_notes": self._review_notes(
                    missing_context=missing_context,
                    spec_gaps=spec_gaps,
                    prompt=prompt,
                    tool=tool,
                ),
            }
            candidates.append(candidate)
        return candidates

    def _difficulty(self, complexity: str) -> str:
        """把 complexity 映射成审核分流用的 difficulty 等级。

        Anthropic 文章强调 evaluation 必须真实、多步；这里把 complexity 映射成更容易
        被审核者扫读的 trivial / single_step / multi_step / unknown 四档，便于 review
        时优先合并 multi_step 候选、过滤 trivial 候选。
        """

        normalized = (complexity or "").lower().strip()
        if normalized in {"multi_step", "multi-step", "multistep"}:
            return "multi_step"
        if normalized in {"single_step", "single-step", "singlestep"}:
            return "single_step"
        if normalized == "trivial":
            return "trivial"
        return "unknown"

    def _spec_completeness_gaps(self, tool: ToolSpec) -> list[str]:
        """检查工具契约是否缺关键字段，返回 gap 名称列表（空 = 无 gap）。

        为什么把这一步放到生成器而不是只交给 ToolDesignAuditor：
        - auditor 给出的是"评分 + 建议"，但**仍会让弱 spec 进 audit 通过流程**；
        - 生成 candidate 时如果不前置一道 gate，审核者拿到看似"runnable"的候选会
          直接转正——等于在弱契约上叠 eval，bug 离根因越来越远。
        - 这里只挑"会让 Agent 真实走错"的 5 项硬 gap，**不**重复 auditor 的全量检查。

        gap 列表（与 ``_CRITICAL_SPEC_GAPS`` 对齐）：
        - ``missing_when_to_use``：Agent 不知道何时该选这个工具；
        - ``missing_when_not_to_use``：Agent 不知道何时不该选；
        - ``missing_output_contract``：``output_contract`` 为空 / 没有 ``required_fields``；
        - ``missing_evidence_in_output_contract``：``required_fields`` 不含 ``evidence``，
          RuleJudge 无法做 ``must_use_evidence``；
        - ``missing_response_format``：``input_schema.properties`` 不含
          ``response_format``——意味着 Agent 没有 token 控制开关，跑出的工具响应可能
          长到污染上下文窗口。
        """

        gaps: list[str] = []
        if not (tool.when_to_use or "").strip():
            gaps.append("missing_when_to_use")
        if not (tool.when_not_to_use or "").strip():
            gaps.append("missing_when_not_to_use")
        contract = tool.output_contract or {}
        required_fields = set(contract.get("required_fields", []) or [])
        if not contract or not required_fields:
            gaps.append("missing_output_contract")
        elif "evidence" not in required_fields:
            gaps.append("missing_evidence_in_output_contract")
        properties = (tool.input_schema or {}).get("properties") or {}
        if "response_format" not in properties:
            gaps.append("missing_response_format")
        return gaps

    def _default_judge_rules(
        self,
        *,
        tool: ToolSpec,
        required_tools: list[str],
        expected_root_cause: str,
        forbidden_first: str | None,
    ) -> list[dict[str, Any]]:
        """构造默认 judge.rules，**默认就含语义校验**，避免 tautological 必过。

        设计要点（根因方向）：
        - 旧版默认只有 ``must_call_tool`` + ``must_use_evidence``：在 mock replay 链路
          下 ``must_call_tool`` 是必然成立的，``must_use_evidence`` 又只是 substring
          匹配；审核者不修就转正几乎必过 → 真实 bug。
        - 新版加了三类语义/防御性规则，让候选转正后**至少一条规则会真起作用**：
          1. ``expected_root_cause_contains``（仅当 hint 给了 expected_root_cause）
             —— 直接锁住 final answer 必须命中 root cause 文本，否则 FAIL。
          2. ``must_not_modify_before_evidence`` —— 永远加，零成本：
             非 destructive 工具下永远 PASS；destructive 工具下强制 Agent 先拿证据。
          3. ``forbidden_first_tool``（仅当 hint 显式给）—— 防 Agent 用快捷路径绕过
             证据收集（例如直接调用 snapshot 工具回答 trace 类问题）。
        - **保留** ``must_call_tool`` 作为结构 sanity check（确保至少调用了主工具），
          但它不再是"唯一通过门槛"——必要不充分。
        - **不**自动加 ``forbidden_first_tool``：没有领域知识时硬塞会误伤合理替代路径。

        注意：这里**不**做 EvalQualityAuditor 的 tautological 检测——审计与生成解耦，
        让审计独立判断。但本默认规则集合在审计的口径下应该 PASS（即不报
        ``judge.tautological_must_call_tool``）。
        """

        rules: list[dict[str, Any]] = []
        if required_tools:
            rules.append({"type": "must_call_tool", "tool": required_tools[0]})
        rules.append({"type": "must_use_evidence"})
        if expected_root_cause and expected_root_cause.strip():
            rules.append(
                {"type": "expected_root_cause_contains", "text": expected_root_cause}
            )
        rules.append({"type": "must_not_modify_before_evidence"})
        if forbidden_first:
            rules.append({"type": "forbidden_first_tool", "tool": forbidden_first})
        return rules

    def _default_success_criteria(self) -> list[str]:
        """默认 success_criteria：明确反 tautology + 必须解释为何选用该工具。

        与 docs/ARTIFACTS.md 中"success_criteria 是给人看的契约"对齐——这些短句会跟随
        候选进 PR diff，提醒审核者"光被调用不算成功"。
        """

        return [
            "结论必须引用工具返回的 evidence；只调用工具而无证据落地不算成功。",
            "不能在没有证据前修改用户系统状态。",
            "回答必须解释为何当前任务适合这个工具，避免落入 when_not_to_use 场景。",
            "调用工具本身不是成功标准——必须给出可被 RuleJudge 验证的根因或行为结论。",
        ]

    def _build_verifiable_outcome(self, hint: dict[str, Any]) -> dict[str, Any]:
        """构造 verifiable_outcome；保留 evidence_ids 与 evidence 两种形态。

        框架对外字段约定（与 ``EvalQualityAuditor`` / ``RuleJudge`` 对齐）：
        - ``expected_root_cause``：字符串；为空字符串时 promoter 会拒绝转正。
        - ``evidence`` / ``evidence_ids``：list[str]；任一非空都视为合法
          verifiable_outcome（详见 EvalQualityAuditor.verifiability.missing_expected_root_cause
          的合法替代规则）。
        """

        outcome: dict[str, Any] = {
            "expected_root_cause": hint.get("expected_root_cause", ""),
        }
        evidence = hint.get("evidence", [])
        if evidence:
            outcome["evidence"] = evidence
        evidence_ids = hint.get("evidence_ids")
        if evidence_ids:
            outcome["evidence_ids"] = evidence_ids
        return outcome

    def _review_notes(
        self,
        *,
        missing_context: list[str],
        spec_gaps: list[str],
        prompt: str,
        tool: ToolSpec,
    ) -> list[str]:
        """生成候选审核 checklist。

        每条候选**至少**带一条"人工核对 prompt 真实性"提醒；其它按缺什么补什么写：
        - spec_gaps（工具契约缺字段）→ 强烈提示先改 ``tools.yaml`` 而不是改 eval；
        - missing fixture / expected_root_cause → 提示补 hint；
        - prompt 偏短 → 提示补充业务背景；
        - 永远附 anti-tautology 提醒（以前的 must_call_tool 默认仍可能被审核者误用）。

        反作弊提醒（P1 根因治理，本轮加固）：
        默认 judge 已经加了语义规则（``must_use_evidence`` /
        ``expected_root_cause_contains`` / ``must_not_modify_before_evidence``），
        但 ``must_call_tool`` 仍在 rules 里。审核者如果把 must_call_tool 的工具名
        改错或把语义规则全删掉，仍会得到 tautological eval。这条 review note 就是
        在审核者眼前再钉一遍。
        """

        notes: list[str] = []
        if spec_gaps:
            gap_text = ", ".join(spec_gaps)
            notes.append(
                f"工具契约缺关键字段（{gap_text}），review_status 已置 needs_review。"
                "请先修 tools.yaml（补 when_to_use / when_not_to_use / output_contract /"
                " evidence / response_format），不要在弱契约上补 eval。"
            )
        if "fixture" in missing_context:
            notes.append(
                "需要补 initial_context/fixture：当前候选没有真实用户上下文，无法运行。"
            )
        if "expected_root_cause" in missing_context:
            notes.append(
                "需要补 expected_root_cause：缺少可被 RuleJudge 验证的真实根因。"
            )
        notes.append(
            "需要人工核对 user_prompt 的真实性，确认它来自真实用户问题而非工具描述改写。"
        )
        notes.append(
            "judge 默认已含 must_use_evidence / expected_root_cause_contains / "
            "must_not_modify_before_evidence 等语义规则，但 must_call_tool 仍是结构占位。"
            "转正前请确认：(a) must_call_tool 指向的工具名正确；(b) 至少一条语义规则真"
            "能区分 good/bad path；(c) 不要把所有语义规则删光只剩 must_call_tool，否则"
            "会被 EvalQualityAuditor 报 tautological（工具自己证明自己好用）。"
        )
        notes.append(
            "success_criteria 必须包含可验证行为/证据/根因要求；只列 required_tools 名"
            "等同于把『调用即通过』写成评估标准，会被 EvalQualityAuditor 的 "
            "success_criteria_only_required_tools finding 钉住。"
        )
        if (tool.side_effects or {}).get("destructive"):
            notes.append(
                "工具被标 destructive：默认 judge 已加 must_not_modify_before_evidence；"
                "请审核者额外检查 user_prompt 是否设计了『先取证再改』的多步路径。"
            )
        if len(prompt) < 40:
            notes.append("user_prompt 偏短，可能缺少必要业务背景，请人工补充。")
        return notes

    def _prompt_from_tool(self, project: ProjectSpec, tool: ToolSpec) -> str:
        domain = project.domain or "这个系统"
        intent = tool.when_to_use or tool.description
        intent = re.sub(r"\s+", " ", intent).strip(" .。")
        if not intent:
            intent = "定位一次用户报告的问题"
        return (
            f"线上 {domain} 出现一个需要复盘的异常。请根据已有上下文定位最可能的根因，"
            f"说明你依赖的证据，并给出下一步处理建议。场景线索：{intent}"
        )

    def _remove_tool_name(self, prompt: str, tool: ToolSpec) -> str:
        cleaned = prompt.replace(tool.name, "相关诊断能力")
        if tool.namespace:
            cleaned = cleaned.replace(f"{tool.namespace}.{tool.name}", "相关诊断能力")
        return cleaned

    def _scrub_cheating_signals(self, prompt: str) -> str:
        """最终兜底：把 prompt 里"动词 + 工具/tool" 共现/常见短语替换为通用占位。

        为什么需要：``_remove_tool_name`` 只去掉具体工具名，但如果 hint 作者写了
        "请使用相关工具定位 ..."，仍会被 EvalQualityAuditor 报
        ``realism.cheating_prompt``。这里**不抛错**，只把作弊片段替换为"按可用证据"，
        让候选仍可被审核但 prompt 不再泄露调用路径。

        这是 deterministic substring 替换，不是 NLU——审核者仍需人工核对最终
        prompt 是否真实。
        """

        scrubbed = prompt
        for phrase in self._CHEATING_PHRASES:
            scrubbed = re.sub(re.escape(phrase), "按可用证据", scrubbed, flags=re.IGNORECASE)
        lowered = scrubbed.lower()
        for verb, noun in self._CHEATING_TOKEN_PAIRS:
            if verb in lowered and noun in lowered:
                # 共现命中：直接把"工具/tool"替换为通用名词，让 verb 失去作弊指向。
                # 用 case-insensitive 替换避免漏掉首字母大写的 Tool。
                scrubbed = re.sub(noun, "证据来源", scrubbed, flags=re.IGNORECASE)
                lowered = scrubbed.lower()
        return scrubbed
