"""CLI 错误显示治理测试。

为什么需要这组测试：真实用户接入 agent-tool-harness 时，**最常见的失败面就是 YAML
路径错、字段错、source=tests 缺 --tests**。如果 CLI 把 Python traceback 直接抛出来，
真实团队会卡在“到底是我配错了还是框架有 bug”。这组测试锁死“出错时必须给出可行动
hint 且退出码 = 2”这一行为。

测试纪律：
- 不允许放宽断言来追求通过；如果未来某条 hint 文案要改，必须同时更新这里的断言，
  并解释改动如何让真实用户更容易定位问题。
"""

from __future__ import annotations

import pytest

from agent_tool_harness.cli import main


def _write(path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def test_cli_reports_friendly_error_for_missing_tools_file(tmp_path, capsys):
    """传错 --tools 路径时，CLI 必须输出 file not found 提示并退出码 2。"""

    rc = main(["audit-tools", "--tools", str(tmp_path / "nope.yaml"), "--out", str(tmp_path / "o")])
    err = capsys.readouterr().err

    assert rc == 2
    assert "file not found" in err or "configuration invalid" in err
    assert "hint" in err


def test_cli_reports_friendly_error_for_scalar_root_tools_yaml(tmp_path, capsys):
    """tools.yaml root 是 scalar 时，必须报 configuration invalid 而不是 traceback。"""

    bad = tmp_path / "tools.yaml"
    _write(bad, "just-a-string\n")
    rc = main(["audit-tools", "--tools", str(bad), "--out", str(tmp_path / "o")])
    err = capsys.readouterr().err

    assert rc == 2
    assert "configuration invalid" in err
    assert "mapping or list" in err  # ConfigError 原文里要包含位置/字段提示
    assert "hint" in err


def test_cli_reports_friendly_error_for_bad_tools_entry(tmp_path, capsys):
    """tools[*] 不是 mapping 时，CLI 应给出条目位置提示。"""

    bad = tmp_path / "tools.yaml"
    _write(bad, "tools:\n  - not-a-mapping\n")
    rc = main(["audit-tools", "--tools", str(bad), "--out", str(tmp_path / "o")])
    err = capsys.readouterr().err

    assert rc == 2
    assert "configuration invalid" in err
    assert "tools[0]" in err


def test_cli_reports_friendly_error_for_duplicate_eval_id(tmp_path, capsys):
    """eval.id 重复必须被 CLI 转成可行动错误。"""

    bad = tmp_path / "evals.yaml"
    prompt = "'enough length user prompt text'"
    entry_a = (
        "  - {id: dup, name: a, category: c, split: training, realism_level: real,\n"
        f"     complexity: multi_step, source: s, user_prompt: {prompt},\n"
        "     initial_context: {x: 1}, verifiable_outcome: {y: 2}, success_criteria: [a],\n"
        "     expected_tool_behavior: {required_tools: [t]}, judge: {rules: []}}\n"
    )
    entry_b = (
        "  - {id: dup, name: b, category: c, split: training, realism_level: real,\n"
        f"     complexity: multi_step, source: s, user_prompt: {prompt},\n"
        "     initial_context: {x: 1}, verifiable_outcome: {y: 2}, success_criteria: [a],\n"
        "     expected_tool_behavior: {required_tools: [t]}, judge: {rules: []}}\n"
    )
    _write(bad, "evals:\n" + entry_a + entry_b)
    rc = main(["audit-evals", "--evals", str(bad), "--out", str(tmp_path / "o")])
    err = capsys.readouterr().err

    assert rc == 2
    assert "configuration invalid" in err
    assert "dup" in err
    assert "unique" in err


def test_cli_warns_when_tools_yaml_is_empty(tmp_path, capsys):
    """空 tools.yaml 不强制 hard fail，但必须打印 warning，避免静默 0 工具评估。"""

    empty = tmp_path / "tools.yaml"
    _write(empty, "tools: []\n")
    rc = main(["audit-tools", "--tools", str(empty), "--out", str(tmp_path / "o")])
    captured = capsys.readouterr()

    assert rc == 0
    assert "warning" in captured.err
    assert "empty" in captured.err


def test_cli_rejects_source_tests_without_tests_arg(tmp_path, capsys):
    """`--source tests` 缺 `--tests` 应给出明确组合错误，而不是 argparse 内部异常。"""

    project = tmp_path / "project.yaml"
    _write(project, "project:\n  name: demo\n  domain: d\n  description: x\n")
    tools = tmp_path / "tools.yaml"
    _write(tools, "tools: []\n")
    rc = main(
        [
            "generate-evals",
            "--project",
            str(project),
            "--tools",
            str(tools),
            "--source",
            "tests",
            "--out",
            str(tmp_path / "out.yaml"),
        ]
    )
    err = capsys.readouterr().err

    assert rc == 2
    assert "--tests" in err
    assert "requires" in err


def test_cli_argparse_unknown_command_still_uses_argparse(capsys):
    """argparse 自身的 usage error 仍由 argparse 处理（保持原退出码 2）。"""

    with pytest.raises(SystemExit) as excinfo:
        main(["definitely-not-a-command"])
    assert excinfo.value.code == 2
