"""Anthropic-compatible provider preflight 契约测试（v1.x 第三轮）。

中文学习型说明
==============
这些测试不是为了把通过率刷高，而是把"未来真实 LLM judge live 之前最容易
出的安全事故"以 fake/monkeypatch 形式钉死：

- 缺 env 配置时 preflight **必须**清晰报出 `missing_fields`，而不是静默
  pass；
- `.gitignore` 不忽略 `.env` 时 **必须**给可行动 hint；
- `.env.example` 含真实 `=value` 时 **必须**报具体 KEY 名，但**不**回 value
  本身（防止 preflight artifact 二次泄漏）；
- 8 类 error taxonomy 的 message 模板**必须**脱敏（用真实长 key / 真实
  base_url 试探，确认它们不会出现在 message 中）；
- preflight artifact (`preflight.json` / `preflight.md`) 在任何路径下
  **必须**不出现 `api_key` / `base_url` 字面值；
- preflight CLI 在 `monkeypatch.setattr(socket, "socket", _BannedSocket)`
  下仍跑通——双重钉死"不开网络"硬约束。
"""

from __future__ import annotations

import socket
from pathlib import Path

from agent_tool_harness.cli import main as cli_main
from agent_tool_harness.judges.preflight import (
    PREFLIGHT_SCHEMA_VERSION,
    AnthropicCompatibleConfig,
    PreflightReport,
    run_preflight,
    write_preflight_artifacts,
)

# 这些 fake 常量用于"泄漏扫描"——任何真实 key 形态字符串都不应出现在
# preflight artifact / message 模板中。故意用"显眼可识别"格式，便于 grep。
FAKE_KEY = "sk-fake-preflight-key-DO-NOT-USE-IN-PROD"
FAKE_BASE_URL = "https://fake-anthropic-compatible.preflight.example.invalid"
FAKE_MODEL = "fake-preflight-model"


def _full_config() -> AnthropicCompatibleConfig:
    return AnthropicCompatibleConfig(
        provider="anthropic_compatible",
        base_url=FAKE_BASE_URL,
        api_key=FAKE_KEY,
        model=FAKE_MODEL,
    )


def test_preflight_reports_missing_fields_when_env_empty(tmp_path: Path) -> None:
    """空 config 必须报全部 4 个字段缺失，并产出可行动 hint。

    模拟边界：用户首次安装、还没写 .env，跑 preflight。
    """

    config = AnthropicCompatibleConfig()
    # 临时仓库结构：含 .gitignore（合规）+ .env.example（合规）。
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "AGENT_TOOL_HARNESS_LLM_API_KEY=\n", encoding="utf-8"
    )
    report = run_preflight(config, repo_root=tmp_path)
    assert isinstance(report, PreflightReport)
    assert report.schema_version == PREFLIGHT_SCHEMA_VERSION
    assert report.live_mode_enabled is False
    assert set(report.config_status["missing_fields"]) == {
        "AGENT_TOOL_HARNESS_LLM_PROVIDER",
        "AGENT_TOOL_HARNESS_LLM_BASE_URL",
        "AGENT_TOOL_HARNESS_LLM_API_KEY",
        "AGENT_TOOL_HARNESS_LLM_MODEL",
    }
    assert report.summary["config_complete"] is False
    assert report.summary["ready_for_live"] is False
    assert any("AGENT_TOOL_HARNESS_LLM_API_KEY" in h for h in report.actionable_hints)


def test_preflight_flags_gitignore_missing_dotenv(tmp_path: Path) -> None:
    """.gitignore 不含 `.env` 时必须给可行动 hint。

    模拟边界：用户从模板克隆但忘了把 .env 加到 .gitignore，准备 commit
    包含真实 key 的 .env。
    """

    (tmp_path / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "AGENT_TOOL_HARNESS_LLM_API_KEY=\n", encoding="utf-8"
    )
    report = run_preflight(_full_config(), repo_root=tmp_path)
    assert report.gitignore_status["ignores_dotenv"] is False
    assert report.summary["gitignore_safe"] is False
    assert any(".gitignore" in h for h in report.actionable_hints)


def test_preflight_detects_real_value_in_env_example_without_leaking(
    tmp_path: Path,
) -> None:
    """.env.example 含真实 `KEY=VALUE` 时必须报 KEY 名但**不**把 VALUE 写进 artifact。

    模拟边界：有人把测试时 export 的真实 key 误粘到 .env.example。
    """

    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    leaked_value = "sk-preflight-leaked-value-DO-NOT-USE"
    (tmp_path / ".env.example").write_text(
        f"AGENT_TOOL_HARNESS_LLM_API_KEY={leaked_value}\n",
        encoding="utf-8",
    )
    report = run_preflight(_full_config(), repo_root=tmp_path)
    assert report.env_example_status["all_placeholders"] is False
    assert "AGENT_TOOL_HARNESS_LLM_API_KEY" in report.env_example_status[
        "non_placeholder_keys"
    ]
    # 关键断言：value 本身不允许出现在任何 status 字段或 hint 中。
    serialized = repr(report.env_example_status) + " ".join(report.actionable_hints)
    assert leaked_value not in serialized


def test_preflight_error_taxonomy_messages_are_safe(tmp_path: Path) -> None:
    """即使 config 含真实长 key / base_url，8 类 error message 也不应泄漏。"""

    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "AGENT_TOOL_HARNESS_LLM_API_KEY=\n", encoding="utf-8"
    )
    report = run_preflight(_full_config(), repo_root=tmp_path)
    self_test = report.provider_self_test
    assert self_test["error_taxonomy_total"] == 8
    assert self_test["error_taxonomy_safe"] == 8
    for entry in self_test["results"]:
        assert entry["leaks_api_key"] is False
        assert entry["leaks_base_url"] is False


def test_preflight_artifacts_do_not_contain_secret_literals(
    tmp_path: Path,
) -> None:
    """`preflight.json` / `preflight.md` 任何路径下都不能出现 key/base_url 字面值。"""

    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "AGENT_TOOL_HARNESS_LLM_API_KEY=\n", encoding="utf-8"
    )
    out = tmp_path / "out"
    report = run_preflight(_full_config(), repo_root=tmp_path)
    write_preflight_artifacts(report, out)

    json_text = (out / "preflight.json").read_text(encoding="utf-8")
    md_text = (out / "preflight.md").read_text(encoding="utf-8")
    for blob in (json_text, md_text):
        assert FAKE_KEY not in blob
        assert FAKE_BASE_URL not in blob
        # FAKE_MODEL 也属敏感（model 名可能透露模型选型），同样不应落到
        # preflight artifact——本轮 preflight 只回 model_set 布尔。
        assert FAKE_MODEL not in blob


def test_cli_judge_provider_preflight_runs_offline_under_socket_ban(
    tmp_path: Path, monkeypatch
) -> None:
    """CLI `judge-provider-preflight` 在禁用 socket.socket 后仍然跑通。

    模拟边界：双重保险——业务代码不应在 preflight 路径上开任何 socket。
    """

    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "AGENT_TOOL_HARNESS_LLM_API_KEY=\n", encoding="utf-8"
    )

    class _BannedSocket:
        def __init__(self, *a, **kw):
            raise RuntimeError("socket is banned in preflight test")

    monkeypatch.setattr(socket, "socket", _BannedSocket)

    out = tmp_path / "preflight_out"
    rc = cli_main(
        [
            "judge-provider-preflight",
            "--out",
            str(out),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert (out / "preflight.json").is_file()
    assert (out / "preflight.md").is_file()


def test_cli_judge_provider_preflight_with_real_env_does_not_leak(
    tmp_path: Path, monkeypatch
) -> None:
    """env 中含 fake key/base_url/model 时，artifact 必须不泄漏字面值。"""

    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_PROVIDER", "anthropic_compatible")
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_BASE_URL", FAKE_BASE_URL)
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_API_KEY", FAKE_KEY)
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_MODEL", FAKE_MODEL)
    (tmp_path / ".gitignore").write_text(".env\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text(
        "AGENT_TOOL_HARNESS_LLM_API_KEY=\n", encoding="utf-8"
    )

    out = tmp_path / "preflight_out"
    rc = cli_main(
        [
            "judge-provider-preflight",
            "--out",
            str(out),
            "--repo-root",
            str(tmp_path),
        ]
    )
    assert rc == 0
    json_text = (out / "preflight.json").read_text(encoding="utf-8")
    md_text = (out / "preflight.md").read_text(encoding="utf-8")
    for blob in (json_text, md_text):
        assert FAKE_KEY not in blob
        assert FAKE_BASE_URL not in blob
        assert FAKE_MODEL not in blob
    # 但是字段齐全 + .gitignore 合规 + .env.example 合规这件事必须能从 json 看出来。
    import json as _json

    data = _json.loads(json_text)
    assert data["summary"]["config_complete"] is True
    assert data["summary"]["gitignore_safe"] is True
    assert data["summary"]["env_example_safe"] is True
    assert data["summary"]["ready_for_live"] is False  # 永远 False，本轮不开 live
