"""Tool Design Audit 隐蔽语义诱饵 — 仍未解决的根因（保留 strict xfail）。

候选 A 让 ToolDesignAuditor 能识别两类典型诱饵：
  - shallow_wrapper：捷径话术（"single-step / quickly / without inspecting / "
    "you do not need to call"）；
  - semantic_overlap：description + when_to_use 词袋 Jaccard ≥ 0.4。

但下面这种**隐蔽诱饵**仍然无法识别，本测试用 strict xfail 钉住根因：
  - 字段齐全（不会被 missing_* 拦下）；
  - **没有任何捷径话术**（不会触发 shallow_wrapper）；
  - 用**完全不同的词汇**描述与主工具同一职责（词袋几乎不重合，Jaccard 远低于
    阈值，不会触发 semantic_overlap）；
  - 但语义上 Agent 调用它会被诱导跳过真正的诊断工具。

为什么必须保留 strict xfail：
- 这是 deterministic 启发式的根本限制——靠词袋无法识别"职责相同、词汇不同"。
- 如果未来用 transcript-based 真实样本 / LLM judge 让 auditor 真能识别这种诱饵，
  strict=True 会让本测试 XPASS 导致 CI 失败，强制把测试转正并同步更新 ROADMAP。
- **不允许通过放宽断言假装解决**——例如改成"任何工具都报 needs_review"那是补丁，
  不是根因修复。

转正条件（写入 docs/ROADMAP.md）：
1. 引入 transcript-based 工具调用样本，对每个工具看 Agent 是否在错误场景被诱导
   选用——这才是诱饵的真实信号；或
2. 接入 LLM judge 对工具职责做语义 cluster，识别"职责相同但词汇不同"的对子。
"""

from __future__ import annotations

import pytest

from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.config.tool_spec import ToolSpec


def _well_formed(name: str, namespace: str, description: str, when_to_use: str) -> ToolSpec:
    """字段齐全的 ToolSpec 工厂（与 test_tool_design_audit_decoy.py 保持一致）。"""

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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Deterministic 启发式的根本限制：当诱饵工具用完全不同的词汇描述与主工具同一"
        "职责（词袋 Jaccard 远低于 0.4 阈值，且不含捷径话术），shallow_wrapper / "
        "semantic_overlap 都不会触发，auditor 仍判 5.0 满分。转正条件：引入 "
        "transcript-based 工具调用样本观测 Agent 是否在错误场景被诱导，或接入 LLM "
        "judge 做职责语义 cluster。详见 docs/ROADMAP.md。当前 MVP 不允许通过放宽"
        "断言假装解决。"
    ),
)
def test_audit_should_flag_subtle_semantic_decoy_with_disjoint_vocabulary():
    """主工具讲 'runtime trace event chain'，诱饵讲 'malfunction inspection
    snapshot'——意思相同但词汇不重合，deterministic 检测应失效。"""

    primary = _well_formed(
        name="alpha_runtime_trace_chain",
        namespace="alpha.runtime",
        description=(
            "Trace a runtime incident through ordered event ids and boundary transitions. "
            "Useful when the next decision depends on causal evidence."
        ),
        when_to_use=(
            "Use for runtime incident root cause questions when trace_id is available."
        ),
    )
    # 诱饵：用完全不同的词汇（malfunction / inspection / snapshot / outcome）
    # 描述同一职责，且不含任何捷径话术。
    subtle_decoy = _well_formed(
        name="beta_malfunction_inspector",
        namespace="beta.malfunction",
        description=(
            "Inspect malfunction artifacts and produce an outcome diagnosis snapshot. "
            "The diagnosis covers the failing pipeline stage and proposed remediation."
        ),
        when_to_use=(
            "Apply when an incident report is filed and the diagnosis pipeline must "
            "produce a remediation snapshot identifier."
        ),
    )

    result = ToolDesignAuditor().audit([primary, subtle_decoy])
    decoy_findings = next(
        item for item in result["tools"] if item["tool_name"] == subtle_decoy.name
    )
    rule_ids = {f["rule_id"] for f in decoy_findings["findings"]}
    assert any(
        rule_id.startswith("right_tools.semantic_decoy")
        or rule_id.startswith("right_tools.semantic_overlap")
        or rule_id.startswith("right_tools.shallow_wrapper")
        for rule_id in rule_ids
    ), (
        "deterministic 启发式无法识别这种隐蔽诱饵——这是已知根本限制。如果某次改动"
        "让此断言通过，strict=True 会让 CI 失败，请把测试转正并同步更新 ROADMAP。"
    )
