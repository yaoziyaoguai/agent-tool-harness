"""scaffold-tools CLI / API 防回归测试 (v2.x 内部试用 bootstrap MVP)。

测试目标（**发现真实 bug，不是凑通过率**）：

1. **scaffold 绝不执行用户代码**：用一个 import-side-effect 会抛
   `RuntimeError("would-have-executed")` 的桩文件，证明 scaffold 仍然成功。
   如果将来有人偷懒改成 `importlib.import_module`，这条测试立刻 FAIL。
2. **能从简单函数抽 name / docstring / params / type hints / return**。
3. **生成 draft YAML 含 5 行固定披露**：generated draft / review required /
   does not execute tools / does not read secrets / not production-approved。
4. **不能可靠推断的字段必须写 TODO**——禁止伪造 production-grade 字段。
5. **默认拒绝覆盖** `--out`，加 `--force` 才能覆盖。
6. **CLI 参数与 docs CLI snippet 不漂移**：通过 argparse `_actions` 校验。

为什么这些测试覆盖真实 onboarding bug：
- 内部小组试用前，工程治理硬约束是"绝不执行用户代码 / 绝不读 secrets"；
- 任何静默 `import` 退路都会破坏这个契约——本测试用 fake 模块做反向验证；
- 任何把 TODO 字段伪造成"看起来像 production-grade"的回退都会让 reviewer
  误以为 draft 已经可用。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from agent_tool_harness.scaffold import (
    ScaffoldedTool,
    scaffold_tools_yaml,
    scan_python_module,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


# === Phase 1: scan_python_module 纯函数行为 ===========================


def test_scan_extracts_name_docstring_params_and_return_annotation() -> None:
    """证明 ast 扫描能抽出 5 类机械可推断信息。

    模拟一个内部团队的"工具函数"原型：带 docstring + 类型注解 + 默认值。
    """
    source = textwrap.dedent(
        '''
        def fetch_trace_events(trace_id: str, limit: int = 20) -> dict:
            """Fetch ordered trace events for the given trace_id.

            Returns a dict with summary / evidence / next_action fields.
            """
            return {"summary": "..."}

        def _private_helper():
            pass
        '''
    )
    tools = scan_python_module(source, source_path="demo_tools.py")
    assert len(tools) == 1, "私有函数 _private_helper 必须被排除"
    t: ScaffoldedTool = tools[0]
    assert t.name == "fetch_trace_events"
    assert t.docstring is not None and "Fetch ordered trace events" in t.docstring
    assert t.return_annotation == "dict"
    assert [(p.name, p.annotation, p.has_default) for p in t.params] == [
        ("trace_id", "str", False),
        ("limit", "int", True),
    ]
    assert t.source_path == "demo_tools.py"
    assert t.line >= 1


def test_scan_marks_unannotated_params_as_todo() -> None:
    """缺类型注解的参数必须显式写 TODO_unannotated，**绝不**伪造类型。

    这条直接对应"哪些信息必须人工 review"——type hint 缺失是真实信号，
    把它假装成 `str` 是文档欺骗。
    """
    source = "def loose_tool(payload, retry=3):\n    return payload\n"
    tools = scan_python_module(source, source_path="loose.py")
    assert tools[0].params[0].annotation == "TODO_unannotated"
    assert tools[0].return_annotation == "TODO_unannotated"


# === Phase 2: scaffold_tools_yaml 端到端 ==============================


def test_scaffold_does_not_import_or_execute_user_code(tmp_path: Path) -> None:
    """**核心安全测试**：扫到带 import-side-effect 的桩文件不得触发执行。

    桩文件顶层会 `raise RuntimeError("would-have-executed")`。如果
    scaffold 退化成动态 import（违反"绝不执行用户代码"硬约束），
    这条测试会立刻抛 RuntimeError 而不是 PASS。
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "danger.py").write_text(
        textwrap.dedent(
            '''
            raise RuntimeError("would-have-executed")  # noqa: this MUST never run

            def visible_tool(x: str) -> dict:
                """Visible tool: should still be scaffolded by ast even though
                module top-level would crash on import."""
                return {"x": x}
            '''
        ),
        encoding="utf-8",
    )
    out = tmp_path / "tools.draft.yaml"
    summary = scaffold_tools_yaml(src, out)
    assert summary["tool_count"] == 1
    text = out.read_text(encoding="utf-8")
    assert "name: visible_tool" in text


def test_scaffold_yaml_contains_five_disclosure_lines(tmp_path: Path) -> None:
    """draft 文件头必须固定包含 5 行披露——任何一行被悄悄删都视为治理回退。"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "ok.py").write_text("def t(x: str) -> dict:\n    return {}\n", encoding="utf-8")
    out = tmp_path / "tools.draft.yaml"
    scaffold_tools_yaml(src, out)
    text = out.read_text(encoding="utf-8")
    required_phrases = [
        "generated draft",
        "review required",
        "does not execute tools",
        "does not read secrets",
        "not production-approved",
    ]
    for phrase in required_phrases:
        assert phrase in text, f"draft 文件头必须保留披露字符串: {phrase!r}"


def test_scaffold_writes_todo_for_semantic_fields(tmp_path: Path) -> None:
    """when_to_use / output_contract / token_policy / side_effects 必须写 TODO。

    禁止 scaffold 伪装成"production-grade"。这是 review 必须存在的边界。
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "ok.py").write_text(
        "def my_tool(x: str) -> dict:\n    '''desc.'''\n    return {}\n",
        encoding="utf-8",
    )
    out = tmp_path / "tools.draft.yaml"
    scaffold_tools_yaml(src, out)
    text = out.read_text(encoding="utf-8")
    for must_be_todo in [
        "when_to_use: TODO_when_to_use",
        "when_not_to_use: TODO_when_not_to_use",
        "namespace: TODO_namespace",
        "required_fields: TODO_required_fields",
        "max_output_tokens: TODO_int",
        "destructive: TODO_bool",
        "open_world_access: TODO_bool",
    ]:
        assert must_be_todo in text, f"semantic field 必须写 TODO 而非伪造: {must_be_todo!r}"


def test_scaffold_includes_source_path_metadata_for_reviewer(tmp_path: Path) -> None:
    """每个 tool 必须带 metadata.scaffold_source 让 reviewer 跳回源码。"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "a.py").write_text("\n\ndef foo(x: str) -> dict:\n    return {}\n", encoding="utf-8")
    out = tmp_path / "tools.draft.yaml"
    scaffold_tools_yaml(src, out)
    text = out.read_text(encoding="utf-8")
    assert "scaffold_source: a.py:" in text
    assert "scaffold_status: draft" in text


def test_scaffold_refuses_to_overwrite_without_force(tmp_path: Path) -> None:
    """覆盖保护：避免冲掉手写正式 tools.yaml 的真实风险场景。"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "ok.py").write_text("def t(x: str) -> dict:\n    return {}\n", encoding="utf-8")
    out = tmp_path / "tools.yaml"
    out.write_text("tools: []  # hand-written\n", encoding="utf-8")
    with pytest.raises(FileExistsError, match="refused to overwrite"):
        scaffold_tools_yaml(src, out)
    assert "hand-written" in out.read_text(encoding="utf-8")
    summary = scaffold_tools_yaml(src, out, force=True)
    assert summary["tool_count"] == 1
    assert "hand-written" not in out.read_text(encoding="utf-8")


def test_scaffold_skips_tests_dir_and_dotfiles(tmp_path: Path) -> None:
    """测试目录里的 helper 不该被当工具——这是真实噪音过滤需求。"""
    src = tmp_path / "src"
    (src / "tests").mkdir(parents=True)
    (src / "tests" / "test_helper.py").write_text(
        "def helper_should_be_skipped(x: str) -> dict:\n    return {}\n", encoding="utf-8"
    )
    (src / ".hidden").mkdir()
    (src / ".hidden" / "x.py").write_text(
        "def hidden_should_be_skipped(x: str) -> dict:\n    return {}\n", encoding="utf-8"
    )
    (src / "real.py").write_text(
        "def real_tool(x: str) -> dict:\n    return {}\n", encoding="utf-8"
    )
    out = tmp_path / "tools.draft.yaml"
    summary = scaffold_tools_yaml(src, out)
    assert summary["tool_count"] == 1
    text = out.read_text(encoding="utf-8")
    assert "name: real_tool" in text
    assert "helper_should_be_skipped" not in text
    assert "hidden_should_be_skipped" not in text


def test_scaffold_handles_empty_directory(tmp_path: Path) -> None:
    """空目录写出 `tools: []` + 解释提示，不抛异常。"""
    src = tmp_path / "empty_src"
    src.mkdir()
    out = tmp_path / "tools.draft.yaml"
    summary = scaffold_tools_yaml(src, out)
    assert summary["tool_count"] == 0
    text = out.read_text(encoding="utf-8")
    assert "tools: []" in text
    assert "没有抽取到任何候选工具" in text


def test_scaffold_handles_syntax_error_file_without_aborting(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """单个文件 SyntaxError 不应该中止整个扫描——这是 onboarding 时常见场景
    （半成品文件 / 一份 .py 用了较新 syntax）。"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "broken.py").write_text("def broken(:\n", encoding="utf-8")
    (src / "ok.py").write_text("def good(x: str) -> dict:\n    return {}\n", encoding="utf-8")
    out = tmp_path / "tools.draft.yaml"
    summary = scaffold_tools_yaml(src, out)
    assert summary["tool_count"] == 1
    captured = capsys.readouterr()
    assert "broken.py" in captured.err
    assert "SyntaxError" in captured.err


# === Phase 3: CLI 端到端 ==============================================


def test_cli_scaffold_tools_subcommand_is_registered() -> None:
    """argparse 必须注册 scaffold-tools 子命令。"""
    from agent_tool_harness.cli import _build_parser

    parser = _build_parser()
    subparsers_action = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    assert "scaffold-tools" in subparsers_action.choices


def test_cli_scaffold_tools_required_flags() -> None:
    """--source / --out 必填；--force 是布尔 flag。"""
    from agent_tool_harness.cli import _build_parser

    parser = _build_parser()
    subparsers_action = next(
        a for a in parser._actions if isinstance(a, argparse._SubParsersAction)
    )
    sub = subparsers_action.choices["scaffold-tools"]
    flag_actions = {a.dest: a for a in sub._actions if a.dest != "help"}
    assert flag_actions["source"].required is True
    assert flag_actions["out"].required is True
    assert flag_actions["force"].const is True


def test_cli_scaffold_tools_runs_end_to_end(tmp_path: Path) -> None:
    """端到端：CLI 跑完后 draft 文件存在 + 含 tool name + 退出码 0。"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "ok.py").write_text(
        "def my_tool(payload: dict) -> dict:\n    '''do thing.'''\n    return payload\n",
        encoding="utf-8",
    )
    out = tmp_path / "tools.draft.yaml"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_tool_harness.cli",
            "scaffold-tools",
            "--source",
            str(src),
            "--out",
            str(out),
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "name: my_tool" in text
    assert "generated draft" in text
    assert f"wrote {out}" in result.stdout


def test_cli_scaffold_tools_overwrite_protection_via_cli(tmp_path: Path) -> None:
    """CLI 路径上的 --force 防护必须真的拦得住覆盖。"""
    src = tmp_path / "src"
    src.mkdir()
    (src / "ok.py").write_text("def t(x: str) -> dict:\n    return {}\n", encoding="utf-8")
    out = tmp_path / "tools.yaml"
    out.write_text("tools: []  # precious\n", encoding="utf-8")
    cmd = [
        sys.executable,
        "-m",
        "agent_tool_harness.cli",
        "scaffold-tools",
        "--source",
        str(src),
        "--out",
        str(out),
    ]
    bad = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True)
    assert bad.returncode == 2
    assert "refused to overwrite" in bad.stderr
    assert "precious" in out.read_text(encoding="utf-8")
    good = subprocess.run(cmd + ["--force"], cwd=REPO_ROOT, capture_output=True, text=True)
    assert good.returncode == 0
    assert "precious" not in out.read_text(encoding="utf-8")


# === Phase 4: 反向安全检查 ============================================


def test_scaffold_output_does_not_contain_secrets_lookalikes(tmp_path: Path) -> None:
    """draft 输出里**不得**意外渲染 sk- key / Authorization header 等字面值。

    用户源码可能包含这类字符串（例如 docstring 里贴了 `Authorization: Bearer xxx`
    举例），scaffold 当前**只**取 docstring 第一行——这条测试钉死即使源码
    docstring 含 secrets 字面值，也不会被复制进 draft 的"description"。
    """
    src = tmp_path / "src"
    src.mkdir()
    (src / "leaky.py").write_text(
        textwrap.dedent(
            '''
            def call_api(url: str) -> dict:
                """First line is safe.

                Internal note: Authorization: Bearer sk-test_THIS_MUST_NOT_LEAK_TO_DRAFT
                """
                return {}
            '''
        ),
        encoding="utf-8",
    )
    out = tmp_path / "tools.draft.yaml"
    scaffold_tools_yaml(src, out)
    text = out.read_text(encoding="utf-8")
    assert "First line is safe" in text
    assert "sk-test_THIS_MUST_NOT_LEAK_TO_DRAFT" not in text
    assert "Authorization: Bearer" not in text
