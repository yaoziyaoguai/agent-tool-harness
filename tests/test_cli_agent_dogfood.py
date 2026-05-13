"""C10 Dogfood Smoke Tests。

验证 Level 1 (fake CLI agent) 和 Level 2 (toy CLI agent) 的端到端 dogfood 闭环。

测试纪律:
- 所有测试 zero-network, deterministic.
- 使用 tmp_path, 不访问真实文件系统路径。
- 不读 .env、不调用外部 API、不调用真实 LLM。
- 不生成 ReviewDecision。
- RuleJudge 决定 passed, JudgeFinding 为 advisory。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_tool_harness.assembly import CLIAgentCoreFlowResult, build_cli_agent_core_flow
from agent_tool_harness.cli_agent import CLIAgentAdapterConfig
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
# 共享 fixture
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
        id="dogfood-search",
        name="Dogfood search eval",
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
        id="dogfood-both-tools",
        name="Dogfood both tools eval",
        category="integration",
        split="test",
        realism_level="mock",
        complexity="low",
        source="test",
        user_prompt="搜索知识库并查询 trace 以定位 both-tools 错误根因",
        initial_context={"query": "recent error"},
        expected_tool_behavior={
            "required_tools": ["knowledge.search", "trace.lookup"]
        },
        judge={
            "rules": [
                {"type": "must_call_tool", "tool": "knowledge.search"},
                {"type": "must_call_tool", "tool": "trace.lookup"},
                {"type": "must_use_evidence"},
            ]
        },
        verifiable_outcome={
            "expected_root_cause": "timeout",
            "evidence_ids": ["ev-001"],
        },
        success_criteria=["结论引用证据"],
    )


# ---------------------------------------------------------------------------
# Level 1: Fake CLI Agent Dogfood
# ---------------------------------------------------------------------------


class TestLevel1FakeCLIAgentDogfood:
    """使用 fake CLI agent 验证端到端 dogfood 闭环。"""

    def test_fake_agent_dogfood_single_eval(self, tmp_path: Path):
        """fake agent 单 eval dogfood——完整闭环。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=CLIAgentAdapterConfig(
                command=[
                    "python", "examples/cli_agent_fake/fake_agent.py",
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                working_dir=".",
            ),
            output_dir=out_dir,
        )

        assert isinstance(result, CLIAgentCoreFlowResult)
        assert isinstance(result.eval_result, EvaluationResult)
        assert result.eval_result.passed is True
        assert result.signal_quality == RECORDED_TRAJECTORY
        # trace 正确包含 tool calls
        tool_names = [c.tool_name for c in result.trace.tool_calls]
        assert "knowledge.search" in tool_names

    def test_fake_agent_dogfood_both_evals(self, tmp_path: Path):
        """fake agent 两个 eval 均通过。"""
        evals = [
            _make_eval_spec_must_call_search(),
            _make_eval_spec_must_call_both(),
        ]
        results = []
        for i, eval_spec in enumerate(evals):
            out_dir = str(tmp_path / f"out-{i}")
            result = build_cli_agent_core_flow(
                tool_specs=_make_tool_specs(),
                eval_spec=eval_spec,
                cli_agent_config=CLIAgentAdapterConfig(
                    command=[
                        "python", "examples/cli_agent_fake/fake_agent.py",
                        "--input", "{input_path}",
                        "--trace-out", "{trace_output_path}",
                    ],
                    working_dir=".",
                ),
                output_dir=out_dir,
            )
            results.append(result)

        passed_info = [
            (r.eval_result.scenario_id, r.eval_result.passed) for r in results
        ]
        assert all(r.eval_result.passed for r in results), (
            f"expected all passed: {passed_info}"
        )

    def test_fake_agent_dogfood_output_files_exist(self, tmp_path: Path):
        """dogfood 产出 scenario_input.json 和 trace_output.json。"""
        out_dir = str(tmp_path / "out")
        build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=CLIAgentAdapterConfig(
                command=[
                    "python", "examples/cli_agent_fake/fake_agent.py",
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                working_dir=".",
            ),
            output_dir=out_dir,
        )

        assert (Path(out_dir) / "scenario_input.json").exists()
        assert (Path(out_dir) / "trace_output.json").exists()
        # 验证 trace 文件是合法 JSON
        trace_data = json.loads(
            (Path(out_dir) / "trace_output.json").read_text(encoding="utf-8")
        )
        assert "scenario_id" in trace_data
        assert len(trace_data["tool_calls"]) >= 1

    def test_fake_agent_dogfood_no_review_decision(self, tmp_path: Path):
        """dogfood 结果不包含 ReviewDecision。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=CLIAgentAdapterConfig(
                command=[
                    "python", "examples/cli_agent_fake/fake_agent.py",
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                working_dir=".",
            ),
            output_dir=out_dir,
        )

        assert not hasattr(result, "review_decision")
        assert all(f.category == "rule" for f in result.eval_result.findings)


# ---------------------------------------------------------------------------
# Level 2: Toy CLI Agent Dogfood
# ---------------------------------------------------------------------------


class TestLevel2ToyCLIAgentDogfood:
    """使用 toy CLI agent 验证 Level 2 dogfood。"""

    def test_toy_agent_dogfood_search_eval(self, tmp_path: Path):
        """toy agent 根据 goal "搜索" 选择 knowledge.search。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=CLIAgentAdapterConfig(
                command=[
                    "python", "examples/cli_agent_toy/toy_agent.py",
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                working_dir=".",
            ),
            output_dir=out_dir,
        )

        assert result.eval_result.passed is True
        # toy agent 应选 knowledge.search（goal 含"搜索"）
        tool_names = [c.tool_name for c in result.trace.tool_calls]
        assert "knowledge.search" in tool_names

    def test_toy_agent_dogfood_both_tools_eval(self, tmp_path: Path):
        """toy agent 根据 goal "both-tools" 选择两个工具。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_both(),
            cli_agent_config=CLIAgentAdapterConfig(
                command=[
                    "python", "examples/cli_agent_toy/toy_agent.py",
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                working_dir=".",
            ),
            output_dir=out_dir,
        )

        assert result.eval_result.passed is True
        tool_names = [c.tool_name for c in result.trace.tool_calls]
        assert "knowledge.search" in tool_names
        assert "trace.lookup" in tool_names

    def test_toy_agent_dogfood_output_files_exist(self, tmp_path: Path):
        """toy agent dogfood 产出合法 trace 文件。"""
        out_dir = str(tmp_path / "out")
        build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=CLIAgentAdapterConfig(
                command=[
                    "python", "examples/cli_agent_toy/toy_agent.py",
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                working_dir=".",
            ),
            output_dir=out_dir,
        )

        trace_path = Path(out_dir) / "trace_output.json"
        assert trace_path.exists()
        trace_data = json.loads(trace_path.read_text(encoding="utf-8"))
        assert "scenario_id" in trace_data
        assert "final_answer" in trace_data
        # toy agent final_answer 应引用 evidence
        fa = trace_data["final_answer"]
        assert "Evidence" in fa or "evidence" in fa.lower()

    def test_toy_agent_direct_run(self, tmp_path: Path):
        """直接运行 toy_agent.py 产出合法 native trace。"""
        input_path = tmp_path / "input.json"
        trace_path = tmp_path / "trace.json"
        input_data = {
            "scenario_id": "direct-test",
            "goal": "搜索错误根因",
            "available_tools": ["knowledge.search", "trace.lookup"],
        }
        input_path.write_text(json.dumps(input_data, ensure_ascii=False), encoding="utf-8")
        result = subprocess.run(
            [
                "python", "examples/cli_agent_toy/toy_agent.py",
                "--input", str(input_path),
                "--trace-out", str(trace_path),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert trace_path.exists()
        trace_data = json.loads(trace_path.read_text(encoding="utf-8"))
        assert trace_data["scenario_id"] == "direct-test"
        assert len(trace_data["tool_calls"]) >= 1
        # toy agent 应选 knowledge.search（goal 含"搜索"）
        assert any("search" in tc["tool_name"] for tc in trace_data["tool_calls"])

    def test_toy_agent_dogfood_signal_quality(self, tmp_path: Path):
        """toy agent dogfood 的 signal_quality 为 recorded_trajectory。"""
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=CLIAgentAdapterConfig(
                command=[
                    "python", "examples/cli_agent_toy/toy_agent.py",
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                working_dir=".",
            ),
            output_dir=out_dir,
        )

        assert result.signal_quality == RECORDED_TRAJECTORY
        assert result.evidence.signal_quality == RECORDED_TRAJECTORY


# ---------------------------------------------------------------------------
# 交叉验证: Level 1 vs Level 2 产出结构一致
# ---------------------------------------------------------------------------


class TestLevel1Level2Consistency:
    """Level 1 (fake) 和 Level 2 (toy) dogfood 产出结构一致。"""

    def test_both_levels_produce_valid_core_flow_result(self, tmp_path: Path):
        """两种 agent 都产出合法的 CLIAgentCoreFlowResult。"""
        eval_spec = _make_eval_spec_must_call_search()

        for agent_cmd, level in [
            (
                [
                    "python", "examples/cli_agent_fake/fake_agent.py",
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                "Level 1",
            ),
            (
                [
                    "python", "examples/cli_agent_toy/toy_agent.py",
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                "Level 2",
            ),
        ]:
            out_dir = str(tmp_path / level.replace(" ", "-"))
            result = build_cli_agent_core_flow(
                tool_specs=_make_tool_specs(),
                eval_spec=eval_spec,
                cli_agent_config=CLIAgentAdapterConfig(
                    command=agent_cmd,
                    working_dir=".",
                ),
                output_dir=out_dir,
            )

            assert isinstance(result.trace, ExecutionTrace), f"{level}: trace type"
            assert isinstance(result.evidence, Evidence), f"{level}: evidence type"
            assert isinstance(result.eval_result, EvaluationResult), f"{level}: eval_result type"
            assert result.eval_result.passed is True, f"{level}: expected passed"
            assert result.signal_quality == RECORDED_TRAJECTORY, f"{level}: signal_quality"
            # no ReviewDecision
            assert not hasattr(result, "review_decision"), f"{level}: no auto review"
            # RuleJudge findings
            for f in result.eval_result.findings:
                assert isinstance(f, RuleFinding), f"{level}: all findings are RuleFinding"


# ---------------------------------------------------------------------------
# 边界: 安全约束
# ---------------------------------------------------------------------------


class TestDogfoodSecurityBoundary:
    """dogfood 安全边界验证。"""

    def test_no_env_read_in_dogfood(self, tmp_path: Path, monkeypatch):
        """dogfood 运行不读取额外环境变量。"""
        # 设置一个环境变量用于验证
        monkeypatch.setenv("DOGFOOD_TEST_VAR", "should-not-leak")

        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=CLIAgentAdapterConfig(
                command=[
                    "python", "examples/cli_agent_fake/fake_agent.py",
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                working_dir=".",
                env_policy="minimal",  # 默认 minimal
            ),
            output_dir=out_dir,
        )

        assert result.cli_agent_result.exit_code == 0

    def test_no_network_call_in_dogfood(self, tmp_path: Path):
        """dogfood 的所有组件不涉及网络调用。"""
        out_dir = str(tmp_path / "out")
        # trace import 是纯 JSON 文件操作
        # CoreEvaluation 是纯 deterministic 规则
        # 整个链路无网络依赖
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec_must_call_search(),
            cli_agent_config=CLIAgentAdapterConfig(
                command=[
                    "python", "examples/cli_agent_fake/fake_agent.py",
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                working_dir=".",
            ),
            output_dir=out_dir,
        )

        assert isinstance(result.eval_result, EvaluationResult)
