"""Level 3 my-first-agent demo adapter 测试。

测试纪律:
- adapter 内部逻辑：使用 mock 对象，不依赖真实 my-first-agent import。
- 集成路径：通过 subprocess 调用真实 adapter，验证完整闭环。
- 所有测试 zero-network, deterministic。
- 不读 .env、不调用外部 API、不调用真实 LLM。
- 不生成 ReviewDecision。
"""

from __future__ import annotations

# adapter 内部函数——通过 importlib 加载（examples/ 不是 Python package，
# 避免为测试添加 __init__.py 污染 examples 目录）。
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_tool_harness.assembly import CLIAgentCoreFlowResult, build_cli_agent_core_flow
from agent_tool_harness.cli_agent import CLIAgentAdapterConfig
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.core_contract import (
    EvaluationResult,
    ExecutionTrace,
)
from agent_tool_harness.signal_quality import RECORDED_TRAJECTORY
from agent_tool_harness.trace_import import TraceImportAdapter

_ADAPTER_MODULE_PATH = (
    Path(__file__).resolve().parent.parent
    / "examples" / "my_first_agent_demo" / "adapter.py"
)

_spec = importlib.util.spec_from_file_location(
    "my_first_agent_demo_adapter", str(_ADAPTER_MODULE_PATH)
)
_adapter = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_adapter)

AdapterInputError = _adapter.AdapterInputError
_demo_result_to_native_trace = _adapter._demo_result_to_native_trace
_read_scenario_input = _adapter._read_scenario_input
_resolve_agent_path = _adapter._resolve_agent_path

# ---------------------------------------------------------------------------
# 共享 fixture / helper
# ---------------------------------------------------------------------------

_ADAPTER_PATH = str(
    Path(__file__).resolve().parent.parent
    / "examples" / "my_first_agent_demo" / "adapter.py"
)

# my-first-agent 路径（仅用于 @integration 测试的 subprocess env）。
# 假设 my-first-agent 与 agent-tool-harness 为同级目录。
# 如果路径不存在，integration 测试会在运行时跳过。
_AGENT_PATH = str(
    Path(__file__).resolve().parent.parent.parent / "my-first-agent"
)


def _subprocess_env() -> dict[str, str]:
    """返回用于 subprocess 集成测试的 env，包含 MY_FIRST_AGENT_PATH。

    路径由 agent-tool-harness 仓库相对位置推断（同级目录）。
    CI 上不设对应路径时应通过 -m \"not integration\" 跳过集成测试。
    """
    env = dict(os.environ)
    # 优先用外部已设值，否则用相对推断路径
    if not env.get("MY_FIRST_AGENT_PATH"):
        env["MY_FIRST_AGENT_PATH"] = _AGENT_PATH
    return env


def _make_mock_demo_step(
    index: int = 1,
    tool_name: str = "demo.write_demo_note",
    tool_input: dict | None = None,
    status: str = "executed",
    safe_preview: str = "wrote note (140 bytes)",
    content_length: int = 140,
    error_type: str | None = None,
):
    """构造模拟 DemoStep 对象，匹配 my-first-agent 的 DemoStep 接口。"""
    action = MagicMock()
    action.tool_name = tool_name
    action.tool_input = tool_input or {"path": "/tmp/note.md", "content": "hello"}

    envelope = MagicMock()
    envelope.status = status
    envelope.safe_preview = safe_preview
    envelope.content_length = content_length
    envelope.error_type = error_type

    step = MagicMock()
    step.action = action
    step.envelope = envelope
    return step


def _make_mock_demo_result(
    scenario_id: str = "demo-test",
    task: str = "create a demo note",
    provider: str = "fake",
    steps: list | None = None,
    final_answer: str = "wrote demo note to /tmp/note.md",
    workspace: str = "/tmp/workspace",
):
    """构造模拟 DemoResult 对象。"""
    result = MagicMock()
    result.steps = [_make_mock_demo_step()] if steps is None else steps
    result.final_answer = final_answer
    result.provider = provider
    result.workspace = workspace
    return result


def _make_tool_specs() -> list[ToolSpec]:
    return [
        ToolSpec(
            name="write_demo_note",
            namespace="demo",
            version="1.0",
            description="写入 demo note",
            when_to_use="需要写入 demo note 时",
            when_not_to_use="不需要时",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
            },
            output_contract={"evidence": "list"},
            token_policy={"max_tokens_per_call": 1000},
            side_effects={"destructive": False},
            executor={"type": "python", "module": "write_demo_note"},
        ),
    ]


def _make_eval_spec() -> EvalSpec:
    return EvalSpec(
        id="level3-dogfood",
        name="Level 3 local-only dogfood",
        category="integration",
        split="test",
        realism_level="mock",
        complexity="low",
        source="test",
        user_prompt="create a demo note about Level 3 dogfood verification",
        initial_context={},
        expected_tool_behavior={"required_tools": ["demo.write_demo_note"]},
        judge={
            "rules": [
                {"type": "must_call_tool", "tool": "demo.write_demo_note"},
                {"type": "must_use_evidence"},
            ]
        },
        verifiable_outcome={"expected_root_cause": "demo completed"},
        success_criteria=["结论引用证据"],
    )


# ---------------------------------------------------------------------------
# _resolve_agent_path
# ---------------------------------------------------------------------------


class TestResolveAgentPath:
    def test_env_var_override(self, monkeypatch):
        monkeypatch.setenv("MY_FIRST_AGENT_PATH", "/custom/path")
        assert _resolve_agent_path() == Path("/custom/path").resolve()

    def test_missing_env_var_exits(self, monkeypatch):
        """MY_FIRST_AGENT_PATH 未设置时必须报错并 exit(2)。"""
        monkeypatch.delenv("MY_FIRST_AGENT_PATH", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            _resolve_agent_path()
        assert exc_info.value.code == 2


# ---------------------------------------------------------------------------
# _read_scenario_input
# ---------------------------------------------------------------------------


class TestReadScenarioInput:
    def test_valid_input_with_goal(self, tmp_path):
        p = tmp_path / "input.json"
        p.write_text(json.dumps({"scenario_id": "s1", "goal": "do something"}))
        data = _read_scenario_input(p)
        assert data["scenario_id"] == "s1"
        assert data["_resolved_goal"] == "do something"

    def test_valid_input_with_task(self, tmp_path):
        p = tmp_path / "input.json"
        p.write_text(json.dumps({"scenario_id": "s1", "task": "write note"}))
        data = _read_scenario_input(p)
        assert data["_resolved_goal"] == "write note"

    def test_valid_input_with_prompt(self, tmp_path):
        p = tmp_path / "input.json"
        p.write_text(json.dumps({"scenario_id": "s1", "prompt": "hello"}))
        data = _read_scenario_input(p)
        assert data["_resolved_goal"] == "hello"

    def test_valid_input_with_user_prompt(self, tmp_path):
        p = tmp_path / "input.json"
        p.write_text(json.dumps({"scenario_id": "s1", "user_prompt": "greet"}))
        data = _read_scenario_input(p)
        assert data["_resolved_goal"] == "greet"

    def test_missing_scenario_id(self, tmp_path):
        p = tmp_path / "input.json"
        p.write_text(json.dumps({"goal": "do something"}))
        with pytest.raises(AdapterInputError, match="scenario_id"):
            _read_scenario_input(p)

    def test_empty_scenario_id(self, tmp_path):
        p = tmp_path / "input.json"
        p.write_text(json.dumps({"scenario_id": "", "goal": "do"}))
        with pytest.raises(AdapterInputError, match="scenario_id"):
            _read_scenario_input(p)

    def test_missing_goal(self, tmp_path):
        p = tmp_path / "input.json"
        p.write_text(json.dumps({"scenario_id": "s1"}))
        with pytest.raises(AdapterInputError, match="must provide one of"):
            _read_scenario_input(p)

    def test_file_not_found(self, tmp_path):
        p = tmp_path / "nonexistent.json"
        with pytest.raises(AdapterInputError, match="not found"):
            _read_scenario_input(p)

    def test_invalid_json(self, tmp_path):
        p = tmp_path / "input.json"
        p.write_text("not json")
        with pytest.raises(AdapterInputError, match="invalid JSON"):
            _read_scenario_input(p)

    def test_not_a_dict(self, tmp_path):
        p = tmp_path / "input.json"
        p.write_text("[1, 2, 3]")
        with pytest.raises(AdapterInputError, match="must be a JSON object"):
            _read_scenario_input(p)


# ---------------------------------------------------------------------------
# _demo_result_to_native_trace
# ---------------------------------------------------------------------------


class TestDemoResultToNativeTrace:
    def test_single_step_happy_path(self):
        result = _make_mock_demo_result(
            scenario_id="demo-test",
            steps=[_make_mock_demo_step(index=1)],
        )
        trace = _demo_result_to_native_trace(result, "demo-test")

        assert trace["scenario_id"] == "demo-test"
        assert len(trace["tool_calls"]) == 1
        assert len(trace["tool_results"]) == 1
        assert trace["tool_calls"][0]["call_id"] == "c1"
        assert trace["tool_calls"][0]["tool_name"] == "demo.write_demo_note"
        assert trace["tool_results"][0]["call_id"] == "c1"
        assert trace["tool_results"][0]["status"] == "success"
        assert "evidence" in trace["tool_results"][0]["output"]
        assert trace["tool_results"][0]["output"]["evidence"][0]["id"] == "ev-001"
        assert "final_answer" in trace
        assert "Evidence" in trace["final_answer"]

    def test_multiple_steps(self):
        steps = [
            _make_mock_demo_step(index=1, tool_name="demo.write_demo_note"),
            _make_mock_demo_step(index=2, tool_name="demo.shell_check"),
        ]
        result = _make_mock_demo_result(steps=steps)
        trace = _demo_result_to_native_trace(result, "multi")

        assert len(trace["tool_calls"]) == 2
        assert len(trace["tool_results"]) == 2
        assert trace["tool_calls"][0]["call_id"] == "c1"
        assert trace["tool_calls"][1]["call_id"] == "c2"
        assert trace["tool_results"][0]["call_id"] == "c1"
        assert trace["tool_results"][1]["call_id"] == "c2"
        # evidence IDs 递增
        assert trace["tool_results"][0]["output"]["evidence"][0]["id"] == "ev-001"
        assert trace["tool_results"][1]["output"]["evidence"][0]["id"] == "ev-002"

    def test_failed_step_status(self):
        step = _make_mock_demo_step(status="failed", error_type="tool_failure")
        result = _make_mock_demo_result(steps=[step])
        trace = _demo_result_to_native_trace(result, "fail-test")

        assert trace["tool_results"][0]["status"] == "error"
        assert trace["tool_results"][0]["error"] == "tool_failure"

    def test_metadata_fields(self):
        result = _make_mock_demo_result()
        trace = _demo_result_to_native_trace(result, "meta-test")

        meta = trace["metadata"]
        assert meta["source_agent"] == "my-first-agent local demo"
        assert meta["level"] == "3 local-only wrapper dogfood"
        assert "adapter" in meta
        assert meta["provider"] == "fake"

    def test_final_answer_cites_evidence_ids(self):
        result = _make_mock_demo_result(steps=[_make_mock_demo_step()])
        trace = _demo_result_to_native_trace(result, "cite-test")

        assert "ev-001" in trace["final_answer"]
        assert "Evidence" in trace["final_answer"]

    def test_tool_input_preserved_in_arguments(self):
        tool_input = {"path": "/tmp/out.md", "content": "custom content"}
        step = _make_mock_demo_step(tool_input=tool_input)
        result = _make_mock_demo_result(steps=[step])
        trace = _demo_result_to_native_trace(result, "args-test")

        assert trace["tool_calls"][0]["arguments"]["path"] == "/tmp/out.md"
        assert trace["tool_calls"][0]["arguments"]["content"] == "custom content"

    def test_empty_steps_produces_empty_arrays(self):
        result = _make_mock_demo_result(steps=[])
        trace = _demo_result_to_native_trace(result, "empty-test")

        assert trace["tool_calls"] == []
        assert trace["tool_results"] == []
        # final_answer 仍存在但不包含 evidence ID
        assert "final_answer" in trace


# ---------------------------------------------------------------------------
# adapter subprocess 测试（依赖真实 my-first-agent）
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestAdapterSubprocess:
    """通过 subprocess 调用 adapter.py，验证真实闭环。"""

    def test_adapter_happy_path(self, tmp_path):
        """完整 adapter 子进程调用——产出合法 native trace JSON。"""
        input_p = tmp_path / "input.json"
        input_p.write_text(json.dumps({
            "scenario_id": "subprocess-test",
            "goal": "create a demo note about integration testing",
        }))
        trace_p = tmp_path / "trace.json"

        result = subprocess.run(
            [
                sys.executable, _ADAPTER_PATH,
                "--input", str(input_p),
                "--trace-out", str(trace_p),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(),
        )

        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert trace_p.exists()
        trace = json.loads(trace_p.read_text(encoding="utf-8"))
        assert trace["scenario_id"] == "subprocess-test"
        assert len(trace["tool_calls"]) >= 1
        assert len(trace["tool_results"]) >= 1
        assert "final_answer" in trace
        assert "Evidence" in trace["final_answer"]

    def test_trace_is_valid_native_schema(self, tmp_path):
        """原生 trace 可被 TraceImportAdapter native mode 导入。"""
        input_p = tmp_path / "input.json"
        input_p.write_text(json.dumps({
            "scenario_id": "native-import-test",
            "goal": "create a demo note for schema validation",
        }))
        trace_p = tmp_path / "trace.json"

        result = subprocess.run(
            [
                sys.executable, _ADAPTER_PATH,
                "--input", str(input_p),
                "--trace-out", str(trace_p),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(),
        )

        assert result.returncode == 0

        adapter = TraceImportAdapter(mode="native")
        execution_trace = adapter.import_file(trace_p)
        assert isinstance(execution_trace, ExecutionTrace)
        assert execution_trace.scenario_id == "native-import-test"
        assert len(execution_trace.tool_calls) >= 1
        assert len(execution_trace.tool_results) >= 1
        assert execution_trace.final_answer is not None

    def test_missing_input_file(self, tmp_path):
        input_p = tmp_path / "nonexistent.json"
        trace_p = tmp_path / "trace.json"
        result = subprocess.run(
            [
                sys.executable, _ADAPTER_PATH,
                "--input", str(input_p),
                "--trace-out", str(trace_p),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(),
        )
        assert result.returncode != 0
        assert "not found" in result.stderr

    def test_missing_goal_field(self, tmp_path):
        input_p = tmp_path / "input.json"
        input_p.write_text(json.dumps({"scenario_id": "no-goal"}))
        trace_p = tmp_path / "trace.json"
        result = subprocess.run(
            [
                sys.executable, _ADAPTER_PATH,
                "--input", str(input_p),
                "--trace-out", str(trace_p),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(),
        )
        assert result.returncode != 0
        assert "must provide one of" in result.stderr

    def test_invalid_json_input(self, tmp_path):
        input_p = tmp_path / "input.json"
        input_p.write_text("not json {{{")
        trace_p = tmp_path / "trace.json"
        result = subprocess.run(
            [
                sys.executable, _ADAPTER_PATH,
                "--input", str(input_p),
                "--trace-out", str(trace_p),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(),
        )
        assert result.returncode != 0
        assert "invalid json" in result.stderr.lower()

    def test_trace_output_parent_created(self, tmp_path):
        input_p = tmp_path / "input.json"
        input_p.write_text(json.dumps({
            "scenario_id": "mkdir-test",
            "goal": "parent directory must be auto-created",
        }))
        trace_p = tmp_path / "deep" / "nested" / "trace.json"
        result = subprocess.run(
            [
                sys.executable, _ADAPTER_PATH,
                "--input", str(input_p),
                "--trace-out", str(trace_p),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(),
        )
        assert result.returncode == 0
        assert trace_p.exists()


# ---------------------------------------------------------------------------
# CLIAgentAdapter + Core Flow 集成测试
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLevel3CLIAgentCoreFlow:
    """通过 CLIAgentAdapter → adapter.py subprocess → TraceImportAdapter 验证闭环。"""

    def test_cli_agent_core_flow_e2e(self, tmp_path, monkeypatch):
        """完整 Level 3 dogfood 闭环：CLIAgentAdapter → wrapper → CoreFlow。"""
        monkeypatch.setenv("MY_FIRST_AGENT_PATH", _AGENT_PATH)
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec(),
            cli_agent_config=CLIAgentAdapterConfig(
                command=[
                    sys.executable, _ADAPTER_PATH,
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                working_dir=".",
                env_policy="inherit",
            ),
            output_dir=out_dir,
        )

        assert isinstance(result, CLIAgentCoreFlowResult)
        assert isinstance(result.eval_result, EvaluationResult)
        assert result.eval_result.passed is True
        assert result.signal_quality == RECORDED_TRAJECTORY

        # trace 正确包含 tool calls
        tool_names = [c.tool_name for c in result.trace.tool_calls]
        assert "demo.write_demo_note" in tool_names

    def test_cli_agent_output_files_exist(self, tmp_path, monkeypatch):
        """产出 scenario_input.json 和 trace_output.json。"""
        monkeypatch.setenv("MY_FIRST_AGENT_PATH", _AGENT_PATH)
        out_dir = str(tmp_path / "out")
        build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec(),
            cli_agent_config=CLIAgentAdapterConfig(
                command=[
                    sys.executable, _ADAPTER_PATH,
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                working_dir=".",
                env_policy="inherit",
            ),
            output_dir=out_dir,
        )

        assert (Path(out_dir) / "scenario_input.json").exists()
        assert (Path(out_dir) / "trace_output.json").exists()
        trace_data = json.loads(
            (Path(out_dir) / "trace_output.json").read_text(encoding="utf-8")
        )
        assert "scenario_id" in trace_data
        assert len(trace_data["tool_calls"]) >= 1

    def test_no_review_decision(self, tmp_path, monkeypatch):
        """不自动生成 ReviewDecision。"""
        monkeypatch.setenv("MY_FIRST_AGENT_PATH", _AGENT_PATH)
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec(),
            cli_agent_config=CLIAgentAdapterConfig(
                command=[
                    sys.executable, _ADAPTER_PATH,
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                working_dir=".",
                env_policy="inherit",
            ),
            output_dir=out_dir,
        )

        assert not hasattr(result, "review_decision")
        assert all(f.category == "rule" for f in result.eval_result.findings)

    def test_signal_quality_is_recorded_trajectory(self, tmp_path, monkeypatch):
        """signal_quality 是 recorded_trajectory（不是 tautological_replay）。"""
        monkeypatch.setenv("MY_FIRST_AGENT_PATH", _AGENT_PATH)
        out_dir = str(tmp_path / "out")
        result = build_cli_agent_core_flow(
            tool_specs=_make_tool_specs(),
            eval_spec=_make_eval_spec(),
            cli_agent_config=CLIAgentAdapterConfig(
                command=[
                    sys.executable, _ADAPTER_PATH,
                    "--input", "{input_path}",
                    "--trace-out", "{trace_output_path}",
                ],
                working_dir=".",
                env_policy="inherit",
            ),
            output_dir=out_dir,
        )

        assert result.signal_quality == RECORDED_TRAJECTORY
        assert result.evidence.signal_quality == RECORDED_TRAJECTORY


# ---------------------------------------------------------------------------
# 安全边界测试
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestLevel3SecurityBoundary:
    """Level 3 wrapper 安全边界验证。"""

    def test_no_api_key_required(self, tmp_path, monkeypatch):
        """adapter 不需要 ANTHROPIC_API_KEY 也能跑。"""
        monkeypatch.setenv("MY_FIRST_AGENT_PATH", _AGENT_PATH)
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        input_p = tmp_path / "input.json"
        input_p.write_text(json.dumps({
            "scenario_id": "no-key-test",
            "goal": "no API key needed",
        }))
        trace_p = tmp_path / "trace.json"

        result = subprocess.run(
            [
                sys.executable, _ADAPTER_PATH,
                "--input", str(input_p),
                "--trace-out", str(trace_p),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(),
        )
        assert result.returncode == 0

    def test_no_env_read(self, tmp_path, monkeypatch):
        """wrapper 不读取 .env 文件。"""
        monkeypatch.setenv("MY_FIRST_AGENT_PATH", _AGENT_PATH)
        monkeypatch.setenv("MY_FIRST_AGENT_LLM_PROVIDER", "anthropic")
        # 即使设置了 provider 环境变量指向真实 LLM，adapter 也不应该失败——
        # 因为它只调用 run_local_demo()，后者永远用 FakeProvider。

        input_p = tmp_path / "input.json"
        input_p.write_text(json.dumps({
            "scenario_id": "env-boundary-test",
            "goal": "env boundary verification",
        }))
        trace_p = tmp_path / "trace.json"

        result = subprocess.run(
            [
                sys.executable, _ADAPTER_PATH,
                "--input", str(input_p),
                "--trace-out", str(trace_p),
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=_subprocess_env(),
        )
        assert result.returncode == 0

        trace = json.loads(trace_p.read_text(encoding="utf-8"))
        assert trace["metadata"]["provider"] == "fake"


# ---------------------------------------------------------------------------
# adapter 命令行参数测试
# ---------------------------------------------------------------------------


class TestAdapterArgParsingErrors:
    def test_missing_input_arg(self):
        result = subprocess.run(
            [sys.executable, _ADAPTER_PATH, "--trace-out", "/tmp/t.json"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0

    def test_missing_trace_out_arg(self):
        result = subprocess.run(
            [sys.executable, _ADAPTER_PATH, "--input", "/tmp/i.json"],
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode != 0
