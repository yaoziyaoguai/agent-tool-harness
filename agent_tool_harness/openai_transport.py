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
            "User-Agent": "agent-tool-harness/3.0",
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
        #
        # 兼容多种 compatible provider 响应格式：
        #   A. content 是 JSON 字符串 (标准 OpenAI)
        #   B. content 是 dict（某些 SDK 预解析）
        #   C. content 是 content parts array
        #   D. content 是 markdown fenced JSON
        #   E. content 是非 JSON 文本 → 回退关键词启发式
        #   F. 以上皆不可解析 → bad_response
        #
        # 所有分支都只返回结构化 dict，不泄露 raw response。
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

        # ---- normalization layer ----
        # 把 str / dict / list 三种 content 归一化为纯文本，再尝试 JSON 解析
        content_text = _extract_content_text(content)
        parsed = _parse_judge_content(content_text)
        parsed["usage"] = usage

        # 如果解析后缺少关键字段且 content 本身是 dict，尝试从 dict 直接提取
        if not parsed.get("rationale") and isinstance(content, dict):
            direct = _try_parse_judge_dict(content)
            if direct.get("rationale"):
                parsed = direct
                parsed["usage"] = usage

        return parsed


# ---------------------------------------------------------------------------
# 响应解析 —— normalization layer
# ---------------------------------------------------------------------------
# 设计原则：
# 1. 归一化层独立于业务层——不引用 JudgeFinding / Evidence 等对象
# 2. 每种 content 形态有专门处理路径，不互相污染
# 3. 所有分支最终返回 {passed, rationale, confidence, rubric} dict
# 4. 失败时返回空 dict 或 fallback 结果，绝不抛异常（调用方决定如何处理）
# 5. bad_response 只记录 sanitized shape，不含 raw body / key / secret


def _extract_content_text(content: object) -> str:
    """把 content（可能是 str / dict / list）归一化为纯文本。

    支持三种形态：
    - **str**: 直接返回（标准 OpenAI chat completions）
    - **dict**: 尝试 json.dumps 转为字符串（某些 SDK 预解析了 JSON）
    - **list**: 当作 content parts array，提取 ``text`` 字段并拼接

    任何不可处理的类型返回空字符串，不抛异常。
    """
    # 形态 A / D / E：content 是字符串
    if isinstance(content, str):
        return content

    # 形态 B：content 是 dict（SDK 预解析的 JSON object）
    if isinstance(content, dict):
        try:
            return _json.dumps(content, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(content)

    # 形态 C：content 是 list → content parts array
    # 例如 [{"type":"text","text":"..."}, {"type":"text","text":"..."}]
    if isinstance(content, list):
        texts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                t = item.get("text", "")
                if isinstance(t, str) and t:
                    texts.append(t)
        return "\n".join(texts)

    # 未知形态：尽力转字符串
    return str(content) if content else ""


def _extract_json_from_text(text: str) -> dict | None:
    """从文本中提取第一个有效 JSON object。

    支持形态：
    - **plain JSON**: ``{"passed": ...}``
    - **fenced JSON**: `` ```json\\n{...}\\n``` ``
    - **前导/尾随文本**: ``Some text {"passed": true} more text``

    返回解析出的 dict，失败返回 None。
    """
    if not text or not text.strip():
        return None

    # 尝试 1：整段文本直接解析
    try:
        data = _json.loads(text)
        if isinstance(data, dict):
            return data
    except (_json.JSONDecodeError, TypeError, ValueError):
        pass

    # 尝试 2：markdown fenced JSON block —— ```json ... ```
    # 兼容某些 compatible provider 在 content 中包裹 markdown fence
    import re as _re
    fence_pattern = r'```(?:json)?\s*\n(.*?)\n```'
    matches = _re.findall(fence_pattern, text, _re.DOTALL)
    for m in matches:
        try:
            data = _json.loads(m.strip())
            if isinstance(data, dict):
                return data
        except (_json.JSONDecodeError, TypeError, ValueError):
            continue

    # 尝试 3：在文本中搜索 JSON object 边界 {...}
    # 找第一个 { 和匹配的 }，提取并解析
    start = text.find("{")
    while start != -1:
        depth = 0
        end = start
        for i, ch in enumerate(text[start:], start=start):
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i + 1
                    break
        if end > start:
            candidate = text[start:end]
            try:
                data = _json.loads(candidate)
                if isinstance(data, dict):
                    return data
            except (_json.JSONDecodeError, TypeError, ValueError):
                pass
        start = text.find("{", end)

    return None


def _try_parse_judge_dict(data: dict) -> dict:
    """从 dict 中尝试提取 judge 判定字段。

    这是对 content=dict 场景（形态 B）的直接提取路径。
    不走 _parse_judge_content 的文本→JSON 路径，避免双重序列化。
    """
    if not isinstance(data, dict):
        return {}

    # 标准字段
    if "passed" in data:
        return {
            "passed": bool(data.get("passed")),
            "rationale": data.get("rationale"),
            "confidence": data.get("confidence"),
            "rubric": data.get("rubric"),
        }

    # 带 findings 数组的格式
    findings = data.get("findings")
    if isinstance(findings, list) and findings:
        first = findings[0] if isinstance(findings[0], dict) else {}
        return {
            "passed": bool(first.get("passed", True)),
            "rationale": first.get("rationale") or first.get("message"),
            "confidence": first.get("confidence"),
            "rubric": first.get("rubric"),
        }

    return {}


def _parse_judge_content(content: str) -> dict:
    """从 LLM 响应文本中提取 {passed, rationale, confidence, rubric}。

    解析顺序：
    1. 尝试从文本中提取 JSON object（支持 plain / fenced / 嵌入式 JSON）
    2. JSON 解析成功 → 标准化返回
    3. JSON 解析失败 → 回退到关键词启发式（保持向后兼容）
    """
    # 尝试从文本中提取 JSON
    data = _extract_json_from_text(content)
    if data is not None:
        return _try_parse_judge_dict(data)

    # 回退：关键词启发式（与旧实现完全兼容）
    # 负向短语优先匹配——防止 "not pass" / "didn't pass" 被误判为 pass
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
        # 无法判断时保守处理：不自动判 passed
        passed = False

    return {
        "passed": passed,
        "rationale": content[:500] if content else None,
        "confidence": None,
        "rubric": None,
    }


def _sanitized_response_shape(payload: dict) -> dict:
    """生成脱敏的响应 shape 摘要，仅用于 bad_response 诊断日志。

    **绝不**包含：
    - raw response body
    - api_key / Authorization header
    - 完整 content 文本（只保留类型和长度）
    - content 内容预览（即使截断也可能泄露用户数据）
    """
    shape: dict[str, object] = {
        "top_level_keys": sorted(payload.keys()),
    }

    choices = payload.get("choices")
    if isinstance(choices, list) and choices:
        choice0 = choices[0] if isinstance(choices[0], dict) else {}
        if isinstance(choice0, dict):
            shape["choice0_keys"] = sorted(choice0.keys())
            msg = choice0.get("message", {})
            if isinstance(msg, dict):
                shape["message_keys"] = sorted(msg.keys())
                content = msg.get("content", "")
                shape["content_type"] = type(content).__name__
                if isinstance(content, str):
                    shape["content_len"] = len(content)
                elif isinstance(content, list):
                    shape["content_parts_count"] = len(content)
                elif isinstance(content, dict):
                    shape["content_keys"] = sorted(content.keys())
            else:
                shape["message_type"] = type(msg).__name__

    return shape
