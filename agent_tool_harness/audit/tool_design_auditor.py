from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from agent_tool_harness.config.tool_spec import ToolSpec


@dataclass
class AuditFinding:
    """单条 ToolDesignAuditor finding 的结构化表示。

    字段语义（v0.2 第二轮新增 principle / why_it_matters）：
    - ``rule_id``：规则唯一 id，前缀对应 Anthropic 工具设计 5 类原则之一
      （right_tools / namespacing / meaningful_context / token_efficiency /
      prompt_spec）。
    - ``severity``：``high`` / ``medium`` / ``low``。high 会出现在 report.md
      的 actionable 摘要里。
    - ``message``：人类可读的"问题是什么"。
    - ``suggestion``：人类可读的"该怎么修"，与 ``message`` 一一对应。
    - ``principle``（v0.2 新增）：从 rule_id 派生的 Anthropic 原则 token，让
      消费者不必自己解析 rule_id 前缀。默认空字符串，``to_dict`` 会自动派生。
    - ``why_it_matters``（v0.2 新增）：可选的"为什么这条规则重要"补充段；当
      ``message`` 已经能解释清楚时，这里允许为空，避免冗余。

    设计动机：v0.1 期间 finding 只暴露 ``rule_id / severity / message /
    suggestion`` 四个字段，下游（report / 远程 dashboard / CI bot）想按
    Anthropic 原则归类必须自己解析 rule_id 字符串——这是脆弱耦合。
    显式 ``principle`` 字段让 finding 自描述，未来加新原则也只需要改
    `_PRINCIPLE_TITLES` 而不必改任何消费者。

    不负责：
    - 不做 LLM 语义判定，不读源码——这是 deterministic 启发式。
    - 不携带"分数"——分数在 ``ToolAuditResult.category_scores`` 上。

    artifact 排查路径：``audit_tools.json`` → ``tools[*].findings[*]``。
    """

    rule_id: str
    severity: str
    message: str
    suggestion: str
    principle: str = ""
    why_it_matters: str = ""


# Anthropic 工具设计 5 类原则的 principle token → 人类可读标题。
# 用于 ``AuditFinding.to_dict`` 自动派生 principle 字段，也用于 MarkdownReport
# 渲染 actionable 摘要时显示原则归类。
_PRINCIPLE_TITLES: dict[str, str] = {
    "right_tools": "Choosing the right tools (Anthropic principle 1)",
    "namespacing": "Namespacing tools (Anthropic principle 2)",
    "meaningful_context": "Returning meaningful context (Anthropic principle 3)",
    "token_efficiency": "Optimizing tool responses for token efficiency (Anthropic principle 4)",
    "prompt_spec": "Prompt-engineering your tool descriptions (Anthropic principle 5)",
}


def _derive_principle(rule_id: str) -> str:
    """从 rule_id 前缀派生 principle token，对未知前缀回退为前缀本身。

    设计动机：所有 finding 的 rule_id 已经按 ``<principle>.<sub-rule>`` 命名，
    这里只是把这层 implicit 约定显式化为 finding 字段，降低下游解析成本。
    """

    return rule_id.split(".", 1)[0] if "." in rule_id else rule_id


@dataclass
class ToolAuditResult:
    tool_name: str
    qualified_name: str
    category_scores: dict[str, int]
    findings: list[AuditFinding] = field(default_factory=list)

    @property
    def overall_score(self) -> float:
        if not self.category_scores:
            return 0.0
        return round(sum(self.category_scores.values()) / len(self.category_scores), 2)

    def to_dict(self) -> dict[str, Any]:
        # v0.2 第二轮新增：把每条 finding 的 ``principle`` 字段自动填充并附带
        # 人类可读 ``principle_title``——下游消费者（report.md / 远程 dashboard）
        # 不必再解析 rule_id 字符串。**back-compat**：原有 rule_id / severity /
        # message / suggestion 不变；新增字段都是追加，老消费者忽略即可。
        finding_dicts = []
        for finding in self.findings:
            d = dict(finding.__dict__)
            if not d.get("principle"):
                d["principle"] = _derive_principle(finding.rule_id)
            d["principle_title"] = _PRINCIPLE_TITLES.get(
                d["principle"], d["principle"]
            )
            finding_dicts.append(d)
        return {
            "tool_name": self.tool_name,
            "qualified_name": self.qualified_name,
            "overall_score": self.overall_score,
            "category_scores": self.category_scores,
            "findings": finding_dicts,
        }


class ToolDesignAuditor:
    """按 Agent 工具设计原则审计 tools.yaml。

    架构边界：
    - 负责检查工具“是否适合给 Agent 使用”，而不是检查 Python 函数能否运行。
    - 输出五类评分：right_tools、namespacing、meaningful_context、token_efficiency、prompt_spec。
    - 不执行工具、不读取用户运行时状态，也不修改工具实现。

    为什么这样拆：
    Agent 工具是确定性系统和非确定性 Agent 之间的契约。这个 auditor 先检查契约设计，
    后续 runner 才检查 Agent 在真实 transcript 中是否正确使用这些契约。

    扩展点：
    - 可以增加项目领域规则，例如 destructive 工具必须要求 evidence。
    - 可以接入 LLM reviewer，但当前 MVP 保持 deterministic rule audit。
    """

    CATEGORY_KEYS = [
        "right_tools",
        "namespacing",
        "meaningful_context",
        "token_efficiency",
        "prompt_spec",
    ]

    GENERIC_NAME_TOKENS = {
        "get",
        "list",
        "set",
        "update",
        "run",
        "call",
        "api",
        "query",
        # v0.2 候选 A 扩充：以下 token 出现在工具名里几乎一定是"动词太泛"——
        # Agent 看不出该工具到底解决什么资源/工作流。如果你的项目真的有合理用例
        # （例如 ``<domain>_<resource>_check``），可以通过拼接更具体的资源名让
        # 工具名 token 集合长度 > 2，从而绕过本规则（详见 _score_namespace）。
        "check",
        "analyze",
        "debug",
        "read",
        "quick",
        "info",
        "data",
        "do",
        "process",
        "handle",
    }
    LOW_LEVEL_HINTS = {"api wrapper", "raw api", "endpoint", "crud", "database row", "直接封装"}

    # v0.2 候选 A 新增：浅封装 / 单步捷径诱饵关键短语。
    # 设计动机：Anthropic *Writing effective tools for agents* 的 "Choosing the
    # right tools" 章节强调，工具应该体现真实工作流边界，而不是声称"一步给答案"。
    # 诱饵工具常用如下话术让 Agent 误以为可以跳过中间步骤：
    #   - "single-step shortcut" / "quickly returns" / "without inspecting"
    #   - "you do not need to call other tools" / "directly returns root cause"
    # 这些短语只是 deterministic 启发式，**不能识别所有语义诱饵**——更隐蔽的诱饵
    # （没有捷径话术但职责仍重叠）需要 transcript / LLM judge 才能解决，已记
    # docs/ROADMAP.md，并由 tests/test_tool_design_audit_subtle_decoy_xfail.py
    # 用 strict xfail 钉根因。
    _SHALLOW_WRAPPER_PHRASES = (
        "single-step shortcut",
        "single step shortcut",
        "one-step shortcut",
        "one step shortcut",
        "quickly returns",
        "without inspecting",
        "without checking",
        "without calling",
        "no need to call",
        "you do not need to call",
        "you don't need to call",
        "directly returns root cause",
        "directly gives root cause",
        "skip the trace",
        "skip the underlying",
    )

    # 用于语义重叠 Jaccard 计算的 stopword 集合。
    # 设计权衡：保留 stopword 会让任何两个英文工具描述都"看起来像"——所以这里只剔
    # 最常见、对工具职责无贡献的虚词。**不是** NLU 词典，新增 stopword 必须同步
    # 调整 docs/TESTING.md 的回归覆盖说明，避免悄悄改变阈值灵敏度。
    _OVERLAP_STOPWORDS = frozenset(
        {
            "the", "a", "an", "and", "or", "but", "for", "with", "from", "into", "onto",
            "this", "that", "these", "those",
            "use", "used", "using", "tool", "tools", "agent", "agents", "user", "users",
            "should", "will", "can", "may", "must",
            "when", "while", "where", "what", "which",
            "any", "all", "each", "other",
            "without", "before", "after", "during",
            "first", "next", "last",
            "available", "given",
            "provide", "provides", "providing",
            "return", "returns", "returning",
            "supports", "support", "based", "via",
        }
    )

    # 语义重叠 Jaccard 阈值。
    # 选择 0.4 的根因：在 examples/runtime_debug 真实 spec 上，三对工具最高
    # Jaccard 约 0.20-0.28（彼此职责真分明），而 decoy 测试中诱饵 vs 主工具
    # Jaccard 约 0.42-0.55；取 0.4 既能命中诱饵，又能避免误伤合理 spec。
    # 调整阈值前必须重跑 tests/test_tool_design_audit_decoy.py 与
    # tests/test_tool_design_audit_semantic.py 的反向断言。
    _OVERLAP_JACCARD_THRESHOLD = 0.4

    # 触发顶层 ``semantic_risk_detected`` warning 的高严重度 finding 集合。
    # 任何工具命中其中之一就让顶层 warnings 提示"score 高 ≠ 没问题"，避免
    # CI / 远程消费者只看 average_score 而漏掉真实风险。新增 high-severity
    # 语义信号时记得在这里登记。
    _SEMANTIC_RISK_RULES = frozenset(
        {
            "right_tools.shallow_wrapper",
            "right_tools.semantic_overlap",
            "prompt_spec.usage_boundary_duplicated",
        }
    )

    def audit(self, tools: list[ToolSpec]) -> dict[str, Any]:
        name_counts = Counter(tool.name for tool in tools)
        namespace_counts = Counter(tool.namespace for tool in tools)
        # v0.2 候选 A 新增：先全局算一次"description+when_to_use 词袋的两两 Jaccard
        # 重叠"，结果缓存进 dict 避免在 _score_right_tool 里 O(n^2) 重复算。
        # 选择把它放在 audit() 这一层而不是 audit_tool() 里：因为重叠是**关系**属性，
        # 单工具视角无法判断；放对层级也方便未来引入 LLM judge 后替换实现而不影响
        # 调用方。
        overlap_map = self._semantic_overlap_pairs(tools)
        results = [
            self.audit_tool(
                tool,
                tools,
                name_counts=name_counts,
                namespace_counts=namespace_counts,
                semantic_overlap_with=overlap_map.get(tool.name, []),
            )
            for tool in tools
        ]
        # 顶层 warnings 字段（P0 治理）：
        # 真实坑——之前空 tools 时 CLI 只在 stderr 打印 "(warning) tools file is
        # empty"，但 audit_tools.json 完全无 finding、average_score=0，CI/远程消费者
        # 看不到任何信号；用户接 pipeline 会以为"audit 通过"。这里把"零输入"作为
        # 显式 warning 写进 artifact，让派生数据真实反映"零输入"这一接入失败。
        warnings: list[str] = []
        if not tools:
            warnings.append(
                "empty_input: tools list is empty; nothing to audit. "
                "请确认 tools.yaml 已经声明了真实工具，否则后续 run/judge 都会无效。"
            )
        # v0.2 候选 A 新增：当任何工具命中 high-severity 语义信号时，顶层加 warning，
        # 让 CI/远程消费者一眼看到"score 高 ≠ 没问题"。
        risky_tools = sorted(
            {
                r.qualified_name
                for r in results
                if any(f.rule_id in self._SEMANTIC_RISK_RULES for f in r.findings)
            }
        )
        if risky_tools:
            warnings.append(
                "semantic_risk_detected: 以下工具命中浅封装 / 语义重叠 / 边界重复等"
                "启发式信号，必须人工 review，不要只看 overall_score: "
                + ", ".join(risky_tools)
            )
        return {
            "summary": {
                "tool_count": len(tools),
                "average_score": self._average(result.overall_score for result in results),
                "low_score_tools": [
                    result.qualified_name for result in results if result.overall_score < 3.5
                ],
                "warnings": warnings,
                # v0.2 候选 A 新增：明确披露 audit 信号等级。
                # 设计动机：之前用户拿到 audit_tools.json 时无法判断这是"deterministic
                # 规则审计"还是"语义级 LLM 审计"，容易把启发式 PASS 误当成
                # production-grade 工具设计证明。这里显式写明 deterministic_heuristic，
                # 与 MockReplayAdapter 的 signal_quality 披露一致——让用户知道当前
                # 局限，转正条件已记 docs/ROADMAP.md。
                "signal_quality": "deterministic_heuristic",
                "signal_quality_note": (
                    "ToolDesignAuditor 当前是 deterministic 启发式：检查字段完整性 + "
                    "名称/描述/边界关键词共现，不读工具源码、不调用工具、不做 LLM "
                    "语义判断。可以识别字段缺失、generic name、浅封装捷径话术、字段齐全"
                    "但 description / when_to_use 高度重叠的工具对；**无法**识别字段"
                    "齐全且没有捷径话术但语义上仍是诱饵的工具——后者需要 transcript / "
                    "LLM judge，已记 docs/ROADMAP.md。"
                ),
            },
            "tools": [result.to_dict() for result in results],
        }

    def audit_tool(
        self,
        tool: ToolSpec,
        all_tools: list[ToolSpec] | None = None,
        *,
        name_counts: Counter[str] | None = None,
        namespace_counts: Counter[str] | None = None,
        semantic_overlap_with: list[str] | None = None,
    ) -> ToolAuditResult:
        all_tools = all_tools or [tool]
        name_counts = name_counts or Counter(item.name for item in all_tools)
        namespace_counts = namespace_counts or Counter(item.namespace for item in all_tools)
        # ``semantic_overlap_with`` 由 audit() 预计算并显式注入；如果调用方直接调
        # audit_tool 而没传，就退化为"无重叠"——保持单工具自测可用。
        semantic_overlap_with = semantic_overlap_with or []
        findings: list[AuditFinding] = []
        scores = {
            "right_tools": self._score_right_tool(
                tool, all_tools, findings, semantic_overlap_with=semantic_overlap_with
            ),
            "namespacing": self._score_namespace(tool, name_counts, namespace_counts, findings),
            "meaningful_context": self._score_context(tool, findings),
            "token_efficiency": self._score_token_efficiency(tool, findings),
            "prompt_spec": self._score_prompt_spec(tool, findings),
        }
        return ToolAuditResult(
            tool_name=tool.name,
            qualified_name=tool.qualified_name,
            category_scores=scores,
            findings=findings,
        )

    def _score_right_tool(
        self,
        tool: ToolSpec,
        all_tools: list[ToolSpec],
        findings: list[AuditFinding],
        *,
        semantic_overlap_with: list[str] | None = None,
    ) -> int:
        semantic_overlap_with = semantic_overlap_with or []
        score = 5
        combined = f"{tool.description} {tool.when_to_use}".lower()
        if any(hint in combined for hint in self.LOW_LEVEL_HINTS):
            score -= 2
            findings.append(
                AuditFinding(
                    "right_tools.low_level_wrapper",
                    "high",
                    "工具描述像底层 API wrapper，而不是面向 Agent 的工作流工具。",
                    "把多个底层操作合并成一个高影响任务边界，并返回决策所需上下文。",
                )
            )
        # v0.2 候选 A 新增：浅封装捷径话术诱饵（high）。
        # 设计动机：诱饵工具常用 "single-step shortcut" / "you do not need to call"
        # 等话术，让 Agent 误以为可以跳过中间诊断步骤。命中即扣 2 分。
        # 这是 deterministic 启发式——隐蔽诱饵（不含这些话术）需要 transcript /
        # LLM judge，已记 docs/ROADMAP.md 并由 strict xfail 钉住根因。
        if any(phrase in combined for phrase in self._SHALLOW_WRAPPER_PHRASES):
            score -= 2
            findings.append(
                AuditFinding(
                    "right_tools.shallow_wrapper",
                    "high",
                    "description / when_to_use 含"
                    "捷径话术（single-step shortcut / quickly returns / "
                    "without inspecting / you do not need to call 等），"
                    "可能诱导 Agent 跳过真正的诊断流程。",
                    "去掉捷径承诺，明确该工具只在哪些前置条件下成立；"
                    "如果它真的能一步给答案，请在 description 写出可验证的边界。",
                    why_it_matters=(
                        "Agent 阅读工具 description 决定调用顺序。捷径话术会让"
                        "Agent 优先选择此工具并跳过真正能拿到证据的工具调用——"
                        "在生产环境表现为'一次调用，结论无证据'，根因看不到。"
                    ),
                )
            )
        # v0.2 候选 A 新增：跨工具语义重叠（high）。
        # overlap_map 由 audit() 用 description + when_to_use 词袋的 Jaccard 算出，
        # 阈值 _OVERLAP_JACCARD_THRESHOLD=0.4。命中是双向的——必须双方都报，
        # 否则审核者会以为另一方"没问题"。
        if semantic_overlap_with:
            score -= 2
            findings.append(
                AuditFinding(
                    "right_tools.semantic_overlap",
                    "high",
                    "description + when_to_use 与以下工具高度重叠（Jaccard ≥ "
                    f"{self._OVERLAP_JACCARD_THRESHOLD}）："
                    + ", ".join(semantic_overlap_with)
                    + "。Agent 选择时可能分心或被诱饵命中。",
                    "明确两者的真实边界差异（输入前提 / 输出粒度 / 触发场景），"
                    "或合并为一个支持 mode/filter 的工具。",
                    why_it_matters=(
                        "工具集合里出现职责高度重叠的两条工具时，Agent 选择会变得"
                        "不稳定（同一问题不同 trace 可能选不同工具），且任一条只要被"
                        "诱饵化（加入捷径话术）就会污染结果。Anthropic 工具设计指南"
                        "建议每个工具承担清晰、不可替代的工作流边界。"
                    ),
                )
            )
        if len(tool.description.split()) < 10 and len(tool.description) < 80:
            score -= 1
            findings.append(
                AuditFinding(
                    "right_tools.too_little_intent",
                    "medium",
                    "description 没有清楚说明真实工作流和任务价值。",
                    "用新同事能理解的语言说明该工具解决什么诊断/执行任务。",
                )
            )
        if not tool.when_to_use:
            score -= 1
            findings.append(
                AuditFinding(
                    "right_tools.missing_when_to_use",
                    "medium",
                    "缺少 when_to_use，Agent 难以判断何时调用。",
                    "补充触发场景、输入前提和典型用户问题。",
                )
            )
        if len(all_tools) > 12:
            score -= 1
            findings.append(
                AuditFinding(
                    "right_tools.too_many_tools",
                    "medium",
                    "工具数量偏多，可能增加 Agent 选择负担。",
                    "按 workflow 聚合高频链路，保留少量高信号工具。",
                )
            )
        overlap = self._overlap_count(tool, all_tools)
        if overlap:
            score -= 1
            findings.append(
                AuditFinding(
                    "right_tools.overlap",
                    "medium",
                    "存在名称或职责相近的工具，Agent 可能分心。",
                    "明确边界，或合并为一个支持 mode/filter 的工具。",
                )
            )
        return max(score, 1)

    def _score_namespace(
        self,
        tool: ToolSpec,
        name_counts: Counter[str],
        namespace_counts: Counter[str],
        findings: list[AuditFinding],
    ) -> int:
        score = 5
        if not tool.namespace:
            score -= 2
            findings.append(
                AuditFinding(
                    "namespacing.missing_namespace",
                    "high",
                    "缺少 namespace，工具来源和资源边界不清。",
                    "按 service/resource/workflow 设置 namespace，例如 runtime.trace。",
                )
            )
        if name_counts[tool.name] > 1:
            score -= 2
            findings.append(
                AuditFinding(
                    "namespacing.duplicate_name",
                    "high",
                    "工具名重复，Agent 和 recorder 难以稳定区分。",
                    "使用能表达任务边界的唯一工具名。",
                )
            )
        tokens = set(tool.name.lower().replace("-", "_").split("_"))
        if tokens & self.GENERIC_NAME_TOKENS and len(tokens) <= 2:
            score -= 1
            findings.append(
                AuditFinding(
                    "namespacing.generic_name",
                    "medium",
                    "工具名过于泛化，没有自然表达任务边界。",
                    "把资源和动作写进名称，例如 <domain>_<resource>_<action>。",
                )
            )
        if tool.namespace and namespace_counts[tool.namespace] == 1 and "." not in tool.namespace:
            score -= 0
        return max(score, 1)

    def _score_context(self, tool: ToolSpec, findings: list[AuditFinding]) -> int:
        score = 5
        contract = tool.output_contract
        required_fields = set(contract.get("required_fields", []))
        if not {"summary", "evidence"}.issubset(required_fields):
            score -= 2
            findings.append(
                AuditFinding(
                    "meaningful_context.missing_summary_evidence",
                    "high",
                    "output_contract 没有强制 summary/evidence，返回可能无法支撑判断。",
                    "要求工具返回简明 summary、证据列表和可追踪 technical ID。",
                )
            )
        if "next_action" not in required_fields and not contract.get("next_actions"):
            score -= 1
            findings.append(
                AuditFinding(
                    "meaningful_context.missing_next_action",
                    "medium",
                    "输出没有下一步建议，Agent 可能停在低层观察。",
                    "返回 next_action 或 next_actions，说明下一步应查什么。",
                )
            )
        if not contract.get("technical_ids") and "technical_id" not in required_fields:
            score -= 1
            findings.append(
                AuditFinding(
                    "meaningful_context.missing_technical_id",
                    "medium",
                    "输出没有稳定 technical ID，后续工具调用难以衔接。",
                    "同时提供人类可读 label 和后续调用需要的 ID。",
                )
            )
        if contract.get("raw_fields_allowed", True) is True:
            score -= 1
            findings.append(
                AuditFinding(
                    "meaningful_context.raw_fields_unbounded",
                    "low",
                    "未限制低层技术字段泛滥，可能浪费上下文。",
                    "只返回和诊断/决策相关的字段，把原始详情放到 detailed 模式。",
                )
            )
        return max(score, 1)

    def _score_token_efficiency(self, tool: ToolSpec, findings: list[AuditFinding]) -> int:
        score = 5
        policy = tool.token_policy
        checks = {
            "supports_pagination": "支持 pagination，避免一次返回过多事件。",
            "supports_filtering": "支持 filtering，让 Agent 缩小范围。",
            "supports_range_selection": "支持 range selection，适合 trace/log 工具。",
            "max_output_tokens": "设置 max_output_tokens，避免工具吞掉上下文窗口。",
            "default_limit": "设置合理 default_limit，避免默认返回过宽。",
        }
        for key, message in checks.items():
            if not policy.get(key):
                score -= 1
                findings.append(
                    AuditFinding(
                        f"token_efficiency.missing_{key}",
                        "medium",
                        message.replace("支持", "缺少").replace("设置", "缺少"),
                        message,
                    )
                )
        if not policy.get("truncation_guidance"):
            score -= 1
            findings.append(
                AuditFinding(
                    "token_efficiency.missing_truncation_guidance",
                    "medium",
                    "截断时没有告诉 Agent 如何缩小查询范围。",
                    "返回 truncation_guidance，例如建议 event_id/time_range/filter。",
                )
            )
        if not policy.get("actionable_errors", False):
            score -= 1
            findings.append(
                AuditFinding(
                    "token_efficiency.non_actionable_errors",
                    "medium",
                    "错误响应可能只是裸 traceback。",
                    "错误应包含 cause、retryable、suggested_fix 和可用参数提示。",
                )
            )
        return max(score, 1)

    def _score_prompt_spec(self, tool: ToolSpec, findings: list[AuditFinding]) -> int:
        score = 5
        if len(tool.description) < 80:
            score -= 1
            findings.append(
                AuditFinding(
                    "prompt_spec.short_description",
                    "medium",
                    "description 太短，不像在教新同事如何使用。",
                    "说明工具目的、输入语义、输出解释和典型误用。",
                )
            )
        if not tool.when_to_use or not tool.when_not_to_use:
            score -= 2
            findings.append(
                AuditFinding(
                    "prompt_spec.missing_usage_boundaries",
                    "high",
                    "缺少 when_to_use/when_not_to_use 边界。",
                    "同时写清适用场景和不适用场景，减少误调用。",
                )
            )
        # v0.2 候选 A 新增：when_to_use 与 when_not_to_use 完全相同 → 等于没有边界。
        # 真实 bug：用户复制 when_to_use 到 when_not_to_use 试图"凑齐字段"绕过
        # missing_usage_boundaries 检查，但 Agent 拿到的边界信息为零。
        if (
            tool.when_to_use
            and tool.when_not_to_use
            and tool.when_to_use.strip().lower() == tool.when_not_to_use.strip().lower()
        ):
            score -= 2
            findings.append(
                AuditFinding(
                    "prompt_spec.usage_boundary_duplicated",
                    "high",
                    "when_to_use 与 when_not_to_use 文本完全相同，等于没有边界。",
                    "重写 when_not_to_use，明确"
                    "在哪些场景该工具反而是错误选择（输入前提缺失 / 资源类型不匹配 / "
                    "需要先调用其它工具等）。",
                    why_it_matters=(
                        "Agent 同时读取 when_to_use 和 when_not_to_use 来决定是否"
                        "选用此工具。两段文本相同时 Agent 拿到的有效边界信息为零，"
                        "等于工具自己声称'任何场景都用我'——这往往是用户复制粘贴"
                        "为了'凑齐字段'绕过 missing_usage_boundaries 的真实痕迹。"
                    ),
                )
            )
        # v0.2 候选 A 新增：when_to_use / when_not_to_use 过短（< 30 字符）。
        # 经验阈值：少于 30 字符基本只能写一句"Use it." / "Don't use it."，无法
        # 表达触发条件或反例。命中即 medium。
        for label, text in (
            ("when_to_use", tool.when_to_use),
            ("when_not_to_use", tool.when_not_to_use),
        ):
            if text and len(text.strip()) < 30:
                score -= 1
                findings.append(
                    AuditFinding(
                        "prompt_spec.shallow_usage_boundary",
                        "medium",
                        f"{label} 过短（<30 字符），表达不出真实触发/排除条件。",
                        f"补充 {label}：写出输入前提、典型用户问题或反例场景。",
                    )
                )
                break  # 同一工具只报一次该 finding，避免噪音
        if not tool.input_schema.get("properties"):
            score -= 1
            findings.append(
                AuditFinding(
                    "prompt_spec.weak_input_schema",
                    "high",
                    "input_schema 不严格，参数语义不稳定。",
                    "使用 JSON Schema properties/required 描述参数。",
                )
            )
        # v0.2 候选 A 新增：input_schema.properties 缺 response_format。
        # Anthropic 工具设计指南建议工具暴露 response_format（concise / detailed 等）
        # 让 Agent 主动控制 token 使用。仅在 properties 非空但缺 response_format 时报，
        # 避免与 weak_input_schema 重复。
        properties = tool.input_schema.get("properties") or {}
        if properties and "response_format" not in properties:
            score -= 1
            findings.append(
                AuditFinding(
                    "prompt_spec.missing_response_format",
                    "medium",
                    "input_schema.properties 缺 response_format 参数，"
                    "Agent 无法主动控制返回粒度（concise / detailed），"
                    "在长上下文里容易踩 token 预算。",
                    "在 input_schema.properties 增加 response_format 枚举字段，"
                    "并在 output_contract 声明对应的 response_formats。",
                )
            )
        if not tool.output_contract:
            score -= 1
            findings.append(
                AuditFinding(
                    "prompt_spec.missing_output_contract",
                    "high",
                    "缺少 output_contract，Agent 无法预期返回结构。",
                    "声明 required_fields、evidence 格式、ID 字段和错误结构。",
                )
            )
        if "destructive" not in tool.side_effects and "open_world_access" not in tool.side_effects:
            score -= 1
            findings.append(
                AuditFinding(
                    "prompt_spec.missing_side_effect_labels",
                    "medium",
                    "side_effects 没有标注 destructive/open_world_access。",
                    "明确副作用等级，供 runner/judge 检查证据前禁止修改。",
                )
            )
        return max(score, 1)

    def _overlap_count(self, tool: ToolSpec, all_tools: list[ToolSpec]) -> int:
        tokens = set(tool.name.lower().replace("-", "_").split("_"))
        count = 0
        for other in all_tools:
            if other is tool:
                continue
            other_tokens = set(other.name.lower().replace("-", "_").split("_"))
            min_shared = max(2, min(len(tokens), len(other_tokens)) - 1)
            if tokens and len(tokens & other_tokens) >= min_shared:
                count += 1
        return count

    def _semantic_overlap_pairs(self, tools: list[ToolSpec]) -> dict[str, list[str]]:
        """计算"description + when_to_use 词袋"两两 Jaccard 重叠。

        负责什么：
        - 输入一组 ToolSpec，输出 ``{tool_name: [overlap_qualified_names...]}``，
          供 audit() 注入到每个工具的 audit_tool 调用。
        - 用 ``_OVERLAP_STOPWORDS`` 过滤虚词，只保留携带职责语义的实词；阈值
          ``_OVERLAP_JACCARD_THRESHOLD = 0.4`` 的取值原因写在常量注释里。

        不负责什么：
        - 不做语言学/同义词归一（"trace" vs "log" 不会被归一），所以**无法识别**
          "同义不同词"的隐蔽诱饵——这是 deterministic 启发式的根本限制，已记
          docs/ROADMAP.md，由 tests/test_tool_design_audit_subtle_decoy_xfail.py
          用 strict xfail 钉住根因，转正条件需要 transcript / LLM judge。
        - 不读工具源码，不调用工具——只看 spec 文本。

        为什么写在 audit() 里预计算而不是 audit_tool 里逐工具算：
        - 重叠是**关系**属性；放对层级方便未来替换实现（例如换成 LLM embedding）
          而不影响调用方。
        - 避免 O(n^2) 重复扫描。

        artifact 排查路径：``audit_tools.json`` → 每个工具的 findings 里若出现
        ``right_tools.semantic_overlap``，``message`` 末尾会列出与之重叠的工具
        qualified_name。
        """

        def bag(text: str) -> set[str]:
            cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in text.lower())
            return {
                token
                for token in cleaned.split()
                if len(token) > 2 and token not in self._OVERLAP_STOPWORDS
            }

        bags = {tool.name: bag(f"{tool.description} {tool.when_to_use}") for tool in tools}
        pairs: dict[str, list[str]] = {tool.name: [] for tool in tools}
        for i, a in enumerate(tools):
            for b in tools[i + 1:]:
                ba, bb = bags[a.name], bags[b.name]
                if not ba or not bb:
                    continue
                jaccard = len(ba & bb) / len(ba | bb)
                if jaccard >= self._OVERLAP_JACCARD_THRESHOLD:
                    pairs[a.name].append(b.qualified_name)
                    pairs[b.name].append(a.qualified_name)
        return pairs

    def _average(self, values: Any) -> float:
        values = list(values)
        if not values:
            return 0.0
        return round(sum(values) / len(values), 2)
