"""Tool spec quality inspection 测试。

覆盖:
- 10 条 deterministic rule 的 positive / negative 测试
- ERROR / WARNING / INFO severity 边界
- CoreEvaluation 集成路径
- EvaluationResult.passed 语义
- 向后兼容（CoreEvaluation 无 spec_inspector）
- rule_id 稳定性
- 无 LLM / 网络 / .env 依赖
"""

from __future__ import annotations

from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.core_contract import (
    EvaluationResult,
    JudgeFinding,
    RuleFinding,
)
from agent_tool_harness.core_evaluation import CoreEvaluation
from agent_tool_harness.tool_spec_inspection import ToolSpecInspector

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_tool_spec(**overrides) -> ToolSpec:
    """构造测试用 ToolSpec，默认值构成 well-formed tool。"""
    defaults = dict(
        name="kb.search_articles",
        namespace="kb",
        version="1.0.0",
        description="Search the knowledge base for articles matching a natural language query. "
        "Returns ranked results with titles, snippets, and links.",
        when_to_use="When the agent needs to find documentation or troubleshooting guides.",
        when_not_to_use="When the article ID is already known — use kb.get_article instead.",
        input_schema={
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language search query",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return",
                },
            },
            "required": ["query"],
        },
        output_contract={
            "required_fields": ["articles", "total_count"],
            "summary": "Returns matching articles with relevance scores",
        },
        token_policy={
            "max_output_tokens": 2000,
            "default_limit": 10,
            "supports_pagination": True,
        },
        side_effects={
            "destructive": False,
            "open_world_access": False,
        },
    )
    defaults.update(overrides)
    return ToolSpec.from_dict(defaults)


def _make_minimal_tool_spec(**overrides) -> ToolSpec:
    """构造最小可解析 ToolSpec（description 只有 one word, 无 schema 等）。"""
    defaults = dict(
        name="minimal.tool",
        namespace="test",
        version="0.0.1",
        description="minimal",
    )
    defaults.update(overrides)
    return ToolSpec.from_dict(defaults)


# ---------------------------------------------------------------------------
# Positive tests — well-formed tool spec
# ---------------------------------------------------------------------------


class TestWellFormedToolSpec:
    """well-formed tool spec 不产生任何 ERROR-level finding。"""

    def test_all_rules_pass_for_well_formed_spec(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec()
        findings = inspector.inspect([spec])

        assert len(findings) == 10

        # 所有 finding 的 rule_passed 应为 True（WARNING/INFO rules）
        # 注意：ERROR rules 对 well-formed spec 也是 rule_passed=True
        for f in findings:
            assert f.rule_passed is True, f"{f.rule_type}: {f.message}"

    def test_all_findings_are_rule_finding(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec()
        findings = inspector.inspect([spec])

        for f in findings:
            assert isinstance(f, RuleFinding)
            assert f.category == "rule"

    def test_rule_ids_are_stable(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec()
        findings = inspector.inspect([spec])

        rule_types = sorted(f.rule_type for f in findings)
        expected = sorted(
            [
                "tool_spec.description.exists",
                "tool_spec.description.useful_length",
                "tool_spec.input_schema.exists",
                "tool_spec.parameter.name.explicit",
                "tool_spec.required_parameter.documented",
                "tool_spec.output_contract.documented",
                "tool_spec.side_effects.documented",
                "tool_spec.when_to_use.documented",
                "tool_spec.when_not_to_use.documented",
                "tool_spec.token_policy.defined",
            ]
        )
        assert rule_types == expected

    def test_empty_list_returns_empty_findings(self):
        inspector = ToolSpecInspector()
        findings = inspector.inspect([])
        assert findings == []

    def test_multiple_tools_each_get_10_findings(self):
        inspector = ToolSpecInspector()
        specs = [
            _make_tool_spec(name="tool_a"),
            _make_tool_spec(name="tool_b"),
            _make_tool_spec(name="tool_c"),
        ]
        findings = inspector.inspect(specs)
        assert len(findings) == 30  # 3 tools × 10 rules


# ---------------------------------------------------------------------------
# ERROR rules — rule_passed=False 影响 passed
# ---------------------------------------------------------------------------


class TestErrorRules:
    """ERROR: description.exists / input_schema.exists。"""

    def test_missing_description_is_error(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(description="")
        findings = inspector.inspect([spec])

        desc_finding = _find_by_rule_type(findings, "tool_spec.description.exists")
        assert desc_finding.rule_passed is False
        assert desc_finding.severity == "high"

    def test_whitespace_only_description_is_error(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(description="   ")
        findings = inspector.inspect([spec])

        desc_finding = _find_by_rule_type(findings, "tool_spec.description.exists")
        assert desc_finding.rule_passed is False

    def test_empty_input_schema_is_error(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(
            input_schema={},
        )
        findings = inspector.inspect([spec])

        schema_finding = _find_by_rule_type(findings, "tool_spec.input_schema.exists")
        assert schema_finding.rule_passed is False
        assert schema_finding.severity == "high"

    def test_input_schema_no_properties_is_error(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(
            input_schema={"type": "object"},
        )
        findings = inspector.inspect([spec])

        schema_finding = _find_by_rule_type(findings, "tool_spec.input_schema.exists")
        assert schema_finding.rule_passed is False

    def test_input_schema_empty_properties_is_error(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(
            input_schema={"type": "object", "properties": {}},
        )
        findings = inspector.inspect([spec])

        schema_finding = _find_by_rule_type(findings, "tool_spec.input_schema.exists")
        assert schema_finding.rule_passed is False

    def test_error_findings_affect_passed(self):
        """ERROR finding → rule_passed=False → EvaluationResult.passed=False。"""
        from agent_tool_harness.config.eval_spec import EvalSpec
        from agent_tool_harness.core_contract import (
            Evidence,
            ExecutionTrace,
            ToolCall,
            ToolResult,
        )

        inspector = ToolSpecInspector()
        spec = _make_tool_spec(description="")

        eval_spec = EvalSpec.from_dict(
            {
                "name": "test",
                "scenarios": [{"id": "s1", "goal": "test"}],
                "tools": [],
            },
            source_path="/tmp",
        )

        evidence = Evidence(
            trace=ExecutionTrace(
                scenario_id="s1",
                tool_calls=[
                    ToolCall(tool_name="kb.search", arguments={}, call_id="c1")
                ],
                tool_results=[
                    ToolResult(
                        call_id="c1", tool_name="kb.search", status="success"
                    )
                ],
            )
        )

        result = CoreEvaluation(spec_inspector=inspector).evaluate(
            evidence, eval_spec, tool_specs=[spec]
        )

        # ERROR finding 应导致 passed=False
        assert result.passed is False
        # 至少有一条 rule_passed=False
        error_findings = [f for f in result.findings if not f.rule_passed]
        assert len(error_findings) >= 1


# ---------------------------------------------------------------------------
# WARNING rules — rule_passed=True 不影响 passed
# ---------------------------------------------------------------------------


class TestWarningRules:
    """WARNING: description.useful_length / parameter.name.explicit /
    required_parameter.documented / output_contract.documented /
    side_effects.documented / when_to_use.documented /
    when_not_to_use.documented。"""

    def test_short_description_is_warning(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(description="search knowledge")
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_spec.description.useful_length")
        assert f.rule_passed is True  # WARNING 不影响 passed
        assert f.severity == "medium"

    def test_generic_parameter_name_is_warning(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(
            input_schema={
                "type": "object",
                "properties": {
                    "data": {"type": "string", "description": "input data"},
                },
            }
        )
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_spec.parameter.name.explicit")
        assert f.rule_passed is True
        assert "data" in f.message

    def test_missing_required_documentation_is_warning(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                # 缺 required
            }
        )
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_spec.required_parameter.documented")
        assert f.rule_passed is True
        assert "not declared" in f.message

    def test_empty_output_contract_is_warning(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(output_contract={})
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_spec.output_contract.documented")
        assert f.rule_passed is True
        assert "empty" in f.message

    def test_empty_side_effects_is_warning(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(side_effects={})
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_spec.side_effects.documented")
        assert f.rule_passed is True

    def test_empty_when_to_use_is_warning(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(when_to_use="")
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_spec.when_to_use.documented")
        assert f.rule_passed is True

    def test_empty_when_not_to_use_is_warning(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(when_not_to_use="")
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_spec.when_not_to_use.documented")
        assert f.rule_passed is True

    def test_warning_findings_do_not_affect_passed(self):
        """WARNING finding 不影响 EvaluationResult.passed。

        构造一个 spec 触发所有 WARNING 但无 ERROR（description 有内容、
        input_schema 有 properties）。
        """
        from agent_tool_harness.config.eval_spec import EvalSpec
        from agent_tool_harness.core_contract import (
            Evidence,
            ExecutionTrace,
            ToolCall,
            ToolResult,
        )

        inspector = ToolSpecInspector()
        spec = _make_tool_spec(
            description="a short description",  # 短 → WARNING
            when_to_use="",  # 空 → WARNING
            when_not_to_use="",  # 空 → WARNING
            output_contract={},  # 空 → WARNING
            side_effects={},  # 空 → WARNING
            token_policy={},  # 空 → INFO
            input_schema={
                "type": "object",
                "properties": {
                    "data": {"type": "string"},  # 泛化 → WARNING
                    "query": {"type": "string"},
                },
                # 缺 required → WARNING
            },
        )

        eval_spec = EvalSpec.from_dict(
            {
                "name": "test",
                "scenarios": [{"id": "s1", "goal": "test"}],
                "tools": [],
            },
            source_path="/tmp",
        )

        evidence = Evidence(
            trace=ExecutionTrace(
                scenario_id="s1",
                tool_calls=[
                    ToolCall(
                        tool_name="test.tool", arguments={"data": "x"}, call_id="c1"
                    )
                ],
                tool_results=[
                    ToolResult(
                        call_id="c1", tool_name="test.tool", status="success"
                    )
                ],
            )
        )

        result = CoreEvaluation(spec_inspector=inspector).evaluate(
            evidence, eval_spec, tool_specs=[spec]
        )

        # WARNING/INFO findings 不影响 passed——spec inspection rules 全 rule_passed=True
        spec_findings = [
            f
            for f in result.findings
            if isinstance(f, RuleFinding)
            and f.rule_type.startswith("tool_spec.")
        ]
        for f in spec_findings:
            assert f.rule_passed is True, f"{f.rule_type}: {f.message}"


# ---------------------------------------------------------------------------
# INFO rule
# ---------------------------------------------------------------------------


class TestInfoRule:
    """INFO: token_policy.defined。"""

    def test_empty_token_policy_is_info(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(token_policy={})
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_spec.token_policy.defined")
        assert f.rule_passed is True  # INFO 不影响 passed
        assert f.severity == "low"

    def test_info_does_not_affect_passed(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(token_policy={})
        findings = inspector.inspect([spec])

        for f in findings:
            assert f.rule_passed is True  # well-formed spec, 只有 INFO 违规


# ---------------------------------------------------------------------------
# Severity / passed boundary 集成测试
# ---------------------------------------------------------------------------


class TestSeverityPassedBoundary:
    """severity ↔ rule_passed ↔ EvaluationResult.passed 边界。"""

    def test_high_severity_error_produces_rule_passed_false(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(description="")
        findings = inspector.inspect([spec])

        desc_f = _find_by_rule_type(findings, "tool_spec.description.exists")
        assert desc_f.severity == "high"
        assert desc_f.rule_passed is False

    def test_medium_severity_warning_produces_rule_passed_true(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(
            when_to_use="",
            when_not_to_use="",
            output_contract={},
            side_effects={},
            input_schema={
                "type": "object",
                "properties": {"q": {"type": "string"}},
            },
        )
        findings = inspector.inspect([spec])

        for f in findings:
            if f.severity == "medium":
                assert f.rule_passed is True, f"{f.rule_type}: {f.message}"

    def test_low_severity_info_produces_rule_passed_true(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(token_policy={})
        findings = inspector.inspect([spec])

        info_findings = [f for f in findings if f.severity == "low"]
        assert len(info_findings) >= 1
        for f in info_findings:
            assert f.rule_passed is True

    def test_judge_finding_does_not_affect_passed(self):
        """JudgeFinding 的 severity 不影响 deterministic passed。"""
        result = EvaluationResult(
            scenario_id="test",
            findings=[
                RuleFinding(
                    finding_id="r1",
                    severity="high",
                    category="rule",
                    message="rule passed",
                    evidence_ref="e1",
                    rule_passed=True,
                ),
                JudgeFinding(
                    finding_id="j1",
                    severity="high",
                    category="judge",
                    message="judge says bad",
                    evidence_ref="e1",
                ),
            ],
            passed=True,
        )
        # passed 只用 RuleFinding 计算
        passed = all(
            f.rule_passed for f in result.findings if isinstance(f, RuleFinding)
        )
        assert passed is True

    def test_review_decision_not_auto_generated(self):
        """ReviewDecision 不属于 CoreEvaluation 产出。"""
        # CoreEvaluation 只产出 EvaluationResult，无 ReviewDecision
        from agent_tool_harness.core_contract import ReviewDecision

        assert not hasattr(EvaluationResult, "review_decision")
        # ReviewDecision 必须由人工显式创建
        rd = ReviewDecision(
            decision="approved", reviewer="human", notes="ok"
        )
        assert rd.decision == "approved"


# ---------------------------------------------------------------------------
# CoreEvaluation 集成
# ---------------------------------------------------------------------------


class TestCoreEvaluationIntegration:
    """CoreEvaluation + ToolSpecInspector 集成路径。"""

    def test_spec_inspector_appends_findings(self):
        from agent_tool_harness.config.eval_spec import EvalSpec
        from agent_tool_harness.core_contract import (
            Evidence,
            ExecutionTrace,
            ToolCall,
            ToolResult,
        )

        inspector = ToolSpecInspector()
        spec = _make_tool_spec()

        eval_spec = EvalSpec.from_dict(
            {
                "name": "test",
                "scenarios": [{"id": "s1", "goal": "test"}],
                "tools": [],
            },
            source_path="/tmp",
        )
        evidence = Evidence(
            trace=ExecutionTrace(
                scenario_id="s1",
                tool_calls=[
                    ToolCall(
                        tool_name="kb.search", arguments={}, call_id="c1"
                    )
                ],
                tool_results=[
                    ToolResult(
                        call_id="c1", tool_name="kb.search", status="success"
                    )
                ],
            )
        )

        result = CoreEvaluation(spec_inspector=inspector).evaluate(
            evidence, eval_spec, tool_specs=[spec]
        )

        spec_findings = [
            f
            for f in result.findings
            if isinstance(f, RuleFinding)
            and f.rule_type.startswith("tool_spec.")
        ]
        assert len(spec_findings) == 10

    def test_no_tool_specs_no_spec_findings(self):
        """tool_specs=None 时不运行 spec inspection，向后兼容。"""
        from agent_tool_harness.config.eval_spec import EvalSpec
        from agent_tool_harness.core_contract import (
            Evidence,
            ExecutionTrace,
            ToolCall,
            ToolResult,
        )

        inspector = ToolSpecInspector()

        eval_spec = EvalSpec.from_dict(
            {
                "name": "test",
                "scenarios": [{"id": "s1", "goal": "test"}],
                "tools": [],
            },
            source_path="/tmp",
        )
        evidence = Evidence(
            trace=ExecutionTrace(
                scenario_id="s1",
                tool_calls=[
                    ToolCall(tool_name="t", arguments={}, call_id="c1")
                ],
                tool_results=[
                    ToolResult(call_id="c1", tool_name="t", status="success")
                ],
            )
        )

        # 不传 tool_specs → 无 spec findings
        result = CoreEvaluation(spec_inspector=inspector).evaluate(
            evidence, eval_spec
        )
        spec_findings = [
            f
            for f in result.findings
            if isinstance(f, RuleFinding)
            and f.rule_type.startswith("tool_spec.")
        ]
        assert len(spec_findings) == 0

    def test_no_spec_inspector_backward_compat(self):
        """无 spec_inspector 的 CoreEvaluation 行为不变。"""
        from agent_tool_harness.config.eval_spec import EvalSpec
        from agent_tool_harness.core_contract import (
            Evidence,
            ExecutionTrace,
            ToolCall,
            ToolResult,
        )

        eval_spec = EvalSpec.from_dict(
            {
                "name": "test",
                "scenarios": [{"id": "s1", "goal": "test"}],
                "tools": [],
            },
            source_path="/tmp",
        )
        evidence = Evidence(
            trace=ExecutionTrace(
                scenario_id="s1",
                tool_calls=[
                    ToolCall(tool_name="t", arguments={}, call_id="c1")
                ],
                tool_results=[
                    ToolResult(call_id="c1", tool_name="t", status="success")
                ],
            )
        )

        # 默认构造（无 spec_inspector）
        result = CoreEvaluation().evaluate(evidence, eval_spec)
        spec_findings = [
            f
            for f in result.findings
            if isinstance(f, RuleFinding)
            and f.rule_type.startswith("tool_spec.")
        ]
        assert len(spec_findings) == 0

    def test_tool_specs_ignored_when_no_spec_inspector(self):
        """传了 tool_specs 但没有 spec_inspector 时应安全忽略。"""
        from agent_tool_harness.config.eval_spec import EvalSpec
        from agent_tool_harness.core_contract import (
            Evidence,
            ExecutionTrace,
            ToolCall,
            ToolResult,
        )

        spec = _make_tool_spec(description="")
        eval_spec = EvalSpec.from_dict(
            {
                "name": "test",
                "scenarios": [{"id": "s1", "goal": "test"}],
                "tools": [],
            },
            source_path="/tmp",
        )
        evidence = Evidence(
            trace=ExecutionTrace(
                scenario_id="s1",
                tool_calls=[
                    ToolCall(tool_name="t", arguments={}, call_id="c1")
                ],
                tool_results=[
                    ToolResult(call_id="c1", tool_name="t", status="success")
                ],
            )
        )

        # 无 spec_inspector 但有 tool_specs → 安全忽略
        result = CoreEvaluation().evaluate(
            evidence, eval_spec, tool_specs=[spec]
        )
        spec_findings = [
            f
            for f in result.findings
            if isinstance(f, RuleFinding)
            and f.rule_type.startswith("tool_spec.")
        ]
        assert len(spec_findings) == 0


# ---------------------------------------------------------------------------
# 边界情况
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_minimal_tool_spec_triggers_error_findings(self):
        inspector = ToolSpecInspector()
        spec = _make_minimal_tool_spec()
        findings = inspector.inspect([spec])

        # 至少 description.exists 和 input_schema.exists 应该是 ERROR
        desc_f = _find_by_rule_type(findings, "tool_spec.description.exists")
        schema_f = _find_by_rule_type(findings, "tool_spec.input_schema.exists")

        # description="minimal" → 非空 → passed
        assert desc_f.rule_passed is True
        # 无 input_schema → ERROR
        assert schema_f.rule_passed is False

    def test_none_input_schema(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(input_schema=None)
        findings = inspector.inspect([spec])

        schema_f = _find_by_rule_type(findings, "tool_spec.input_schema.exists")
        assert schema_f.rule_passed is False

    def test_none_output_contract(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(output_contract=None)
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_spec.output_contract.documented")
        assert f.rule_passed is True  # WARNING
        assert "empty" in f.message

    def test_finding_id_includes_qualified_name(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec()
        findings = inspector.inspect([spec])

        for f in findings:
            assert spec.qualified_name in f.finding_id, f.finding_id

    def test_evidence_ref_points_to_tool_spec(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec()
        findings = inspector.inspect([spec])

        for f in findings:
            assert spec.qualified_name in f.evidence_ref, f.evidence_ref

    def test_side_effects_destructive_only_still_documented(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(
            side_effects={"destructive": True, "open_world_access": False}
        )
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_spec.side_effects.documented")
        assert "destructive" in f.message

    def test_side_effects_open_world_only_still_documented(self):
        inspector = ToolSpecInspector()
        spec = _make_tool_spec(
            side_effects={"destructive": False, "open_world_access": True}
        )
        findings = inspector.inspect([spec])

        f = _find_by_rule_type(findings, "tool_spec.side_effects.documented")
        assert "open_world_access" in f.message

    def test_no_network_dependency(self):
        """ToolSpecInspector 不 import 任何网络/LLM 模块。"""
        import sys

        network_modules = {
            "httpx",
            "requests",
            "urllib3",
            "aiohttp",
            "openai",
            "anthropic",
        }
        module = sys.modules.get("agent_tool_harness.tool_spec_inspection")
        if module:
            for attr in dir(module):
                obj = getattr(module, attr)
                if hasattr(obj, "__module__"):
                    for bad in network_modules:
                        assert bad not in str(obj.__module__), (
                            f"found {bad} via {attr}"
                        )

    def test_no_env_dependency(self):
        """ToolSpecInspector 不 import os.environ。"""
        import inspect

        from agent_tool_harness import tool_spec_inspection

        source = inspect.getsource(tool_spec_inspection)
        assert "os.environ" not in source
        assert "os.getenv" not in source
        assert "dotenv" not in source


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _find_by_rule_type(findings: list[RuleFinding], rule_type: str) -> RuleFinding:
    for f in findings:
        if f.rule_type == rule_type:
            return f
    raise AssertionError(f"finding with rule_type={rule_type!r} not found")
