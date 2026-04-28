"""analyze-artifacts CLI 真实行为测试。

测试目标（不是为了通过率，而是为了发现真实 bug）：

- 钉死 CLI 能从已有 run 目录复盘 trace 信号；
- 钉死 good run 输出空 signals 但仍有 schema_version / run_metadata；
- 钉死缺路径 / 缺关键 artifact 时给可行动错误，不假成功；
- 钉死 markdown 输出包含 severity / evidence_refs / suggested_fix；
- 钉死 CLI 不会把自己说成 LLM Judge（披露字段必须出现 deterministic 字样）。

为什么不用 mock：CLI 是用户真实接入面，必须真实跑一份小 run 再 analyze，
否则测试只是在测 mock 自己。这里复用已有的 examples/runtime_debug fixture +
EvalRunner 直接生成 run artifacts。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_tool_harness.cli import main


def _run_harness(tmp_path: Path, mock_path: str) -> Path:
    """先用真实 run 子命令生成 artifacts，再交给 analyze-artifacts 复盘。

    这是最贴近真实用户路径的 fixture：他们手里就是这种 run 目录，没有 in-memory 对象。
    """

    out_dir = tmp_path / f"run-{mock_path}"
    rc = main([
        "run",
        "--project", "examples/runtime_debug/project.yaml",
        "--tools", "examples/runtime_debug/tools.yaml",
        "--evals", "examples/runtime_debug/evals.yaml",
        "--out", str(out_dir),
        "--mock-path", mock_path,
    ])
    assert rc == 0
    return out_dir


def test_analyze_artifacts_bad_run_produces_when_not_to_use_signal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """bad run 自然触发 tool_selected_in_when_not_to_use_context 信号。

    若未来谁改 trace_signal_analyzer 阈值或 examples/runtime_debug 的 when_not_to_use
    描述，这条断言会立刻报警——这正是测试要发现的 bug。
    """

    run_dir = _run_harness(tmp_path, "bad")
    out_dir = tmp_path / "analysis-bad"

    rc = main([
        "analyze-artifacts",
        "--run", str(run_dir),
        "--tools", "examples/runtime_debug/tools.yaml",
        "--evals", "examples/runtime_debug/evals.yaml",
        "--out", str(out_dir),
    ])
    assert rc == 0

    payload = json.loads((out_dir / "tool_use_signals.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0.0"
    assert payload["run_metadata"]["extra"]["command"] == "analyze-artifacts"
    assert payload["analysis_kind"] == "trace_derived_deterministic_heuristic"
    assert "deterministic" in payload["analysis_kind_note"].lower()

    flat = [
        s
        for sigs in payload["signals_by_eval"].values()
        for s in sigs
    ]
    assert any(s["signal_type"] == "tool_selected_in_when_not_to_use_context" for s in flat)
    for s in flat:
        # 字段契约：所有信号必带这 7 个字段（与 analyzer 单测同一组契约）。
        for key in (
            "signal_type", "severity", "evidence_refs",
            "related_tool", "related_eval", "why_it_matters", "suggested_fix",
        ):
            assert key in s

    md = (out_dir / "tool_use_signals.md").read_text(encoding="utf-8")
    assert "tool_selected_in_when_not_to_use_context" in md
    assert "[high]" in md
    assert "evidence:" in md
    assert "suggested fix" in md
    assert "NOT an LLM Judge" in md


def test_analyze_artifacts_good_run_emits_zero_signals_but_schema_complete(
    tmp_path: Path,
) -> None:
    """good run 不应触发任何 trace 信号；但 JSON 仍要有完整 schema 字段。

    这条钉死 "0 signal != broken"，避免未来有人把 0 signal 当成异常 fail。
    """

    run_dir = _run_harness(tmp_path, "good")
    out_dir = tmp_path / "analysis-good"

    rc = main([
        "analyze-artifacts",
        "--run", str(run_dir),
        "--tools", "examples/runtime_debug/tools.yaml",
        "--evals", "examples/runtime_debug/evals.yaml",
        "--out", str(out_dir),
    ])
    assert rc == 0

    payload = json.loads((out_dir / "tool_use_signals.json").read_text(encoding="utf-8"))
    assert payload["signal_count"] == 0
    assert payload["schema_version"] == "1.0.0"
    assert payload["signals_by_eval"]  # 至少包含 eval_id key（可能是空 list）
    for sigs in payload["signals_by_eval"].values():
        assert sigs == []

    md = (out_dir / "tool_use_signals.md").read_text(encoding="utf-8")
    assert "signal count: **0**" in md
    assert "No deterministic trace-derived signals fired" in md


def test_analyze_artifacts_missing_run_dir_gives_actionable_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--run 路径不存在时必须报可行动错误，不允许假成功。"""

    out_dir = tmp_path / "out"
    rc = main([
        "analyze-artifacts",
        "--run", str(tmp_path / "does-not-exist"),
        "--tools", "examples/runtime_debug/tools.yaml",
        "--out", str(out_dir),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "--run" in err
    assert "agent-tool-harness run" in err
    assert not out_dir.exists() or not (out_dir / "tool_use_signals.json").exists()


def test_analyze_artifacts_run_dir_without_jsonl_artifacts_errors(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """目录存在但既无 tool_calls.jsonl 也无 tool_responses.jsonl → 可行动错误。

    这模拟 "用户传错目录"（例如指到 runs/ 顶层而不是某次具体 run）。
    """

    fake_run = tmp_path / "fake-run"
    fake_run.mkdir()
    (fake_run / "README.md").write_text("not a real run")
    out_dir = tmp_path / "out"

    rc = main([
        "analyze-artifacts",
        "--run", str(fake_run),
        "--tools", "examples/runtime_debug/tools.yaml",
        "--out", str(out_dir),
    ])
    assert rc == 2
    err = capsys.readouterr().err
    assert "tool_calls.jsonl" in err
    assert "tool_responses.jsonl" in err


def test_analyze_artifacts_without_evals_warns_and_skips_when_not_to_use_signal(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """不传 --evals 时：必须 stderr 警告 + 不再触发 when_not_to_use 信号。

    这条钉死 "user_prompt 来源契约"：when_not_to_use 信号必须依赖 user_prompt 才能算出，
    否则会引入虚假信号。
    """

    run_dir = _run_harness(tmp_path, "bad")
    out_dir = tmp_path / "analysis-no-evals"

    rc = main([
        "analyze-artifacts",
        "--run", str(run_dir),
        "--tools", "examples/runtime_debug/tools.yaml",
        "--out", str(out_dir),
    ])
    assert rc == 0
    err = capsys.readouterr().err
    assert "--evals" in err
    assert "tool_selected_in_when_not_to_use_context" in err

    payload = json.loads((out_dir / "tool_use_signals.json").read_text(encoding="utf-8"))
    flat = [
        s
        for sigs in payload["signals_by_eval"].values()
        for s in sigs
    ]
    assert not any(
        s["signal_type"] == "tool_selected_in_when_not_to_use_context" for s in flat
    )
