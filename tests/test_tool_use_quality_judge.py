"""Tool-use quality judge 测试。

覆盖:
- ToolUseQualityJudge 对所有 6 个 rubric 维度产出 JudgeFinding
- 有信号场景：finding message 包含具体发现
- 无信号场景：finding message 包含 "PASS:"
- 所有 finding 均为 JudgeFinding (advisory only, severity="info")
- 每条 finding 引用正确的 rubric dimension
- tool_specs 可选（无 spec 时部分维度降级 pass）
- CoreEvaluation 集成路径
- JudgeFinding 不影响 passed
- ReviewDecision 不自动生成
- 不读 .env / 不联网
"""

from __future__ import annotations

from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.core_contract import (
    EvaluationResult,
    Evidence,
    ExecutionTrace,
    JudgeFinding,
    RuleFinding,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.tool_use_quality_judge import ToolUseQualityJudge
from agent_tool_harness.tool_use_quality_rubric import ALL_RUBRICS


def _make_spec(**overrides) -> ToolSpec:
    defaults = dict(
        name="search", namespace="db", version="1.0",
        description="Search the database for records matching a query.",
        when_to_use="when finding records", when_not_to_use="for mutations",
        input_schema={}, output_contract={}, token_policy={},
        side_effects={}, executor={},
    )
    defaults.update(overrides)
    return ToolSpec(**defaults)


def _make_trace(**overrides) -> ExecutionTrace:
    defaults = dict(
        scenario_id="s1",
        tool_calls=[ToolCall(tool_name="search", arguments={"q": "x"}, call_id="c1")],
        tool_results=[
            ToolResult(
                call_id="c1", tool_name="search", status="success",
                output={"id": 1, "name": "x", "description": "a thing"},
            )
        ],
        final_answer="Found x: a thing.",
    )
    defaults.update(overrides)
    return ExecutionTrace(**defaults)


def _make_evidence(trace=None) -> Evidence:
    return Evidence(trace=trace or _make_trace())


# ---------------------------------------------------------------------------
# Happy path: all 6 dimensions
# ---------------------------------------------------------------------------


class TestAllDimensions:
    def test_produces_six_findings(self):
        judge = ToolUseQualityJudge(tool_specs=[_make_spec()])
        evidence = _make_evidence()
        findings = judge.evaluate(evidence)
        assert len(findings) == 6

    def test_all_findings_are_judge_finding(self):
        judge = ToolUseQualityJudge(tool_specs=[_make_spec()])
        evidence = _make_evidence()
        findings = judge.evaluate(evidence)

        for f in findings:
            assert isinstance(f, JudgeFinding), f"expected JudgeFinding, got {type(f)}"
            assert f.category == "judge"
            assert f.severity == "info"

    def test_all_findings_reference_rubric(self):
        judge = ToolUseQualityJudge(tool_specs=[_make_spec()])
        evidence = _make_evidence()
        findings = judge.evaluate(evidence)

        for f in findings:
            assert f.rubric is not None, "JudgeFinding must include rubric text"

        # 每条 finding 的 rubric 文本应匹配某个维度的 rubric_text
        rubric_texts = {r.rubric_text for r in ALL_RUBRICS}
        matched = 0
        for f in findings:
            if f.rubric in rubric_texts:
                matched += 1
        assert matched == 6, f"Only {matched}/6 findings match known rubric texts"

    def test_all_findings_have_fake_provider(self):
        judge = ToolUseQualityJudge(tool_specs=[_make_spec()])
        evidence = _make_evidence()
        findings = judge.evaluate(evidence)

        for f in findings:
            assert f.provider == "tool-use-quality-judge"
            assert f.model == "fake-heuristic"

    def test_no_specs_no_trace_produces_all_pass(self):
        judge = ToolUseQualityJudge()
        evidence = _make_evidence(
            _make_trace(
                tool_calls=[], tool_results=[],
                final_answer="The task completed successfully with no tool calls needed."
            )
        )
        findings = judge.evaluate(evidence)

        assert len(findings) == 6
        for f in findings:
            assert "PASS" in f.message


# ---------------------------------------------------------------------------
# D4: tool_choice_reasonableness
# ---------------------------------------------------------------------------


class TestToolChoiceReasonableness:
    def test_name_overlap_detected(self):
        judge = ToolUseQualityJudge(tool_specs=[
            _make_spec(name="search_user"),
            _make_spec(name="search_users"),
        ])
        trace = _make_trace(
            tool_calls=[ToolCall(tool_name="search_user", arguments={}, call_id="c1")],
            tool_results=[
                ToolResult(call_id="c1", tool_name="search_user", status="success", output={})
            ],
        )
        findings = judge.evaluate(Evidence(trace=trace))

        tc = _find_by_provider(findings, "tool_choice_reasonableness")
        assert tc is not None
        assert "PASS" not in tc.message  # should find overlap

    def test_no_overlap_pass(self):
        judge = ToolUseQualityJudge(tool_specs=[
            _make_spec(name="search"),
            _make_spec(name="create"),
            _make_spec(name="delete"),
        ])
        trace = _make_trace(
            tool_calls=[ToolCall(tool_name="search", arguments={}, call_id="c1")],
            tool_results=[
                ToolResult(call_id="c1", tool_name="search", status="success", output={})
            ],
        )
        findings = judge.evaluate(Evidence(trace=trace))

        tc = _find_by_provider(findings, "tool_choice_reasonableness")
        assert tc is not None
        assert "PASS" in tc.message


# ---------------------------------------------------------------------------
# D4: tool_too_low_level
# ---------------------------------------------------------------------------


class TestToolTooLowLevel:
    def test_api_wrapper_detected(self):
        judge = ToolUseQualityJudge(tool_specs=[
            _make_spec(name="query", description="This is an API wrapper for querying data."),
        ])
        findings = judge.evaluate(_make_evidence())

        tl = _find_by_provider(findings, "tool_too_low_level")
        assert tl is not None
        assert "PASS" not in tl.message
        assert "api wrapper" in tl.message.lower()

    def test_crud_operation_detected(self):
        judge = ToolUseQualityJudge(tool_specs=[
            _make_spec(name="upsert", description="CRUD operation for upserting records."),
        ])
        findings = judge.evaluate(_make_evidence())

        tl = _find_by_provider(findings, "tool_too_low_level")
        assert tl is not None
        assert "PASS" not in tl.message

    def test_clean_description_pass(self):
        judge = ToolUseQualityJudge(tool_specs=[
            _make_spec(name="search", description="Find relevant documents by semantic query."),
        ])
        findings = judge.evaluate(_make_evidence())

        tl = _find_by_provider(findings, "tool_too_low_level")
        assert tl is not None
        assert "PASS" in tl.message


# ---------------------------------------------------------------------------
# D4: frequently_chained_tools
# ---------------------------------------------------------------------------


class TestFrequentlyChainedTools:
    def test_repeated_pair_detected(self):
        judge = ToolUseQualityJudge(tool_specs=[_make_spec()])
        trace = _make_trace(
            tool_calls=[
                ToolCall(tool_name="search", arguments={}, call_id="c1"),
                ToolCall(tool_name="get", arguments={}, call_id="c2"),
                ToolCall(tool_name="search", arguments={}, call_id="c3"),
                ToolCall(tool_name="get", arguments={}, call_id="c4"),
                ToolCall(tool_name="search", arguments={}, call_id="c5"),
                ToolCall(tool_name="get", arguments={}, call_id="c6"),
            ],
            tool_results=[
                ToolResult(call_id=f"c{i}", tool_name="t", status="success", output={})
                for i in range(1, 7)
            ],
        )
        findings = judge.evaluate(Evidence(trace=trace))

        fc = _find_by_provider(findings, "frequently_chained_tools")
        assert fc is not None
        assert "PASS" not in fc.message
        assert "search→get" in fc.rationale

    def test_no_repeated_pair_pass(self):
        judge = ToolUseQualityJudge(tool_specs=[_make_spec()])
        trace = _make_trace(
            tool_calls=[
                ToolCall(tool_name="search", arguments={}, call_id="c1"),
                ToolCall(tool_name="get", arguments={}, call_id="c2"),
                ToolCall(tool_name="update", arguments={}, call_id="c3"),
            ],
            tool_results=[
                ToolResult(call_id=f"c{i}", tool_name="t", status="success", output={})
                for i in range(1, 4)
            ],
        )
        findings = judge.evaluate(Evidence(trace=trace))

        fc = _find_by_provider(findings, "frequently_chained_tools")
        assert fc is not None
        assert "PASS" in fc.message

    def test_less_than_two_calls_pass(self):
        judge = ToolUseQualityJudge(tool_specs=[_make_spec()])
        trace = _make_trace(
            tool_calls=[ToolCall(tool_name="search", arguments={}, call_id="c1")],
            tool_results=[
                ToolResult(call_id="c1", tool_name="search", status="success", output={})
            ],
        )
        findings = judge.evaluate(Evidence(trace=trace))

        fc = _find_by_provider(findings, "frequently_chained_tools")
        assert fc is not None
        assert "PASS" in fc.message


# ---------------------------------------------------------------------------
# D4: missing_domain_tool
# ---------------------------------------------------------------------------


class TestMissingDomainTool:
    def test_fragmented_namespace_detected(self):
        judge = ToolUseQualityJudge(tool_specs=[
            _make_spec(name="search", namespace="db"),
            _make_spec(name="get", namespace="db"),
            _make_spec(name="update", namespace="db"),
        ])
        trace = _make_trace(
            tool_calls=[
                ToolCall(tool_name="search", arguments={}, call_id="c1"),
                ToolCall(tool_name="get", arguments={}, call_id="c2"),
                ToolCall(tool_name="update", arguments={}, call_id="c3"),
            ],
            tool_results=[
                ToolResult(call_id="c1", tool_name="search", status="success", output={}),
                ToolResult(call_id="c2", tool_name="get", status="success", output={}),
                ToolResult(call_id="c3", tool_name="update", status="success", output={}),
            ],
        )
        findings = judge.evaluate(Evidence(trace=trace))

        md = _find_by_provider(findings, "missing_domain_tool")
        assert md is not None
        assert "PASS" not in md.message
        assert "db" in md.rationale

    def test_few_tools_pass(self):
        judge = ToolUseQualityJudge(tool_specs=[
            _make_spec(name="search", namespace="db"),
            _make_spec(name="get", namespace="db"),
        ])
        trace = _make_trace(
            tool_calls=[ToolCall(tool_name="search", arguments={}, call_id="c1")],
            tool_results=[
                ToolResult(call_id="c1", tool_name="search", status="success", output={})
            ],
        )
        findings = judge.evaluate(Evidence(trace=trace))

        md = _find_by_provider(findings, "missing_domain_tool")
        assert md is not None
        assert "PASS" in md.message

    def test_no_specs_pass(self):
        judge = ToolUseQualityJudge()
        findings = judge.evaluate(_make_evidence())

        md = _find_by_provider(findings, "missing_domain_tool")
        assert md is not None
        assert "PASS" in md.message


# ---------------------------------------------------------------------------
# D5: missing_fields_for_next_call
# ---------------------------------------------------------------------------


class TestMissingFieldsForNextCall:
    def test_ids_without_context_detected(self):
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="search", status="success",
                    output={"id": 1, "user_id": 2, "count": 10},
                ),
            ]
        )
        judge = ToolUseQualityJudge()
        findings = judge.evaluate(Evidence(trace=trace))

        mf = _find_by_provider(findings, "missing_fields_for_next_call")
        assert mf is not None
        assert "PASS" not in mf.message
        assert "c1" in mf.rationale

    def test_ids_with_name_pass(self):
        judge = ToolUseQualityJudge()
        findings = judge.evaluate(_make_evidence())  # has "id" and "name"

        mf = _find_by_provider(findings, "missing_fields_for_next_call")
        assert mf is not None
        assert "PASS" in mf.message

    def test_list_output_skipped(self):
        """非 dict 输出被跳过（不报 missing fields）。"""
        trace = _make_trace(
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="search", status="success",
                    output=["id1", "id2"],
                ),
            ]
        )
        judge = ToolUseQualityJudge()
        findings = judge.evaluate(Evidence(trace=trace))

        mf = _find_by_provider(findings, "missing_fields_for_next_call")
        assert mf is not None
        assert "PASS" in mf.message

    def test_empty_output_pass(self):
        trace = _make_trace(
            tool_results=[
                ToolResult(call_id="c1", tool_name="search", status="success", output={})
            ]
        )
        judge = ToolUseQualityJudge()
        findings = judge.evaluate(Evidence(trace=trace))

        mf = _find_by_provider(findings, "missing_fields_for_next_call")
        assert mf is not None


# ---------------------------------------------------------------------------
# D5: final_answer_faithfulness
# ---------------------------------------------------------------------------


class TestFinalAnswerFaithfulness:
    def test_empty_answer_detected(self):
        trace = _make_trace(final_answer="")
        judge = ToolUseQualityJudge()
        findings = judge.evaluate(Evidence(trace=trace))

        ff = _find_by_provider(findings, "final_answer_faithfulness")
        assert ff is not None
        assert "empty" in ff.message.lower()

    def test_short_answer_detected(self):
        trace = _make_trace(final_answer="OK.")
        judge = ToolUseQualityJudge()
        findings = judge.evaluate(Evidence(trace=trace))

        ff = _find_by_provider(findings, "final_answer_faithfulness")
        assert ff is not None
        assert "short" in ff.message.lower()

    def test_whitespace_only_answer_detected(self):
        trace = _make_trace(final_answer="   ")
        judge = ToolUseQualityJudge()
        findings = judge.evaluate(Evidence(trace=trace))

        ff = _find_by_provider(findings, "final_answer_faithfulness")
        assert ff is not None
        assert "empty" in ff.message.lower()

    def test_substantial_answer_pass(self):
        trace = _make_trace(
            final_answer="The search returned result x with description 'a thing'."
        )
        judge = ToolUseQualityJudge()
        findings = judge.evaluate(Evidence(trace=trace))

        ff = _find_by_provider(findings, "final_answer_faithfulness")
        assert ff is not None
        assert "PASS" in ff.message


# ---------------------------------------------------------------------------
# Advisory only boundary
# ---------------------------------------------------------------------------


class TestAdvisoryBoundary:
    def test_judge_finding_does_not_affect_passed(self):
        """JudgeFinding 不改变 EvaluationResult.passed。"""
        # 只有 RuleFinding（全 pass）→ passed=True
        # 即使有很多 JudgeFinding，passed 仍为 True
        result = EvaluationResult(
            scenario_id="test",
            findings=[
                RuleFinding(
                    finding_id="r1", severity="high", category="rule",
                    message="ok", evidence_ref="e1", rule_passed=True,
                ),
                JudgeFinding(
                    finding_id="j1", severity="info", category="judge",
                    message="advisory note", evidence_ref="e1",
                ),
                JudgeFinding(
                    finding_id="j2", severity="info", category="judge",
                    message="another note", evidence_ref="e1",
                ),
            ],
            passed=True,
        )
        passed = all(f.rule_passed for f in result.findings if isinstance(f, RuleFinding))
        assert passed is True

    def test_all_findings_are_info_severity(self):
        judge = ToolUseQualityJudge(tool_specs=[_make_spec()])
        findings = judge.evaluate(_make_evidence())

        for f in findings:
            assert f.severity == "info", (
                f"JudgeFinding severity must be 'info', got '{f.severity}'"
            )

    def test_review_decision_not_auto_generated(self):
        from agent_tool_harness.core_contract import ReviewDecision

        assert not hasattr(EvaluationResult, "review_decision")
        rd = ReviewDecision(decision="approved", reviewer="human", notes="ok")
        assert rd.decision == "approved"


# ---------------------------------------------------------------------------
# CoreEvaluation 集成
# ---------------------------------------------------------------------------


class TestCoreEvaluationIntegration:
    def test_judge_findings_appended_to_results(self):
        from agent_tool_harness.config.eval_spec import EvalSpec
        from agent_tool_harness.core_evaluation import CoreEvaluation

        eval_spec = EvalSpec.from_dict(
            {"name": "test", "scenarios": [{"id": "s1", "goal": "test"}], "tools": []},
            source_path="/tmp",
        )
        judge = ToolUseQualityJudge(tool_specs=[_make_spec()])
        evidence = _make_evidence()
        result = CoreEvaluation(judge_provider=judge).evaluate(evidence, eval_spec)

        judge_findings = [
            f for f in result.findings if isinstance(f, JudgeFinding)
        ]
        assert len(judge_findings) == 6

    def test_judge_findings_do_not_change_passed(self):
        """JudgeFinding 全 info advisory → passed 由 RuleFinding 决定。"""
        from agent_tool_harness.config.eval_spec import EvalSpec
        from agent_tool_harness.core_evaluation import CoreEvaluation

        eval_spec = EvalSpec.from_dict(
            {"name": "test", "scenarios": [{"id": "s1", "goal": "test"}], "tools": []},
            source_path="/tmp",
        )
        judge = ToolUseQualityJudge(tool_specs=[_make_spec()])
        evidence = _make_evidence()

        # Well-formed trace → all RuleFindings pass
        result = CoreEvaluation(judge_provider=judge).evaluate(evidence, eval_spec)

        rule_findings = [
            f for f in result.findings if isinstance(f, RuleFinding)
        ]
        all_rule_pass = all(f.rule_passed for f in rule_findings)
        assert result.passed == all_rule_pass


# ---------------------------------------------------------------------------
# 边界情况
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_no_network_dependency(self):
        import sys

        network_modules = {"httpx", "requests", "urllib3", "aiohttp", "openai", "anthropic"}
        module = sys.modules.get("agent_tool_harness.tool_use_quality_judge")
        if module:
            for attr in dir(module):
                obj = getattr(module, attr)
                if hasattr(obj, "__module__"):
                    for bad in network_modules:
                        assert bad not in str(obj.__module__), f"found {bad} via {attr}"

    def test_no_env_dependency(self):
        import inspect

        from agent_tool_harness import tool_use_quality_judge

        source = inspect.getsource(tool_use_quality_judge)
        assert "os.environ" not in source
        assert "os.getenv" not in source
        assert "dotenv" not in source

    def test_empty_trace_all_pass_findings(self):
        judge = ToolUseQualityJudge(tool_specs=[_make_spec()])
        evidence = _make_evidence(
            _make_trace(
                tool_calls=[], tool_results=[],
                final_answer="No tool calls were needed for this scenario."
            )
        )
        findings = judge.evaluate(evidence)

        assert len(findings) == 6
        for f in findings:
            ok = (
                "PASS" in f.message
                or "empty" in f.message.lower()
                or "fewer" in f.message.lower()
            )
            assert ok
            assert f.severity == "info"

    def test_multiple_results_missing_fields(self):
        """多个 tool_result 缺少 context fields。"""
        trace = _make_trace(
            tool_calls=[
                ToolCall(tool_name="search", arguments={}, call_id="c1"),
                ToolCall(tool_name="get", arguments={}, call_id="c2"),
            ],
            tool_results=[
                ToolResult(
                    call_id="c1", tool_name="search", status="success",
                    output={"id": 1},
                ),
                ToolResult(
                    call_id="c2", tool_name="get", status="success",
                    output={"record_id": 2},
                ),
            ],
        )
        judge = ToolUseQualityJudge()
        findings = judge.evaluate(Evidence(trace=trace))

        mf = _find_by_provider(findings, "missing_fields_for_next_call")
        assert mf is not None
        assert "2 tool_result" in mf.message.lower()


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _find_by_provider(findings: list[JudgeFinding], dimension_id: str) -> JudgeFinding | None:
    """通过 rubric text 匹配查找对应维度的 finding。"""
    from agent_tool_harness.tool_use_quality_rubric import RUBRICS_BY_ID

    target_rubric = RUBRICS_BY_ID[dimension_id].rubric_text
    for f in findings:
        if f.rubric == target_rubric:
            return f
    return None
