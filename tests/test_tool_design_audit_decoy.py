"""Tool Design Audit 语义诱饵 — 候选 A 转正后的红线测试。

历史背景：
本测试原为 ``test_tool_design_audit_decoy_xfail.py``，用 strict xfail 钉住
"ToolDesignAuditor 当前只做 structural/completeness 检查，对字段齐全但语义上是诱饵
（与主工具职责重叠、声称一步给出 root cause 的浅封装）仍判 5.0 满分"这一根因 gap。

**候选 A 转正（commit feat: harden tool-design audit semantic signals）后**，
ToolDesignAuditor 已能识别两类典型诱饵信号：
  - 浅封装捷径话术（``right_tools.shallow_wrapper``）：工具描述含"single-step
    shortcut / quickly returns / you do not need to call other tools"等关键词；
  - 跨工具语义重叠（``right_tools.semantic_overlap``）：description + when_to_use
    词袋 Jaccard 超过阈值（默认 0.4）。

**仍未解决（保留 xfail 钉根因）**：
更隐蔽的诱饵——字段齐全、没有捷径话术、用完全不同的词汇描述同一职责——deterministic
启发式无法识别，需要 transcript-based 或 LLM judge 才能真正判断"这两个工具语义上是
不是同一件事"。该 gap 由独立的 ``tests/test_tool_design_audit_subtle_decoy_xfail.py``
继续用 strict xfail 钉住，转正条件已写入 docs/ROADMAP.md。

测试纪律：
- 本文件断言**不允许放宽**——如果未来某次改动让诱饵 finding 消失，必须先找根因，
  绝不能把断言改弱。
- 反向断言（``test_well_formed_distinct_tools_do_not_trigger_semantic_finding``）
  保护"合理的两条不同职责工具"不被误报，是反补丁保险。
"""

from __future__ import annotations

from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.config.tool_spec import ToolSpec


def _well_formed(name: str, namespace: str, description: str, when_to_use: str) -> ToolSpec:
    """构造一个**字段完美**的 ToolSpec。

    所有结构性字段都写到位（input_schema、output_contract、token_policy、side_effects、
    executor），让当前 auditor 的所有结构检查都通过。差异只出现在 description /
    when_to_use 的语义上：诱饵工具会声称"一步到位"，并与主工具职责重叠。
    这样测试聚焦在"语义信号检测"这一根因上，而不是被字段缺失噪声混淆。
    """

    return ToolSpec(
        name=name,
        namespace=namespace,
        version="0.1",
        description=description,
        when_to_use=when_to_use,
        when_not_to_use="Do not use for purely visual layout questions.",
        input_schema={
            "type": "object",
            "required": ["trace_id"],
            "properties": {
                "trace_id": {"type": "string"},
                "response_format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                    "default": "concise",
                },
            },
        },
        output_contract={
            "required_fields": ["summary", "evidence", "next_action", "technical_id"],
            "technical_ids": True,
            "raw_fields_allowed": False,
            "response_formats": ["concise", "detailed"],
            "error_shape": ["summary", "cause", "retryable", "suggested_fix"],
        },
        token_policy={
            "supports_pagination": True,
            "supports_filtering": True,
            "supports_range_selection": True,
            "max_output_tokens": 800,
            "default_limit": 10,
            "truncation_guidance": "Narrow by trace_id.",
            "actionable_errors": True,
        },
        side_effects={"destructive": False, "open_world_access": False},
        executor={"type": "python", "module": "demo", "function": name},
    )


def test_audit_should_flag_semantic_decoy_tool_overlapping_with_primary():
    """主工具 + 诱饵工具同时存在时，auditor 必须 flag 诱饵。

    诱饵特征：
    - 浅封装捷径话术（"single-step shortcut" / "quickly returns" / "without
      inspecting" / "you do not need to call"）；
    - 与主工具的 description / when_to_use 高度重叠；
    - 字段齐全（不会被 missing_* 类 finding 拦下）。

    auditor 必须给出至少一条 ``right_tools.shallow_wrapper`` 或
    ``right_tools.semantic_overlap`` 类 high-severity finding，且顶层 summary
    的 ``warnings`` 必须包含 ``semantic_risk_detected``——否则用户只看 average_score
    会误以为工具设计合格。
    """

    primary = _well_formed(
        name="primary_trace_event_chain",
        namespace="primary.trace",
        description=(
            "Trace a runtime incident through ordered event ids and boundary transitions. "
            "Use this when a user reports a runtime behavior mismatch and the next decision "
            "depends on causal evidence rather than a visual snapshot."
        ),
        when_to_use=(
            "Use first for suspected runtime, checkpoint, or input-boundary incidents where "
            "the user asks for root cause and the trace_id is available."
        ),
    )
    decoy = _well_formed(
        name="primary_quick_root_cause",
        namespace="primary.quick",
        description=(
            "Quickly returns a likely root cause guess from a runtime trace_id without "
            "inspecting the underlying event chain or checkpoint state. Designed to give "
            "agents a single-step shortcut for any runtime incident question."
        ),
        when_to_use=(
            "Use first for any runtime, checkpoint, or input-boundary issue when a trace_id "
            "is available; you do not need to call other primary tools."
        ),
    )

    result = ToolDesignAuditor().audit([primary, decoy])
    decoy_findings = next(item for item in result["tools"] if item["tool_name"] == decoy.name)
    rule_ids = {f["rule_id"] for f in decoy_findings["findings"]}

    assert any(
        rule_id.startswith("right_tools.semantic_decoy")
        or rule_id.startswith("right_tools.semantic_overlap")
        or rule_id.startswith("right_tools.shallow_wrapper")
        or rule_id.startswith("right_tools.overlap")
        for rule_id in rule_ids
    ), (
        "Tool Design Audit 必须把字段齐全的语义诱饵 flag 为 shallow_wrapper / "
        "semantic_overlap；如果该断言失败，先去 ToolDesignAuditor 找根因，不要"
        "放宽断言。"
    )

    # 顶层 warnings 必须显式披露 semantic_risk，避免用户只看 average_score 失误。
    warnings = result["summary"]["warnings"]
    assert any("semantic_risk_detected" in w for w in warnings), warnings
    # signal_quality 必须保持 deterministic_heuristic——不允许被偷偷升级。
    assert result["summary"]["signal_quality"] == "deterministic_heuristic"


def test_well_formed_distinct_tools_do_not_trigger_semantic_finding():
    """反向断言（反补丁保险）：两条职责真正分明、字段都齐全的工具不能被误报
    shallow_wrapper / semantic_overlap。

    模拟的真实 bug：阈值 / stopword 集合调得太敏感时，所有英文工具都会被报"重叠"，
    用户会失去对这条 finding 的信任。本断言钉住"合理工具不被误伤"这条根因边界。
    """

    tool_a = _well_formed(
        name="payments_invoice_lookup",
        namespace="payments.invoice",
        description=(
            "Look up an invoice by id and return summary, line items, and the customer "
            "billing contact for downstream payment reconciliation workflows."
        ),
        when_to_use=(
            "Use when the user asks about an invoice status, line items, or the billing "
            "contact email; requires invoice_id."
        ),
    )
    tool_b = _well_formed(
        name="shipping_address_validator",
        namespace="shipping.address",
        description=(
            "Validate a customer shipping address against the carrier registry and return "
            "normalized fields plus deliverability score."
        ),
        when_to_use=(
            "Use when the user submits a new address or wants to confirm whether a stored "
            "address is deliverable; requires address payload."
        ),
    )
    result = ToolDesignAuditor().audit([tool_a, tool_b])
    for item in result["tools"]:
        rule_ids = {f["rule_id"] for f in item["findings"]}
        assert "right_tools.shallow_wrapper" not in rule_ids, item["tool_name"]
        assert "right_tools.semantic_overlap" not in rule_ids, item["tool_name"]
    warnings = result["summary"]["warnings"]
    assert not any("semantic_risk_detected" in w for w in warnings), warnings

