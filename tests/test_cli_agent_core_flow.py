"""CLIAgentAdapter Core Flow 集成测试 — Slice 4。

验证完整闭环：ScenarioSpec → CLIAgentAdapter → fake CLI agent → trace file
→ TraceImportAdapter → ExecutionTrace → Evidence → CoreEvaluation
→ EvaluationResult → ReportSummary。

测试纪律:
- 所有测试 zero-network, deterministic.
- 使用 fake CLI 命令（python -c / 临时脚本），不调用真实 Agent。
- 不读 .env、不调用外部 API。
- 不生成 ReviewDecision。
- RuleJudge 决定 passed，JudgeFinding 为 advisory。
- 不破坏 demo replay 路径。
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_tool_harness.assembly import (
    CLIAgentCoreFlowResult,
    build_cli_agent_core_flow,
    build_demo_core_flow,
)
from agent_tool_harness.cli_agent import (
    CLIAgentAdapterConfig,
)
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.core_contract import (
    EvaluationResult,
    Evidence,
    ExecutionTrace,
    RuleFinding,
)
from agent_tool_harness.signal_quality import RECORDED_TRAJECTORY

# ---------------------------------------------------------------------------
# 共享 fixture 数据
# ---------------------------------------------------------------------------


def _make_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="search",
            namespace="knowledge",
            version="1.0",
            description="搜索知识库",
            when_to_use="查找信息时",
            when_not_to_use="信息已知时",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            output_contract={"evidence": "list"},
            token_policy={"max_tokens_per_call": 1000},
            side_effects={"destructive": False},
            executor={"type": "python", "module": "search_tool"},
        ),
        ToolSpec(
            name="lookup",
            namespace="trace",
            version="1.0",
            description="查询 trace",
            when_to_use="需要 trace 详情时",
            when_not_to_use="不需要时",
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
            },
            output_contract={"evidence": "list"},
            token_policy={"max_tokens_per_call": 500},
            side_effects={"destructive": False},
            executor={"type": "python", "module": "lookup_tool"},
        ),
    ]


def _make_eval_spec_must_call_search() -> EvalSpec:
    return EvalSpec(
        id="fake-cli-search",
        name="Fake CLI agent search eval",
        category="integration",
        split="test",
        realism_level="mock",
        complexity="low",
        source="test",
        user_prompt="使用知识库搜索查找最近错误根因",
        initial_context={"query": "recent error"},
        expected_tool_behavior={"required_tools": ["knowledge.search"]},
        judge={
            "rules": [
                {"type": "must_call_tool", "tool": "knowledge.search"},
                {"type": "must_use_evidence"},
            ]
        },
        verifiable_outcome={
            "expected_root_cause": "timeout",
            "evidence_ids": ["ev-001"],
        },
        success_criteria=["结论引用证据"],
    )


def _make_eval_spec_must_call_both() -> EvalSpec:
    return EvalSpec(
        id="fake-cli-both-tools",
        name="Fake CLI agent both tools eval",
        category="integration",
        split="test",
        realism_level="mock",
        complexity="low",
        source="test",
        user_prompt="使用知识库搜索和 trace 查询定位最近错误根因",
        initial_context={"query": "recent error"},
        expected_tool_behavior={
            "required_tools": ["knowledge.search", "trace.lookup"]
        },
        judge={
            "rules": [
                {"type": "must_call_tool", "tool": "knowledge.search"},
                {"type": "must_call_tool", "tool": "trace.lookup"},
            ]
        },
        verifiable_outcome={
            "expected_root_cause": "timeout",
            "evidence_ids": ["ev-001"],
        },
        success_criteria=["结论引用证据"],
    )


# ---------------------------------------------------------------------------
# fake CLI agent helpers —— 临时 Python 脚本
# ---------------------------------------------------------------------------

_INPUT_ARG = "{input_path}"
_TRACE_ARG = "{trace_output_path}"

# 读取 scenario input + 写入带 knowledge.search 工具调用的 trace
# tool_results 含 evidence id，final_answer 引用 evidence
_FAKE_AGENT_SEARCH_SCRIPT = (
    "import json,sys,pathlib;"
    "args=sys.argv;"
    "trace_path=args[args.index('--trace-out')+1] if '--trace-out' in args else args[2];"
    "input_path=args[args.index('--input')+1] if '--input' in args else args[1];"
    "data=json.loads(pathlib.Path(input_path).read_text());"
    "sid=data.get('scenario_id','unknown');"
    "trace={'scenario_id':sid,"
    "'tool_calls':[{'call_id':'c1','tool_name':'knowledge.search','arguments':{'query':'test'}}],"
    "'tool_results':[{'call_id':'c1','tool_name':'knowledge.search','status':'success',"
    "'output':{'evidence':[{'id':'ev-001','label':'timeout root cause'}],'summary':'ok'}}],"
    "'final_answer':"
    "'Root cause: timeout. Evidence: ev-001 — SSO session storage misconfiguration.'};"
    "pathlib.Path(trace_path).parent.mkdir(parents=True,exist_ok=True);"
    "pathlib.Path(trace_path).write_text(json.dumps(trace))"
)


def _fake_agent_search_cmd() -> list[str]:
    """fake CLI agent——调用 knowledge.search 工具。"""
    return [
        "python", "-c",
        _FAKE_AGENT_SEARCH_SCRIPT,
        "--input", _INPUT_ARG,
        "--trace-out", _TRACE_ARG,
    ]


# 读取 scenario input + 写入带两个工具调用的 trace
_FAKE_AGENT_BOTH_SCRIPT = (
    "import json,sys,pathlib;"
    "args=sys.argv;"
    "trace_path=args[args.index('--trace-out')+1] if '--trace-out' in args else args[2];"
    "input_path=args[args.index('--input')+1] if '--input' in args else args[1];"
    "data=json.loads(pathlib.Path(input_path).read_text());"
    "sid=data.get('scenario_id','unknown');"
    "trace={'scenario_id':sid,"
    "'tool_calls':["
    "{'call_id':'c1','tool_name':'knowledge.search','arguments':{'query':'test'}},"
    "{'call_id':'c2','tool_name':'trace.lookup','arguments':{'id':'ev-001'}}"
    "],"
    "'tool_results':["
    "{'call_id':'c1','tool_name':'knowledge.search','status':'success',"
    "'output':{'evidence':[{'id':'ev-001','label':'timeout root cause'}],'summary':'ok'}},"
    "{'call_id':'c2','tool_name':'trace.lookup','status':'success',"
    "'output':{'evidence':[{'id':'ev-001','label':'timeout root cause'}],'detail':'SSO misconfig'}}"
    "],"
    "'final_answer':'Root cause: timeout. Evidence: ev-001 — found via search and trace lookup.'};"
    "pathlib.Path(trace_path).parent.mkdir(parents=True,exist_ok=True);"
    "pathlib.Path(trace_path).write_text(json.dumps(trace))"
)


def _fake_agent_both_cmd() -> list[str]:
    """fake CLI agent——调用 knowledge.search + trace.lookup 两个工具。"""
    return [
        "python", "-c",
        _FAKE_AGENT_BOTH_SCRIPT,
        "--input", _INPUT_ARG,
        "--trace-out", _TRACE_ARG,
    ]


# 写入空 trace + exit 1
_FAKE_AGENT_EXIT1_SCRIPT = (
    "import json,sys,pathlib;"
    "args=sys.argv;"
    "trace_path=args[args.index('--trace-out')+1] if '--trace-out' in args else args[2];"
    "trace={'scenario_id':'err','tool_calls':[],'tool_results':[],'final_answer':''};"
    "pathlib.Path(trace_path).parent.mkdir(parents=True,exist_ok=True);"
    "pathlib.Path(trace_path).write_text(json.dumps(trace));"
    "sys.exit(1)"
)


def _fake_agent_exit1_cmd() -> list[str]:
    """返回空 trace + exit code 1 的 fake agent。"""
    return [
        "python", "-c",
        _FAKE_AGENT_EXIT1_SCRIPT,
        "--input", _INPUT_ARG,
        "--trace-out", _TRACE_ARG,
    ]


def _valid_cli_config(command: list[str] | None = None) -> CLIAgentAdapterConfig:
    """构建合法 CLIAgentAdapterConfig。"""
    return CLIAgentAdapterConfig(
        command=command or _fake_agent_search_cmd(),
    )


# ---------------------------------------------------------------------------
# 1. 核心闭环 — happy path
# ---------------------------------------------------------------------------


class TestCLIAgentCoreFlowHappyPath:
    """build_cli_agent_core_flow() 端到端闭环。"""

    def test_end_to_end_closed_loop(self, tmp_path: Path):
        """完整闭环：ScenarioSpec → fake CLI agent → EvaluationResult → ReportSummary。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        assert isinstance(result, CLIAgentCoreFlowResult)
        assert isinstance(result.trace, ExecutionTrace)
        assert isinstance(result.evidence, Evidence)
        assert isinstance(result.eval_result, EvaluationResult)
        assert result.signal_quality == RECORDED_TRAJECTORY

    def test_closed_loop_passed_true_when_rules_satisfied(self, tmp_path: Path):
        """fake agent 调用了 knowledge.search → must_call_tool 规则通过。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        assert result.eval_result.passed is True, (
            f"expected passed=True, got {result.eval_result.passed}"
        )

    def test_rule_findings_in_eval_result(self, tmp_path: Path):
        """EvaluationResult 包含 RuleFinding（category="rule"）。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        assert len(result.eval_result.findings) >= 1
        for f in result.eval_result.findings:
            assert isinstance(f, RuleFinding)
            assert f.category == "rule"

    def test_trace_contains_tool_calls_from_fake_agent(self, tmp_path: Path):
        """ExecutionTrace 中的 tool_calls 来自 fake agent 输出。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        tool_names = [c.tool_name for c in result.trace.tool_calls]
        assert "knowledge.search" in tool_names

    def test_scenario_input_file_written(self, tmp_path: Path):
        """验证 scenario input JSON 被正确写入。"""
        out_dir = str(tmp_path / "out")
        build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        input_path = Path(out_dir) / "scenario_input.json"
        assert input_path.exists()
        data = json.loads(input_path.read_text(encoding="utf-8"))
        assert data["scenario_id"] == "fake-cli-search"
        assert "knowledge.search" in data["available_tools"]

    def test_both_tools_called_and_rules_pass(self, tmp_path: Path):
        """fake agent 调用两个工具，两条 must_call_tool 规则均通过。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_both(),
            cli_agent_config=_valid_cli_config(command=_fake_agent_both_cmd()),
            output_dir=out_dir,
        )

        assert result.eval_result.passed is True
        tool_names = [c.tool_name for c in result.trace.tool_calls]
        assert "knowledge.search" in tool_names
        assert "trace.lookup" in tool_names


# ---------------------------------------------------------------------------
# 2. CLI agent result 数据传递
# ---------------------------------------------------------------------------


class TestCLIAgentResultPropagation:
    """CLIAgentCoreFlowResult 正确传递 cli_agent_result 字段。"""

    def test_cli_agent_result_present(self, tmp_path: Path):
        """cli_agent_result 包含 exit_code / stdout / stderr / elapsed_seconds。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        car = result.cli_agent_result
        assert car.exit_code == 0
        assert len(car.stdout_summary) >= 0
        assert isinstance(car.elapsed_seconds, float)
        assert car.elapsed_seconds >= 0

    def test_cli_agent_result_errors_empty_on_success(self, tmp_path: Path):
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        assert result.cli_agent_result.errors == []

    def test_execution_trace_from_cli_result(self, tmp_path: Path):
        """CLIAgentCoreFlowResult.trace 与 cli_agent_result.execution_trace 一致。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        car_trace = result.cli_agent_result.execution_trace
        assert car_trace is not None
        assert result.trace.scenario_id == car_trace.scenario_id


# ---------------------------------------------------------------------------
# 3. Signal quality
# ---------------------------------------------------------------------------


class TestSignalQuality:
    """CLI agent 的 signal_quality 为 RECORDED_TRAJECTORY。"""

    def test_signal_quality_is_recorded_trajectory(self, tmp_path: Path):
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        assert result.signal_quality == RECORDED_TRAJECTORY

    def test_evidence_signal_quality(self, tmp_path: Path):
        """Evidence 中的 signal_quality 与 CLIAgentCoreFlowResult 一致。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        assert result.evidence.signal_quality == RECORDED_TRAJECTORY

    def test_signal_quality_not_tautological(self, tmp_path: Path):
        """CLI agent 的 signal_quality 不是 tautological_replay。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        assert result.signal_quality != "tautological_replay"


# ---------------------------------------------------------------------------
# 4. Metrics / ReportSummary
# ---------------------------------------------------------------------------


class TestMetricsAndReportSummary:
    """metrics 正确聚合，ReportSummary 正确构造。"""

    def test_metrics_contains_report_summary(self, tmp_path: Path):
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        assert "report_summary" in result.metrics
        rs = result.metrics["report_summary"]
        assert rs.total_scenarios == 1
        assert rs.signal_quality == RECORDED_TRAJECTORY

    def test_metrics_passed_count(self, tmp_path: Path):
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        assert result.metrics["passed"] == 1
        assert result.metrics["failed"] == 0


# ---------------------------------------------------------------------------
# 5. Error paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    """异常路径处理。"""

    def test_non_zero_exit_does_not_block_core_flow(self, tmp_path: Path):
        """CLI agent exit code != 0 不阻断 Core Flow。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(command=_fake_agent_exit1_cmd()),
            output_dir=out_dir,
        )

        # Core Flow 仍完成
        assert isinstance(result.eval_result, EvaluationResult)
        # cli_agent_result 记录 non-zero exit
        assert result.cli_agent_result.exit_code == 1
        # errors 包含 non-zero exit warning
        non_zero_errors = [
            e for e in result.cli_agent_result.errors if "non-zero" in e
        ]
        assert len(non_zero_errors) >= 1

    def test_empty_trace_passed_false(self, tmp_path: Path):
        """空 trace（没有 must_call 工具）→ passed=False。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(command=_fake_agent_exit1_cmd()),
            output_dir=out_dir,
        )

        # 空 trace 没有 knowledge.search → must_call_tool 失败
        assert result.eval_result.passed is False


# ---------------------------------------------------------------------------
# 6. 架构边界
# ---------------------------------------------------------------------------


class TestBoundaryGuards:
    """架构边界守卫。"""

    def test_no_review_decision_generated(self, tmp_path: Path):
        """CLIAgentCoreFlowResult 不包含 ReviewDecision。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        # result 中不应有 ReviewDecision 字段
        assert not hasattr(result, "review_decision")

        # metrics 中不应有 ReviewDecision
        assert "review_decision" not in result.metrics

    def test_rule_judge_determines_passed(self, tmp_path: Path):
        """passed 由 RuleJudge 的 deterministic 规则决定。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        # 所有 findings 来自 RuleJudge
        rule_findings = [
            f for f in result.eval_result.findings if f.category == "rule"
        ]
        assert len(rule_findings) >= 1

        # passed 由所有 RuleFinding.rule_passed 的 AND 决定
        all_rule_passed = all(
            f.rule_passed for f in rule_findings
        )
        assert result.eval_result.passed == all_rule_passed

    def test_no_judge_findings_without_judge_provider(self, tmp_path: Path):
        """没有 judge_provider 时不产生 JudgeFinding。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        judge_findings = [
            f for f in result.eval_result.findings if f.category == "judge"
        ]
        assert len(judge_findings) == 0

    def test_demo_core_flow_still_works(self, tmp_path: Path):
        """build_demo_core_flow() 不应被 CLI agent 改动影响。"""
        tool_specs = _make_tool_specs()
        # 使用不含 must_use_evidence 的简化 eval spec — MockReplayAdapter
        # 的 tool execution 需要真实 Python 函数才能产出 evidence，这里只验证
        # demo 路径未被破坏即可。
        eval_only_must_call = EvalSpec(
            id="demo-smoke",
            name="demo smoke test",
            category="integration",
            split="test",
            realism_level="mock",
            complexity="low",
            source="test",
            user_prompt="搜索知识库",
            initial_context={"query": "test"},
            expected_tool_behavior={"required_tools": ["knowledge.search"]},
            judge={
                "rules": [
                    {"type": "must_call_tool", "tool": "knowledge.search"},
                ]
            },
            verifiable_outcome={
                "expected_root_cause": "timeout",
                "evidence_ids": ["ev-001"],
            },
            success_criteria=["调用知识库搜索"],
        )

        demo_result = build_demo_core_flow(
            tool_specs=tool_specs,
            eval_spec=eval_only_must_call,
            mock_path="good",
        )

        assert demo_result.signal_quality == "tautological_replay"

    def test_output_dir_contains_input_and_trace_files(self, tmp_path: Path):
        """output_dir 包含 scenario_input.json 和 trace_output.json。"""
        out_dir = str(tmp_path / "out")
        build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=_valid_cli_config(),
            output_dir=out_dir,
        )

        assert (Path(out_dir) / "scenario_input.json").exists()
        assert (Path(out_dir) / "trace_output.json").exists()
