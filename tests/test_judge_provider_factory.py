"""JudgeProviderFactory 测试。

测试纪律：
- 所有测试零网络依赖
- 不读取 .env / os.environ
- 不调用真实 LLM
- 使用 tempfile 创建 fixture 文件
- 所有 live 路径注入 http_factory（绝不回退到真实 HTTPSConnection）
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from agent_tool_harness.judge_provider_factory import (
    FactoryError,
    FactoryResult,
    create_judge_provider,
)
from agent_tool_harness.secrets import MappingSecretSource

# ---------------------------------------------------------------------------
# shared helpers
# ---------------------------------------------------------------------------


def _fake_http_factory(host, port, timeout):
    """注入到 transport 的 fake connection factory，零网络。"""
    conn = MagicMock()
    resp = MagicMock()
    resp.status = 200
    import json

    resp.read.return_value = json.dumps({
        "choices": [{"message": {"content": '{"passed": true, "rationale": "fake"}'}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }).encode("utf-8")
    conn.getresponse.return_value = resp
    return conn


VALID_PROVIDERS_YAML = """
providers:
  openai-native:
    family: openai
    compatibility: native
    model: gpt-4.1-mini
    api_key_env: OPENAI_API_KEY
  anthropic-native:
    family: anthropic
    compatibility: native
    model: claude-sonnet-4-6
    api_key_env: ANTHROPIC_API_KEY
  openai-compatible:
    family: openai
    compatibility: compatible
    model: deepseek-v3
    api_key_env: DEEPSEEK_API_KEY
    base_url: https://api.deepseek.com
"""


# ---------------------------------------------------------------------------
# 1. safety gate: dual flags
# ---------------------------------------------------------------------------


def test_missing_dual_flags_rejected():
    """双标志任一缺失 → FactoryError。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        with pytest.raises(FactoryError, match="双标志"):
            create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="openai-native",
                live_enabled=False,
                live_confirmed=False,
            )


def test_live_only_without_confirm_rejected():
    """仅 live_enabled → FactoryError。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        with pytest.raises(FactoryError, match="双标志"):
            create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="openai-native",
                live_enabled=True,
                live_confirmed=False,
            )


# ---------------------------------------------------------------------------
# 2. safety gate: missing config
# ---------------------------------------------------------------------------


def test_missing_llm_config_rejected():
    """缺 --llm-config → FactoryError。"""
    with pytest.raises(FactoryError, match="llm-config"):
        create_judge_provider(
            llm_config_path="",
            llm_provider_name="openai-native",
            live_enabled=True,
            live_confirmed=True,
        )


def test_missing_llm_provider_rejected():
    """缺 --llm-provider → FactoryError。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        with pytest.raises(FactoryError, match="llm-provider"):
            create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="",
                live_enabled=True,
                live_confirmed=True,
            )


# ---------------------------------------------------------------------------
# 3. safety gate: missing API key
# ---------------------------------------------------------------------------


def test_missing_api_key_rejected():
    """secret source 中不存在对应 key → MissingApiKeyError。"""
    from agent_tool_harness.llm_config import MissingApiKeyError

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        with pytest.raises(MissingApiKeyError):
            create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="openai-native",
                live_enabled=True,
                live_confirmed=True,
                secret_source=MappingSecretSource({}),
            )


# ---------------------------------------------------------------------------
# 4. successful creation
# ---------------------------------------------------------------------------


def test_create_openai_native_provider():
    """成功创建 openai-native provider（注入 http_factory + secret_source，零网络）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        try:
            result = create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="openai-native",
                live_enabled=True,
                live_confirmed=True,
                secret_source=MappingSecretSource({"OPENAI_API_KEY": "sk-test"}),
                http_factory=_fake_http_factory,
            )
            assert isinstance(result, FactoryResult)
            assert result.provider_name == "openai-native"
            assert result.mode == "live"
            assert result.config.model == "gpt-4.1-mini"
            assert result.transport.is_live_ready is True
        finally:
            pass


def test_create_anthropic_native_provider():
    """成功创建 anthropic-native provider（注入 http_factory + secret_source，零网络）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        try:
            result = create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="anthropic-native",
                live_enabled=True,
                live_confirmed=True,
                secret_source=MappingSecretSource({"ANTHROPIC_API_KEY": "sk-ant-test"}),
                http_factory=_fake_http_factory,
            )
            assert result.provider_name == "anthropic-native"
            assert result.transport.is_live_ready is True
        finally:
            pass


def test_create_compatible_provider():
    """成功创建 openai-compatible provider（注入 http_factory + secret_source，零网络）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        try:
            result = create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="openai-compatible",
                live_enabled=True,
                live_confirmed=True,
                secret_source=MappingSecretSource({"DEEPSEEK_API_KEY": "sk-deepseek-test"}),
                http_factory=_fake_http_factory,
            )
            assert result.provider_name == "openai-compatible"
        finally:
            pass


# ---------------------------------------------------------------------------
# 5. provider not found
# ---------------------------------------------------------------------------


def test_unknown_provider_name():
    """不存在的 provider 名 → KeyError（经 FactoryError 包装）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        with pytest.raises(FactoryError):
            create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="nonexistent",
                live_enabled=True,
                live_confirmed=True,
                secret_source=MappingSecretSource({"OPENAI_API_KEY": "sk-test"}),
            )


# ---------------------------------------------------------------------------
# 6. config file not found
# ---------------------------------------------------------------------------


def test_config_file_not_found():
    """配置文件不存在 → FileNotFoundError。"""
    with pytest.raises(FileNotFoundError):
        create_judge_provider(
            llm_config_path="/nonexistent/providers.yaml",
            llm_provider_name="openai-native",
            live_enabled=True,
            live_confirmed=True,
            secret_source=MappingSecretSource({"OPENAI_API_KEY": "sk-test"}),
        )


# ---------------------------------------------------------------------------
# 6b. zero-network assertion
# ---------------------------------------------------------------------------


def test_factory_live_path_never_creates_real_https_connection(monkeypatch):
    """注入 http_factory 后，真实 HTTPSConnection 绝对不会被创建。"""
    import http.client as _http_client

    call_count = [0]

    def banned_https(*args, **kwargs):
        call_count[0] += 1
        raise AssertionError(
            "测试禁止创建真实 HTTPSConnection——http_factory 未生效或被绕过"
        )

    monkeypatch.setattr(_http_client, "HTTPSConnection", banned_https)

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        try:
            result = create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="openai-native",
                live_enabled=True,
                live_confirmed=True,
                secret_source=MappingSecretSource({"OPENAI_API_KEY": "sk-test"}),
                http_factory=_fake_http_factory,
            )
            # 触发 evaluate → send → 内部的 HTTP 调用
            from agent_tool_harness.core_contract import (
                Evidence,
                ExecutionTrace,
            )
            trace = ExecutionTrace(
                scenario_id="zt", tool_calls=[], tool_results=[], final_answer="zt"
            )
            evidence = Evidence(trace=trace, signal_quality="zt")
            findings = result.provider.evaluate(evidence)
            assert len(findings) >= 1
        finally:
            pass

    assert call_count[0] == 0, (
        f"真实 HTTPSConnection 被创建了 {call_count[0]} 次——"
        " http_factory 路径未正确覆盖"
    )


# ---------------------------------------------------------------------------
# 6c. missing secret_source → FactoryError
# ---------------------------------------------------------------------------


def test_missing_secret_source_rejected():
    """没有 secret_source → FactoryError（新安全闸门）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        with pytest.raises(FactoryError, match="secret source"):
            create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="openai-native",
                live_enabled=True,
                live_confirmed=True,
            )


# ---------------------------------------------------------------------------
# 6d. error messages must not contain key
# ---------------------------------------------------------------------------


def test_factory_error_message_does_not_contain_key():
    """Factory 错误信息不包含 api_key。"""
    src = MappingSecretSource({"OPENAI_API_KEY": "sk-secret-value"})
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML.replace("openai-native", "nonexistent"))
        with pytest.raises(FactoryError) as exc:
            create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="openai-native",
                live_enabled=True,
                live_confirmed=True,
                secret_source=src,
            )
        assert "sk-secret-value" not in str(exc.value)


# ---------------------------------------------------------------------------
# 7. provider returns functioning judge
# ---------------------------------------------------------------------------


def test_created_provider_returns_findings():
    """factory 创建的 provider 通过注入的 fake transport 返回 findings，零网络。"""
    from agent_tool_harness.core_contract import (
        Evidence,
        ExecutionTrace,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        try:
            result = create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="openai-native",
                live_enabled=True,
                live_confirmed=True,
                secret_source=MappingSecretSource({"OPENAI_API_KEY": "sk-test"}),
                http_factory=_fake_http_factory,
            )
            provider = result.provider
            trace = ExecutionTrace(
                scenario_id="test",
                tool_calls=[],
                tool_results=[],
                final_answer="test",
            )
            evidence = Evidence(trace=trace, signal_quality="test")
            findings = provider.evaluate(evidence)
            assert isinstance(findings, list)
            assert len(findings) >= 1
            assert findings[0].provider == "openai-native"
            assert result.transport._http_factory is not None
        finally:
            pass
