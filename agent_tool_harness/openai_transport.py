"""OpenAI-compatible HTTP transport —— 安全门控、零新依赖。

本模块负责什么
==============
为 OpenAI native / compatible provider 提供真实 HTTPS transport 骨架。
严格使用标准库 ``http.client``，不引入第三方依赖。

本模块**不**负责什么
====================
- 不引入 ``requests`` / ``httpx`` / ``openai`` 等第三方依赖
- 不在测试 / smoke 中真实联网（通过 ``http_factory`` 注入 fake connection）
- 不构造 prompt / rubric（由 LLMJudgeProvider 负责）
- 不做 API key 管理（key 由 factory 通过 ``resolve_api_key()`` 读取后传入）

默认安全闸门
============
``live_enabled`` / ``live_confirmed`` 双标志与 CLI ``--live`` /
``--confirm-i-have-real-key`` 一一对应。任一为 False 时 ``send()``
直接抛 ``_TransportError(ERROR_DISABLED_LIVE)``，绝不进入网络分支。

错误分类映射（与 legacy 8 类 taxonomy 对齐）
============================================
- 401 / 403 → ``auth_error``
- 429 → ``rate_limited``
- 5xx → ``provider_error``
- socket.timeout / TimeoutError → ``timeout``
- OSError / ConnectionError → ``network_error``
- 200 但 JSON 解析失败 / 缺关键字段 → ``bad_response``

脱敏硬约束
==========
- 永远不把 api_key / base_url / Authorization header 写入异常 message
- 永远不把 raw response body 落入 artifact
- transport.send 只返回 {passed, rationale, confidence, rubric, usage}
"""

from __future__ import annotations

import json as _json
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

# ---------------------------------------------------------------------------
# 错误分类常量（与 legacy judges/provider.py 对齐）
# ---------------------------------------------------------------------------

ERROR_MISSING_CONFIG = "missing_config"
ERROR_DISABLED_LIVE = "disabled_live_provider"
ERROR_AUTH = "auth_error"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_NETWORK = "network_error"
ERROR_TIMEOUT = "timeout"
ERROR_BAD_RESPONSE = "bad_response"
ERROR_PROVIDER = "provider_error"

# 默认可重试错误：只有瞬时性错误值得重试
DEFAULT_RETRYABLE_CODES = (ERROR_RATE_LIMITED, ERROR_NETWORK, ERROR_TIMEOUT)


# ---------------------------------------------------------------------------
# 内部异常
# ---------------------------------------------------------------------------


class _TransportError(Exception):
    """内部用：携带错误分类 slug 的 transport 异常。

    用户永远不会直接看到此类异常文本——上层 provider 会捕获它、
    读取 error_code、构造脱敏 message。
    """

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


# ---------------------------------------------------------------------------
# 安全消息模板
# ---------------------------------------------------------------------------


def _safe_message(error_code: str) -> str:
    """根据错误分类返回固定安全提示文本（不含任何用户输入）。"""
    table = {
        ERROR_MISSING_CONFIG: (
            "OpenAI provider 缺必要配置（api_key 或 model）；见 .env.example。"
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
# OpenAI Transport
# ---------------------------------------------------------------------------


class OpenAITransport:
    """OpenAI-compatible 真实 HTTPS transport（默认 disabled）。

    使用方式
    --------
    1. 测试 / smoke：传 ``http_factory`` 注入 fake connection，
       ``live_enabled=True``、``live_confirmed=True``
    2. 真实 live：用户完整 opt-in（双标志 + api_key + model）后构造，
       ``http_factory=None`` 回落到 ``http.client.HTTPSConnection``
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str = "https://api.openai.com",
        live_enabled: bool = False,
        live_confirmed: bool = False,
        http_factory: Callable[..., Any] | None = None,
        timeout_s: float = 30.0,
        max_attempts: int = 1,
        base_delay_s: float = 0.5,
        max_delay_s: float = 8.0,
        retryable_error_codes: tuple[str, ...] | None = None,
        sleep_fn: Callable[[float], None] | None = None,
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
        self.last_attempts_summary: list[dict] = []

    @property
    def is_live_ready(self) -> bool:
        """本 transport 当前是否完整 opt-in。"""
        return self._enabled

    def send(self, request: dict) -> dict:
        """发送一次 OpenAI Chat Completions 请求。

        request dict 应包含 messages 等 OpenAI Chat Completions 字段。
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
            path = (parts.path or "").rstrip("/") + "/chat/completions"
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
        try:
            body = _json.dumps(body_dict, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            raise _TransportError(ERROR_BAD_RESPONSE) from None

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
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

        # 从 choices[0].message.content 提取 judge 判定
        choices = payload.get("choices", [])
        if not isinstance(choices, list) or not choices:
            raise _TransportError(ERROR_BAD_RESPONSE)
        choice = choices[0]
        if not isinstance(choice, dict):
            raise _TransportError(ERROR_BAD_RESPONSE)
        message = choice.get("message", {})
        if not isinstance(message, dict):
            raise _TransportError(ERROR_BAD_RESPONSE)
        content = message.get("content", "")
        if not isinstance(content, str):
            content = ""

        # 解析 content 中的 judge 字段
        parsed = _parse_judge_content(content)
        parsed["usage"] = usage
        return parsed


# ---------------------------------------------------------------------------
# 响应解析
# ---------------------------------------------------------------------------


def _parse_judge_content(content: str) -> dict:
    """从 LLM 响应文本中提取 {passed, rationale, confidence, rubric}。

    尝试 JSON 解析；失败则回退到关键词启发式。
    """
    # 尝试 JSON 解析
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

    # 回退：关键词启发式
    content_lower = content.lower()
    passed = "pass" in content_lower and "fail" not in content_lower
    return {
        "passed": passed,
        "rationale": content[:500] if content else None,
        "confidence": None,
        "rubric": None,
    }
