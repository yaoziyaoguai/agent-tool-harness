"""Judge Provider Factory —— 安全门控的真实 LLM judge 构造入口。

本模块负责什么
==============
在严格的安全闸门下创建真实 LLM JudgeProvider：
1. 校验双标志（live_enabled + live_confirmed）
2. 从 LLMProviderRegistry 获取 LLMProviderConfig
3. 通过 resolve_api_key() 显式读取 API key
4. 根据 family/compatibility 选择正确的 transport
5. 构造并返回 LLMJudgeProvider

本模块**不**负责什么
====================
- 不做 HTTP 请求
- 不读 .env 文件 / load_dotenv()
- 不存储 API key（只通过 resolve_api_key 瞬时读取）
- 不静默 fallback——任何条件不满足都报错

安全闸门规则（5 条硬约束）
==========================
1. live_enabled + live_confirmed 缺一 → FactoryError
2. llm_config 未提供 → FactoryError
3. llm_provider 未指定 → FactoryError
4. api_key 环境变量不存在 → MissingApiKeyError（透传）
5. compatible provider 缺 base_url → FactoryError
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class FactoryError(ValueError):
    """factory 安全闸门拒绝创建 provider。

    携带可行动错误信息，不包含任何 secret。
    """

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# ---------------------------------------------------------------------------
# provider family / compatibility 常量（与 llm_config.py 对齐）
# ---------------------------------------------------------------------------

FAMILY_OPENAI = "openai"
FAMILY_ANTHROPIC = "anthropic"
COMPAT_NATIVE = "native"
COMPAT_COMPATIBLE = "compatible"

# native provider 默认 endpoint（硬编码，不来自配置）
NATIVE_BASE_URLS = {
    FAMILY_OPENAI: "https://api.openai.com",
    FAMILY_ANTHROPIC: "https://api.anthropic.com",
}


@dataclass
class FactoryResult:
    """factory 的返回结果。

    provider: LLMJudgeProvider 实例（实现了 CoreJudgeProvider Protocol）
    config: 用来构造此 provider 的 LLMProviderConfig（元数据）
    transport: 底层 transport 实例（用于读取 last_attempts_summary 等）
    """

    provider: Any
    config: Any
    transport: Any
    provider_name: str
    mode: str = "live"


def create_judge_provider(
    *,
    llm_config_path: str,
    llm_provider_name: str,
    live_enabled: bool = False,
    live_confirmed: bool = False,
    http_factory: Any = None,
    timeout_s: float = 30.0,
) -> FactoryResult:
    """创建真实 LLM JudgeProvider（安全门控入口）。

    这是 CLI 和 Python API 创建真实 LLM judge 的**唯一**入口。

    Args:
        llm_config_path: provider 配置文件路径（yaml/json）
        llm_provider_name: 要使用的 provider 名称
        live_enabled: 用户声明意图打开 live（对应 CLI --live）
        live_confirmed: 用户二次确认有真实 key（对应 CLI --confirm-i-have-real-key）
        http_factory: 测试注入用 fake connection factory
        timeout_s: HTTP 超时秒数

    Returns:
        FactoryResult: 包含 provider、config、transport 的聚合结果

    Raises:
        FactoryError: 安全闸门未通过
        FileNotFoundError: 配置文件不存在
        MissingApiKeyError: api_key_env 环境变量不存在或为空
    """
    # 安全闸门 1：双标志必须完整
    if not (live_enabled and live_confirmed):
        raise FactoryError(
            "真实 LLM judge 需要 --live 和 --confirm-i-have-real-key 双标志同时使用。"
            " 缺少任一标志 → 拒绝创建。这不是 bug，是安全闸门。"
        )

    # 安全闸门 2：必须提供配置文件
    if not llm_config_path:
        raise FactoryError(
            "--llm-config 必须提供 provider 配置文件的路径。"
        )

    # 安全闸门 3：必须指定 provider 名称
    if not llm_provider_name:
        raise FactoryError(
            "--llm-provider 必须指定要使用的 provider 名称。"
        )

    # 加载配置
    from agent_tool_harness.llm_config import (
        load_provider_registry_from_file,
        resolve_api_key,
    )

    registry = load_provider_registry_from_file(llm_config_path)

    try:
        llm_config = registry.get(llm_provider_name)
    except KeyError as exc:
        raise FactoryError(str(exc)) from None

    # 安全闸门 4：显式读取 API key
    api_key = resolve_api_key(llm_config)

    # 安全闸门 5：compatible provider 必须有 base_url
    family = llm_config.family.value
    compatibility = llm_config.compatibility.value
    if compatibility == COMPAT_COMPATIBLE and not llm_config.base_url:
        raise FactoryError(
            f"compatible provider '{llm_provider_name}' 必须提供 base_url；"
            " native provider 使用默认 endpoint。"
        )

    # 解析 base_url：native 用硬编码默认值，compatible 用配置值
    if compatibility == COMPAT_NATIVE:
        base_url = NATIVE_BASE_URLS.get(family)
        if base_url is None:
            raise FactoryError(
                f"未知 provider family: {family}（仅支持 openai / anthropic）。"
            )
    else:
        base_url = llm_config.base_url  # type: ignore[assignment]

    # 构造 transport
    transport = _build_transport(
        family=family,
        api_key=api_key,
        model=llm_config.model,
        base_url=base_url,
        live_enabled=live_enabled,
        live_confirmed=live_confirmed,
        http_factory=http_factory,
        timeout_s=timeout_s,
    )

    # 构造 LLMJudgeProvider
    from agent_tool_harness.llm_judge import LLMJudgeProvider

    provider = LLMJudgeProvider(
        transport=transport,
        provider_name=llm_provider_name,
        model=llm_config.model,
        temperature=llm_config.temperature,
        max_tokens=llm_config.max_tokens or 1024,
    )

    return FactoryResult(
        provider=provider,
        config=llm_config,
        transport=transport,
        provider_name=llm_provider_name,
        mode="live",
    )


def _build_transport(
    *,
    family: str,
    api_key: str,
    model: str,
    base_url: str,
    live_enabled: bool,
    live_confirmed: bool,
    http_factory: Any,
    timeout_s: float,
) -> Any:
    """根据 family 选择对应的 transport 实现。"""
    if family == FAMILY_OPENAI:
        from agent_tool_harness.openai_transport import OpenAITransport

        return OpenAITransport(
            api_key=api_key,
            model=model,
            base_url=base_url,
            live_enabled=live_enabled,
            live_confirmed=live_confirmed,
            http_factory=http_factory,
            timeout_s=timeout_s,
        )
    elif family == FAMILY_ANTHROPIC:
        from agent_tool_harness.anthropic_transport import AnthropicTransport

        return AnthropicTransport(
            api_key=api_key,
            model=model,
            base_url=base_url,
            live_enabled=live_enabled,
            live_confirmed=live_confirmed,
            http_factory=http_factory,
            timeout_s=timeout_s,
        )
    else:
        raise FactoryError(
            f"不支持的 provider family: {family}（仅支持 openai / anthropic）。"
        )
