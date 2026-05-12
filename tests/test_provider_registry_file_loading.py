"""load_provider_registry_from_file() 测试。

测试纪律：
- 所有测试零网络依赖
- 不读取 .env / os.environ
- 不调用真实 LLM
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent_tool_harness.llm_config import (
    ConfigValidationError,
    LLMProviderConfig,
    LLMProviderRegistry,
    load_provider_registry_from_file,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _write_yaml(path: Path, data: dict) -> None:
    import yaml as _yaml

    path.write_text(_yaml.dump(data, default_flow_style=False), encoding="utf-8")


def _write_json(path: Path, data: dict) -> None:
    import json as _json

    path.write_text(_json.dumps(data, indent=2), encoding="utf-8")


VALID_PROVIDERS = {
    "providers": {
        "openai-native": {
            "family": "openai",
            "compatibility": "native",
            "model": "gpt-4.1-mini",
            "api_key_env": "OPENAI_API_KEY",
        },
        "anthropic-native": {
            "family": "anthropic",
            "compatibility": "native",
            "model": "claude-sonnet-4-6",
            "api_key_env": "ANTHROPIC_API_KEY",
        },
    }
}


# ---------------------------------------------------------------------------
# 1. basic file loading
# ---------------------------------------------------------------------------


def test_load_from_yaml():
    """从 YAML 文件加载 provider registry。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "providers.yaml"
        _write_yaml(path, VALID_PROVIDERS)
        registry = load_provider_registry_from_file(str(path))
        assert isinstance(registry, LLMProviderRegistry)
        assert len(registry) == 2
        assert "openai-native" in registry
        assert "anthropic-native" in registry


def test_load_from_json():
    """从 JSON 文件加载 provider registry。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "providers.json"
        _write_json(path, VALID_PROVIDERS)
        registry = load_provider_registry_from_file(str(path))
        assert len(registry) == 2


def test_load_from_path_object():
    """支持 pathlib.Path 作为参数。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "providers.yaml"
        _write_yaml(path, VALID_PROVIDERS)
        registry = load_provider_registry_from_file(path)
        assert len(registry) == 2


# ---------------------------------------------------------------------------
# 2. file not found
# ---------------------------------------------------------------------------


def test_file_not_found():
    """文件不存在时抛出 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError, match="provider config file not found"):
        load_provider_registry_from_file("/nonexistent/path/providers.yaml")


# ---------------------------------------------------------------------------
# 3. invalid config
# ---------------------------------------------------------------------------


def test_invalid_yaml_schema():
    """顶层不是 dict 时抛出 ConfigValidationError。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "bad.yaml"
        _write_yaml(path, ["not", "a", "dict"])
        with pytest.raises(ConfigValidationError):
            load_provider_registry_from_file(str(path))


def test_missing_providers_key():
    """缺少 providers 键时抛出 ConfigValidationError。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "bad.yaml"
        _write_yaml(path, {"something_else": {}})
        with pytest.raises(ConfigValidationError):
            load_provider_registry_from_file(str(path))


def test_empty_providers():
    """providers 为空时抛出 ConfigValidationError。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "bad.yaml"
        _write_yaml(path, {"providers": {}})
        with pytest.raises(ConfigValidationError):
            load_provider_registry_from_file(str(path))


# ---------------------------------------------------------------------------
# 4. loaded configs are accessible
# ---------------------------------------------------------------------------


def test_loaded_config_fields():
    """加载后的 config 字段正确可读。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "providers.yaml"
        _write_yaml(path, VALID_PROVIDERS)
        registry = load_provider_registry_from_file(str(path))
        cfg = registry.get("openai-native")
        assert isinstance(cfg, LLMProviderConfig)
        assert cfg.name == "openai-native"
        assert cfg.family.value == "openai"
        assert cfg.compatibility.value == "native"
        assert cfg.model == "gpt-4.1-mini"
        assert cfg.api_key_env == "OPENAI_API_KEY"


def test_list_providers():
    """list_providers 返回排序后的名称列表。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "providers.yaml"
        _write_yaml(path, VALID_PROVIDERS)
        registry = load_provider_registry_from_file(str(path))
        assert registry.list_providers() == ["anthropic-native", "openai-native"]


# ---------------------------------------------------------------------------
# 5. does NOT read env vars
# ---------------------------------------------------------------------------


def test_load_does_not_read_env_vars():
    """load_provider_registry_from_file 不读取环境变量。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "providers.yaml"
        _write_yaml(path, VALID_PROVIDERS)
        # 设置一个 fake 环境变量确认 load 不受影响
        import os

        old_val = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "should-not-be-read"
        try:
            registry = load_provider_registry_from_file(str(path))
            assert len(registry) == 2
        finally:
            if old_val is not None:
                os.environ["OPENAI_API_KEY"] = old_val
            else:
                os.environ.pop("OPENAI_API_KEY", None)


# ---------------------------------------------------------------------------
# 6. inline api_key rejection
# ---------------------------------------------------------------------------


def test_reject_inline_api_key():
    """包含 inline api_key 的配置被拒绝。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "bad.yaml"
        _write_yaml(
            path,
            {
                "providers": {
                    "bad-provider": {
                        "family": "openai",
                        "compatibility": "native",
                        "model": "gpt-4",
                        "api_key_env": "OAI_KEY",
                        "api_key": "sk-do-not-do-this",
                    }
                }
            },
        )
        with pytest.raises(ConfigValidationError, match="inline api_key"):
            load_provider_registry_from_file(str(path))


def test_reject_missing_model():
    """缺少 model 字段被拒绝。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "bad.yaml"
        _write_yaml(
            path,
            {
                "providers": {
                    "no-model": {
                        "family": "openai",
                        "compatibility": "native",
                        "api_key_env": "OAI_KEY",
                    }
                }
            },
        )
        with pytest.raises(ConfigValidationError, match="model"):
            load_provider_registry_from_file(str(path))
