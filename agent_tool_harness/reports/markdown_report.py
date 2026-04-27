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
                "- **Artifact schema 详见 [docs/ARTIFACTS.md](../docs/ARTIFACTS.md)**；"
                "复盘失败时优先读 transcript.jsonl / tool_calls.jsonl / tool_responses.jsonl。"
            ),
            "",
            "## Tool Design Audit",
            "",
            f"- Tool count: {audit_tools.get('summary', {}).get('tool_count', 0)}",
            f"- Average score: {audit_tools.get('summary', {}).get('average_score', 0)}",
            f"- Low score tools: {low_score_tools}",
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
        lines.extend(
            [
                "",
                "## Improvement Suggestions",
                "",
                "- Review low-score tool audit findings before adding more evals.",
                "- Keep generated evals as candidates until context and outcomes are complete.",
                "- Inspect transcript/tool call artifacts before changing tests.",
                "- Fix tool descriptions, eval criteria, or adapter behavior from evidence.",
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
        block.append("- Next steps:")
        for hint in self._next_steps(status, missing, forbidden_hit, max_calls_hit, runtime_reason):
            block.append(f"    - {hint}")
        block.append("")
        return block

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
