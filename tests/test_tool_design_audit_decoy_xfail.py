"""Tool Design Audit 语义诱饵 gap 的红线测试。

为什么这个测试存在 / 暴露什么根因：
=====================================
Anthropic 的 *Writing effective tools for agents* 在 "Choosing the right tools
for agents" 一节强调，工具设计要避免与已有工具职责重叠、避免"看起来万能但其实
是浅封装"的工具——因为 Agent 会被这种工具诱导走错路（一上来就调那个声称能
"一步给出 root cause"的工具，跳过真正的 trace 分析）。

当前 ``ToolDesignAuditor`` 只做 **结构 / 字段完备性** 检查（namespace 是否存在、
output_contract 是否声明 summary/evidence、token_policy 是否声明分页等），它**不
读工具源码**，也**不读真实工具响应**。这意味着：一个字段写得无懈可击但语义上是
诱饵的工具（例如声称"能从 trace_id 一步给出 root cause"，且与已有 trace 工具
职责重叠），auditor 仍会判 5.0 满分零 finding。

**这就是这条 xfail 暴露的真实根因**：v0.1 的 audit 能力只能判"工具规范填了没"，
不能判"工具语义是不是在骗 Agent"。这不是"加几条规则就能补"的小漏洞，而是 v0.1
audit 框架的能力边界——必须等 v0.2 引入语义信号 / transcript 样本 / LLM judge
才能真正闭环。

为什么是 strict xfail 而不是别的形式：
=====================================
``strict=True`` 强制：一旦未来某次改动让 auditor 真的能识别这个诱饵，xfail 会
变成 XPASS 让 CI 失败，**强制**我们把这个测试改成普通 passing 测试并同步更新
``docs/ROADMAP.md`` 的转正条件——这是把"能力提升"和"文档更新"绑死的根因型护栏。

为什么不能删除 / 弱化这个测试（v0.1 期间硬约束）：
- 删测试 = 删除 v0.1 已知能力边界的可审计标记；
- 改 ``strict=False`` = 允许 audit 静默"假装能识别诱饵"而不被发现；
- 把断言改宽（例如改成"只要有任何 finding 就过"）= 用 hack 假装解决，等于让
  Agent 在生产里继续被诱饵工具骗；
- 把 reason 文案改虚（例如"未来再说"）= 失去对转正条件的可审计追溯。

以上任何一种都直接违反 ROADMAP §"v0.2 候选 A"与 §3 "v0.2/tool-design-semantic-
signal 分支归档决议"中明确的 v0.1 release 期间硬约束。

与 v0.2 工作区分支的精确对应关系：
=====================================
- 候选 A 实现已存在于本地分支 ``v0.2/tool-design-semantic-signal``（HEAD
  ``7cac829`` ``feat: prototype tool design semantic signals``）；该分支**仅本地**
  存在，未推 origin，未 merge 到 main；
- 该分支正是这条 xfail 的"假想转正候选实现"；
- v0.1 release 期间禁止任何形式的合入 / push / cherry-pick 该分支（详见
  ``docs/ROADMAP.md`` §"v0.1 当前 blocking issue" §3 归档决议）；
- 一旦该分支（或等价语义能力）合入 main，本测试预期 XPASS，必须同步：
  1. 删 ``@pytest.mark.xfail`` 装饰器 / 改成普通 passing 测试；
  2. 更新 ``docs/ROADMAP.md`` §3 把状态从"归档"改为"已合入 v0.2"；
  3. 把对应的 ``signal_quality`` 维度 / transcript 样本 / LLM judge 来源
     在测试 docstring 里注明。

转正所需的真实信号源（任一满足）：
- transcript-based 语义级 audit（读 Agent 真实调用链，识别"跳过主工具直接走捷径"
  的模式）；
- 真实 tool response 样本驱动的 contract drift 检测（看返回里有没有 evidence /
  technical_id / next_action 等 grounding 字段，浅封装通常都没有）；
- 新增 ``signal_quality`` 维度对工具职责重叠 / 浅封装做严格判定（候选 A 路线）；
- LLM judge 对 description / when_to_use 的语义比对（v0.3+ 真实 LLM 接入后）。
"""

from __future__ import annotations

import pytest

from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.config.tool_spec import ToolSpec


def _well_formed(name: str, namespace: str, description: str, when_to_use: str) -> ToolSpec:
    """构造一个**字段完美但语义可疑**的 ToolSpec。

    所有结构性字段都写到位（input_schema、output_contract、token_policy、side_effects、
    executor），让当前 auditor 的所有结构检查都通过。差异只出现在 description /
    when_to_use 的语义上：诱饵工具会声称“一步到位”，并与主工具职责重叠。
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Anthropic 'Choosing the right tools for agents' gap：当前 Tool Design Audit 只做 "
        "structural/completeness 检查，对字段齐全但语义上是诱饵（与主工具职责重叠、声称一步"
        "给出 root cause 的浅封装）仍判 5.0 满分。转正条件：引入 transcript-based 或真实 tool "
        "response 样本驱动的语义级 audit，或新增 signal_quality 维度对职责重叠/低抽象层做更严格"
        "判定，详见 docs/ROADMAP.md。当前 MVP 不允许通过放宽断言假装解决。"
    ),
)
def test_audit_should_flag_semantic_decoy_tool_overlapping_with_primary():
    """主工具 + 诱饵工具同时存在时，auditor 应该 flag 诱饵——当前做不到。"""

    primary = _well_formed(
        name="runtime_trace_event_chain",
        namespace="runtime.trace",
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
        name="runtime_quick_root_cause",
        namespace="runtime.quick",
        description=(
            "Quickly returns a likely root cause guess from a runtime trace_id without "
            "inspecting the underlying event chain or checkpoint state. Designed to give "
            "agents a single-step shortcut for any runtime incident question."
        ),
        when_to_use=(
            "Use first for any runtime, checkpoint, or input-boundary issue when a trace_id "
            "is available; you do not need to call other runtime tools."
        ),
    )

    result = ToolDesignAuditor().audit([primary, decoy])
    decoy_findings = next(item for item in result["tools"] if item["tool_name"] == decoy.name)
    rule_ids = {f["rule_id"] for f in decoy_findings["findings"]}

    # 期望 auditor 把诱饵 flag 为：与已有工具语义重叠 / 浅封装 / 单步声称过强。
    assert any(
        rule_id.startswith("right_tools.semantic_decoy")
        or rule_id.startswith("right_tools.overlap")
        or rule_id.startswith("right_tools.shallow_wrapper")
        for rule_id in rule_ids
    ), (
        "Tool Design Audit 当前不能识别语义诱饵工具——这是已知 gap。"
        "如果某次改动让此断言通过，xfail strict=True 会触发 XPASS 让 CI 失败，"
        "请把这个测试改为普通 passing 测试并同步更新 docs/ROADMAP.md 的转正条件。"
    )
