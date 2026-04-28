from __future__ import annotations

from typing import Any


class MarkdownReport:
    """生成面向 review 的 Markdown 报告。

    架构边界：
    - 只聚合 audit、judge、diagnosis、metrics 的摘要，不重新计算判定。
    - 不隐藏 raw artifacts；报告会指向 transcript/tool_calls/tool_responses。
    - 保持文本格式稳定，方便测试和 CI artifact review。

    可行动性原则（P1）：
    - 每个 eval 单独成段，把“调用了什么 / 缺什么 / 触发了什么禁忌”一次说清楚。
    - 每段末尾给出 next-step 建议，但都基于已有 artifact 字段，不引入新判定来源。
    - 顶部固定渲染 Methodology Caveats 段，提醒读者 RuleJudge 是启发式、
      MockReplayAdapter 是 deterministic replay、Tool Design Audit 不是语义级判断。

    用户项目自定义入口：
    - 报告内容取自 metrics.json / judge_results.json / diagnosis.json / audit_*.json，
      用户项目通过自定义 ToolSpec/EvalSpec/judge.rules 间接影响报告渲染；
      report 本身不暴露用户级配置点。

    扩展点（仅 ROADMAP，不在本轮实现）：
    - per-eval token/latency 指标；trajectory 节选块；HTML/JSON 报告变体。
    """

    REQUIRED_SECTIONS = [
        "Tool Design Audit",
        "Eval Quality Audit",
        "Agent Tool-Use Eval",
        "Transcript-derived Diagnosis",
        "Improvement Suggestions",
        "Failure Attribution",
    ]

    def render(
        self,
        *,
        project: dict[str, Any],
        metrics: dict[str, Any],
        audit_tools: dict[str, Any],
        audit_evals: dict[str, Any],
        judge_results: dict[str, Any],
        diagnosis: dict[str, Any],
    ) -> str:
        """渲染一次 run 的 Markdown 摘要。

        report 是派生视图，不负责重新判定成败。这里会展示 skipped/error 指标，是为了让用户
        一眼区分“Agent 判断失败”和“runner/adapter 执行链路异常”，但最终复盘仍应回到 JSONL。
        """

        low_score_tools = ", ".join(
            audit_tools.get("summary", {}).get("low_score_tools", [])
        ) or "none"
        not_runnable = ", ".join(
            audit_evals.get("summary", {}).get("not_runnable", [])
        ) or "none"
        # Signal quality banner：把 adapter 自报的信号质量等级显式渲染在报告顶部，
        # 避免真实团队把 mock PASS 当成评估信号。这里只渲染，不评分；等级和说明
        # 都来自 ``signal_quality`` 模块，由 EvalRunner 写入 metrics。
        signal_quality = str(metrics.get("signal_quality", "unknown"))
        signal_quality_note = str(metrics.get("signal_quality_note", ""))
        lines = [
            f"# Agent Tool Harness Report: {project.get('name', 'unknown')}",
            "",
            "## Signal Quality",
            "",
            f"- Level: `{signal_quality}`",
            f"- Note: {signal_quality_note}",
            "",
            (
                "> ⚠️  当前 Agent Tool Harness 是 MVP；signal_quality 反映本次 run 的信号边界。"
                "PASS/FAIL 不能替代真实 LLM agentic loop 的评估，详见 README 与 docs/ROADMAP.md。"
            ),
            "",
            "## Methodology Caveats",
            "",
            (
                "- **RuleJudge 是确定性启发式判定**，只覆盖 must_call_tool / forbidden_first_tool /"
                " max_tool_calls / expected_root_cause_contains / must_use_evidence /"
                " must_not_modify_before_evidence 这几类显式规则；不做 LLM 语义判分。"
            ),
            (
                "- **MockReplayAdapter 是 deterministic replay**，按 eval 自带的"
                " expected_tool_behavior 反向回放工具调用；它不是真实 LLM Agent，"
                "PASS/FAIL 不代表工具对真实 Agent 好用。"
            ),
            (
                "- **Tool Design Audit 当前只做 structural / completeness 检查**，"
                "不读 Python 源码、不调用工具、不识别语义诱饵；"
                "高分 ≠ 工具语义上好用，详见 docs/ROADMAP.md。"
            ),
            (
                "- **Failure attribution 是 deterministic heuristic，不是 LLM Judge**："
                "下面 Per-Eval Details 中的 finding / category / root_cause_hypothesis"
                "都是 TranscriptAnalyzer 按规则派生的方向性结论，**不能替代真实根因**；"
                "请按 evidence_refs 回到 raw artifacts 验证。"
            ),
            (
                "- **Artifact schema 详见 [docs/ARTIFACTS.md](../docs/ARTIFACTS.md)**；"
                "复盘失败时优先读 transcript.jsonl / tool_calls.jsonl / tool_responses.jsonl。"
            ),
            "",
            "## Tool Design Audit",
            "",
            f"- Tool count: {audit_tools.get('summary', {}).get('tool_count', 0)}",
            f"- Average score: {audit_tools.get('summary', {}).get('average_score', 0)}",
            f"- Low score tools: {low_score_tools}",
            *self._render_audit_signal_quality(audit_tools),
            *self._render_audit_warnings(audit_tools),
            *self._render_audit_high_severity_findings(audit_tools),
            "",
            "## Eval Quality Audit",
            "",
            f"- Eval count: {audit_evals.get('summary', {}).get('eval_count', 0)}",
            f"- Average score: {audit_evals.get('summary', {}).get('average_score', 0)}",
            f"- Not runnable: {not_runnable}",
            "",
            "## Agent Tool-Use Eval",
            "",
            f"- Total evals: {metrics.get('total_evals', 0)}",
            f"- Passed: {metrics.get('passed', 0)}",
            f"- Failed: {metrics.get('failed', 0)}",
            f"- Skipped: {metrics.get('skipped_evals', 0)}",
            f"- Errors: {metrics.get('error_evals', 0)}",
            f"- Total tool calls: {metrics.get('total_tool_calls', 0)}",
            "",
        ]
        for result in judge_results.get("results", []):
            status = "PASS" if result.get("passed") else "FAIL"
            lines.append(f"- {result.get('eval_id')}: {status}")

        # 每个 eval 的可行动详情段，按 eval_id join judge + diagnosis。
        # 不重新判定，只把已有 artifact 字段重新组织成“失败现场速读”视图。
        diag_by_id = {
            str(item.get("eval_id")): item for item in diagnosis.get("results", [])
        }
        lines.extend(["", "## Per-Eval Details", ""])
        for result in judge_results.get("results", []):
            eval_id = str(result.get("eval_id"))
            lines.extend(self._render_eval_detail(result, diag_by_id.get(eval_id)))

        lines.extend(["", "## Transcript-derived Diagnosis", ""])
        for item in diagnosis.get("results", []):
            lines.append(f"- {item.get('eval_id')}: {item.get('summary')}")
            if item.get("tool_sequence"):
                lines.append(f"  Tool sequence: {', '.join(item['tool_sequence'])}")

        # 顶层 Failure Attribution：把所有 eval 的 finding 按 category 聚合，让 review 者
        # 一眼看到“本次 run 主要是工具设计 / eval 定义 / Agent 工具选择 / runtime 哪类
        # 问题”。CI 也可以基于这块文本做 grep。诊断为 deterministic heuristic，详见上
        # 方 Methodology Caveats。
        lines.extend(["", "## Failure Attribution", ""])
        lines.extend(self._render_failure_attribution(diagnosis))

        lines.extend(
            [
                "",
                "## Improvement Suggestions",
                "",
                "- Review low-score tool audit findings before adding more evals.",
                "- Keep generated evals as candidates until context and outcomes are complete.",
                "- Inspect transcript/tool call artifacts before changing tests.",
                "- Fix tool descriptions, eval criteria, or adapter behavior from evidence.",
                "- 优先修 root_cause_hypothesis 指向的 category，再回到 raw artifacts 验证。",
                "",
                "## Artifacts",
                "",
                "- transcript.jsonl",
                "- tool_calls.jsonl",
                "- tool_responses.jsonl",
                "- metrics.json",
                "- audit_tools.json",
                "- audit_evals.json",
                "- judge_results.json",
                "- diagnosis.json",
                "- report.md",
                "",
                "字段说明详见 [docs/ARTIFACTS.md](../docs/ARTIFACTS.md)。",
            ]
        )
        return "\n".join(lines) + "\n"

    def _render_audit_signal_quality(self, audit_tools: dict[str, Any]) -> list[str]:
        """渲染 Tool Design Audit 顶层 signal_quality 披露。

        负责什么：把 ToolDesignAuditor 写到 audit_tools.json 的
        ``signal_quality`` + ``signal_quality_note`` 字段呈现到 report.md，
        让用户在 report 里直接看到"这是 deterministic 启发式"的边界声明，
        不必去翻 audit_tools.json。

        不负责什么：不重新判定信号等级——只忠实转写 audit 输出。

        为什么单独抽出：与 MockReplayAdapter 的 signal_quality banner 风格保持
        一致；未来如果 audit 升级到 LLM judge，这里只需要被动跟随，渲染逻辑不变。

        artifact 排查路径：``audit_tools.json`` → ``summary.signal_quality``
        / ``summary.signal_quality_note``。
        """

        summary = audit_tools.get("summary", {})
        sq = summary.get("signal_quality")
        if not sq:
            return []
        note = summary.get("signal_quality_note", "")
        return [
            "",
            "### Tool Design Audit signal quality",
            "",
            f"- Level: `{sq}`",
            f"- Note: {note}",
        ]

    def _render_audit_warnings(self, audit_tools: dict[str, Any]) -> list[str]:
        """渲染 Tool Design Audit 顶层 warnings。

        最关键的是把 ``semantic_risk_detected`` 写到 report 显眼位置——
        这是"score 高 ≠ 没问题"的反误读护栏。如果只看 average_score，用户
        会以为 5.0 满分就万事大吉；warning 强制把命中浅封装/语义重叠/边界
        重复的工具列出来。
        """

        warnings = audit_tools.get("summary", {}).get("warnings") or []
        if not warnings:
            return []
        out = ["", "### Tool Design Audit warnings", ""]
        for w in warnings:
            out.append(f"- ⚠️  {w}")
        return out

    def _render_audit_high_severity_findings(
        self, audit_tools: dict[str, Any]
    ) -> list[str]:
        """渲染所有工具的 high-severity finding + principle + suggested_fix。

        负责什么：让用户在 report.md 里直接看到"哪个工具 / 哪条规则 / 属于
        Anthropic 哪条原则 / 为什么重要 / 怎么修"五元组，不必去翻
        audit_tools.json。只展示 high severity 是为了避免 report 过长——
        medium / low 仍然写在 audit_tools.json 里。

        v0.2 第二轮新增：渲染 ``principle_title`` 与 ``why_it_matters`` 字段
        （由 ToolDesignAuditor.AuditFinding 自动派生 / 可选填充），让消费者
        不用解析 rule_id 字符串就能按原则归类。

        不负责什么：不做新的判定逻辑——只是按 severity 过滤已有 finding。
        """

        rows: list[str] = []
        for tool in audit_tools.get("tools", []):
            high = [f for f in tool.get("findings", []) if f.get("severity") == "high"]
            if not high:
                continue
            rows.append(f"- **{tool.get('tool_name')}**:")
            for f in high:
                principle_title = f.get("principle_title") or f.get("principle") or ""
                principle_seg = f" _[{principle_title}]_" if principle_title else ""
                rows.append(
                    f"  - `{f.get('rule_id')}`{principle_seg} — {f.get('message')}"
                )
                why = f.get("why_it_matters")
                if why:
                    rows.append(f"    - why_it_matters: {why}")
                fix = f.get("suggested_fix") or f.get("suggestion")
                if fix:
                    rows.append(f"    - suggested_fix: {fix}")
        if not rows:
            return []
        return ["", "### Tool Design Audit high-severity findings", ""] + rows

    def _render_eval_detail(
        self,
        judge: dict[str, Any],
        diag: dict[str, Any] | None,
    ) -> list[str]:
        """渲染单个 eval 的可行动详情段。

        归类原则：
        - **Status**：PASS / FAIL / SKIPPED / ERROR；后两者从 judge.checks 的 rule.type 反推
          (eval_not_runnable / tool_registry_initialization_failed /
          adapter_execution_failed)。
        - **Tool sequence**：来自 diagnosis；空序列时显示 ``<no tool calls>``。
        - **Required tools**：列出 OK / Missing 状态，让用户一眼看到证据链断点。
        - **Forbidden first tool triggered**：扫 judge.checks，捕获失败的 forbidden_first_tool。
        - **Max tool calls violation**：同上。
        - **Runtime error / skipped reason**：从 error 类 rule.message 直接透传。
        - **Next steps**：根据上述事实派生的人类可行动建议；不是新的判定。
        """

        eval_id = str(judge.get("eval_id", "<unknown>"))
        diag = diag or {}
        checks = list(judge.get("checks", []))
        status = self._derive_status(judge, checks)
        tool_sequence = list(diag.get("tool_sequence", []))
        missing = list(diag.get("missing_required_tools", []))

        forbidden_hit: str | None = None
        max_calls_hit: str | None = None
        runtime_reason: str | None = None
        for check in checks:
            rule = check.get("rule", {}) or {}
            rule_type = rule.get("type")
            if not check.get("passed"):
                if rule_type == "forbidden_first_tool":
                    forbidden_hit = str(check.get("message", ""))
                elif rule_type == "max_tool_calls":
                    max_calls_hit = str(check.get("message", ""))
                elif rule_type in {
                    "eval_not_runnable",
                    "tool_registry_initialization_failed",
                    "adapter_execution_failed",
                }:
                    runtime_reason = f"[{rule_type}] {check.get('message', '')}"

        # required tools 的 OK/Missing 状态需要从 judge.checks 的 must_call_tool 与
        # diagnosis.missing_required_tools 推导，确保 PASS 时也能看到具体走过哪些工具。
        required_status = self._required_tools_status(checks, missing)

        block = [f"### {eval_id} — {status}", ""]
        if tool_sequence:
            block.append(f"- Tool sequence: {', '.join(tool_sequence)}")
        else:
            block.append("- Tool sequence: <no tool calls>")
        if required_status:
            block.append("- Required tools:")
            for entry in required_status:
                block.append(f"    - {entry}")
        if forbidden_hit:
            block.append(f"- Forbidden first tool triggered: {forbidden_hit}")
        if max_calls_hit:
            block.append(f"- Max tool calls exceeded: {max_calls_hit}")
        if runtime_reason:
            block.append(f"- Runtime / skipped reason: {runtime_reason}")
        block.append(
            "- Signal note: 该结果同样受顶部 signal_quality 限制；如为 tautological_replay，"
            "PASS/FAIL 不可作为真实 Agent 工具能力评估。"
        )

        # Failure attribution（本轮新增，借鉴 LangSmith failure tags / OTel span attributes /
        # Anthropic 工具评估方法论）：把 deterministic heuristic 派生的 finding 列表以
        # 可读方式展开。每条 finding 必须给出 severity / category / why_it_matters /
        # suggested_fix / evidence_refs，让用户能直接判断"是工具设计、eval 定义、Agent
        # 工具选择，还是 runtime/工具执行"问题。报告中刻意不省略 evidence_refs，
        # 鼓励读者跳回 raw artifact 验证。
        diag = diag or {}
        findings = list(diag.get("findings", []) or [])
        category_summary = dict(diag.get("category_summary", {}) or {})
        root_cause = str(diag.get("root_cause_hypothesis", "") or "")
        what_to_check = list(diag.get("what_to_check_next", []) or [])

        if findings:
            block.append("- Failure attribution (heuristic, not root cause):")
            for finding in findings:
                ftype = finding.get("type", "<unknown>")
                severity = finding.get("severity", "?")
                category = finding.get("category", "?")
                why = finding.get("why_it_matters", "")
                fix = finding.get("suggested_fix", "")
                refs = finding.get("evidence_refs", []) or []
                related = finding.get("related_tool_or_eval") or ""
                related_text = f" (related: `{related}`)" if related else ""
                block.append(
                    f"    - [{severity}/{category}] **{ftype}**{related_text} — {why}"
                )
                # v1.0 候选 A 增量（per-eval 视角）：把 evidence grounding 类
                # finding 的结构化字段也直接渲染在 Per-Eval Details，让用户在每条
                # eval 块内就能复盘 grounding 失败原因；避免"category 聚合区有信息
                # 但 per-eval 区缺信息"导致用户漏看。
                if ftype == "evidence_grounded_in_decoy_tool":
                    cited_refs = finding.get("cited_refs") or []
                    cited_tools = finding.get("cited_tools") or []
                    required_tools = finding.get("required_tools") or []
                    if cited_refs or cited_tools:
                        block.append(
                            f"        - Cited evidence: {cited_refs} from non-required "
                            f"tool(s) {cited_tools}; required={required_tools}"
                        )
                elif ftype == "no_evidence_grounding":
                    had_evidence = finding.get("tool_responses_had_evidence")
                    available = finding.get("available_evidence_refs") or []
                    if had_evidence is True:
                        block.append(
                            f"        - Tool returned evidence ({available}) but "
                            "final_answer did not cite any id/label — fix prompt or "
                            "Agent strategy."
                        )
                    elif had_evidence is False:
                        block.append(
                            "        - Tool responses contained no evidence id/label — "
                            "fix tool output_contract.required_fields first."
                        )
                if fix:
                    block.append(f"        - Suggested fix: {fix}")
                if refs:
                    block.append(f"        - Evidence: {', '.join(refs)}")
        if category_summary and any(v for v in category_summary.values()):
            counts = ", ".join(
                f"{cat}={count}" for cat, count in category_summary.items() if count
            )
            block.append(f"- Category breakdown: {counts}")
        if root_cause:
            block.append(f"- Root cause hypothesis: {root_cause}")
        if what_to_check:
            block.append("- What to check next:")
            for ref in what_to_check:
                block.append(f"    - {ref}")

        # v0.2 第三轮新增：trace-derived tool-use 信号渲染。
        # 这些信号来自 TraceSignalAnalyzer，是从 raw tool_responses payload + ToolSpec
        # output_contract 复盘出来的"contract / 模式"层面证据，与上方 rule-derived
        # findings 正交。展示时显式标注 source=trace，避免读者混淆。
        signals = list(diag.get("tool_use_signals", []) or [])
        if signals:
            block.append("- Trace-derived tool-use signals (deterministic, from raw artifacts):")
            for sig in signals:
                stype = sig.get("signal_type", "<unknown>")
                severity = sig.get("severity", "?")
                related = sig.get("related_tool") or ""
                related_text = f" (tool: `{related}`)" if related else ""
                why = sig.get("why_it_matters", "")
                block.append(
                    f"    - [{severity}] **{stype}**{related_text} — {why}"
                )
                fix = sig.get("suggested_fix")
                if fix:
                    block.append(f"        - Suggested fix: {fix}")
                refs = sig.get("evidence_refs", []) or []
                if refs:
                    block.append(f"        - Evidence: {', '.join(refs)}")

        block.append("- Next steps:")
        for hint in self._next_steps(status, missing, forbidden_hit, max_calls_hit, runtime_reason):
            block.append(f"    - {hint}")
        block.append("")
        return block

    def _render_failure_attribution(self, diagnosis: dict[str, Any]) -> list[str]:
        """聚合所有 eval 的 finding，按 category 输出汇总。

        负责什么：把 deterministic heuristic 派生的 finding 集中展示，方便 review
        者快速判断本次 run 主要踩的是哪一类问题（工具设计 / eval 定义 / Agent
        工具选择 / runtime）。

        不负责什么：不做语义级根因，不做去重打分，不做 LLM 解释。所有结论必须
        回到对应 eval 的 evidence_refs 才能确认。

        为什么这样设计：CI / PR review / 团队周会都希望先看一段“本次 run 主要痛
        点”概览，而不是逐个 eval 翻 detail。这里只做最基础的 category 聚合 +
        高 severity finding 列表，避免把 heuristic 包装成精准结论。

        未来扩展点：等真的接入 LLM Judge / trace 后，可在此输出 attribution 置
        信度、跨 eval 同类问题的合并、修复优先级排序。
        """
        results = list(diagnosis.get("results", []) or [])
        if not results:
            return ["- 当前没有可归因的 eval 结果。"]

        # category -> list[(eval_id, finding)]，方便分桶展示。
        buckets: dict[str, list[tuple[str, dict[str, Any]]]] = {}
        any_finding = False
        for item in results:
            eval_id = str(item.get("eval_id", ""))
            for finding in item.get("findings", []) or []:
                any_finding = True
                category = str(finding.get("category", "uncategorized"))
                buckets.setdefault(category, []).append((eval_id, finding))

        lines: list[str] = [
            "Diagnosis is a deterministic heuristic — review evidence_refs before acting.",
            "",
        ]
        if not any_finding:
            lines.append("- 本次 run 未触发任何 failure attribution finding。")
            return lines

        order = [
            "tool_design",
            "eval_definition",
            "agent_tool_choice",
            "runtime",
        ]
        seen = set()
        for category in order + sorted(buckets.keys()):
            if category in seen or category not in buckets:
                continue
            seen.add(category)
            entries = buckets[category]
            lines.append(f"### Category: {category} ({len(entries)})")
            for eval_id, finding in entries:
                ftype = finding.get("type", "<unknown>")
                severity = finding.get("severity", "?")
                related = finding.get("related_tool_or_eval") or ""
                related_text = f" related=`{related}`" if related else ""
                lines.append(
                    f"- `{eval_id}` [{severity}] **{ftype}**{related_text}"
                )
                # v1.0 候选 A：evidence grounding 类 finding 的结构化细节渲染。
                # 这些字段由 TranscriptAnalyzer 显式塞入 finding payload；report
                # 只负责渲染，不二次推理。**不渲染** finding 内部 deterministic
                # 启发式之外的内容，避免暗示这是 LLM 级根因。
                if ftype == "evidence_grounded_in_decoy_tool":
                    cited_refs = finding.get("cited_refs") or []
                    cited_tools = finding.get("cited_tools") or []
                    required_tools = finding.get("required_tools") or []
                    if cited_refs or cited_tools:
                        lines.append(
                            f"    - Cited evidence: {cited_refs} from non-required "
                            f"tool(s) {cited_tools}; required={required_tools}"
                        )
                elif ftype == "no_evidence_grounding":
                    had_evidence = finding.get("tool_responses_had_evidence")
                    available = finding.get("available_evidence_refs") or []
                    if had_evidence is True:
                        lines.append(
                            f"    - Tool returned evidence ({available}) but "
                            "final_answer did not cite any id/label — fix prompt or "
                            "Agent strategy."
                        )
                    elif had_evidence is False:
                        lines.append(
                            "    - Tool responses contained no evidence id/label — fix "
                            "tool output_contract.required_fields first."
                        )
                fix = finding.get("suggested_fix")
                if fix:
                    lines.append(f"    - Suggested fix: {fix}")
            lines.append("")
        return lines

    def _derive_status(
        self,
        judge: dict[str, Any],
        checks: list[dict[str, Any]],
    ) -> str:
        """把 judge_results 中的 runner 级失败显式翻译成 SKIPPED / ERROR。

        runner 在 eval skip / registry init failure / adapter execution failure 三种路径
        会塞入特殊 rule.type；此处把它们从 FAIL 中拆出来，避免读者把链路异常误读为
        Agent 工具选择失败。
        """

        if judge.get("passed"):
            return "PASS"
        for check in checks:
            rule_type = (check.get("rule") or {}).get("type")
            if rule_type == "eval_not_runnable":
                return "SKIPPED"
            if rule_type in {
                "tool_registry_initialization_failed",
                "adapter_execution_failed",
            }:
                return "ERROR"
        return "FAIL"

    def _required_tools_status(
        self,
        checks: list[dict[str, Any]],
        missing: list[str],
    ) -> list[str]:
        """给出每个 must_call_tool 规则对应工具的 OK / Missing 状态。

        从 judge.checks 取 must_call_tool 规则，结合 diagnosis.missing_required_tools 得到
        真实 OK/Missing 划分；must_call_one_of 也一并展示，避免读者漏看“至少调用一个”的契约。
        """

        rows: list[str] = []
        missing_set = {str(name) for name in missing}
        for check in checks:
            rule = check.get("rule") or {}
            if rule.get("type") == "must_call_tool":
                name = str(rule.get("tool", ""))
                if not name:
                    continue
                marker = "Missing" if name in missing_set or not check.get("passed") else "OK"
                rows.append(f"`{name}` — {marker}")
            elif rule.get("type") == "must_call_one_of":
                tools = sorted(str(t) for t in rule.get("tools", []))
                marker = "OK" if check.get("passed") else "Missing"
                rows.append(f"one_of {tools} — {marker}")
        return rows

    def _next_steps(
        self,
        status: str,
        missing: list[str],
        forbidden_hit: str | None,
        max_calls_hit: str | None,
        runtime_reason: str | None,
    ) -> list[str]:
        """从已知失败事实派生的可行动建议。

        刻意保持启发式且简短：建议必须可被任意真实团队按 artifact 立刻执行，不引入
        新判定。所有建议都强调“先看 raw artifacts”，避免读者依赖派生视图。
        """

        if status == "PASS":
            return [
                "复盘 tool_calls.jsonl / tool_responses.jsonl，确认调用顺序合理且 evidence 真实。",
                "若想增强信号，请等待真实 LLM adapter 上线（见 docs/ROADMAP.md 信号质量章节）。",
            ]
        if status == "SKIPPED":
            return [
                "查看 audit_evals.json 里该 eval 的 findings 与 missing_context，补全后再跑。",
                "在 transcript.jsonl 中搜索 runner_skip 事件确认跳过原因。",
            ]
        if status == "ERROR":
            return [
                "查看 transcript.jsonl 中 runner_error 事件的 traceback，"
                "定位 adapter 或 registry 错误。",
                "修复后重跑；不要靠改测试或调弱 audit 绕过 runtime 错误。",
            ]
        hints: list[str] = []
        if forbidden_hit:
            hints.append(
                "第一步工具选择错误：检查 Agent prompt 与 tool description 是否引导错误入口。"
            )
        if missing:
            hints.append(
                "缺失关键工具调用：在 tool_calls.jsonl 确认是否被 Agent 跳过；"
                f"missing={missing}。"
            )
        if max_calls_hit:
            hints.append(
                "工具调用次数超过预算：在 tool_calls.jsonl 中识别冗余调用；"
                "考虑收紧 prompt 或提升工具返回信息密度。"
            )
        if runtime_reason:
            hints.append("看 transcript.jsonl 的 runner_error 事件以获取真实 traceback。")
        if not hints:
            hints.append(
                "judge_results.json 中的 failed checks 是首要线索；"
                "再回到 transcript / tool_calls / tool_responses 三件套定位证据缺口。"
            )
        return hints
