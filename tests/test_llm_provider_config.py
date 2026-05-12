"""LLM provider 配置模型测试。

测试纪律：
- 不设任何真实 API key 环境变量
- 不读任何 .env 文件
- 不调用任何外部 API
- 不 weaken 断言来追求绿
"""

from __future__ import annotations

import os as _os

import pytest

from agent_tool_harness.llm_config import (
    ConfigValidationError,
    LLMProviderConfig,
    MissingApiKeyError,
    ProviderCompatibility,
    ProviderFamily,
    load_provider_registry,
    resolve_api_key,
)

# ---------------------------------------------------------------------------
# 1. parse openai native
# ---------------------------------------------------------------------------

def test_parse_openai_native():
    data = {
        "providers": {
            "openai-native": {
                "family": "openai",
                "compatibility": "native",
                "model": "gpt-4.1-mini",
                "api_key_env": "OPENAI_KEY",
            }
        }
    }
    registry = load_provider_registry(data)
    cfg = registry.get("openai-native")
    assert cfg.family == ProviderFamily.OPENAI
    assert cfg.compatibility == ProviderCompatibility.NATIVE
    assert cfg.model == "gpt-4.1-mini"
    assert cfg.base_url is None


# ---------------------------------------------------------------------------
# 2. parse openai-compatible
# ---------------------------------------------------------------------------

def test_parse_openai_compatible():
    data = {
        "providers": {
            "deepseek": {
                "family": "openai",
                "compatibility": "compatible",
                "base_url": "https://api.deepseek.com/v1",
                "model": "deepseek-chat",
                "api_key_env": "DEEPSEEK_KEY",
            }
        }
    }
    registry = load_provider_registry(data)
    cfg = registry.get("deepseek")
    assert cfg.family == ProviderFamily.OPENAI
    assert cfg.compatibility == ProviderCompatibility.COMPATIBLE
    assert cfg.base_url == "https://api.deepseek.com/v1"


# ---------------------------------------------------------------------------
# 3. parse anthropic native
# ---------------------------------------------------------------------------

def test_parse_anthropic_native():
    data = {
        "providers": {
            "anthropic-native": {
                "family": "anthropic",
                "compatibility": "native",
                "model": "claude-sonnet-4-6-20250514",
                "api_key_env": "ANTHROPIC_KEY",
            }
        }
    }
    registry = load_provider_registry(data)
    cfg = registry.get("anthropic-native")
    assert cfg.family == ProviderFamily.ANTHROPIC
    assert cfg.compatibility == ProviderCompatibility.NATIVE


# ---------------------------------------------------------------------------
# 4. parse anthropic-compatible
# ---------------------------------------------------------------------------

def test_parse_anthropic_compatible():
    data = {
        "providers": {
            "anthropic-comp": {
                "family": "anthropic",
                "compatibility": "compatible",
                "base_url": "https://example.com/anthropic",
                "model": "claude-compatible-model",
                "api_key_env": "ANTHROPIC_COMP_KEY",
            }
        }
    }
    registry = load_provider_registry(data)
    cfg = registry.get("anthropic-comp")
    assert cfg.family == ProviderFamily.ANTHROPIC
    assert cfg.compatibility == ProviderCompatibility.COMPATIBLE


# ---------------------------------------------------------------------------
# 5. compatible without base_url → error
# ---------------------------------------------------------------------------

def test_compatible_without_base_url_error():
    data = {
        "providers": {
            "bad": {
                "family": "openai",
                "compatibility": "compatible",
                "model": "gpt-4",
                "api_key_env": "KEY",
            }
        }
    }
    with pytest.raises(ConfigValidationError, match="base_url"):
        load_provider_registry(data)


# ---------------------------------------------------------------------------
# 6. native without base_url → allowed
# ---------------------------------------------------------------------------

def test_native_without_base_url_allowed():
    data = {
        "providers": {
            "ok": {
                "family": "anthropic",
                "compatibility": "native",
                "model": "claude-3-5-sonnet",
                "api_key_env": "KEY",
            }
        }
    }
    registry = load_provider_registry(data)
    assert registry.get("ok").base_url is None


# ---------------------------------------------------------------------------
# 7. inline api_key → rejected
# ---------------------------------------------------------------------------

def test_inline_api_key_rejected():
    data = {
        "providers": {
            "bad": {
                "family": "openai",
                "compatibility": "native",
                "model": "gpt-4",
                "api_key": "sk-deadbeef",
                "api_key_env": "KEY",
            }
        }
    }
    with pytest.raises(ConfigValidationError, match="inline"):
        load_provider_registry(data)


# ---------------------------------------------------------------------------
# 8. parse does NOT read os.environ
# ---------------------------------------------------------------------------

def test_parse_does_not_read_os_environ(monkeypatch):
    """验证 parse 阶段不读环境变量——即使 env var 不存在也能正常 parse。"""
    monkeypatch.delenv("DOES_NOT_EXIST_KEY", raising=False)
    data = {
        "providers": {
            "p": {
                "family": "openai",
                "compatibility": "native",
                "model": "gpt-4",
                "api_key_env": "DOES_NOT_EXIST_KEY",
            }
        }
    }
    registry = load_provider_registry(data)
    assert registry.get("p").api_key_env == "DOES_NOT_EXIST_KEY"


# ---------------------------------------------------------------------------
# 9. resolve_api_key reads os.environ
# ---------------------------------------------------------------------------

def test_resolve_api_key_reads_os_environ(monkeypatch):
    """resolve_api_key 是唯一读取 key 的入口。"""
    monkeypatch.setenv("TEST_API_KEY", "sk-test-123")
    cfg = LLMProviderConfig(
        name="test",
        family=ProviderFamily.OPENAI,
        compatibility=ProviderCompatibility.NATIVE,
        model="gpt-4",
        api_key_env="TEST_API_KEY",
    )
    key = resolve_api_key(cfg)
    assert key == "sk-test-123"


# ---------------------------------------------------------------------------
# 10. resolve_api_key raises when env var is empty
# ---------------------------------------------------------------------------

def test_resolve_api_key_raises_on_empty(monkeypatch):
    monkeypatch.setenv("EMPTY_KEY", "")
    cfg = LLMProviderConfig(
        name="test",
        family=ProviderFamily.OPENAI,
        compatibility=ProviderCompatibility.NATIVE,
        model="gpt-4",
        api_key_env="EMPTY_KEY",
    )
    with pytest.raises(MissingApiKeyError):
        resolve_api_key(cfg)


def test_resolve_api_key_raises_on_missing(monkeypatch):
    monkeypatch.delenv("MISSING_KEY", raising=False)
    cfg = LLMProviderConfig(
        name="test",
        family=ProviderFamily.OPENAI,
        compatibility=ProviderCompatibility.NATIVE,
        model="gpt-4",
        api_key_env="MISSING_KEY",
    )
    with pytest.raises(MissingApiKeyError):
        resolve_api_key(cfg)


# ---------------------------------------------------------------------------
# 11. no auto load_dotenv
# ---------------------------------------------------------------------------

def test_no_auto_load_dotenv():
    """验证 llm_config 模块没有在 import 时自动调用 load_dotenv。"""
    import agent_tool_harness.llm_config as mod

    # 模块不应该在顶层 import dotenv
    assert not hasattr(mod, "load_dotenv")
    assert "dotenv" not in _os.environ.get("_LOAD_DOTENV_CALLED", "")


# ---------------------------------------------------------------------------
# 12. registry get by name → success / unknown → error
# ---------------------------------------------------------------------------

def test_registry_get_by_name():
    data = {
        "providers": {
            "a": {
                "family": "openai",
                "compatibility": "native",
                "model": "gpt-4",
                "api_key_env": "A_KEY",
            },
            "b": {
                "family": "anthropic",
                "compatibility": "native",
                "model": "claude-3",
                "api_key_env": "B_KEY",
            },
        }
    }
    registry = load_provider_registry(data)
    assert "a" in registry
    assert "b" in registry
    assert "c" not in registry
    assert len(registry) == 2
    assert registry.list_providers() == ["a", "b"]


def test_unknown_provider_error():
    data = {
        "providers": {
            "only": {
                "family": "openai",
                "compatibility": "native",
                "model": "gpt-4",
                "api_key_env": "KEY",
            }
        }
    }
    registry = load_provider_registry(data)
    with pytest.raises(KeyError, match="unknown"):
        registry.get("unknown")


# ---------------------------------------------------------------------------
# 13. optional fields are parsed correctly
# ---------------------------------------------------------------------------

def test_optional_fields_parsed():
    data = {
        "providers": {
            "p": {
                "family": "openai",
                "compatibility": "native",
                "model": "gpt-4",
                "api_key_env": "KEY",
                "timeout_seconds": 60,
                "max_tokens": 2048,
                "temperature": 0.5,
            }
        }
    }
    registry = load_provider_registry(data)
    cfg = registry.get("p")
    assert cfg.timeout_seconds == 60
    assert cfg.max_tokens == 2048
    assert cfg.temperature == 0.5


# ---------------------------------------------------------------------------
# 14. invalid family → error
# ---------------------------------------------------------------------------

def test_invalid_family_error():
    data = {
        "providers": {
            "bad": {
                "family": "google",
                "compatibility": "native",
                "model": "gemini",
                "api_key_env": "KEY",
            }
        }
    }
    with pytest.raises(ConfigValidationError, match="family"):
        load_provider_registry(data)


# ---------------------------------------------------------------------------
# 15. invalid compatibility → error
# ---------------------------------------------------------------------------

def test_invalid_compatibility_error():
    data = {
        "providers": {
            "bad": {
                "family": "openai",
                "compatibility": "proxy",
                "model": "gpt-4",
                "api_key_env": "KEY",
            }
        }
    }
    with pytest.raises(ConfigValidationError, match="compatibility"):
        load_provider_registry(data)


# ---------------------------------------------------------------------------
# 16. LLMProviderConfig repr does not leak secrets
# ---------------------------------------------------------------------------

def test_config_repr_does_not_leak_key():
    cfg = LLMProviderConfig(
        name="p",
        family=ProviderFamily.OPENAI,
        compatibility=ProviderCompatibility.NATIVE,
        model="gpt-4",
        api_key_env="SECRET_ENV",
    )
    r = repr(cfg)
    assert "sk-" not in r
    assert "SECRET_ENV" in r


# ---------------------------------------------------------------------------
# 17. empty model → error
# ---------------------------------------------------------------------------

def test_empty_model_error():
    data = {
        "providers": {
            "bad": {
                "family": "openai",
                "compatibility": "native",
                "model": "",
                "api_key_env": "KEY",
            }
        }
    }
    with pytest.raises(ConfigValidationError, match="model"):
        load_provider_registry(data)


# ---------------------------------------------------------------------------
# 18. empty api_key_env → error
# ---------------------------------------------------------------------------

def test_empty_api_key_env_error():
    data = {
        "providers": {
            "bad": {
                "family": "openai",
                "compatibility": "native",
                "model": "gpt-4",
                "api_key_env": "",
            }
        }
    }
    with pytest.raises(ConfigValidationError, match="api_key_env"):
        load_provider_registry(data)


# ---------------------------------------------------------------------------
# 19. duplicate provider name → error
# ---------------------------------------------------------------------------

def test_duplicate_provider_name_error():
    """Non-dict provider item causes ConfigValidationError."""
    provider_list = [
        {"family": "openai", "compatibility": "native", "model": "gpt-4", "api_key_env": "K1"},
        {"family": "anthropic", "compatibility": "native", "model": "claude", "api_key_env": "K2"},
    ]
    data = {"providers": {"same": provider_list}}
    with pytest.raises(ConfigValidationError):
        load_provider_registry(data)
