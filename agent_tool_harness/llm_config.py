"""LLM Provider 配置模型 —— 多 provider 注册与安全 key 读取。

本模块负责什么
==============
为 OpenAI / Anthropic native/compatible 四类 provider 提供统一的配置模型和
注册表。支持从 YAML-like dict 解析配置、按名称查找 provider、显式安全读取
API key / base_url / model。

本模块**不**负责什么
====================
- 不调用任何外部 API / 网络 / LLM
- 不在 parse 阶段读取 SecretSource（只有 resolve 函数显式调用时才读）
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
2. api_key_env / base_url_env / model_env 只是名称引用，不会出现在 artifact 中
3. 真实值读取是显式的 resolve_provider_runtime_config() 调用，可审计、可 mock

为什么不支持 inline api_key
---------------------------
1. inline key 会通过 git / artifact / log / screen share 泄漏
2. api_key_env 让 key 永远只存在于 env file / SecretSource 中
3. 跨项目隔离：不同项目用不同的 env var 前缀，不会互相污染

为什么支持 base_url_env / model_env
------------------------------------
1. 第三方转接 API 的 key / base_url / model 都应从 env file 读取
2. 不在 YAML 中写死真实 URL 或 model 名
3. 兼容已有静态 base_url / model 写法，新增 env 引用方式
"""

from __future__ import annotations

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

    parse 阶段只做 schema 校验，不读 SecretSource——key / url / model
    在 resolve_provider_runtime_config() 显式调用时才读取。

    字段规则：
    - api_key_env: 必填，指向 SecretSource 中的 key 名
    - model / model_env: 互斥，至少一个存在
    - base_url / base_url_env: 互斥；compatible 必须有一个
    """

    name: str
    family: ProviderFamily
    compatibility: ProviderCompatibility
    model: str
    api_key_env: str
    base_url: str | None = None
    base_url_env: str | None = None
    model_env: str | None = None
    timeout_seconds: float = 30.0
    max_tokens: int | None = None
    temperature: float | None = None

    def __repr__(self) -> str:
        # 不暴露任何可能包含 secret 的字段
        return (
            f"LLMProviderConfig(name={self.name!r}, family={self.family.value}, "
            f"compatibility={self.compatibility.value}, model={self.model!r}, "
            f"api_key_env={self.api_key_env!r}, base_url_set={bool(self.base_url)}, "
            f"base_url_env_set={bool(self.base_url_env)}, model_env_set={bool(self.model_env)})"
        )


# ---------------------------------------------------------------------------
# 运行时已解析配置（含真实 secret，repr 脱敏）
# ---------------------------------------------------------------------------


@dataclass
class ResolvedLLMProviderConfig:
    """resolve 后的运行时配置，持有真实 api_key / base_url / model。

    repr / str 不能显示 api_key——这是硬约束。
    不能写入 report / artifact。
    错误信息不能包含 api_key。
    """

    api_key: str
    base_url: str
    model: str

    def __repr__(self) -> str:
        return (
            f"ResolvedLLMProviderConfig(base_url={self.base_url!r}, "
            f"model={self.model!r}, api_key=****)"
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
    - model 和 model_env 互斥，至少一个存在
    - api_key_env 必填且非空
    - base_url 和 base_url_env 互斥
    - compatible 必须有 base_url 或 base_url_env
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
    # model / model_env 互斥
    has_model = bool(cfg.model and cfg.model.strip())
    has_model_env = bool(cfg.model_env and cfg.model_env.strip())
    if has_model and has_model_env:
        raise ConfigValidationError(cfg.name, "model 和 model_env 不能同时存在")
    if not has_model and not has_model_env:
        raise ConfigValidationError(cfg.name, "model 或 model_env 必填其一")
    if not cfg.api_key_env or not cfg.api_key_env.strip():
        raise ConfigValidationError(cfg.name, "api_key_env 必填且不能为空")
    # base_url / base_url_env 互斥
    has_base_url = bool(cfg.base_url)
    has_base_url_env = bool(cfg.base_url_env and cfg.base_url_env.strip())
    if has_base_url and has_base_url_env:
        raise ConfigValidationError(cfg.name, "base_url 和 base_url_env 不能同时存在")
    if cfg.compatibility == ProviderCompatibility.COMPATIBLE:
        if not has_base_url and not has_base_url_env:
            raise ConfigValidationError(
                cfg.name,
                "compatible provider 必须提供 base_url 或 base_url_env",
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
    """resolve 时环境变量不存在或为空。"""

    def __init__(self, env_var: str) -> None:
        super().__init__(
            f"secret 变量 {env_var} 不存在或为空。"
            f" 请确认 --env-file 或 --allow-os-env 中已设置该变量。"
        )
        self.env_var = env_var


class MissingSecretError(KeyError):
    """resolve 时 base_url_env / model_env 对应的变量不存在或为空。"""

    def __init__(self, env_var: str, field: str) -> None:
        super().__init__(
            f"secret 变量 {env_var}（用于 {field}）不存在或为空。"
            f" 请确认 --env-file 或 --allow-os-env 中已设置该变量。"
        )
        self.env_var = env_var
        self.field = field


# native provider 默认 endpoint（硬编码，不来自配置）
NATIVE_BASE_URLS = {
    ProviderFamily.OPENAI: "https://api.openai.com",
    ProviderFamily.ANTHROPIC: "https://api.anthropic.com",
}


def resolve_api_key(config: LLMProviderConfig, secret_source: Any) -> str:
    """从 SecretSource 读取 API key。

    这是**唯一**读取 key 的入口。parse 阶段不调此函数。
    如果环境变量不存在或为空，抛出 MissingApiKeyError。

    使用方式：
        config = registry.get("openai-native")
        key = resolve_api_key(config, secret_source)  # 显式读取
    """
    key = _resolve_secret(secret_source, config.api_key_env)
    if not key or not key.strip():
        raise MissingApiKeyError(config.api_key_env)
    return key.strip()


def resolve_provider_runtime_config(
    config: LLMProviderConfig,
    secret_source: Any,
) -> ResolvedLLMProviderConfig:
    """从 SecretSource 解析完整运行时配置（api_key + base_url + model）。

    这是**唯一**读取所有 secret 的入口。parse 阶段不调此函数。
    所有 gating 通过后，在真实 live 调用前调用。

    解析规则：
    - api_key: 从 api_key_env 读取（必填）
    - base_url: 优先 base_url_env → static base_url → native 默认值
    - model: 优先 model_env → static model
    """
    # resolve api_key
    api_key = _resolve_secret(secret_source, config.api_key_env)
    if not api_key or not api_key.strip():
        raise MissingApiKeyError(config.api_key_env)
    api_key = api_key.strip()

    # resolve base_url
    if config.base_url_env:
        base_url = _resolve_secret(secret_source, config.base_url_env)
        if not base_url or not base_url.strip():
            raise MissingSecretError(config.base_url_env, "base_url")
        base_url = base_url.strip()
    elif config.base_url:
        base_url = config.base_url
    else:
        # native provider 使用硬编码默认 endpoint
        base_url = NATIVE_BASE_URLS.get(config.family)
        if base_url is None:
            raise ConfigValidationError(
                config.name,
                f"无法确定 base_url：family={config.family.value} 无默认 endpoint",
            )

    # resolve model
    if config.model_env:
        model = _resolve_secret(secret_source, config.model_env)
        if not model or not model.strip():
            raise MissingSecretError(config.model_env, "model")
        model = model.strip()
    else:
        model = config.model.strip()

    return ResolvedLLMProviderConfig(
        api_key=api_key,
        base_url=base_url,
        model=model,
    )


def _resolve_secret(secret_source: Any, name: str) -> str | None:
    """从 SecretSource 读取单个值。兼容有 / 无 get 方法的对象。"""
    if secret_source is None:
        return None
    get_fn = getattr(secret_source, "get", None)
    if callable(get_fn):
        return get_fn(name)
    return None


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

    model_raw = raw.get("model")
    model = str(model_raw) if model_raw else ""

    cfg = LLMProviderConfig(
        name=name,
        family=family,
        compatibility=compatibility,
        model=model,
        api_key_env=str(raw.get("api_key_env", "")),
        base_url=raw.get("base_url"),
        base_url_env=raw.get("base_url_env"),
        model_env=raw.get("model_env"),
        timeout_seconds=float(raw.get("timeout_seconds", 30.0)),
        max_tokens=raw.get("max_tokens"),
        temperature=raw.get("temperature"),
    )
    _validate_provider_config(cfg)
    return cfg


def load_provider_registry_from_file(path: str) -> LLMProviderRegistry:
    """从 YAML/JSON 文件加载 provider 配置注册表。

    这是 CLI ``--llm-config`` / ``--dry-run-provider`` 的文件加载入口。
    不读取环境变量，不调用外部 API。

    Args:
        path: provider 配置文件的路径（.yaml / .yml / .json）

    Returns:
        校验通过后的 LLMProviderRegistry

    Raises:
        FileNotFoundError: 文件不存在
        ConfigValidationError: 配置校验失败
    """
    import json as _json
    from pathlib import Path as _Path

    import yaml as _yaml

    _path = _Path(path) if not isinstance(path, _Path) else path
    if not _path.exists():
        raise FileNotFoundError(f"provider config file not found: {_path}")
    text = _path.read_text(encoding="utf-8")
    if _path.suffix in {".yaml", ".yml"}:
        data = _yaml.safe_load(text)
    else:
        data = _json.loads(text)
    if not isinstance(data, dict):
        raise ConfigValidationError("(root)", "provider config 顶层必须是 dict")
    return load_provider_registry(data)


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
