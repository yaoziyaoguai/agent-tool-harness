"""ToolDesignAuditor 候选 A 新增能力的正向 + 反向测试。

为什么单独成文件：
- 这一组测试钉的是"字段齐全 ≠ 工具设计合格"这条根因边界——它与 decoy 红线测试
  互补：那一组钉"语义诱饵能否被识别"，本组钉"字段层伪装能否被识别"。
- 每个测试都同时含**正向断言**（坏例必须出 finding）和**反向断言**（好例不能误报），
  这是反补丁保险——避免阈值/关键词调得太敏感导致用户失去对 finding 的信任。
- fake/mock 边界：本文件只用最小 ToolSpec 内存对象，不调用任何真实工具、不读
  examples/runtime_debug 之外的项目。

测试纪律（与 docs/TESTING.md 同步）：
- 不允许通过放宽断言追求绿——如果断言失败必须修 ToolDesignAuditor 实现。
- signal_quality 必须永远是 ``deterministic_heuristic``——不允许被偷偷升级为
  production-grade，否则用户会误以为当前 audit 已经是语义级证明。
"""

from __future__ import annotations

from typing import Any

from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.config.tool_spec import ToolSpec


def _make(**overrides: Any) -> ToolSpec:
    """生成字段齐全的最小 ToolSpec，便于测试只针对一个变量做反例。"""

    base: dict[str, Any] = {
        "name": "alpha_resource_action",
        "namespace": "alpha.resource",
        "version": "0.1",
        "description": (
            "Look up a customer billing invoice by its invoice id and return summary "
            "plus the billing contact information for downstream reconciliation."
        ),
        "when_to_use": "Use when the user asks about an invoice status or billing contact.",
        "when_not_to_use": "Do not use for shipping address questions.",
        "input_schema": {
            "type": "object",
            "required": ["invoice_id"],
            "properties": {
                "invoice_id": {"type": "string"},
                "response_format": {
                    "type": "string",
                    "enum": ["concise", "detailed"],
                },
            },
        },
        "output_contract": {
            "required_fields": ["summary", "evidence", "next_action", "technical_id"],
            "raw_fields_allowed": False,
        },
        "token_policy": {
            "supports_pagination": True,
            "supports_filtering": True,
            "supports_range_selection": True,
            "max_output_tokens": 800,
            "default_limit": 10,
            "truncation_guidance": "Narrow by invoice_id.",
            "actionable_errors": True,
        },
        "side_effects": {"destructive": False, "open_world_access": False},
        "executor": {"type": "python", "module": "demo", "function": "alpha"},
    }
    base.update(overrides)
    return ToolSpec(**base)


# ---------------------------------------------------------------------------
# 1) signal_quality 披露
# ---------------------------------------------------------------------------


def test_audit_summary_discloses_deterministic_heuristic_signal_quality():
    """模拟的真实 bug：用户拿到 audit_tools.json，average_score=4.8，没有 finding，
    就以为工具设计已经"过审"。本断言钉住顶层必须显式写 ``signal_quality`` 与 note，
    告诉用户当前是 deterministic 启发式而非语义级证明。
    """

    result = ToolDesignAuditor().audit([_make()])
    assert result["summary"]["signal_quality"] == "deterministic_heuristic"
    note = result["summary"]["signal_quality_note"]
    assert "deterministic" in note.lower()
    # 必须明确写出"无法识别"的边界，避免用户误读
    assert "无法" in note or "cannot" in note.lower() or "needs" in note.lower()


# ---------------------------------------------------------------------------
# 2) 浅封装捷径话术
# ---------------------------------------------------------------------------


def test_audit_flags_shallow_wrapper_phrases():
    """诱饵 description 含 "single-step shortcut" 等捷径话术 → 必须 high finding。"""

    tool = _make(
        description=(
            "Quickly returns a likely root cause guess from a runtime trace_id without "
            "inspecting the underlying event chain. A single-step shortcut for incident "
            "questions."
        ),
    )
    result = ToolDesignAuditor().audit([tool])
    rule_ids = {f["rule_id"] for f in result["tools"][0]["findings"]}
    assert "right_tools.shallow_wrapper" in rule_ids
    # 顶层 warnings 必须暴露 semantic_risk
    assert any("semantic_risk_detected" in w for w in result["summary"]["warnings"])


def test_audit_does_not_flag_normal_description_as_shallow_wrapper():
    """反向断言：合理 description 不能被误报浅封装。"""

    result = ToolDesignAuditor().audit([_make()])
    rule_ids = {f["rule_id"] for f in result["tools"][0]["findings"]}
    assert "right_tools.shallow_wrapper" not in rule_ids


# ---------------------------------------------------------------------------
# 3) 跨工具语义重叠
# ---------------------------------------------------------------------------


def test_audit_flags_semantic_overlap_between_two_similar_tools():
    """两个工具 description / when_to_use 高度重合（Jaccard ≥ 0.4）→ 双方都报。

    设计动机：单边只罚一方会让审核者误以为另一方"没问题"——所以检测必须双向写入。
    """

    a = _make(
        name="alpha_invoice_lookup",
        namespace="alpha.invoice",
        description=(
            "Lookup invoice billing summary contact reconciliation downstream "
            "customer payment workflow status."
        ),
        when_to_use="Lookup invoice billing summary contact downstream reconciliation status.",
    )
    b = _make(
        name="beta_invoice_lookup",
        namespace="beta.invoice",
        description=(
            "Lookup invoice billing summary contact reconciliation downstream "
            "customer payment workflow status duplicate."
        ),
        when_to_use="Lookup invoice billing summary contact downstream reconciliation status.",
    )
    result = ToolDesignAuditor().audit([a, b])
    for item in result["tools"]:
        rule_ids = {f["rule_id"] for f in item["findings"]}
        assert "right_tools.semantic_overlap" in rule_ids, item["tool_name"]


def test_audit_does_not_flag_distinct_tools_as_semantic_overlap():
    """反向断言（反补丁保险）：两条职责真正分明的工具不能被误报。"""

    a = _make(
        name="payments_invoice_lookup",
        namespace="payments.invoice",
        description=(
            "Look up a customer billing invoice by its invoice id and return summary "
            "plus the billing contact information for downstream reconciliation."
        ),
        when_to_use="Use when the user asks about an invoice status or billing contact.",
    )
    b = _make(
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
        when_not_to_use="Do not use for invoice or billing questions.",
    )
    result = ToolDesignAuditor().audit([a, b])
    for item in result["tools"]:
        rule_ids = {f["rule_id"] for f in item["findings"]}
        assert "right_tools.semantic_overlap" not in rule_ids, item["tool_name"]


# ---------------------------------------------------------------------------
# 4) 边界重复 / 过短
# ---------------------------------------------------------------------------


def test_audit_flags_duplicate_when_to_use_and_when_not_to_use():
    """when_to_use 与 when_not_to_use 文本完全相同 → 等于没有边界 → high finding。"""

    same = "Use for any runtime incident question with a trace_id."
    tool = _make(when_to_use=same, when_not_to_use=same)
    result = ToolDesignAuditor().audit([tool])
    rule_ids = {f["rule_id"] for f in result["tools"][0]["findings"]}
    assert "prompt_spec.usage_boundary_duplicated" in rule_ids


def test_audit_flags_shallow_when_to_use_boundary():
    """when_to_use 或 when_not_to_use 过短（<30 字符）→ medium finding。"""

    tool = _make(when_to_use="Use it.", when_not_to_use="Do not use it for layout.")
    result = ToolDesignAuditor().audit([tool])
    rule_ids = {f["rule_id"] for f in result["tools"][0]["findings"]}
    assert "prompt_spec.shallow_usage_boundary" in rule_ids


# ---------------------------------------------------------------------------
# 5) 缺 response_format
# ---------------------------------------------------------------------------


def test_audit_flags_missing_response_format_in_input_schema():
    """input_schema.properties 缺 response_format → medium finding。"""

    tool = _make(
        input_schema={
            "type": "object",
            "required": ["invoice_id"],
            "properties": {"invoice_id": {"type": "string"}},
        },
    )
    result = ToolDesignAuditor().audit([tool])
    rule_ids = {f["rule_id"] for f in result["tools"][0]["findings"]}
    assert "prompt_spec.missing_response_format" in rule_ids


def test_audit_does_not_flag_response_format_when_present():
    """反向断言：含 response_format 时不能误报。"""

    result = ToolDesignAuditor().audit([_make()])
    rule_ids = {f["rule_id"] for f in result["tools"][0]["findings"]}
    assert "prompt_spec.missing_response_format" not in rule_ids


# ---------------------------------------------------------------------------
# 6) 扩充的 generic name token
# ---------------------------------------------------------------------------


def test_audit_flags_generic_name_with_check_token():
    """工具名只用 ``check`` + 一个泛化词 → generic_name finding。

    模拟的真实 bug：用户写一个 ``checker`` 工具，名字毫无信息量，Agent 不知道
    它解决什么资源/工作流——这是接入期最常见的命名坑之一。
    """

    tool = _make(name="check_data", namespace="domain.x")
    result = ToolDesignAuditor().audit([tool])
    rule_ids = {f["rule_id"] for f in result["tools"][0]["findings"]}
    assert "namespacing.generic_name" in rule_ids


def test_audit_does_not_flag_specific_name_with_check_token():
    """反向断言：``check`` 出现在更具体的名字里（token 集合 > 2）不应误报。"""

    tool = _make(name="payments_invoice_check_status", namespace="payments.invoice")
    result = ToolDesignAuditor().audit([tool])
    rule_ids = {f["rule_id"] for f in result["tools"][0]["findings"]}
    assert "namespacing.generic_name" not in rule_ids


# ---------------------------------------------------------------------------
# 7) demo 真实 spec 不被误报（端到端反补丁保险）
# ---------------------------------------------------------------------------


def test_runtime_debug_demo_spec_does_not_trigger_semantic_findings():
    """examples/runtime_debug 的三个工具是手工精心写的真实 spec——必须不被新增
    findings 误报；否则说明阈值调得太敏感，用户体验会被拖坏。
    """

    from agent_tool_harness.config.loader import load_tools

    tools = load_tools("examples/runtime_debug/tools.yaml")
    result = ToolDesignAuditor().audit(tools)
    for item in result["tools"]:
        rule_ids = {f["rule_id"] for f in item["findings"]}
        assert "right_tools.shallow_wrapper" not in rule_ids, item["tool_name"]
        assert "right_tools.semantic_overlap" not in rule_ids, item["tool_name"]
        assert "prompt_spec.usage_boundary_duplicated" not in rule_ids, item["tool_name"]
        assert "prompt_spec.missing_response_format" not in rule_ids, item["tool_name"]
    assert not any(
        "semantic_risk_detected" in w for w in result["summary"]["warnings"]
    ), result["summary"]["warnings"]
