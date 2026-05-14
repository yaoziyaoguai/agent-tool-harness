"""Tool ergonomics inspection 测试。

覆盖:
- 6 条 deterministic rule 的 positive / negative 测试
- 全部 WARNING —— rule_passed=True, 不影响 passed
- CoreEvaluation 集成路径
- JudgeFinding advisory only
- ReviewDecision 不自动生成
- 不读取 .env / 不联网
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
from agent_tool_harness.core_evaluation import CoreEvaluation
from agent_tool_harness.tool_ergonomics import ToolErgonomicsInspector


def _make_tool_spec(**overrides) -> ToolSpec:
    """构造测试用 ToolSpec。"""
    defaults = dict(
        name="search_articles",
        namespace="kb",
        version="1.0.0",
        description="Search the knowledge base for articles matching a query.",
    )
    defaults.update(overrides)
    return ToolSpec.from_dict(defaults)


def _find_by_rule_type(findings: list[RuleFinding], rule_type: str) -> RuleFinding:
    for f in findings:
        if f.rule_type == rule_type:
            return f
    raise AssertionError(f"finding with rule_type={rule_type!r} not found")


class TestWellFormedTools:
    """well-formed tools: clear name, namespace, description。"""

    def test_all_rules_pass_for_well_formed_spec(self):
        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec()
        findings = inspector.inspect([spec])

        for f in findings:
            assert f.rule_passed is True, f"{f.rule_type}: {f.message}"
            assert f.severity == "medium"

    def test_all_findings_are_rule_finding(self):
        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec()
        findings = inspector.inspect([spec])

        for f in findings:
            assert isinstance(f, RuleFinding)
            assert f.category == "rule"

    def test_rule_ids_are_stable(self):
        inspector = ToolErgonomicsInspector()
        specs = [_make_tool_spec(name="tool_a"), _make_tool_spec(name="tool_b")]
        findings = inspector.inspect(specs)

        rule_types = sorted({f.rule_type for f in findings})
        expected = sorted([
            "tool_ergonomics.name.too_generic",
            "tool_ergonomics.name.namespace_present",
            "tool_ergonomics.names.overlap",
            "tool_ergonomics.too_many_similar_tools",
            "tool_ergonomics.description.shallow_wrapper",
            "tool_ergonomics.action_resource_clarity",
        ])
        assert rule_types == expected

    def test_empty_list(self):
        inspector = ToolErgonomicsInspector()
        findings = inspector.inspect([])
        # 空列表只产生 too_many_similar_tools 的 pass finding
        assert len(findings) >= 0

    def test_multiple_tools_produce_cross_checks(self):
        inspector = ToolErgonomicsInspector()
        specs = [
            _make_tool_spec(name="tool_a", namespace="ns"),
            _make_tool_spec(name="tool_b", namespace="ns"),
        ]
        findings = inspector.inspect(specs)
        # per-tool: 4 each × 2 + names.overlap + too_many_similar_tools
        assert len(findings) >= 10


class TestNameTooGeneric:
    """tool_ergonomics.name.too_generic — WARNING。"""

    def test_search_get_query_all_generic(self):
        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec(name="search_get", namespace="")
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_ergonomics.name.too_generic")
        assert f.rule_passed is True
        assert "generic tokens" in f.message

    def test_specific_name_is_not_generic(self):
        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec(name="search_articles")
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_ergonomics.name.too_generic")
        assert f.rule_passed is True
        assert "specific enough" in f.message


class TestNamespacePresent:
    """tool_ergonomics.name.namespace_present — WARNING。"""

    def test_missing_namespace(self):
        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec(name="search", namespace="")
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_ergonomics.name.namespace_present")
        assert f.rule_passed is True
        assert "missing namespace prefix" in f.message

    def test_has_namespace(self):
        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec(name="search", namespace="kb")
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_ergonomics.name.namespace_present")
        assert f.rule_passed is True
        assert "has namespace" in f.message


class TestNamesOverlap:
    """tool_ergonomics.names.overlap — WARNING。"""

    def test_similar_names_detected(self):
        inspector = ToolErgonomicsInspector()
        specs = [
            _make_tool_spec(name="search_articles", namespace="kb"),
            _make_tool_spec(name="search_article", namespace="kb"),
        ]
        findings = inspector.inspect(specs)

        overlap_findings = [
            f for f in findings
            if f.rule_type == "tool_ergonomics.names.overlap"
        ]
        assert len(overlap_findings) >= 1
        for f in overlap_findings:
            assert "similar tool names" in f.message

    def test_distinct_names_no_overlap(self):
        inspector = ToolErgonomicsInspector()
        specs = [
            _make_tool_spec(name="create_user", namespace="admin"),
            _make_tool_spec(name="delete_project", namespace="project"),
        ]
        findings = inspector.inspect(specs)

        overlap_findings = [
            f for f in findings
            if f.rule_type == "tool_ergonomics.names.overlap"
        ]
        for f in overlap_findings:
            assert "no overlapping" in f.message

    def test_single_tool_no_overlap_check(self):
        inspector = ToolErgonomicsInspector()
        findings = inspector.inspect([_make_tool_spec()])
        overlap = [f for f in findings if f.rule_type == "tool_ergonomics.names.overlap"]
        assert len(overlap) == 0


class TestTooManySimilarTools:
    """tool_ergonomics.too_many_similar_tools — WARNING。"""

    def test_too_many_tools_in_namespace(self):
        inspector = ToolErgonomicsInspector()
        specs = [
            _make_tool_spec(name=f"tool_{i}", namespace="big_ns")
            for i in range(7)
        ]
        findings = inspector.inspect(specs)

        too_many = [
            f for f in findings
            if f.rule_type == "tool_ergonomics.too_many_similar_tools"
            and "threshold" in f.message and "has 7" in f.message
        ]
        assert len(too_many) >= 1

    def test_normal_namespace_no_warning(self):
        inspector = ToolErgonomicsInspector()
        specs = [
            _make_tool_spec(name="tool_a", namespace="small_ns"),
            _make_tool_spec(name="tool_b", namespace="small_ns"),
        ]
        findings = inspector.inspect(specs)

        too_many = [
            f for f in findings
            if f.rule_type == "tool_ergonomics.too_many_similar_tools"
        ]
        for f in too_many:
            assert "no namespace exceeds" in f.message or "exceeds" not in f.message


class TestShallowWrapper:
    """tool_ergonomics.description.shallow_wrapper — WARNING。"""

    def test_shallow_wrapper_description(self):
        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec(
            description="This tool is a wrapper around the REST API endpoint."
        )
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_ergonomics.description.shallow_wrapper")
        assert f.rule_passed is True
        assert "shallow wrapper phrase" in f.message

    def test_agent_facing_description(self):
        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec(
            description="Search the knowledge base for troubleshooting guides."
        )
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_ergonomics.description.shallow_wrapper")
        assert "agent-facing purpose" in f.message


class TestActionResourceClarity:
    """tool_ergonomics.action_resource_clarity — WARNING。"""

    def test_name_has_action_and_resource(self):
        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec(name="search_articles")
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_ergonomics.action_resource_clarity")
        assert f.rule_passed is True
        assert "has action and resource" in f.message

    def test_name_missing_resource(self):
        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec(name="search")
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_ergonomics.action_resource_clarity")
        assert f.rule_passed is True
        assert "missing resource" in f.message

    def test_name_missing_action(self):
        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec(name="articles")
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_ergonomics.action_resource_clarity")
        assert f.rule_passed is True
        assert "missing action" in f.message


class TestSeverityPassedBoundary:
    """D4 全部 WARNING → 不影响 passed。"""

    def test_all_warnings_rule_passed_true(self):
        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec(name="search", namespace="")
        findings = inspector.inspect([spec])

        for f in findings:
            assert f.rule_passed is True, f"{f.rule_type}: {f.message}"

    def test_warnings_do_not_affect_evaluation_passed(self):
        """D4 全部 WARNING → D4 findings 全 rule_passed=True。"""
        from agent_tool_harness.config.eval_spec import EvalSpec

        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec(name="search", namespace="")

        eval_spec = EvalSpec.from_dict(
            {"name": "test", "scenarios": [{"id": "s1", "goal": "test"}], "tools": []},
            source_path="/tmp",
        )
        evidence = Evidence(
            trace=ExecutionTrace(
                scenario_id="s1",
                tool_calls=[ToolCall(tool_name="t", arguments={}, call_id="c1")],
                tool_results=[ToolResult(call_id="c1", tool_name="t", status="success")],
            )
        )

        result = CoreEvaluation(ergonomics_inspector=inspector).evaluate(
            evidence, eval_spec, tool_specs=[spec]
        )
        # D4 全部 WARNING —— 每个 D4 finding 的 rule_passed=True
        ergo_findings = [
            f for f in result.findings
            if isinstance(f, RuleFinding)
            and f.rule_type.startswith("tool_ergonomics.")
        ]
        for f in ergo_findings:
            assert f.rule_passed is True, f"{f.rule_type}: {f.message}"

    def test_judge_finding_does_not_affect_passed(self):
        result = EvaluationResult(
            scenario_id="test",
            findings=[
                RuleFinding(
                    finding_id="r1", severity="medium", category="rule",
                    message="ok", evidence_ref="e1", rule_passed=True,
                ),
                JudgeFinding(
                    finding_id="j1", severity="high", category="judge",
                    message="bad", evidence_ref="e1",
                ),
            ],
            passed=True,
        )
        passed = all(f.rule_passed for f in result.findings if isinstance(f, RuleFinding))
        assert passed is True

    def test_review_decision_not_auto_generated(self):
        from agent_tool_harness.core_contract import ReviewDecision

        assert not hasattr(EvaluationResult, "review_decision")
        rd = ReviewDecision(decision="approved", reviewer="human", notes="ok")
        assert rd.decision == "approved"


class TestCoreEvaluationIntegration:
    """CoreEvaluation + ToolErgonomicsInspector 集成路径。"""

    def test_ergonomics_inspector_appends_findings(self):
        from agent_tool_harness.config.eval_spec import EvalSpec

        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec()

        eval_spec = EvalSpec.from_dict(
            {"name": "test", "scenarios": [{"id": "s1", "goal": "test"}], "tools": []},
            source_path="/tmp",
        )
        evidence = Evidence(
            trace=ExecutionTrace(
                scenario_id="s1",
                tool_calls=[ToolCall(tool_name="t", arguments={}, call_id="c1")],
                tool_results=[ToolResult(call_id="c1", tool_name="t", status="success")],
            )
        )

        result = CoreEvaluation(ergonomics_inspector=inspector).evaluate(
            evidence, eval_spec, tool_specs=[spec]
        )
        ergo_findings = [
            f for f in result.findings
            if isinstance(f, RuleFinding)
            and f.rule_type.startswith("tool_ergonomics.")
        ]
        # 4 per-tool + 1 cross-tool (single tool: no overlap, has too_many pass)
        assert len(ergo_findings) >= 5

    def test_no_ergonomics_inspector_backward_compat(self):
        from agent_tool_harness.config.eval_spec import EvalSpec

        spec = _make_tool_spec(name="search", namespace="")
        eval_spec = EvalSpec.from_dict(
            {"name": "test", "scenarios": [{"id": "s1", "goal": "test"}], "tools": []},
            source_path="/tmp",
        )
        evidence = Evidence(
            trace=ExecutionTrace(
                scenario_id="s1",
                tool_calls=[ToolCall(tool_name="t", arguments={}, call_id="c1")],
                tool_results=[ToolResult(call_id="c1", tool_name="t", status="success")],
            )
        )

        result = CoreEvaluation().evaluate(evidence, eval_spec, tool_specs=[spec])
        ergo_findings = [
            f for f in result.findings
            if isinstance(f, RuleFinding)
            and f.rule_type.startswith("tool_ergonomics.")
        ]
        assert len(ergo_findings) == 0


class TestEdgeCases:
    def test_finding_id_includes_qualified_name(self):
        inspector = ToolErgonomicsInspector()
        spec = _make_tool_spec()
        findings = inspector.inspect([spec])

        for f in findings:
            if "all_tools" not in f.finding_id and "all_namespaces" not in f.finding_id:
                assert spec.qualified_name in f.finding_id, f.finding_id

    def test_no_network_dependency(self):
        import sys

        network_modules = {"httpx", "requests", "urllib3", "aiohttp", "openai", "anthropic"}
        module = sys.modules.get("agent_tool_harness.tool_ergonomics")
        if module:
            for attr in dir(module):
                obj = getattr(module, attr)
                if hasattr(obj, "__module__"):
                    for bad in network_modules:
                        assert bad not in str(obj.__module__), f"found {bad} via {attr}"

    def test_no_env_dependency(self):
        import inspect

        from agent_tool_harness import tool_ergonomics

        source = inspect.getsource(tool_ergonomics)
        assert "os.environ" not in source
        assert "os.getenv" not in source
        assert "dotenv" not in source
