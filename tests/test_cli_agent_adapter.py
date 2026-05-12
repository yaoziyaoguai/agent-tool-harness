"""CLIAgentAdapter Slice 1 测试 — command/config 校验 + input file 准备。

架构边界:
- 所有测试 zero-network, deterministic.
- 使用 fake ScenarioSpec + tmp_path.
- 不运行 subprocess、不读 .env、不调用外部 API。
- 不集成 TraceImportAdapter（Slice 3）。
- 不生成 ReviewDecision。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_tool_harness.cli_agent import (
    CLIAgentAdapter,
    CLIAgentAdapterConfig,
    CLIAgentError,
    CLIAgentPreparedRun,
)
from agent_tool_harness.core_contract import ScenarioSpec

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _valid_command() -> list[str]:
    return [
        "python",
        "run_agent.py",
        "--input",
        "{input_path}",
        "--trace-out",
        "{trace_output_path}",
    ]


def _valid_config(**overrides) -> CLIAgentAdapterConfig:
    kwargs: dict = dict(command=_valid_command(), working_dir=None)
    kwargs.update(overrides)
    return CLIAgentAdapterConfig(**kwargs)


def _valid_scenario() -> ScenarioSpec:
    return ScenarioSpec(
        scenario_id="test-scenario",
        goal="测试场景目标",
        available_tools=["tool.a", "tool.b"],
        success_criteria=["criterion 1"],
    )


# ---------------------------------------------------------------------------
# command 校验
# ---------------------------------------------------------------------------


class TestCommandValidation:
    """command 必须是 list[str]，含必须占位符。"""

    def test_command_must_be_list(self):
        """传入 string command 应拒绝——不接受 shell string。"""
        with pytest.raises(CLIAgentError, match="must be a list"):
            CLIAgentAdapterConfig(command="python run.py")  # type: ignore[arg-type]

    def test_command_must_not_be_empty(self):
        with pytest.raises(CLIAgentError, match="must not be empty"):
            CLIAgentAdapterConfig(command=[])

    def test_command_elements_must_be_strings(self):
        with pytest.raises(CLIAgentError, match="must be a string"):
            CLIAgentAdapterConfig(command=["python", 123])  # type: ignore[list-item]

    def test_missing_input_path_placeholder(self):
        """缺少 {input_path} 占位符 → CLIAgentError。"""
        cmd = ["python", "run.py", "--trace-out", "{trace_output_path}"]
        with pytest.raises(CLIAgentError, match=r"\{input_path\}"):
            CLIAgentAdapterConfig(command=cmd)

    def test_missing_trace_output_placeholder(self):
        """缺少 {trace_output_path} 占位符 → CLIAgentError。"""
        cmd = ["python", "run.py", "--input", "{input_path}"]
        with pytest.raises(CLIAgentError, match=r"\{trace_output_path\}"):
            CLIAgentAdapterConfig(command=cmd)

    def test_valid_command_accepted(self):
        cfg = _valid_config()
        assert cfg.command == _valid_command()

    def test_no_subprocess_run_module_level(self):
        """Slice 1 不 import subprocess。"""
        import agent_tool_harness.cli_agent as ca

        assert "subprocess" not in dir(ca)


# ---------------------------------------------------------------------------
# working_dir 校验
# ---------------------------------------------------------------------------


class TestWorkingDirValidation:
    """working_dir 必须存在且是目录。"""

    def test_working_dir_not_exist(self, tmp_path: Path):
        bad = tmp_path / "nonexistent"
        with pytest.raises(CLIAgentError, match="does not exist"):
            CLIAgentAdapterConfig(command=_valid_command(), working_dir=str(bad))

    def test_working_dir_is_file(self, tmp_path: Path):
        f = tmp_path / "file.txt"
        f.write_text("not a dir")
        with pytest.raises(CLIAgentError, match="not a directory"):
            CLIAgentAdapterConfig(command=_valid_command(), working_dir=str(f))

    def test_working_dir_valid(self, tmp_path: Path):
        cfg = CLIAgentAdapterConfig(
            command=_valid_command(), working_dir=str(tmp_path)
        )
        assert cfg.working_dir == str(tmp_path)

    def test_working_dir_none_is_ok(self):
        """working_dir=None 是合法的——prepare_run 时默认 cwd。"""
        cfg = _valid_config(working_dir=None)
        assert cfg.working_dir is None


# ---------------------------------------------------------------------------
# input file 准备
# ---------------------------------------------------------------------------


class TestInputFilePreparation:
    """ScenarioSpec → input JSON file。"""

    def test_write_input_file_creates_json(self, tmp_path: Path):
        adapter = CLIAgentAdapter(_valid_config())
        path = adapter.write_input_file(_valid_scenario(), tmp_path / "input.json")
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["scenario_id"] == "test-scenario"
        assert data["goal"] == "测试场景目标"
        assert data["available_tools"] == ["tool.a", "tool.b"]

    def test_write_input_file_roundtrip_all_fields(self, tmp_path: Path):
        """所有 ScenarioSpec 字段轮转不丢。"""
        scenario = ScenarioSpec(
            scenario_id="roundtrip-test",
            goal="roundtrip goal",
            available_tools=["t1", "t2"],
            success_criteria=["sc1", "sc2"],
            constraints={"max_steps": 5},
        )
        adapter = CLIAgentAdapter(_valid_config())
        path = adapter.write_input_file(scenario, tmp_path / "roundtrip.json")
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["scenario_id"] == scenario.scenario_id
        assert data["goal"] == scenario.goal
        assert data["available_tools"] == scenario.available_tools
        assert data["success_criteria"] == scenario.success_criteria
        assert data["constraints"] == scenario.constraints

    def test_write_input_file_creates_parent_dir(self, tmp_path: Path):
        """输出路径的父目录不存在时自动创建。"""
        adapter = CLIAgentAdapter(_valid_config())
        deep = tmp_path / "sub" / "deep" / "input.json"
        path = adapter.write_input_file(_valid_scenario(), deep)
        assert path.exists()
        assert path.parent.exists()


# ---------------------------------------------------------------------------
# prepare_run
# ---------------------------------------------------------------------------


class TestPrepareRun:
    """prepare_run 生成执行计划——不执行 subprocess。"""

    def test_prepare_run_returns_prepared_run(self, tmp_path: Path):
        out_dir = tmp_path / "out"
        adapter = CLIAgentAdapter(_valid_config())
        prepared = adapter.prepare_run(_valid_scenario(), output_dir=out_dir)
        assert isinstance(prepared, CLIAgentPreparedRun)

    def test_prepare_run_writes_input_file(self, tmp_path: Path):
        out_dir = tmp_path / "out"
        adapter = CLIAgentAdapter(_valid_config())
        prepared = adapter.prepare_run(_valid_scenario(), output_dir=out_dir)
        assert Path(prepared.input_path).exists()
        data = json.loads(Path(prepared.input_path).read_text(encoding="utf-8"))
        assert data["scenario_id"] == "test-scenario"

    def test_argv_placeholders_replaced(self, tmp_path: Path):
        """占位符 {input_path} / {trace_output_path} 已被替换为实际路径。"""
        out_dir = tmp_path / "out"
        adapter = CLIAgentAdapter(_valid_config())
        prepared = adapter.prepare_run(_valid_scenario(), output_dir=out_dir)
        argv_text = " ".join(prepared.argv)
        assert "{input_path}" not in argv_text
        assert "{trace_output_path}" not in argv_text
        assert str(prepared.input_path) in argv_text
        assert str(prepared.trace_output_path) in argv_text

    def test_argv_is_list_of_str(self, tmp_path: Path):
        out_dir = tmp_path / "out"
        adapter = CLIAgentAdapter(_valid_config())
        prepared = adapter.prepare_run(_valid_scenario(), output_dir=out_dir)
        assert isinstance(prepared.argv, list)
        for arg in prepared.argv:
            assert isinstance(arg, str)

    def test_trace_output_path_under_output_dir(self, tmp_path: Path):
        out_dir = tmp_path / "out"
        adapter = CLIAgentAdapter(_valid_config())
        prepared = adapter.prepare_run(_valid_scenario(), output_dir=out_dir)
        resolved = Path(prepared.trace_output_path).resolve()
        assert str(resolved).startswith(str(out_dir.resolve()))

    def test_input_path_under_output_dir(self, tmp_path: Path):
        out_dir = tmp_path / "out"
        adapter = CLIAgentAdapter(_valid_config())
        prepared = adapter.prepare_run(_valid_scenario(), output_dir=out_dir)
        resolved = Path(prepared.input_path).resolve()
        assert str(resolved).startswith(str(out_dir.resolve()))

    def test_working_dir_from_config(self, tmp_path: Path):
        wd = tmp_path / "work"
        wd.mkdir()
        out_dir = tmp_path / "out"
        adapter = CLIAgentAdapter(_valid_config(working_dir=str(wd)))
        prepared = adapter.prepare_run(_valid_scenario(), output_dir=out_dir)
        assert Path(prepared.working_dir).resolve() == wd.resolve()

    def test_working_dir_defaults_to_cwd(self, tmp_path: Path):
        out_dir = tmp_path / "out"
        adapter = CLIAgentAdapter(_valid_config(working_dir=None))
        prepared = adapter.prepare_run(_valid_scenario(), output_dir=out_dir)
        assert Path(prepared.working_dir).resolve() == Path.cwd().resolve()

    def test_prepared_run_is_frozen(self, tmp_path: Path):
        """CLIAgentPreparedRun 为 frozen dataclass。"""
        from dataclasses import FrozenInstanceError

        out_dir = tmp_path / "out"
        adapter = CLIAgentAdapter(_valid_config())
        prepared = adapter.prepare_run(_valid_scenario(), output_dir=out_dir)
        with pytest.raises(FrozenInstanceError):
            prepared.argv = ["other"]  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 边界行为
# ---------------------------------------------------------------------------


class TestBoundaryBehavior:
    """不读 .env / 不调 API / 不 import TraceImportAdapter / 不生成 ReviewDecision。"""

    def test_no_env_read(self):
        """清空 os.environ 不影�� config 校验。"""
        import os

        saved = dict(os.environ)
        os.environ.clear()
        try:
            cfg = _valid_config()
            assert cfg.command == _valid_command()
        finally:
            os.environ.update(saved)

    def test_no_review_decision(self):
        """cli_agent 模块不导入或定义 ReviewDecision。"""
        import agent_tool_harness.cli_agent as ca

        assert "ReviewDecision" not in dir(ca)

    def test_no_trace_import_adapter_import(self):
        """Slice 1 不 import TraceImportAdapter。"""
        import ast

        import agent_tool_harness.cli_agent as ca

        source = Path(ca.__file__).read_text(encoding="utf-8") if ca.__file__ else ""
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = (
                    node.module
                    if isinstance(node, ast.ImportFrom)
                    else node.names[0].name
                )
                if module and "trace_import" in module:
                    pytest.fail(
                        f"Slice 1 must not import TraceImportAdapter: {ast.dump(node)}"
                    )

    def test_config_fields_present_for_future_slices(self):
        """CLIAgentAdapterConfig 已预留 Slice 2/3 字段但本轮不消费。"""
        cfg = _valid_config()
        assert cfg.timeout_seconds == 300.0
        assert cfg.env_policy == "minimal"
        assert cfg.env_allowlist is None
        assert cfg.allow_shell is False
        assert cfg.max_stdout_chars == 10000
        assert cfg.max_stderr_chars == 10000
        assert cfg.trace_format == "native"
        assert cfg.trace_mapping is None
