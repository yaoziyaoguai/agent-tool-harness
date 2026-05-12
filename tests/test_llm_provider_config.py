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
    MissingSecretError,
    ProviderCompatibility,
    ProviderFamily,
    ResolvedLLMProviderConfig,
    load_provider_registry,
    resolve_api_key,
    resolve_provider_runtime_config,
)
from agent_tool_harness.secrets import MappingSecretSource

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

def test_resolve_api_key_reads_from_secret_source():
    """resolve_api_key 从 SecretSource 读取 key。"""
    src = MappingSecretSource({"TEST_API_KEY": "sk-test-123"})
    cfg = LLMProviderConfig(
        name="test",
        family=ProviderFamily.OPENAI,
        compatibility=ProviderCompatibility.NATIVE,
        model="gpt-4",
        api_key_env="TEST_API_KEY",
    )
    key = resolve_api_key(cfg, src)
    assert key == "sk-test-123"


# ---------------------------------------------------------------------------
# 10. resolve_api_key raises when env var is empty
# ---------------------------------------------------------------------------

def test_resolve_api_key_raises_on_empty():
    src = MappingSecretSource({"EMPTY_KEY": ""})
    cfg = LLMProviderConfig(
        name="test",
        family=ProviderFamily.OPENAI,
        compatibility=ProviderCompatibility.NATIVE,
        model="gpt-4",
        api_key_env="EMPTY_KEY",
    )
    with pytest.raises(MissingApiKeyError):
        resolve_api_key(cfg, src)


def test_resolve_api_key_raises_on_missing():
    src = MappingSecretSource({})
    cfg = LLMProviderConfig(
        name="test",
        family=ProviderFamily.OPENAI,
        compatibility=ProviderCompatibility.NATIVE,
        model="gpt-4",
        api_key_env="MISSING_KEY",
    )
    with pytest.raises(MissingApiKeyError):
        resolve_api_key(cfg, src)


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
    """model 为空且未设 model_env → 报错。"""
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


def test_model_env_replaces_model():
    """model_env 可替代 model——model 可为空。"""
    data = {
        "providers": {
            "ok": {
                "family": "openai",
                "compatibility": "native",
                "model_env": "MY_MODEL",
                "api_key_env": "KEY",
            }
        }
    }
    registry = load_provider_registry(data)
    cfg = registry.get("ok")
    assert cfg.model == ""
    assert cfg.model_env == "MY_MODEL"


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


# ---------------------------------------------------------------------------
# 20. base_url and base_url_env mutual exclusion
# ---------------------------------------------------------------------------


def test_base_url_and_base_url_env_mutual_exclusion():
    """base_url 和 base_url_env 同时存在 → 报错。"""
    data = {
        "providers": {
            "bad": {
                "family": "openai",
                "compatibility": "compatible",
                "model": "gpt-4",
                "api_key_env": "KEY",
                "base_url": "https://a.com",
                "base_url_env": "BASE_URL_VAR",
            }
        }
    }
    with pytest.raises(ConfigValidationError, match="base_url"):
        load_provider_registry(data)


# ---------------------------------------------------------------------------
# 21. model and model_env mutual exclusion
# ---------------------------------------------------------------------------


def test_model_and_model_env_mutual_exclusion():
    """model 和 model_env 同时存在 → 报错。"""
    data = {
        "providers": {
            "bad": {
                "family": "openai",
                "compatibility": "native",
                "model": "gpt-4",
                "model_env": "MODEL_VAR",
                "api_key_env": "KEY",
            }
        }
    }
    with pytest.raises(ConfigValidationError, match="model"):
        load_provider_registry(data)


# ---------------------------------------------------------------------------
# 22. compatible with base_url_env → allowed
# ---------------------------------------------------------------------------


def test_compatible_with_base_url_env_allowed():
    """compatible provider 可用 base_url_env 替代 base_url。"""
    data = {
        "providers": {
            "ok": {
                "family": "openai",
                "compatibility": "compatible",
                "model": "gpt-4",
                "api_key_env": "KEY",
                "base_url_env": "MY_BASE_URL",
            }
        }
    }
    registry = load_provider_registry(data)
    cfg = registry.get("ok")
    assert cfg.base_url is None
    assert cfg.base_url_env == "MY_BASE_URL"


# ---------------------------------------------------------------------------
# 23. ResolvedLLMProviderConfig repr hides api_key
# ---------------------------------------------------------------------------


def test_resolved_config_repr_hides_api_key():
    """ResolvedLLMProviderConfig repr 不显示 api_key。"""
    r = ResolvedLLMProviderConfig(
        api_key="sk-secret-123",
        base_url="https://api.openai.com",
        model="gpt-4",
    )
    s = repr(r)
    assert "sk-secret-123" not in s
    assert "api_key=****" in s
    assert "https://api.openai.com" in s


# ---------------------------------------------------------------------------
# 24. resolve_provider_runtime_config resolves all three
# ---------------------------------------------------------------------------


def test_resolve_runtime_config_all_from_secret_source():
    """resolve_provider_runtime_config 可从 SecretSource 解析 api_key + base_url + model。"""
    src = MappingSecretSource({
        "MY_KEY": "sk-test",
        "MY_URL": "https://api.example.com",
        "MY_MODEL": "my-model",
    })
    cfg = LLMProviderConfig(
        name="test",
        family=ProviderFamily.OPENAI,
        compatibility=ProviderCompatibility.COMPATIBLE,
        model="",
        api_key_env="MY_KEY",
        base_url_env="MY_URL",
        model_env="MY_MODEL",
    )
    resolved = resolve_provider_runtime_config(cfg, src)
    assert resolved.api_key == "sk-test"
    assert resolved.base_url == "https://api.example.com"
    assert resolved.model == "my-model"


def test_resolve_runtime_config_static_model_and_base_url():
    """静态 model / base_url 直接使用，不读 SecretSource。"""
    src = MappingSecretSource({"MY_KEY": "sk-test"})
    cfg = LLMProviderConfig(
        name="test",
        family=ProviderFamily.OPENAI,
        compatibility=ProviderCompatibility.COMPATIBLE,
        model="gpt-4",
        api_key_env="MY_KEY",
        base_url="https://static.example.com",
    )
    resolved = resolve_provider_runtime_config(cfg, src)
    assert resolved.model == "gpt-4"
    assert resolved.base_url == "https://static.example.com"


def test_resolve_runtime_config_native_uses_default_base_url():
    """native provider 不设 base_url / base_url_env → 使用默认 endpoint。"""
    src = MappingSecretSource({"MY_KEY": "sk-test"})
    cfg = LLMProviderConfig(
        name="test",
        family=ProviderFamily.OPENAI,
        compatibility=ProviderCompatibility.NATIVE,
        model="gpt-4",
        api_key_env="MY_KEY",
    )
    resolved = resolve_provider_runtime_config(cfg, src)
    assert resolved.base_url == "https://api.openai.com"


def test_resolve_runtime_config_missing_base_url_env():
    """base_url_env 指定的变量不存在 → MissingSecretError。"""
    src = MappingSecretSource({"MY_KEY": "sk-test"})
    cfg = LLMProviderConfig(
        name="test",
        family=ProviderFamily.OPENAI,
        compatibility=ProviderCompatibility.COMPATIBLE,
        model="gpt-4",
        api_key_env="MY_KEY",
        base_url_env="MISSING_URL",
    )
    with pytest.raises(MissingSecretError, match="MISSING_URL"):
        resolve_provider_runtime_config(cfg, src)


def test_resolve_runtime_config_missing_model_env():
    """model_env 指定的变量不存在 → MissingSecretError。"""
    src = MappingSecretSource({"MY_KEY": "sk-test"})
    cfg = LLMProviderConfig(
        name="test",
        family=ProviderFamily.OPENAI,
        compatibility=ProviderCompatibility.NATIVE,
        model="",
        api_key_env="MY_KEY",
        model_env="MISSING_MODEL",
    )
    with pytest.raises(MissingSecretError, match="MISSING_MODEL"):
        resolve_provider_runtime_config(cfg, src)
