"""Tool-use quality rubric 定义测试。

覆盖:
- RubricDimension frozen dataclass 属性
- 6 条 rubric 维度的稳定性 (id/label/source_module/evidence_sources)
- ALL_RUBRICS / RUBRICS_BY_ID 完整性
- build_rubric_prompt() 输出结构
- ADVISORY_ONLY_PREAMBLE 注入
- Dimensions 过滤
- Evidence context 正确性
- 不读 .env / 不联网
"""

from __future__ import annotations

from agent_tool_harness.core_contract import (
    ExecutionTrace,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.tool_use_quality_rubric import (
    ALL_RUBRICS,
    RUBRIC_FINAL_ANSWER_FAITHFULNESS,
    RUBRIC_FREQUENTLY_CHAINED_TOOLS,
    RUBRIC_MISSING_DOMAIN_TOOL,
    RUBRIC_MISSING_FIELDS_FOR_NEXT_CALL,
    RUBRIC_TOOL_CHOICE_REASONABLENESS,
    RUBRIC_TOOL_TOO_LOW_LEVEL,
    RUBRICS_BY_ID,
    RubricPrompt,
    build_rubric_prompt,
)


def _make_trace(**overrides) -> ExecutionTrace:
    defaults = dict(
        scenario_id="s1",
        tool_calls=[ToolCall(tool_name="search", arguments={"q": "x"}, call_id="c1")],
        tool_results=[
            ToolResult(
                call_id="c1", tool_name="search", status="success",
                output={"id": 1, "name": "x"},
            )
        ],
        final_answer="Found x with id 1.",
    )
    defaults.update(overrides)
    return ExecutionTrace(**defaults)


# ---------------------------------------------------------------------------
# RubricDimension contract
# ---------------------------------------------------------------------------


class TestRubricDimension:
    def test_frozen_dataclass(self):
        r = RUBRIC_TOOL_CHOICE_REASONABLENESS
        assert r.dimension_id == "tool_choice_reasonableness"
        assert r.label == "Tool choice reasonableness"
        assert r.source_module == "D4"
        assert "tool_calls" in r.evidence_sources[0]
        assert r.severity_hint == "info"

    def test_all_six_have_unique_ids(self):
        ids = [r.dimension_id for r in ALL_RUBRICS]
        assert len(ids) == len(set(ids)) == 6

    def test_d4_dimensions(self):
        d4 = [r for r in ALL_RUBRICS if r.source_module == "D4"]
        d4_ids = {r.dimension_id for r in d4}
        assert d4_ids == {
            "tool_choice_reasonableness",
            "tool_too_low_level",
            "frequently_chained_tools",
            "missing_domain_tool",
        }

    def test_d5_dimensions(self):
        d5 = [r for r in ALL_RUBRICS if r.source_module == "D5"]
        d5_ids = {r.dimension_id for r in d5}
        assert d5_ids == {
            "missing_fields_for_next_call",
            "final_answer_faithfulness",
        }

    def test_all_rubrics_have_severity_info(self):
        for r in ALL_RUBRICS:
            assert r.severity_hint == "info", (
                f"{r.dimension_id}: severity_hint should be 'info', got '{r.severity_hint}'"
            )

    def test_all_rubrics_reference_advisory_only(self):
        for r in ALL_RUBRICS:
            assert "advisory only" in r.rubric_text.lower(), (
                f"{r.dimension_id}: rubric_text must mention 'advisory only'"
            )


# ---------------------------------------------------------------------------
# RUBRICS_BY_ID
# ---------------------------------------------------------------------------


class TestRubricsById:
    def test_lookup_all_ids(self):
        for r in ALL_RUBRICS:
            assert RUBRICS_BY_ID[r.dimension_id] is r

    def test_lookup_returns_same_object(self):
        assert RUBRICS_BY_ID["tool_choice_reasonableness"] is RUBRIC_TOOL_CHOICE_REASONABLENESS
        assert RUBRICS_BY_ID["tool_too_low_level"] is RUBRIC_TOOL_TOO_LOW_LEVEL
        assert RUBRICS_BY_ID["frequently_chained_tools"] is RUBRIC_FREQUENTLY_CHAINED_TOOLS
        assert RUBRICS_BY_ID["missing_domain_tool"] is RUBRIC_MISSING_DOMAIN_TOOL
        assert RUBRICS_BY_ID["missing_fields_for_next_call"] is RUBRIC_MISSING_FIELDS_FOR_NEXT_CALL
        assert RUBRICS_BY_ID["final_answer_faithfulness"] is RUBRIC_FINAL_ANSWER_FAITHFULNESS


# ---------------------------------------------------------------------------
# build_rubric_prompt()
# ---------------------------------------------------------------------------


class TestBuildRubricPrompt:
    def test_returns_rubric_prompt(self):
        trace = _make_trace()
        result = build_rubric_prompt(trace)
        assert isinstance(result, RubricPrompt)

    def test_system_prompt_contains_advisory_preamble(self):
        trace = _make_trace()
        result = build_rubric_prompt(trace)
        assert "advisory only" in result.system_prompt
        assert "pass/fail" in result.system_prompt.lower()
        assert "ReviewDecision" in result.system_prompt

    def test_default_includes_all_six_dimensions(self):
        trace = _make_trace()
        result = build_rubric_prompt(trace)
        dim_ids = [r["dimension_id"] for r in result.rubric_catalog]
        assert len(dim_ids) == 6
        for r in ALL_RUBRICS:
            assert r.dimension_id in dim_ids

    def test_dimensions_filtering(self):
        trace = _make_trace()
        result = build_rubric_prompt(trace, dimensions=("tool_choice_reasonableness",))
        dim_ids = [r["dimension_id"] for r in result.rubric_catalog]
        assert dim_ids == ["tool_choice_reasonableness"]

    def test_unknown_dimension_ignored(self):
        trace = _make_trace()
        result = build_rubric_prompt(trace, dimensions=("nonexistent", "tool_too_low_level"))
        dim_ids = [r["dimension_id"] for r in result.rubric_catalog]
        assert dim_ids == ["tool_too_low_level"]

    def test_rubric_catalog_structure(self):
        trace = _make_trace()
        result = build_rubric_prompt(trace)
        for entry in result.rubric_catalog:
            assert "dimension_id" in entry
            assert "label" in entry
            assert "rubric" in entry
            assert isinstance(entry["dimension_id"], str)
            assert isinstance(entry["label"], str)
            assert isinstance(entry["rubric"], str)


# ---------------------------------------------------------------------------
# Evidence context
# ---------------------------------------------------------------------------


class TestEvidenceContext:
    def test_scenario_id(self):
        trace = _make_trace(scenario_id="scenario-abc")
        result = build_rubric_prompt(trace)
        assert result.evidence_context["scenario_id"] == "scenario-abc"

    def test_tool_call_count(self):
        trace = _make_trace(
            tool_calls=[
                ToolCall(tool_name="a", arguments={}, call_id="c1"),
                ToolCall(tool_name="b", arguments={}, call_id="c2"),
            ],
            tool_results=[
                ToolResult(call_id="c1", tool_name="a", status="success", output={}),
                ToolResult(call_id="c2", tool_name="b", status="success", output={}),
            ],
        )
        result = build_rubric_prompt(trace)
        assert result.evidence_context["tool_call_count"] == 2
        assert result.evidence_context["tool_result_count"] == 2

    def test_tool_names_called(self):
        trace = _make_trace(
            tool_calls=[
                ToolCall(tool_name="search", arguments={}, call_id="c1"),
                ToolCall(tool_name="get", arguments={}, call_id="c2"),
            ],
            tool_results=[
                ToolResult(call_id="c1", tool_name="search", status="success", output={}),
                ToolResult(call_id="c2", tool_name="get", status="success", output={}),
            ],
        )
        result = build_rubric_prompt(trace)
        assert result.evidence_context["tool_names_called"] == ["search", "get"]

    def test_tool_result_summaries(self):
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="t", status="success",
                    output={"id": 1, "name": "x"},
                ),
            ]
        )
        result = build_rubric_prompt(trace)
        summaries = result.evidence_context["tool_result_summaries"]
        assert len(summaries) == 1
        assert summaries[0]["call_id"] == "c1"
        assert summaries[0]["tool_name"] == "t"
        assert summaries[0]["status"] == "success"
        assert "id" in summaries[0]["output_keys"]
        assert "name" in summaries[0]["output_keys"]
        assert summaries[0]["has_error"] is False

    def test_tool_result_summary_with_error(self):
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="t", status="error",
                    error="timeout",
                ),
            ]
        )
        result = build_rubric_prompt(trace)
        summaries = result.evidence_context["tool_result_summaries"]
        assert summaries[0]["has_error"] is True

    def test_tool_spec_names(self):
        from agent_tool_harness.config.tool_spec import ToolSpec

        trace = _make_trace()
        specs = [
            ToolSpec(
                name="search", namespace="db", version="1.0", description="search",
                when_to_use="", when_not_to_use="", input_schema={},
                output_contract={}, token_policy={}, side_effects={}, executor={},
            ),
            ToolSpec(
                name="get", namespace="db", version="1.0", description="get",
                when_to_use="", when_not_to_use="", input_schema={},
                output_contract={}, token_policy={}, side_effects={}, executor={},
            ),
        ]
        result = build_rubric_prompt(trace, tool_specs=specs)
        assert "db.search" in result.evidence_context["tool_spec_names"]
        assert "db.get" in result.evidence_context["tool_spec_names"]

    def test_empty_trace(self):
        trace = _make_trace(tool_calls=[], tool_results=[])
        result = build_rubric_prompt(trace)
        assert result.evidence_context["tool_call_count"] == 0
        assert result.evidence_context["tool_result_count"] == 0
        assert result.evidence_context["tool_names_called"] == []


# ---------------------------------------------------------------------------
# Edge cases / no-network
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_network_dependency(self):
        import sys

        network_modules = {"httpx", "requests", "urllib3", "aiohttp", "openai", "anthropic"}
        module = sys.modules.get("agent_tool_harness.tool_use_quality_rubric")
        if module:
            for attr in dir(module):
                obj = getattr(module, attr)
                if hasattr(obj, "__module__"):
                    for bad in network_modules:
                        assert bad not in str(obj.__module__), f"found {bad} via {attr}"

    def test_no_env_dependency(self):
        import inspect

        from agent_tool_harness import tool_use_quality_rubric

        source = inspect.getsource(tool_use_quality_rubric)
        assert "os.environ" not in source
        assert "os.getenv" not in source
        assert "dotenv" not in source

    def test_build_rubric_prompt_deterministic(self):
        trace = _make_trace()
        r1 = build_rubric_prompt(trace)
        r2 = build_rubric_prompt(trace)
        assert r1.system_prompt == r2.system_prompt
        assert r1.rubric_catalog == r2.rubric_catalog
        assert r1.evidence_context == r2.evidence_context
