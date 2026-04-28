"""v1.4 第二轮契约测试：``--judge-provider anthropic_compatible_live`` CLI。

本测试模块负责什么
==================
钉住 v1.4 第二轮新增 CLI 入口的**安全契约**：

1. 默认（无 --live、无 --confirm-i-have-real-key、无 fake fixture）→
   advisory 全部返回 ``disabled_live_provider`` 错误（脱敏），不联网；
2. 单传 --live 不够 → 同样 disabled_live_provider；
3. 双标志齐 + env 缺 → ``missing_config``（脱敏），不联网；
4. fake transport fixture（responses）→ advisory 写入 PASS，但 deterministic
   baseline **不**被覆盖（仍由 RuleJudge 决定 metrics 中 passed/failed）；
5. fake transport fixture（raise_error）→ advisory 写入对应 error_code，
   绝不静默 PASS；
6. 旧路径 ``--judge-provider recorded`` 等不退化（关键回归保护）。

本模块**不**负责什么
====================
- 不真实联网；任何"真实 HTTP"在 CI 永远 disabled；
- 不验证 LLM 语义质量——v1.4 还没有真实 LLM。

用户项目自定义入口
==================
照抄本测试中的 fake fixture 结构（``responses`` / ``raise_error``）即可
让自己的项目在 CI 中走 fake transport 走查 advisory 写入面，不依赖真实 key。
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from agent_tool_harness.cli import main

# 用一个明显的 fake key，便于在所有 artifact / report / metrics 中扫描
# 它是否被泄漏；测试断言"无论走哪条错误/成功路径，FAKE_KEY 都不应出现"。
FAKE_KEY = "sk-test-fake-key-1234567890abcdef-DO-NOT-LEAK"
FAKE_BASE_URL = "https://fake-host.local/v1/messages"


def _project(tmp: Path) -> dict[str, str]:
    """复用 examples/runtime_debug 跑端到端 smoke。"""
    return {
        "project": "examples/runtime_debug/project.yaml",
        "tools": "examples/runtime_debug/tools.yaml",
        "evals": "examples/runtime_debug/evals.yaml",
    }


def _read_judge_results(out: Path) -> dict:
    return json.loads((out / "judge_results.json").read_text(encoding="utf-8"))


def _scan_no_leak(out: Path) -> None:
    """对 run 目录所有文件做 key/url 字面值扫描——泄漏即测试失败。

    这是"防 secret 泄漏"的兜底测试：哪怕 provider/transport 内部脱敏路径
    全部都被 bypass，只要某条新增代码不小心把 key/url 写进了 artifact/
    report/metrics，本扫描就会立刻失败。
    """
    for p in out.rglob("*"):
        if not p.is_file():
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        assert FAKE_KEY not in text, f"FAKE_KEY leaked into {p}"
        assert FAKE_BASE_URL not in text, f"FAKE_BASE_URL leaked into {p}"


def _set_full_env(monkeypatch) -> None:
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_PROVIDER", "anthropic_compatible")
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_BASE_URL", FAKE_BASE_URL)
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_API_KEY", FAKE_KEY)
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_MODEL", "claude-3-fake")


def _clear_env(monkeypatch) -> None:
    for k in (
        "AGENT_TOOL_HARNESS_LLM_PROVIDER",
        "AGENT_TOOL_HARNESS_LLM_BASE_URL",
        "AGENT_TOOL_HARNESS_LLM_API_KEY",
        "AGENT_TOOL_HARNESS_LLM_MODEL",
    ):
        monkeypatch.delenv(k, raising=False)


def _run_cli_with_socket_ban(monkeypatch, args: list[str]) -> int:
    """运行 CLI 且禁止任何真实 socket：CI 永远不应联网。

    若代码不慎触发 socket 构造（比如把 LiveAnthropicTransport 错误地接到了
    真实 HTTPSConnection），本 monkeypatch 会立即抛 RuntimeError 让测试
    显眼失败。
    """
    import socket

    def _banned(*_a, **_kw):  # noqa: ANN001
        raise RuntimeError("CI smoke must not open real sockets!")

    monkeypatch.setattr(socket, "socket", _banned)
    return main(args)


def test_live_default_disabled_no_socket(tmp_path, monkeypatch):
    """默认无 --live、无 --confirm、无 fake fixture → advisory 全 disabled，不联网。"""
    _clear_env(monkeypatch)
    out = tmp_path / "run"
    p = _project(tmp_path)
    rc = _run_cli_with_socket_ban(
        monkeypatch,
        [
            "run",
            "--project", p["project"], "--tools", p["tools"], "--evals", p["evals"],
            "--out", str(out), "--mock-path", "bad",
            "--judge-provider", "anthropic_compatible_live",
        ],
    )
    assert rc == 0
    jr = _read_judge_results(out)
    advisories = jr["dry_run_provider"]["results"]
    assert advisories, "advisory results 不应为空"
    for entry in advisories:
        # env 全空时 AnthropicCompatibleJudgeProvider 在 send 之前优先返回
        # missing_config；若 env 已配但双标志缺则会返回 disabled_live_provider。
        assert entry["error"]["type"] in {
            "missing_config", "disabled_live_provider",
        }


def test_live_only_live_flag_still_disabled(tmp_path, monkeypatch):
    """--live 单独传不算完整 opt-in；env 完整也仍 disabled_live_provider。"""
    _set_full_env(monkeypatch)
    out = tmp_path / "run"
    p = _project(tmp_path)
    rc = _run_cli_with_socket_ban(
        monkeypatch,
        [
            "run",
            "--project", p["project"], "--tools", p["tools"], "--evals", p["evals"],
            "--out", str(out), "--mock-path", "bad",
            "--judge-provider", "anthropic_compatible_live",
            "--live",
        ],
    )
    assert rc == 0
    jr = _read_judge_results(out)
    for entry in jr["dry_run_provider"]["results"]:
        assert entry["error"]["type"] == "disabled_live_provider"
    _scan_no_leak(out)


def test_live_full_optin_but_env_missing(tmp_path, monkeypatch):
    """双标志齐但 env 缺 → missing_config（脱敏）。"""
    _clear_env(monkeypatch)
    out = tmp_path / "run"
    p = _project(tmp_path)
    rc = _run_cli_with_socket_ban(
        monkeypatch,
        [
            "run",
            "--project", p["project"], "--tools", p["tools"], "--evals", p["evals"],
            "--out", str(out), "--mock-path", "bad",
            "--judge-provider", "anthropic_compatible_live",
            "--live", "--confirm-i-have-real-key",
        ],
    )
    assert rc == 0
    jr = _read_judge_results(out)
    for entry in jr["dry_run_provider"]["results"]:
        assert entry["error"]["type"] == "missing_config"


def test_fake_transport_fixture_success(tmp_path, monkeypatch):
    """fake fixture（responses）→ advisory PASS 写入；deterministic baseline 不被覆盖。"""
    _set_full_env(monkeypatch)
    fix = tmp_path / "fake.yaml"
    fix.write_text(
        yaml.safe_dump({
            "responses": {
                "runtime_input_boundary_regression": {
                    "passed": True,
                    "rationale": "fake advisory PASS",
                    "confidence": 0.5,
                    "rubric": "test fixture",
                }
            }
        }),
        encoding="utf-8",
    )
    out = tmp_path / "run"
    p = _project(tmp_path)
    rc = _run_cli_with_socket_ban(
        monkeypatch,
        [
            "run",
            "--project", p["project"], "--tools", p["tools"], "--evals", p["evals"],
            "--out", str(out), "--mock-path", "bad",
            "--judge-provider", "anthropic_compatible_live",
            "--judge-fake-transport-fixture", str(fix),
        ],
    )
    assert rc == 0
    jr = _read_judge_results(out)
    advisories = jr["dry_run_provider"]["results"]
    assert advisories
    entry = advisories[0]
    # 成功路径：entry 含 advisory_result（composite 单 advisory schema）
    assert entry.get("passed") is False  # composite passed = deterministic_passed
    assert entry["advisory_result"]["passed"] is True
    assert entry["advisory_result"]["rationale"] == "fake advisory PASS"
    # deterministic baseline 仍由 RuleJudge 决定（mock-path bad → fail）
    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["failed"] == 1
    _scan_no_leak(out)


def test_fake_transport_fixture_raise_error_sanitized(tmp_path, monkeypatch):
    """fake fixture（raise_error: auth_error）→ advisory 写入脱敏 error_code。"""
    _set_full_env(monkeypatch)
    fix = tmp_path / "fake.yaml"
    fix.write_text(
        yaml.safe_dump({"raise_error": "auth_error"}),
        encoding="utf-8",
    )
    out = tmp_path / "run"
    p = _project(tmp_path)
    rc = _run_cli_with_socket_ban(
        monkeypatch,
        [
            "run",
            "--project", p["project"], "--tools", p["tools"], "--evals", p["evals"],
            "--out", str(out), "--mock-path", "bad",
            "--judge-provider", "anthropic_compatible_live",
            "--judge-fake-transport-fixture", str(fix),
        ],
    )
    assert rc == 0
    jr = _read_judge_results(out)
    for entry in jr["dry_run_provider"]["results"]:
        assert entry["error"]["type"] == "auth_error"
        msg = entry["error"]["message"]
        assert FAKE_KEY not in msg
        assert FAKE_BASE_URL not in msg
    _scan_no_leak(out)


def test_recorded_path_unchanged(tmp_path, monkeypatch):
    """旧 ``--judge-provider recorded`` 路径不退化（v1.4 第二轮兼容性回归）。"""
    rec = tmp_path / "rec.yaml"
    rec.write_text(
        yaml.safe_dump({
            "judgments": {
                "runtime_input_boundary_regression": {
                    "passed": True,
                    "rationale": "recorded baseline",
                    "confidence": 1.0,
                    "rubric": "v1.0",
                }
            }
        }),
        encoding="utf-8",
    )
    out = tmp_path / "run"
    p = _project(tmp_path)
    rc = main([
        "run",
        "--project", p["project"], "--tools", p["tools"], "--evals", p["evals"],
        "--out", str(out), "--mock-path", "good",
        "--judge-provider", "recorded",
        "--judge-recording", str(rec),
    ])
    assert rc == 0
    jr = _read_judge_results(out)
    advisories = jr["dry_run_provider"]["results"]
    assert advisories[0]["provider"] == "recorded"
