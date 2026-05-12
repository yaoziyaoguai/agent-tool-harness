"""Anthropic-compatible HTTP transport —— 安全门控、零新依赖。

本模块负责什么
==============
为 Anthropic native / compatible provider 提供真实 HTTPS transport 骨架。
严格使用标准库 ``http.client``，不引入第三方依赖。

与 legacy ``judges/provider.py::LiveAnthropicTransport`` 的关系
==============================================================
- legacy transport 消费 ``AnthropicCompatibleConfig``（可持有 api_key 字符串、
  直接读 os.environ）
- 本 transport 消费显式传入的 ``api_key`` / ``model`` / ``base_url``，不读
  os.environ，不持有 config 对象——key 由 factory 通过 ``resolve_api_key()``
  读取后传入

本模块**不**负责什么
====================
- 不引入 ``anthropic`` / ``httpx`` / ``requests`` 等第三方依赖
- 不在测试 / smoke 中真实联网（通过 ``http_factory`` 注入）
- 不构造 prompt / rubric（由 LLMJudgeProvider 负责）

错误分类与 legacy 8 类 taxonomy 完全对齐。
"""

from __future__ import annotations

import json as _json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# 错误分类常量（与 legacy 对齐 + 与 openai_transport 共享同一套常量值）
# ---------------------------------------------------------------------------

ERROR_MISSING_CONFIG = "missing_config"
ERROR_DISABLED_LIVE = "disabled_live_provider"
ERROR_AUTH = "auth_error"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_NETWORK = "network_error"
ERROR_TIMEOUT = "timeout"
ERROR_BAD_RESPONSE = "bad_response"
ERROR_PROVIDER = "provider_error"

DEFAULT_RETRYABLE_CODES = (ERROR_RATE_LIMITED, ERROR_NETWORK, ERROR_TIMEOUT)


# ---------------------------------------------------------------------------
# 内部异常
# ---------------------------------------------------------------------------


class _TransportError(Exception):
    """内部用：携带错误分类 slug 的 transport 异常。"""

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


# ---------------------------------------------------------------------------
# 安全消息模板
# ---------------------------------------------------------------------------


def _safe_message(error_code: str) -> str:
    table = {
        ERROR_MISSING_CONFIG: (
            "Anthropic provider 缺必要配置（api_key 或 model）；见 .env.example。"
        ),
        ERROR_DISABLED_LIVE: (
            "live transport 被显式禁用；需要 --live --confirm-i-have-real-key 双标志。"
        ),
        ERROR_AUTH: "transport 报告认证失败（auth_error，已脱敏）。",
        ERROR_RATE_LIMITED: "transport 报告被限流（rate_limited，已脱敏）。",
        ERROR_NETWORK: "transport 报告网络错误（network_error，已脱敏）。",
        ERROR_TIMEOUT: "transport 报告超时（timeout，已脱敏）。",
        ERROR_BAD_RESPONSE: "transport 返回不可解析的响应（bad_response，已脱敏）。",
        ERROR_PROVIDER: "provider 未分类错误（provider_error，已脱敏）。",
    }
    return table.get(error_code, "provider 错误（未分类，已脱敏）。")


# ---------------------------------------------------------------------------
# Anthropic Transport
# ---------------------------------------------------------------------------


class AnthropicTransport:
    """Anthropic-compatible 真实 HTTPS transport（默认 disabled）。

    使用 Anthropic Messages API 格式。
    native provider 默认 endpoint 为 ``https://api.anthropic.com``；
    compatible provider 必须显式提供 ``base_url``。

    使用方式
    --------
    1. 测试 / smoke：传 ``http_factory`` 注入 fake connection
    2. 真实 live：完整 opt-in（双标志 + api_key + model）
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.anthropic.com",
        live_enabled: bool = False,
        live_confirmed: bool = False,
        http_factory: Callable[..., Any] | None = None,
        timeout_s: float = 30.0,
        max_attempts: int = 1,
        base_delay_s: float = 0.5,
        max_delay_s: float = 8.0,
        retryable_error_codes: tuple[str, ...] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
        anthropic_version: str = "2023-06-01",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._enabled = bool(live_enabled and live_confirmed)
        self._http_factory = http_factory
        self._timeout_s = max(1.0, min(120.0, float(timeout_s)))
        self._max_attempts = max(1, int(max_attempts))
        self._base_delay_s = max(0.0, float(base_delay_s))
        self._max_delay_s = max(self._base_delay_s, float(max_delay_s))
        self._retryable_codes = tuple(
            retryable_error_codes
            if retryable_error_codes is not None
            else DEFAULT_RETRYABLE_CODES
        )
        if sleep_fn is None:
            import time as _time
            sleep_fn = _time.sleep
        self._sleep_fn = sleep_fn
        self._anthropic_version = anthropic_version
        self.last_attempts_summary: list[dict] = []

    @property
    def is_live_ready(self) -> bool:
        return self._enabled

    def send(self, request: dict) -> dict:
        """发送一次 Anthropic Messages API 请求。

        request dict 应包含 messages / system / max_tokens 等字段。
        返回 {passed, rationale, confidence, rubric, usage}。
        """
        attempts: list[dict] = []
        last_exc: _TransportError | None = None
        for attempt_idx in range(1, self._max_attempts + 1):
            try:
                result = self._send_once(request)
                attempts.append({"attempt": attempt_idx, "outcome": "success"})
                self.last_attempts_summary = attempts
                return result
            except _TransportError as exc:
                last_exc = exc
                attempts.append({
                    "attempt": attempt_idx,
                    "outcome": "error",
                    "error_code": exc.error_code,
                })
                if exc.error_code not in self._retryable_codes:
                    self.last_attempts_summary = attempts
                    raise
                if attempt_idx >= self._max_attempts:
                    self.last_attempts_summary = attempts
                    raise
                delay = min(
                    self._max_delay_s,
                    self._base_delay_s * (2 ** (attempt_idx - 1)),
                )
                attempts[-1]["sleep_s"] = delay
                self._sleep_fn(delay)
        self.last_attempts_summary = attempts
        if last_exc is not None:
            raise last_exc
        raise _TransportError(ERROR_PROVIDER)

    def _send_once(self, request: dict) -> dict:
        """发送单次 HTTP 请求；任何分类错误统一抛 _TransportError。"""
        if not self._enabled:
            raise _TransportError(ERROR_DISABLED_LIVE)
        if not self._api_key or not self._model:
            raise _TransportError(ERROR_MISSING_CONFIG)

        # 解析 base_url
        try:
            parts = urlsplit(self._base_url)
            host = parts.hostname
            port = parts.port or (443 if parts.scheme == "https" else 80)
            path = (parts.path or "").rstrip("/") + "/v1/messages"
        except Exception:
            raise _TransportError(ERROR_NETWORK) from None
        if not host:
            raise _TransportError(ERROR_NETWORK)

        # 构造 connection
        try:
            if self._http_factory is not None:
                conn = self._http_factory(host, port, self._timeout_s)
            else:
                from http.client import HTTPSConnection
                conn = HTTPSConnection(host, port, timeout=self._timeout_s)
        except Exception:
            raise _TransportError(ERROR_NETWORK) from None

        # 构造请求体：注入 model（如果 request 未指定）
        body_dict = dict(request)
        if "model" not in body_dict:
            body_dict["model"] = self._model
        if "max_tokens" not in body_dict:
            body_dict["max_tokens"] = 1024
        try:
            body = _json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            raise _TransportError(ERROR_BAD_RESPONSE) from None

        headers = {
            "Content-Type": "application/json",
            "x-api-key": self._api_key,
            "anthropic-version": self._anthropic_version,
            "Accept": "application/json",
        }

        try:
            conn.request("POST", path, body=body, headers=headers)
            resp = conn.getresponse()
            status = int(getattr(resp, "status", 0))
            raw = resp.read()
        except TimeoutError:
            raise _TransportError(ERROR_TIMEOUT) from None
        except OSError as exc:
            if "timed out" in str(exc).lower():
                raise _TransportError(ERROR_TIMEOUT) from None
            raise _TransportError(ERROR_NETWORK) from None
        except Exception:
            raise _TransportError(ERROR_NETWORK) from None
        finally:
            try:
                conn.close()
            except Exception:
                pass

        # HTTP 状态码映射
        if status in (401, 403):
            raise _TransportError(ERROR_AUTH)
        if status == 429:
            raise _TransportError(ERROR_RATE_LIMITED)
        if 500 <= status < 600:
            raise _TransportError(ERROR_PROVIDER)
        if status != 200:
            raise _TransportError(ERROR_BAD_RESPONSE)

        # 200 OK：解析响应
        try:
            payload = _json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, _json.JSONDecodeError):
            raise _TransportError(ERROR_BAD_RESPONSE) from None
        if not isinstance(payload, dict):
            raise _TransportError(ERROR_BAD_RESPONSE)

        # 提取 usage
        usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else None

        # 从 content[0].text 提取 judge 判定
        content_list = payload.get("content", [])
        if not isinstance(content_list, list) or not content_list:
            raise _TransportError(ERROR_BAD_RESPONSE)
        first_block = content_list[0]
        if not isinstance(first_block, dict):
            raise _TransportError(ERROR_BAD_RESPONSE)
        text = first_block.get("text", "")
        if not isinstance(text, str):
            text = ""

        # 解析 text 中的 judge 字段
        parsed = _parse_judge_content(text)
        parsed["usage"] = usage
        return parsed


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------


def _parse_judge_content(content: str) -> dict:
    """从 LLM 响应文本中提取 {passed, rationale, confidence, rubric}。

    尝试 JSON 解析；失败则回退到关键词启发式。
    """
    try:
        data = _json.loads(content)
        if isinstance(data, dict) and "passed" in data:
            return {
                "passed": bool(data.get("passed")),
                "rationale": data.get("rationale"),
                "confidence": data.get("confidence"),
                "rubric": data.get("rubric"),
            }
    except (_json.JSONDecodeError, TypeError, ValueError):
        pass

    content_lower = content.lower()
    negative_patterns = [
        "not pass", "didn't pass", "doesn't pass",
        "did not pass", "does not pass",
        "failed", "failure", "should fail", "not successful",
    ]
    has_negative = any(p in content_lower for p in negative_patterns)

    positive_patterns = ["passed", "success", "succeeded"]
    has_positive = any(p in content_lower for p in positive_patterns)

    if has_negative:
        passed = False
    elif has_positive:
        passed = True
    else:
        passed = False

    return {
        "passed": passed,
        "rationale": content[:500] if content else None,
        "confidence": None,
        "rubric": None,
    }
