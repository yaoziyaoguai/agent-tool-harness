"""Tool-use quality LLM judge rubric definitions.

架构边界
--------
- **负责**：定义 D4/D5 LLM advisory 各维度的 rubric 文本、evidence 提取规则、
  结构化 prompt builder。所有 rubric 构建 zero-network, deterministic。
- **不负责**：不调用 LLM、不读取 .env、不生成 JudgeFinding（那是 judge provider 的事）、
  不修改 RuleFinding / EvaluationResult / tool spec、不生成 ReviewDecision。
- **为什么独立于 llm_judge.py**：llm_judge.py 是真实 LLM transport 调用，
  本模块只定义 rubric 骨架和 prompt 结构，供 fake 和 real provider 共用。
- **与 JudgeFinding 的关系**：rubric 文本填充到 JudgeFinding.rubric 字段，
  为 human reviewer 提供"LLM 按什么标准评的"透明度。

Rubric 覆盖维度（6 个，全部 advisory only）
----------------------------------------------
D4 (Tool Ergonomics LLM advisory):
1. tool_choice_reasonableness  — agent 选工具是否合理（基于名字/描述重叠度）
2. tool_too_low_level           — 工具是否只是 API wrapper，缺乏 agent-facing purpose
3. frequently_chained_tools     — 连续调用的工具对/链，可能应合并
4. missing_domain_tool          — 工具链组合缺少对应的高层领域工具

D5 (Tool Response Quality LLM advisory):
5. missing_fields_for_next_call — 工具返回缺少下一步调用需要的字段
6. final_answer_faithfulness    — final_answer 是否忠实基于 tool_results 数据

全部 advisory only: 不影响 EvaluationResult.passed，不自动生成 ReviewDecision。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.core_contract import ExecutionTrace

# ---------------------------------------------------------------------------
# Rubric dimension definition
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RubricDimension:
    """一条 LLM judge rubric 维度定义。

    每条 rubric 告诉 LLM judge "应该从什么角度、按什么标准评判"。
    rubric_text 是可直接注入 system prompt 的评判指令。
    """

    dimension_id: str
    label: str
    source_module: str  # "D4" | "D5"
    rubric_text: str
    evidence_sources: tuple[str, ...]  # 从哪些 evidence 字段提取数据
    severity_hint: str = "info"  # advisory severity for generated JudgeFinding


# ---------------------------------------------------------------------------
# D4 (Tool Ergonomics) rubric dimensions
# ---------------------------------------------------------------------------

RUBRIC_TOOL_CHOICE_REASONABLENESS = RubricDimension(
    dimension_id="tool_choice_reasonableness",
    label="Tool choice reasonableness",
    source_module="D4",
    rubric_text=(
        "Evaluate whether the agent selected the most appropriate tool for each"
        " user intent step. Consider: (a) are there multiple tools with overlapping"
        " names or descriptions that could confuse the agent? (b) did the agent"
        " select a lower-level tool when a higher-level domain tool was available?"
        " (c) did the agent skip calling a tool that the evidence suggests was needed?"
        " Provide a rationale referencing specific tool names and call_ids."
        " This is advisory only — do NOT generate a pass/fail decision."
    ),
    evidence_sources=(
        "ExecutionTrace.tool_calls[*].tool_name",
        "ToolSpec[*].name",
        "ToolSpec[*].description",
    ),
    severity_hint="info",
)

RUBRIC_TOOL_TOO_LOW_LEVEL = RubricDimension(
    dimension_id="tool_too_low_level",
    label="Tool granularity (too low-level)",
    source_module="D4",
    rubric_text=(
        "Evaluate whether any tool operates at too low a level for effective"
        " agent use. Signs of low-level tools: (a) the tool is essentially a"
        " database CRUD operation or raw HTTP endpoint wrapper, (b) the tool"
        " requires the agent to manually compose multiple primitive steps that"
        " should be a single domain action, (c) the tool description mentions"
        " 'API wrapper', 'endpoint', 'CRUD', or similar low-level implementation"
        " details rather than agent-facing purpose. For each identified low-level"
        " tool, suggest what a higher-level domain tool might look like."
        " This is advisory only — do NOT generate a pass/fail decision."
    ),
    evidence_sources=(
        "ToolSpec[*].description",
        "ToolSpec[*].name",
    ),
    severity_hint="info",
)

RUBRIC_FREQUENTLY_CHAINED_TOOLS = RubricDimension(
    dimension_id="frequently_chained_tools",
    label="Frequently chained tools pattern",
    source_module="D4",
    rubric_text=(
        "Analyze the tool call sequence for chains of tools that are frequently"
        " called together in succession. A tool chain is a sequence of 2+ tool"
        " calls where the output of one feeds into the next. If the same chain"
        " pattern appears repeatedly, it may indicate a missing higher-level tool"
        " that consolidates the chain into a single tool call. For each identified"
        " chain, describe: (a) the sequence of tool names, (b) the apparent"
        " data flow between them, (c) a suggested consolidated higher-level tool"
        " name and description. This analysis is pattern-mining — it does not"
        " prove that consolidation is correct, only that it is worth considering."
        " This is advisory only — do NOT generate a pass/fail decision."
    ),
    evidence_sources=(
        "ExecutionTrace.tool_calls[].tool_name",
        "ExecutionTrace.tool_results[].output",
    ),
    severity_hint="info",
)

RUBRIC_MISSING_DOMAIN_TOOL = RubricDimension(
    dimension_id="missing_domain_tool",
    label="Missing higher-level domain tool",
    source_module="D4",
    rubric_text=(
        "Evaluate whether the tool inventory is missing a higher-level domain tool"
        " that would simplify agent workflows. Signs: (a) the agent must call 3+"
        " tools to accomplish what should be a single domain action (e.g.,"
        " 'resolve_incident' vs. search+get+update+comment), (b) the tool names"
        " describe implementation details rather than domain actions (e.g.,"
        " 'query_database' vs. 'find_customer'), (c) the namespace structure does"
        " not reflect the domain's natural boundaries. For each identified gap,"
        " suggest a domain tool name, description, and what existing tools it"
        " would complement or replace. This is advisory only — do NOT generate"
        " a pass/fail decision."
    ),
    evidence_sources=(
        "ToolSpec[*].name",
        "ToolSpec[*].namespace",
        "ExecutionTrace.tool_calls[*].tool_name",
    ),
    severity_hint="info",
)

# ---------------------------------------------------------------------------
# D5 (Tool Response Quality) rubric dimensions
# ---------------------------------------------------------------------------

RUBRIC_MISSING_FIELDS_FOR_NEXT_CALL = RubricDimension(
    dimension_id="missing_fields_for_next_call",
    label="Missing fields for next call",
    source_module="D5",
    rubric_text=(
        "For each tool_result, evaluate whether the response contains the fields"
        " the agent would need to make a subsequent tool call. For example, if"
        " a 'search_articles' result returns article IDs without titles, the"
        " agent cannot display meaningful results without a second call. Signs"
        " of missing fields: (a) returned IDs without corresponding names/titles,"
        " (b) referenced entities without their identifiers for lookup, (c) list"
        " results without pagination cursors or total counts, (d) success status"
        " without the created/updated resource identifier. For each identified"
        " gap, specify which tool_result (call_id) and which fields are missing."
        " This is advisory only — do NOT generate a pass/fail decision."
    ),
    evidence_sources=(
        "ExecutionTrace.tool_results[*].output",
        "ExecutionTrace.tool_calls[*].tool_name",
    ),
    severity_hint="info",
)

RUBRIC_FINAL_ANSWER_FAITHFULNESS = RubricDimension(
    dimension_id="final_answer_faithfulness",
    label="Final answer faithfulness to tool results",
    source_module="D5",
    rubric_text=(
        "Evaluate whether the agent's final answer is faithfully grounded in the"
        " tool_results data. Check: (a) are claims in the answer supported by"
        " data in the tool results? (b) does the answer omit important data"
        " returned by tools? (c) does the answer fabricate or hallucinate details"
        " not present in tool results? (d) does the answer acknowledge tool"
        " errors or empty results rather than silently ignoring them? For each"
        " concern, reference the specific tool_result (call_id) and the specific"
        " claim or omission. This analysis requires comparing the natural language"
        " answer against structured tool outputs — it is inherently approximate."
        " This is advisory only — do NOT generate a pass/fail decision."
    ),
    evidence_sources=(
        "ExecutionTrace.tool_results[*].output",
        "ExecutionTrace.tool_results[*].error",
    ),
    severity_hint="info",
)

# ---------------------------------------------------------------------------
# Rubric catalog
# ---------------------------------------------------------------------------

ALL_RUBRICS: tuple[RubricDimension, ...] = (
    RUBRIC_TOOL_CHOICE_REASONABLENESS,
    RUBRIC_TOOL_TOO_LOW_LEVEL,
    RUBRIC_FREQUENTLY_CHAINED_TOOLS,
    RUBRIC_MISSING_DOMAIN_TOOL,
    RUBRIC_MISSING_FIELDS_FOR_NEXT_CALL,
    RUBRIC_FINAL_ANSWER_FAITHFULNESS,
)

RUBRICS_BY_ID: dict[str, RubricDimension] = {r.dimension_id: r for r in ALL_RUBRICS}

# ---------------------------------------------------------------------------
# Rubric builder
# ---------------------------------------------------------------------------


@dataclass
class RubricPrompt:
    """结构化 LLM judge prompt，包含 system prompt 和 evidence context。

    架构边界：
    - 这是 prompt 的**结构化表示**，不是 raw text。
    - 调用方（LLMJudgeProvider 或 FakeJudgeProvider）负责将其渲染为
      provider-specific 格式（chat messages / completion prompt）。
    - 任何 provider 渲染时，必须保留 advisory_only 和 no_review_decision 约束。
    """

    system_prompt: str
    rubric_catalog: list[dict[str, str]] = field(default_factory=list)
    evidence_context: dict[str, Any] = field(default_factory=dict)


# 全局 system prompt 前缀 —— 所有 LLM judge prompt 必须包含的约束。
_ADVISORY_ONLY_PREAMBLE = (
    "You are a tool-use quality analyst, NOT a pass/fail evaluator."
    " Your analysis is advisory only — it informs human reviewers but does not"
    " determine whether an evaluation passes or fails."
    " You do NOT generate review decisions, scores, or pass/fail judgments."
    " You provide structured observations about tool design, tool choice,"
    " tool response quality, and answer faithfulness."
    " Every observation must reference specific evidence (call_ids, tool names,"
    " tool_result fields). Never fabricate evidence."
    " ReviewDecision is reserved for human reviewers and must not be auto-generated."
)


def build_rubric_prompt(
    trace: ExecutionTrace,
    tool_specs: list[ToolSpec] | None = None,
    dimensions: tuple[str, ...] | None = None,
) -> RubricPrompt:
    """从 evidence 构建 LLM judge prompt 结构。

    所有构建操作 deterministic, zero-network。

    Args:
        trace: Agent 执行轨迹。
        tool_specs: 工具 spec 列表（可选，D4 维度需要）。
        dimensions: 要评估的 rubric 维度（默认全部 6 个）。

    Returns:
        RubricPrompt，包含 system_prompt、rubric_catalog、evidence_context。
    """
    selected_ids = set(dimensions) if dimensions else set(RUBRICS_BY_ID.keys())
    selected_rubrics = [
        RUBRICS_BY_ID[dim_id]
        for dim_id in sorted(selected_ids)
        if dim_id in RUBRICS_BY_ID
    ]

    # 构建 rubric catalog
    rubric_catalog = [
        {
            "dimension_id": r.dimension_id,
            "label": r.label,
            "rubric": r.rubric_text,
        }
        for r in selected_rubrics
    ]

    # 构建 evidence context summary
    tool_names = [tc.tool_name for tc in trace.tool_calls]
    tool_result_summaries = [
        {
            "call_id": tr.call_id,
            "tool_name": tr.tool_name,
            "status": tr.status,
            "output_keys": (
                list(tr.output.keys()) if isinstance(tr.output, dict) and tr.output else []
            ),
            "has_error": bool(tr.error),
        }
        for tr in trace.tool_results
    ]
    spec_names = (
        [s.qualified_name for s in tool_specs]
        if tool_specs
        else []
    )

    evidence_context = {
        "scenario_id": trace.scenario_id,
        "tool_call_count": len(trace.tool_calls),
        "tool_names_called": tool_names,
        "tool_result_count": len(trace.tool_results),
        "tool_result_summaries": tool_result_summaries,
        "tool_spec_names": spec_names,
    }

    return RubricPrompt(
        system_prompt=_ADVISORY_ONLY_PREAMBLE,
        rubric_catalog=rubric_catalog,
        evidence_context=evidence_context,
    )
