"""CLIAgentAdapter Slice 1+2 测试 — command/config 校验 + input file 准备 + subprocess 执行。

架构边界:
- 所有测试 zero-network, deterministic.
- 使用 fake ScenarioSpec + tmp_path + fake CLI 命令.
- 不读 .env、不调用外部 API。
- 不集成 TraceImportAdapter（Slice 3）。
- 不生成 ReviewDecision。
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_tool_harness.cli_agent import (
    CLIAgentAdapter,
    CLIAgentAdapterConfig,
    CLIAgentError,
    CLIAgentPreparedRun,
    CLIAgentResult,
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


# -- Slice 2 helpers: fake CLI 命令（含占位符，通过 config 校验） --

# 占位符填充器——写 trace 文件时只需要 trace_output_path
_TRACE_ARG = "{trace_output_path}"
_INPUT_ARG = "{input_path}"


def _echo_cmd(msg: str = "hello") -> list[str]:
    """echo 命令——测试 stdout 捕获。"""
    return ["echo", msg, _INPUT_ARG, _TRACE_ARG]


_DEFAULT_TRACE_JSON = '{"scenario_id":"t","tool_calls":[],"tool_results":[]}'


def _write_trace_cmd(
    trace_json: str = _DEFAULT_TRACE_JSON,
) -> list[str]:
    """写 trace 文件到 {trace_output_path} 的 Python 脚本。"""
    # ruff: disable that trace_json is used via !r below
    script = (
        "import json,pathlib,sys;"
        f"pathlib.Path(sys.argv[1]).write_text({trace_json!r})"
    )
    return ["python", "-c", script, _TRACE_ARG, _INPUT_ARG]


def _exit_cmd(code: int = 3) -> list[str]:
    """以指定 exit code 退出的命令。"""
    return [
        "python", "-c",
        f"import sys;sys.exit({code})",
        _INPUT_ARG,
        _TRACE_ARG,
    ]


def _sleep_cmd(seconds: int = 10) -> list[str]:
    """sleep 命令——测试 timeout。"""
    return [
        "python", "-c",
        f"import time;time.sleep({seconds})",
        _INPUT_ARG,
        _TRACE_ARG,
    ]


def _stderr_cmd(msg: str = "err msg") -> list[str]:
    """向 stderr 输出的命令。"""
    return [
        "python", "-c",
        f"import sys;print({msg!r},file=sys.stderr)",
        _INPUT_ARG,
        _TRACE_ARG,
    ]


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
        """Slice 2 不 import TraceImportAdapter。"""
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
                        f"Slice 2 must not import TraceImportAdapter: {ast.dump(node)}"
                    )

    def test_config_fields_present_for_slice_3(self):
        """CLIAgentAdapterConfig 已预留 Slice 3 字段但本轮不消费。"""
        cfg = _valid_config()
        assert cfg.trace_format == "native"
        assert cfg.trace_mapping is None


# ---------------------------------------------------------------------------
# Slice 2: run() — 成功路径
# ---------------------------------------------------------------------------


class TestRunSuccess:
    """run() 基本成功路径。"""

    def test_run_returns_result(self, tmp_path: Path):
        """run() 返回 CLIAgentResult，exit_code=0，execution_trace=None。"""
        cfg = _valid_config(command=_echo_cmd("ok"))
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert isinstance(result, CLIAgentResult)
        assert result.exit_code == 0
        assert result.execution_trace is None  # Slice 3
        assert result.elapsed_seconds > 0

    def test_run_captures_stdout(self, tmp_path: Path):
        """stdout 被捕获到 stdout_summary。"""
        cfg = _valid_config(command=_echo_cmd("captured-output"))
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert "captured-output" in result.stdout_summary

    def test_run_captures_stderr(self, tmp_path: Path):
        """stderr 被捕获到 stderr_summary。"""
        cfg = _valid_config(command=_stderr_cmd("error-output"))
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert "error-output" in result.stderr_summary

    def test_run_writes_trace_file(self, tmp_path: Path):
        """CLI 命令写入 trace 文件后，文件存在于 trace_output_path。"""
        cfg = _valid_config(command=_write_trace_cmd())
        adapter = CLIAgentAdapter(cfg)
        out_dir = tmp_path / "out"
        result = adapter.run(_valid_scenario(), output_dir=out_dir)
        trace_file = out_dir / "trace_output.json"
        assert trace_file.exists()
        assert result.errors == []

    def test_run_command_reflects_argv(self, tmp_path: Path):
        """result.command 是执行命令的字符串形式。"""
        cfg = _valid_config(command=_echo_cmd("x"))
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert "echo" in result.command

    def test_run_working_dir(self, tmp_path: Path):
        """result.working_dir 与 config 一致。"""
        wd = tmp_path / "work"
        wd.mkdir()
        cfg = _valid_config(command=_echo_cmd("x"), working_dir=str(wd))
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert Path(result.working_dir).resolve() == wd.resolve()

    def test_run_input_file_created(self, tmp_path: Path):
        """run() 会在 output_dir 下创建 scenario_input.json。"""
        cfg = _valid_config(command=_echo_cmd("x"))
        adapter = CLIAgentAdapter(cfg)
        out_dir = tmp_path / "out"
        adapter.run(_valid_scenario(), output_dir=out_dir)
        input_file = out_dir / "scenario_input.json"
        assert input_file.exists()
        data = json.loads(input_file.read_text(encoding="utf-8"))
        assert data["scenario_id"] == "test-scenario"


# ---------------------------------------------------------------------------
# Slice 2: run() — 错误路径
# ---------------------------------------------------------------------------


class TestRunErrors:
    """非零 exit / timeout / trace 缺失。"""

    def test_non_zero_exit_adds_error(self, tmp_path: Path):
        """exit code != 0 → errors 包含 warning，不抛异常。"""
        cfg = _valid_config(command=_exit_cmd(3))
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert result.exit_code == 3
        assert any("non-zero" in e for e in result.errors)

    def test_non_zero_exit_still_checks_trace(self, tmp_path: Path):
        """非零 exit 不阻断 trace 文件检查——trace 缺失仍需报错。"""
        cfg = _valid_config(command=_exit_cmd(3))
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert any("trace" in e.lower() for e in result.errors)

    def test_timeout_adds_error(self, tmp_path: Path):
        """命令超时 → errors 包含 timeout 信息，exit_code=-1。"""
        cfg = _valid_config(command=_sleep_cmd(30), timeout_seconds=0.3)
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert result.exit_code == -1
        assert any("timed out" in e for e in result.errors)

    def test_timeout_no_duplicate_non_zero_error(self, tmp_path: Path):
        """超时不应额外追加 non-zero exit warning。"""
        cfg = _valid_config(command=_sleep_cmd(30), timeout_seconds=0.3)
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert not any("non-zero" in e for e in result.errors)

    def test_trace_file_missing_adds_error(self, tmp_path: Path):
        """命令不写 trace 文件 → errors 包含 trace missing 信息。"""
        cfg = _valid_config(command=_echo_cmd("no trace written"))
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert any("trace" in e.lower() for e in result.errors)

    def test_command_not_found_adds_error(self, tmp_path: Path):
        """命令不存在 → OSError → errors 包含执行失败信息。"""
        cfg = _valid_config(command=["nonexistent_cmd_xyz", _INPUT_ARG, _TRACE_ARG])
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert result.exit_code == -1
        assert any("execution failed" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Slice 2: 输出截断
# ---------------------------------------------------------------------------


class TestOutputTruncation:
    """stdout/stderr 按 max_*_chars 截断。"""

    def test_stdout_truncation(self, tmp_path: Path):
        """stdout 超出 max_stdout_chars 时截断并附加标记。"""
        long_msg = "A" * 200
        cfg = _valid_config(
            command=_echo_cmd(long_msg), max_stdout_chars=50
        )
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert len(result.stdout_summary) < len(long_msg)
        assert "truncated" in result.stdout_summary
        assert "A" * 50 in result.stdout_summary

    def test_stdout_no_truncation_when_under_limit(self, tmp_path: Path):
        """stdout 未超出限制时不截断。"""
        msg = "short"
        cfg = _valid_config(
            command=_echo_cmd(msg), max_stdout_chars=1000
        )
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert "short" in result.stdout_summary
        assert "truncated" not in result.stdout_summary

    def test_stderr_truncation(self, tmp_path: Path):
        """stderr 超出 max_stderr_chars 时截断并附加标记。"""
        long_err = "E" * 200
        cfg = _valid_config(
            command=_stderr_cmd(long_err), max_stderr_chars=50
        )
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert len(result.stderr_summary) < len(long_err)
        assert "truncated" in result.stderr_summary

    def test_max_chars_none_no_truncation(self, tmp_path: Path):
        """max_*_chars=None 时不截断。"""
        msg = "A" * 2000
        cfg = _valid_config(
            command=_echo_cmd(msg),
            max_stdout_chars=None,
            max_stderr_chars=None,
        )
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert "truncated" not in result.stdout_summary


# ---------------------------------------------------------------------------
# Slice 2: env policy
# ---------------------------------------------------------------------------


class TestEnvPolicy:
    """env_policy: minimal / allowlist / inherit。"""

    def test_minimal_no_extra_env(self, tmp_path: Path):
        """minimal 不传递额外环境变量。通过 python -c 打印 os.environ keys 验证。"""
        check_cmd = [
            "python", "-c",
            "import json,os,sys;json.dump(sorted(os.environ.keys()),sys.stdout)",
            _INPUT_ARG, _TRACE_ARG,
        ]
        os.environ["TEST_EXTRA_VAR_XYZ"] = "should-not-appear"
        try:
            cfg = _valid_config(command=check_cmd, env_policy="minimal")
            adapter = CLIAgentAdapter(cfg)
            result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
            assert "TEST_EXTRA_VAR_XYZ" not in result.stdout_summary
        finally:
            del os.environ["TEST_EXTRA_VAR_XYZ"]

    def test_allowlist_only_passes_allowed(self, tmp_path: Path):
        """allowlist 仅传递列出的变量。"""
        check_cmd = [
            "python", "-c",
            "import json,os,sys;json.dump(sorted(os.environ.keys()),sys.stdout)",
            _INPUT_ARG, _TRACE_ARG,
        ]
        os.environ["TEST_ALLOWED_A"] = "yes"
        os.environ["TEST_NOT_ALLOWED_B"] = "no"
        try:
            cfg = _valid_config(
                command=check_cmd,
                env_policy="allowlist",
                env_allowlist=["TEST_ALLOWED_A", "PATH"],
            )
            adapter = CLIAgentAdapter(cfg)
            result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
            assert "TEST_ALLOWED_A" in result.stdout_summary
            assert "TEST_NOT_ALLOWED_B" not in result.stdout_summary
        finally:
            del os.environ["TEST_ALLOWED_A"]
            del os.environ["TEST_NOT_ALLOWED_B"]

    def test_inherit_passes_all_env(self, tmp_path: Path):
        """inherit 传递全部 os.environ。"""
        check_cmd = [
            "python", "-c",
            "import json,os,sys;json.dump(sorted(os.environ.keys()),sys.stdout)",
            _INPUT_ARG, _TRACE_ARG,
        ]
        os.environ["TEST_INHERIT_VAR"] = "should-appear"
        try:
            cfg = _valid_config(command=check_cmd, env_policy="inherit")
            adapter = CLIAgentAdapter(cfg)
            result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
            assert "TEST_INHERIT_VAR" in result.stdout_summary
        finally:
            del os.environ["TEST_INHERIT_VAR"]


# ---------------------------------------------------------------------------
# Slice 2: shell 安全
# ---------------------------------------------------------------------------


class TestShellSafety:
    """默认 shell=False，allow_shell 需显式 opt-in。"""

    def test_run_uses_list_not_string(self):
        """默认 allow_shell=False，command 保持 list 形式传给 subprocess。"""
        # 不执行——只验证 config 默认值
        cfg = _valid_config()
        assert cfg.allow_shell is False
        assert isinstance(cfg.command, list)

    def test_allow_shell_true_passes_string(self, tmp_path: Path):
        """allow_shell=True 时 subprocess 接收字符串命令。"""
        cfg = _valid_config(command=_echo_cmd("shell-test"), allow_shell=True)
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert result.exit_code == 0
        assert "shell-test" in result.stdout_summary

    def test_allow_shell_true_executes(self, tmp_path: Path):
        """allow_shell=True 时命令正常执行且结果正确。"""
        # 使用简单命令验证 shell=True 路径正常工作
        cfg = _valid_config(
            command=["echo", "via-shell", _INPUT_ARG, _TRACE_ARG],
            allow_shell=True,
        )
        adapter = CLIAgentAdapter(cfg)
        result = adapter.run(_valid_scenario(), output_dir=tmp_path / "out")
        assert result.exit_code == 0
        assert "via-shell" in result.stdout_summary


# ---------------------------------------------------------------------------
# Slice 2: 边界行为
# ---------------------------------------------------------------------------


class TestSlice2Boundary:
    """不读 .env / 不调 API / 不集成 TraceImportAdapter / 不生成 ReviewDecision。"""

    def test_no_env_file_read(self):
        """cli_agent 模块不 import dotenv / load_dotenv。"""
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
                if module and "dotenv" in module:
                    pytest.fail("must not import dotenv")

    def test_no_network_call(self):
        """cli_agent 模块不 import urllib / requests / httpx。"""
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
                if module and any(
                    m in (module or "") for m in ("urllib", "requests", "httpx")
                ):
                    pytest.fail(f"must not import network library: {module}")
