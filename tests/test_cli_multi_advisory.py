"""v1.5 第一轮契约测试：``--judge-advisory`` 多 advisory CLI 入口。

本测试模块负责什么
==================
钉住 v1.5 第一轮新增 CLI flag 的契约：

1. 多次 ``--judge-advisory`` 装配 CompositeJudgeProvider 多 advisory 列表，
   ``judge_results.json::dry_run_provider`` 中应出现 ``advisory_results`` /
   ``vote_distribution`` / ``majority_passed`` 字段；
2. deterministic baseline **不**被 advisory 覆盖：metrics 里的 passed/failed
   仍由 RuleJudge 决定（这是 v1.x 第一轮就立下的反 hack 边界，本轮多 advisory
   不能破坏它）；
3. 与 ``--judge-provider`` 互斥：同时给两者立即 exit 2；
4. 未知 NAME / 缺 ``:`` 分隔 / 缺 PATH → exit 2 + 可行动 hint，**不**默认
   退化成 RuleJudge 让用户误以为成功；
5. 默认无 ``--judge-advisory`` → 不出现 ``dry_run_provider`` 段（v1.0 字节兼容）。

本模块**不**负责什么
====================
- 不真实联网；本 flag 永远不接 live transport；
- 不验证投票算法本身——已由 ``tests/test_composite_multi_advisory.py`` 覆盖。
"""

from __future__ import annotations

import json
from pathlib import Path

from agent_tool_harness.cli import main

EXAMPLE_PROJECT = "examples/runtime_debug/project.yaml"
EXAMPLE_TOOLS = "examples/runtime_debug/tools.yaml"
EXAMPLE_EVALS = "examples/runtime_debug/evals.yaml"


def _set_full_env(monkeypatch) -> None:
    # AnthropicCompatibleJudgeProvider 在 send 之前先校验 4 个 env；多 advisory
    # 中含 anthropic_compatible_* 时若 env 缺会全条目走 missing_config，使
    # vote_distribution.error == total，无法验证 majority 路径——所以 fake env。
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_PROVIDER", "anthropic_compatible")
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_BASE_URL", "https://fake.local/v1/m")
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_API_KEY", "sk-fake-multi-adv-key")
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_MODEL", "claude-3-fake")


def _write_recorded(tmp: Path, name: str, passed: bool) -> Path:
    p = tmp / f"{name}.yaml"
    p.write_text(
        "judgments:\n"
        "  runtime_input_boundary_regression:\n"
        f"    passed: {'true' if passed else 'false'}\n"
        f"    rationale: 'fake recorded advisory {name} ({passed})'\n"
        "    confidence: 0.7\n"
        "    rubric: 'multi-advisory smoke fixture'\n",
        encoding="utf-8",
    )
    return p


def _write_fake_transport(tmp: Path, passed: bool) -> Path:
    p = tmp / "fake_transport.yaml"
    p.write_text(
        "responses:\n"
        "  runtime_input_boundary_regression:\n"
        f"    passed: {'true' if passed else 'false'}\n"
        "    rationale: 'fake transport advisory for multi-advisory smoke'\n"
        "    confidence: 0.5\n"
        "    rubric: 'v1.5 fake_transport multi-advisory fixture'\n",
        encoding="utf-8",
    )
    return p


def _read_judge_results(out: Path) -> dict:
    return json.loads((out / "judge_results.json").read_text(encoding="utf-8"))


def test_multi_advisory_two_recorded_majority(tmp_path, monkeypatch):
    """两条 ``recorded`` advisory → 多 advisory schema 三字段齐 + det 不被覆盖。"""

    _set_full_env(monkeypatch)
    a1 = _write_recorded(tmp_path, "rec_pass", True)
    a2 = _write_recorded(tmp_path, "rec_fail", False)
    out = tmp_path / "run"
    rc = main(
        [
            "run",
            "--project", EXAMPLE_PROJECT, "--tools", EXAMPLE_TOOLS, "--evals", EXAMPLE_EVALS,
            "--out", str(out), "--mock-path", "good",
            "--judge-advisory", f"recorded:{a1}",
            "--judge-advisory", f"recorded:{a2}",
        ]
    )
    assert rc == 0
    jr = _read_judge_results(out)
    drp = jr["dry_run_provider"]
    entry = drp["results"][0]
    assert entry["mode"] == "composite"
    assert entry["provider"] == "composite"
    # 多 advisory schema 三字段必须齐
    assert "advisory_results" in entry
    assert len(entry["advisory_results"]) == 2
    assert "vote_distribution" in entry
    vd = entry["vote_distribution"]
    assert vd["total"] == 2
    assert vd["pass"] + vd["fail"] + vd["error"] == 2
    assert "majority_passed" in entry
    # deterministic baseline 不被覆盖：mock-path good → RuleJudge passed=true
    assert entry["passed"] is True


def test_multi_advisory_mutual_exclusion_with_provider(tmp_path, monkeypatch, capsys):
    """``--judge-advisory`` 与 ``--judge-provider`` 互斥 → exit 2 + 可行动错误。"""

    a1 = _write_recorded(tmp_path, "rec_pass", True)
    out = tmp_path / "run"
    rc = main(
        [
            "run",
            "--project", EXAMPLE_PROJECT, "--tools", EXAMPLE_TOOLS, "--evals", EXAMPLE_EVALS,
            "--out", str(out), "--mock-path", "good",
            "--judge-provider", "recorded", "--judge-recording", str(a1),
            "--judge-advisory", f"recorded:{a1}",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "互斥" in err


def test_multi_advisory_unknown_name(tmp_path, capsys):
    """未知 NAME → exit 2 + hint，不默默退化成 RuleJudge。"""

    out = tmp_path / "run"
    rc = main(
        [
            "run",
            "--project", EXAMPLE_PROJECT, "--tools", EXAMPLE_TOOLS, "--evals", EXAMPLE_EVALS,
            "--out", str(out), "--mock-path", "good",
            "--judge-advisory", "live_llm:/tmp/whatever.yaml",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "未知 NAME" in err


def test_multi_advisory_missing_colon(tmp_path, capsys):
    """缺 ``:`` 分隔 → exit 2 + hint。"""

    out = tmp_path / "run"
    rc = main(
        [
            "run",
            "--project", EXAMPLE_PROJECT, "--tools", EXAMPLE_TOOLS, "--evals", EXAMPLE_EVALS,
            "--out", str(out), "--mock-path", "good",
            "--judge-advisory", "recorded_no_colon",
        ]
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "NAME:PATH" in err


def test_multi_advisory_with_fake_transport(tmp_path, monkeypatch):
    """``recorded`` + ``anthropic_compatible_fake`` 混合，无真实 socket。"""

    import socket

    def _banned(*_a, **_kw):
        raise RuntimeError("multi-advisory smoke must not open real sockets!")

    monkeypatch.setattr(socket, "socket", _banned)

    _set_full_env(monkeypatch)
    a1 = _write_recorded(tmp_path, "rec_pass", True)
    a2 = _write_fake_transport(tmp_path, True)
    out = tmp_path / "run"
    rc = main(
        [
            "run",
            "--project", EXAMPLE_PROJECT, "--tools", EXAMPLE_TOOLS, "--evals", EXAMPLE_EVALS,
            "--out", str(out), "--mock-path", "good",
            "--judge-advisory", f"recorded:{a1}",
            "--judge-advisory", f"anthropic_compatible_fake:{a2}",
        ]
    )
    assert rc == 0
    jr = _read_judge_results(out)
    entry = jr["dry_run_provider"]["results"][0]
    assert len(entry["advisory_results"]) == 2
    assert entry["vote_distribution"]["total"] == 2
    # 同时扫一遍：fake key/url 不应被泄漏到任何 artifact
    for p in out.rglob("*"):
        if p.is_file():
            try:
                text = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            assert "sk-fake-multi-adv-key" not in text
            assert "fake.local" not in text


def test_default_no_advisory_no_dry_run_provider_segment(tmp_path):
    """默认无 ``--judge-advisory`` 与 ``--judge-provider`` → 字节兼容 v1.0。"""

    out = tmp_path / "run"
    rc = main(
        [
            "run",
            "--project", EXAMPLE_PROJECT, "--tools", EXAMPLE_TOOLS, "--evals", EXAMPLE_EVALS,
            "--out", str(out), "--mock-path", "good",
        ]
    )
    assert rc == 0
    jr = _read_judge_results(out)
    # v1.0 字节兼容：未启用任何 dry-run provider 时 dry_run_provider 段不应写入。
    assert "dry_run_provider" not in jr
