"""LLM Provider 配置模型 —— 多 provider 注册与安全 key 读取。

本模块负责什么
==============
为 OpenAI / Anthropic native/compatible 四类 provider 提供统一的配置模型和
注册表。支持从 YAML-like dict 解析配置、按名称查找 provider、显式安全读取
API key。

本模块**不**负责什么
====================
- 不调用任何外部 API / 网络 / LLM
- 不在 parse 阶段读取 os.environ（只有显式 resolve_api_key() 才读）
- 不自动 load_dotenv()
- 不支持 inline api_key（配置中只能写 api_key_env，不能写 key 值）
- 不实现 transport / judge / prompt 工程

与已有代码的关系
================
- ``judges/provider.py::AnthropicCompatibleConfig`` 是旧路径 Anthropic-only
  配置，保持向后兼容，不受本模块影响
- ``judges/provider.py::LiveAnthropicTransport`` / ``FakeJudgeTransport``
  是 transport 层实现，保持独立
- 本模块为新 Core Flow aligned JudgeProvider 提供配置基础

为什么 parse config ≠ 读取 key
-------------------------------
1. parse 阶段在 CI / 测试中运行，不需要真实 key
2. api_key_env 只是环境变量名，不会出现在 artifact / log 中
3. 真实 key 读取是显式的 resolve_api_key() 调用，可审计、可 mock

为什么不支持 inline api_key
---------------------------
1. inline key 会通过 git / artifact / log / screen share 泄漏
2. api_key_env 让 key 永远只存在于 os.environ 中
3. 跨项目隔离：不同项目用不同的 env var 前缀，不会互相污染

为什么 compatible provider 必须显式 base_url
---------------------------------------------
1. native provider 的 endpoint 是已知的（如 api.openai.com）
2. compatible provider 的目标 endpoint 不可知——必须由用户提供
3. 防止"默认指向某个第三方 endpoint"变成隐式 vendor lock-in
"""

from __future__ import annotations

import os as _os
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ProviderFamily(StrEnum):
    """LLM provider 协议族。

    Native 和 compatible 共享同一个 request/response schema，
    区别仅在于 endpoint 来源。
    """

    OPENAI = "openai"
    ANTHROPIC = "anthropic"


class ProviderCompatibility(StrEnum):
    """provider 兼容性模式。

    ``native``：使用官方默认 endpoint（如 api.openai.com）。
    ``compatible``：使用用户指定的 base_url（如 api.deepseek.com）。
    """

    NATIVE = "native"
    COMPATIBLE = "compatible"


# ---------------------------------------------------------------------------
# 配置值对象
# ---------------------------------------------------------------------------


@dataclass
class LLMProviderConfig:
    """单个 LLM provider 的完整配置。

    架构边界：
    - **负责**：存储 provider 的声明式配置（名称、协议族、模型、环境变量名等）。
    - **不负责**：不存储 API key 本体（只存环境变量名）、不做网络调用、
      不做 prompt 工程。

    parse 阶段只做 schema 校验，不读环境变量——key 在 resolve_api_key()
    显式调用时才读取。
    """

    name: str
    family: ProviderFamily
    compatibility: ProviderCompatibility
    model: str
    api_key_env: str
    base_url: str | None = None
    timeout_seconds: float = 30.0
    max_tokens: int | None = None
    temperature: float | None = None

    def __repr__(self) -> str:
        # 不暴露任何可能包含 secret 的字段
        return (
            f"LLMProviderConfig(name={self.name!r}, family={self.family.value}, "
            f"compatibility={self.compatibility.value}, model={self.model!r}, "
            f"api_key_env={self.api_key_env!r}, base_url_set={bool(self.base_url)})"
        )


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------


class ConfigValidationError(ValueError):
    """provider 配置校验失败。

    携带 provider name 和具体错误原因，便于上层（CLI / loader）展示
    可行动错误信息。
    """

    def __init__(self, provider_name: str, reason: str) -> None:
        super().__init__(f"[{provider_name}] {reason}")
        self.provider_name = provider_name
        self.reason = reason


def _validate_provider_config(cfg: LLMProviderConfig) -> None:
    """对单个 LLMProviderConfig 做硬性校验。

    校验规则：
    - family 只能是 openai / anthropic
    - compatibility 只能是 native / compatible
    - model 必填且非空
    - api_key_env 必填且非空
    - compatible 必须有 base_url
    - 禁止 inline api_key 字段（在外层 from_dict 检查）
    """
    if cfg.family not in ProviderFamily:
        raise ConfigValidationError(
            cfg.name,
            f"family 必须是 openai / anthropic，实际: {cfg.family!r}",
        )
    if cfg.compatibility not in ProviderCompatibility:
        raise ConfigValidationError(
            cfg.name,
            f"compatibility 必须是 native / compatible，实际: {cfg.compatibility!r}",
        )
    if not cfg.model or not cfg.model.strip():
        raise ConfigValidationError(cfg.name, "model 必填且不能为空")
    if not cfg.api_key_env or not cfg.api_key_env.strip():
        raise ConfigValidationError(cfg.name, "api_key_env 必填且不能为空")
    if cfg.compatibility == ProviderCompatibility.COMPATIBLE and not cfg.base_url:
        raise ConfigValidationError(
            cfg.name,
            "compatible provider 必须提供 base_url",
        )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class LLMProviderRegistry:
    """provider 配置注册表——按名称查找、校验、列出所有 provider。

    架构边界：
    - **负责**：存储 LLMProviderConfig 列表，支持按 name 查找和校验。
    - **不负责**：不读取环境变量、不实例化 transport、不做网络调用。
    """

    def __init__(self, providers: list[LLMProviderConfig]) -> None:
        self._providers: dict[str, LLMProviderConfig] = {}
        for cfg in providers:
            if cfg.name in self._providers:
                raise ConfigValidationError(
                    cfg.name,
                    "provider name 重复——每个 provider 必须有唯一的 name",
                )
            _validate_provider_config(cfg)
            self._providers[cfg.name] = cfg

    def get(self, name: str) -> LLMProviderConfig:
        """按名称获取 provider config。

        Raises:
            KeyError: 如果 provider 不存在，附带所有可用名称列表。
        """
        if name not in self._providers:
            available = sorted(self._providers.keys())
            raise KeyError(
                f"未知 provider: {name!r}。可用的 provider: {available}"
            )
        return self._providers[name]

    def list_providers(self) -> list[str]:
        """返回所有已注册 provider 的名称列表。"""
        return sorted(self._providers.keys())

    def __len__(self) -> int:
        return len(self._providers)

    def __contains__(self, name: str) -> bool:
        return name in self._providers


# ---------------------------------------------------------------------------
# 安全 key 读取
# ---------------------------------------------------------------------------


class MissingApiKeyError(KeyError):
    """resolve_api_key 时环境变量不存在或为空。"""

    def __init__(self, env_var: str) -> None:
        super().__init__(
            f"环境变量 {env_var} 不存在或为空。"
            f" 请 export {env_var}=<your-key> 后重试。"
            f" 注意：本项目不会自动读取 .env 文件。"
        )
        self.env_var = env_var


def resolve_api_key(config: LLMProviderConfig) -> str:
    """从 os.environ 读取 API key。

    这是**唯一**读取 key 的入口。parse 阶段不调此函数。
    如果环境变量不存在或为空，抛出 MissingApiKeyError。

    使用方式：
        config = registry.get("openai-native")
        key = resolve_api_key(config)  # 显式读取
    """
    key = _os.environ.get(config.api_key_env, "")
    if not key.strip():
        raise MissingApiKeyError(config.api_key_env)
    return key.strip()


# ---------------------------------------------------------------------------
# 从 dict 构造（YAML / JSON 兼容）
# ---------------------------------------------------------------------------


def _parse_provider_dict(name: str, raw: dict[str, Any]) -> LLMProviderConfig:
    """从单个 provider dict 解析为 LLMProviderConfig。

    必须拒绝 inline api_key 字段：
    - 如果 raw 中出现 "api_key" 键，直接报错
    - 只允许 api_key_env
    """
    if "api_key" in raw:
        raise ConfigValidationError(
            name,
            "禁止 inline api_key 字段——请使用 api_key_env 指定环境变量名。"
            " 真实 key 不应出现在任何配置文件中。",
        )

    family_raw = raw.get("family", "")
    try:
        family = ProviderFamily(family_raw)
    except ValueError:
        raise ConfigValidationError(
            name,
            f"family 必须是 openai / anthropic，实际: {family_raw!r}",
        ) from None

    compat_raw = raw.get("compatibility", "")
    try:
        compatibility = ProviderCompatibility(compat_raw)
    except ValueError:
        raise ConfigValidationError(
            name,
            f"compatibility 必须是 native / compatible，实际: {compat_raw!r}",
        ) from None

    cfg = LLMProviderConfig(
        name=name,
        family=family,
        compatibility=compatibility,
        model=str(raw.get("model", "")),
        api_key_env=str(raw.get("api_key_env", "")),
        base_url=raw.get("base_url"),
        timeout_seconds=float(raw.get("timeout_seconds", 30.0)),
        max_tokens=raw.get("max_tokens"),
        temperature=raw.get("temperature"),
    )
    _validate_provider_config(cfg)
    return cfg


def load_provider_registry(data: dict[str, Any]) -> LLMProviderRegistry:
    """从 dict 加载 provider 配置注册表。

    输入格式（YAML parse 后的 dict）：
        {"providers": {"<name>": {<config>}, ...}}

    校验所有 provider，任意一个失败都抛 ConfigValidationError。
    """
    providers_raw = data.get("providers", {})
    if not isinstance(providers_raw, dict):
        raise ConfigValidationError("(root)", "providers 必须是 dict")
    if not providers_raw:
        raise ConfigValidationError("(root)", "providers 不能为空——至少配置一个 provider")

    configs: list[LLMProviderConfig] = []
    for name, raw in providers_raw.items():
        if not isinstance(raw, dict):
            raise ConfigValidationError(
                str(name), f"provider 配置必须是 dict，实际: {type(raw).__name__}"
            )
        configs.append(_parse_provider_dict(str(name), raw))

    return LLMProviderRegistry(configs)
