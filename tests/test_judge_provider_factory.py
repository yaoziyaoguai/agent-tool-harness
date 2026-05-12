"""JudgeProviderFactory 测试。

测试纪律：
- 所有测试零网络依赖
- 不读取 .env / os.environ
- 不调用真实 LLM
- 使用 tempfile 创建 fixture 文件
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from agent_tool_harness.judge_provider_factory import (
    FactoryError,
    FactoryResult,
    create_judge_provider,
)

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
        os.environ["OPENAI_API_KEY"] = "sk-test"
        try:
            with pytest.raises(FactoryError, match="双标志"):
                create_judge_provider(
                    llm_config_path=str(cfg),
                    llm_provider_name="openai-native",
                    live_enabled=False,
                    live_confirmed=False,
                )
        finally:
            os.environ.pop("OPENAI_API_KEY", None)


def test_live_only_without_confirm_rejected():
    """仅 live_enabled → FactoryError。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        os.environ["OPENAI_API_KEY"] = "sk-test"
        try:
            with pytest.raises(FactoryError, match="双标志"):
                create_judge_provider(
                    llm_config_path=str(cfg),
                    llm_provider_name="openai-native",
                    live_enabled=True,
                    live_confirmed=False,
                )
        finally:
            os.environ.pop("OPENAI_API_KEY", None)


# ---------------------------------------------------------------------------
# 2. safety gate: missing config
# ---------------------------------------------------------------------------


def test_missing_llm_config_rejected():
    """缺 --llm-config → FactoryError。"""
    os.environ["OPENAI_API_KEY"] = "sk-test"
    try:
        with pytest.raises(FactoryError, match="llm-config"):
            create_judge_provider(
                llm_config_path="",
                llm_provider_name="openai-native",
                live_enabled=True,
                live_confirmed=True,
            )
    finally:
        os.environ.pop("OPENAI_API_KEY", None)


def test_missing_llm_provider_rejected():
    """缺 --llm-provider → FactoryError。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        os.environ["OPENAI_API_KEY"] = "sk-test"
        try:
            with pytest.raises(FactoryError, match="llm-provider"):
                create_judge_provider(
                    llm_config_path=str(cfg),
                    llm_provider_name="",
                    live_enabled=True,
                    live_confirmed=True,
                )
        finally:
            os.environ.pop("OPENAI_API_KEY", None)


# ---------------------------------------------------------------------------
# 3. safety gate: missing API key
# ---------------------------------------------------------------------------


def test_missing_api_key_rejected():
    """环境变量不存在时 → MissingApiKeyError。"""
    from agent_tool_harness.llm_config import MissingApiKeyError

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        os.environ.pop("OPENAI_API_KEY", None)
        with pytest.raises(MissingApiKeyError):
            create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="openai-native",
                live_enabled=True,
                live_confirmed=True,
            )


# ---------------------------------------------------------------------------
# 4. successful creation
# ---------------------------------------------------------------------------


def test_create_openai_native_provider():
    """成功创建 openai-native provider。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        os.environ["OPENAI_API_KEY"] = "sk-test"
        try:
            result = create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="openai-native",
                live_enabled=True,
                live_confirmed=True,
            )
            assert isinstance(result, FactoryResult)
            assert result.provider_name == "openai-native"
            assert result.mode == "live"
            assert result.config.model == "gpt-4.1-mini"
            assert result.transport.is_live_ready is True
        finally:
            os.environ.pop("OPENAI_API_KEY", None)


def test_create_anthropic_native_provider():
    """成功创建 anthropic-native provider。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        os.environ["ANTHROPIC_API_KEY"] = "sk-ant-test"
        try:
            result = create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="anthropic-native",
                live_enabled=True,
                live_confirmed=True,
            )
            assert result.provider_name == "anthropic-native"
            assert result.transport.is_live_ready is True
        finally:
            os.environ.pop("ANTHROPIC_API_KEY", None)


def test_create_compatible_provider():
    """成功创建 openai-compatible provider（有 base_url）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        os.environ["DEEPSEEK_API_KEY"] = "sk-deepseek-test"
        try:
            result = create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="openai-compatible",
                live_enabled=True,
                live_confirmed=True,
            )
            assert result.provider_name == "openai-compatible"
        finally:
            os.environ.pop("DEEPSEEK_API_KEY", None)


# ---------------------------------------------------------------------------
# 5. provider not found
# ---------------------------------------------------------------------------


def test_unknown_provider_name():
    """不存在的 provider 名 → KeyError（经 FactoryError 包装）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        os.environ["OPENAI_API_KEY"] = "sk-test"
        try:
            with pytest.raises(FactoryError):
                create_judge_provider(
                    llm_config_path=str(cfg),
                    llm_provider_name="nonexistent",
                    live_enabled=True,
                    live_confirmed=True,
                )
        finally:
            os.environ.pop("OPENAI_API_KEY", None)


# ---------------------------------------------------------------------------
# 6. config file not found
# ---------------------------------------------------------------------------


def test_config_file_not_found():
    """配置文件不存在 → FileNotFoundError。"""
    os.environ["OPENAI_API_KEY"] = "sk-test"
    try:
        with pytest.raises(FileNotFoundError):
            create_judge_provider(
                llm_config_path="/nonexistent/providers.yaml",
                llm_provider_name="openai-native",
                live_enabled=True,
                live_confirmed=True,
            )
    finally:
        os.environ.pop("OPENAI_API_KEY", None)


# ---------------------------------------------------------------------------
# 7. provider returns functioning judge
# ---------------------------------------------------------------------------


def test_created_provider_returns_findings():
    """factory 创建的 provider 通过 fake transport 正常工作。"""
    from agent_tool_harness.core_contract import (
        Evidence,
        ExecutionTrace,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = Path(tmpdir) / "providers.yaml"
        cfg.write_text(VALID_PROVIDERS_YAML)
        os.environ["OPENAI_API_KEY"] = "sk-test"
        try:
            result = create_judge_provider(
                llm_config_path=str(cfg),
                llm_provider_name="openai-native",
                live_enabled=True,
                live_confirmed=True,
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
            # transport 未注入 http_factory 时不会真正发网络（但 safety gate 已过）
        finally:
            os.environ.pop("OPENAI_API_KEY", None)
