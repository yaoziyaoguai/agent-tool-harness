import json

import pytest

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.loader import load_evals, load_project, load_tools
from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.judges.rule_judge import RuleJudge
from agent_tool_harness.recorder.run_recorder import RunRecorder
from agent_tool_harness.runner.eval_runner import EvalRunner
from agent_tool_harness.tools.executor_base import ToolExecutionResult
from agent_tool_harness.tools.python_executor import PythonToolExecutor
from agent_tool_harness.tools.registry import ToolRegistry, ToolRegistryError


class FailingAdapter:
    """测试用 adapter：故意在模型/adapter 阶段抛错。

    它模拟真实团队接入 adapter 后，模型调用链路或解析逻辑在工具调用前失败的场景。测试重点
    不是让 adapter 成功，而是确认 EvalRunner 仍然能写完整 artifacts 供复盘。
    """

    def run(self, case, registry, recorder):  # noqa: ANN001
        """抛出 adapter 异常，验证 runner 的失败证据兜底。"""

        raise RuntimeError(f"adapter exploded for {case.id}")


class NoCallAdapter:
    """测试用 adapter：如果被调用就失败。

    它用于证明 EvalQualityAuditor 判定不可运行时，EvalRunner 不会无视 audit 结果继续执行。
    """

    def __init__(self):
        self.called = False

    def run(self, case, registry, recorder):  # noqa: ANN001
        """记录错误调用并抛错；正常测试路径不应该进入这里。"""

        self.called = True
        raise AssertionError("EvalRunner should skip non-runnable evals")


class FakeExecutor:
    """测试用 executor：返回稳定 evidence，不连接任何真实外部系统。

    它让 MockReplayAdapter 可以在自定义工具名上运行，证明 replay 路径来自 eval/tools 配置，
    而不是来自 runtime_debug demo 的硬编码工具名。
    """

    def execute(self, tool: ToolSpec, arguments: dict) -> ToolExecutionResult:
        """返回包含 tool.name 的 evidence，方便测试判断调用序列。"""

        return ToolExecutionResult(
            success=True,
            content={
                "summary": f"{tool.name} executed",
                "technical_id": tool.name,
                "evidence": [{"id": f"{tool.name}-evidence", "label": f"{tool.name} evidence"}],
                "next_action": "continue",
            },
            metadata={"arguments": arguments},
        )


def _tool(name: str, namespace: str = "custom") -> ToolSpec:
    return ToolSpec(
        name=name,
        namespace=namespace,
        version="0.1",
        description="Custom test tool with enough description for registry-focused tests.",
        when_to_use="Use in tests when a deterministic fake tool response is needed.",
        when_not_to_use="Do not use outside test fixtures.",
        input_schema={
            "type": "object",
            "required": ["case_id"],
            "properties": {
                "case_id": {"type": "string"},
                "response_format": {"type": "string", "default": "concise"},
            },
        },
        output_contract={"required_fields": ["summary", "evidence", "next_action"]},
        token_policy={"max_output_tokens": 100, "default_limit": 10},
        side_effects={"destructive": False, "open_world_access": False},
        executor={"type": "fake"},
    )


def _eval_case(
    *,
    required_tools: list[str] | None = None,
    forbidden_first_tool: str | None = None,
    initial_context: dict | None = None,
    verifiable_outcome: dict | None = None,
) -> EvalSpec:
    rules = [
        {"type": "must_use_evidence"},
        {"type": "expected_root_cause_contains", "text": "custom_root"},
    ]
    if forbidden_first_tool:
        rules.append({"type": "forbidden_first_tool", "tool": forbidden_first_tool})
    return EvalSpec(
        id="custom_eval",
        name="Custom eval",
        category="custom",
        split="regression",
        realism_level="regression",
        complexity="multi_step",
        source="test",
        user_prompt="A realistic user asks the agent to diagnose a custom incident.",
        initial_context={"case_id": "case-123"} if initial_context is None else initial_context,
        verifiable_outcome=(
            {"expected_root_cause": "custom_root", "evidence_ids": ["alpha-evidence"]}
            if verifiable_outcome is None
            else verifiable_outcome
        ),
        success_criteria=["Use evidence."],
        expected_tool_behavior={"required_tools": required_tools or ["alpha", "beta"]},
        judge={"rules": rules},
    )


def test_runner_preserves_artifacts_when_adapter_raises(tmp_path):
    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")
    evals = load_evals("examples/runtime_debug/evals.yaml")

    result = EvalRunner().run(project, tools, evals, FailingAdapter(), tmp_path)

    for artifact in EvalRunner.REQUIRED_ARTIFACTS:
        assert (tmp_path / artifact).exists(), artifact
    transcript = (tmp_path / "transcript.jsonl").read_text(encoding="utf-8")
    judge = json.loads((tmp_path / "judge_results.json").read_text(encoding="utf-8"))
    diagnosis = json.loads((tmp_path / "diagnosis.json").read_text(encoding="utf-8"))

    assert "runner_error" in transcript
    assert result["metrics"]["error_evals"] == 1
    assert judge["results"][0]["passed"] is False
    assert judge["results"][0]["checks"][0]["rule"]["type"] == "adapter_execution_failed"
    assert diagnosis["results"][0]["passed"] is False


def test_runner_uses_eval_audit_runnable_gate(tmp_path):
    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")
    adapter = NoCallAdapter()
    weak_eval = _eval_case(initial_context={}, verifiable_outcome={})

    result = EvalRunner().run(project, tools, [weak_eval], adapter, tmp_path)

    judge = json.loads((tmp_path / "judge_results.json").read_text(encoding="utf-8"))
    transcript = (tmp_path / "transcript.jsonl").read_text(encoding="utf-8")
    assert adapter.called is False
    assert result["metrics"]["executed_evals"] == 0
    assert result["metrics"]["skipped_evals"] == 1
    assert judge["results"][0]["checks"][0]["rule"]["type"] == "eval_not_runnable"
    assert "runner_skip" in transcript


def test_mock_replay_adapter_uses_eval_tools_instead_of_demo_names(tmp_path):
    tools = [_tool("alpha"), _tool("beta"), _tool("gamma")]
    registry = ToolRegistry(tools, executors={"fake": FakeExecutor()})
    case = _eval_case(required_tools=["alpha", "beta"], forbidden_first_tool="gamma")

    good = MockReplayAdapter("good").run(case, registry, RunRecorder(tmp_path / "good"))
    bad = MockReplayAdapter("bad").run(case, registry, RunRecorder(tmp_path / "bad"))

    assert [call["tool_name"] for call in good.tool_calls] == ["alpha", "beta"]
    assert [call["tool_name"] for call in bad.tool_calls] == ["gamma"]
    assert "runtime_trace_event_chain" not in json.dumps(good.tool_calls)
    assert "runtime_trace_event_chain" not in json.dumps(bad.tool_calls)


def test_tool_registry_rejects_ambiguous_short_names():
    registry = ToolRegistry([_tool("search", "svc_a"), _tool("search", "svc_b")])

    with pytest.raises(ToolRegistryError):
        registry.get("search")

    result = registry.execute("search", {"case_id": "case-123"})
    assert result.success is False
    assert "ambiguous tool name" in (result.error or "")
    assert registry.get("svc_a.search").qualified_name == "svc_a.search"


def test_python_executor_validates_schema_and_binds_single_named_argument(tmp_path):
    tool_file = tmp_path / "user_tools.py"
    tool_file.write_text(
        """
def echo(query):
    return {"summary": query, "evidence": [{"id": query}], "next_action": "done"}
""",
        encoding="utf-8",
    )
    tool = ToolSpec(
        name="echo",
        namespace="test",
        version="0.1",
        description="Echo query for executor binding tests.",
        when_to_use="Use when testing PythonToolExecutor argument binding.",
        when_not_to_use="Do not use in production.",
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
        },
        output_contract={"required_fields": ["summary", "evidence", "next_action"]},
        token_policy={},
        side_effects={"destructive": False, "open_world_access": False},
        executor={"type": "python", "path": str(tool_file), "function": "echo"},
    )

    ok = PythonToolExecutor().execute(tool, {"query": "abc"})
    missing = PythonToolExecutor().execute(tool, {})
    wrong_type = PythonToolExecutor().execute(tool, {"query": 123})

    assert ok.success is True
    assert ok.content["summary"] == "abc"
    assert missing.success is False
    assert "missing required argument" in (missing.error or "")
    assert wrong_type.success is False
    assert "must be string" in (wrong_type.error or "")


def test_rule_judge_rejects_empty_root_cause_and_uncited_evidence():
    empty_root_case = _eval_case(verifiable_outcome={"expected_root_cause": ""})
    empty_root_case = EvalSpec(
        **{
            **empty_root_case.to_dict(),
            "judge": {"rules": [{"type": "expected_root_cause_contains"}]},
        }
    )
    run = AgentRunResult(
        eval_id=empty_root_case.id,
        final_answer="Root cause: anything. Evidence: ev-1.",
        tool_calls=[],
        tool_responses=[
            {"response": {"success": True, "content": {"evidence": [{"id": "ev-1"}]}}}
        ],
    )
    empty_result = RuleJudge().judge(empty_root_case, run)
    assert empty_result.passed is False
    assert "non-empty text" in empty_result.checks[0].message

    evidence_case = EvalSpec(
        **{**_eval_case().to_dict(), "judge": {"rules": [{"type": "must_use_evidence"}]}}
    )
    uncited = AgentRunResult(
        eval_id=evidence_case.id,
        final_answer="The answer says Evidence exists but cites no id.",
        tool_calls=[],
        tool_responses=[
            {"response": {"success": True, "content": {"evidence": [{"id": "ev-1"}]}}}
        ],
    )
    cited = AgentRunResult(
        eval_id=evidence_case.id,
        final_answer="Evidence: ev-1 supports the conclusion.",
        tool_calls=[],
        tool_responses=uncited.tool_responses,
    )

    assert RuleJudge().judge(evidence_case, uncited).passed is False
    assert RuleJudge().judge(evidence_case, cited).passed is True
