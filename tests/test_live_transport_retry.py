"""LiveAnthropicTransport retry/backoff 治理契约测试（v1.6 第一项）。

中文学习型说明
==============
本文件钉死的边界（任何回归都会立即失败）：

1. **默认 max_attempts=1 → 行为与 v1.5 字节兼容**：retryable error 也只
   尝试一次，``last_attempts_summary`` 长度恰好为 1；
2. **可重试 error 在 max_attempts 内用尽 → 仍然抛同分类异常**，但
   ``last_attempts_summary`` 记录每次 attempt 的 error_code 与 sleep_s；
3. **可重试 error 中途成功 → 返回正常 dict**，``attempts_summary`` 包含
   失败 + 成功序列；
4. **不可重试 error（auth_error / bad_response / missing_config /
   disabled_live_provider / provider_error）永不重试**——即使 max_attempts
   设很大也只调一次 fake connection；这是治理硬约束：避免 401 反复打、
   避免 5xx 推高账单；
5. **退避序列 deterministic**：base=0.5, max=8.0, attempts=5 → sleep 序列
   为 [0.5, 1.0, 2.0, 4.0]（最后一次失败不再 sleep）；通过注入
   ``sleep_fn`` 记录序列断言；
6. **任何路径都不真实 ``time.sleep``**：本文件全程注入 fake clock；
7. **AnthropicCompatibleJudgeProvider 透传 attempts_summary 到
   ``ProviderJudgeResult.extra``**：reviewer 在 ``judge_results.json`` 直接
   能看到 retry 决策，不需要去翻日志；
8. **secret 不泄漏**：异常 / attempts_summary 任何字段都不出现 fake key /
   fake base_url 字面值。

mock/fixture 边界
================
- 用 ``_RetryFakeConn`` 序列化"先失败 N 次后成功"的脚本，模拟真实
  rate_limited / network_error / timeout 边界；
- ``_collected_sleeps`` 列表注入 ``sleep_fn``，本测试**绝不**真实 sleep；
- 仍然全程 ban socket（用 monkeypatch 在 conftest 之外的局部断言）。

不在本测试覆盖的范围
====================
- jitter（v1.6 不引入随机性，测试就能 deterministic）；
- 跨 process / 跨 run 限流（属 v1.7+ backlog）；
- 真实 HTTPS 重试（CI 永远不连真实网）。
"""

from __future__ import annotations

import pytest

from agent_tool_harness.judges.provider import (
    ERROR_AUTH,
    ERROR_NETWORK,
    ERROR_RATE_LIMITED,
    AnthropicCompatibleConfig,
    AnthropicCompatibleJudgeProvider,
    LiveAnthropicTransport,
    _FakeTransportError,
)


class _Case:
    def __init__(self, eval_id: str) -> None:
        self.id = eval_id


class _Run:
    tool_calls: list = []
    tool_responses: list = []
    transcript: list = []


FAKE_KEY = "sk-fake-retry-DO-NOT-USE"
FAKE_BASE_URL = "https://fake-retry.example.invalid/v1/messages"
FAKE_MODEL = "fake-retry-model"


def _config() -> AnthropicCompatibleConfig:
    return AnthropicCompatibleConfig(
        provider="anthropic_compatible",
        base_url=FAKE_BASE_URL,
        api_key=FAKE_KEY,
        model=FAKE_MODEL,
    )


class _Resp:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body


class _RetryFakeConn:
    """脚本化 fake connection：按 ``script`` 顺序返回 status/body 或抛异常。

    ``script`` 元素：
    - ``("status", code, body_bytes)``：返回这一次响应；
    - ``("raise", Exception_instance)``：在 ``request()`` 阶段抛异常。

    LiveAnthropicTransport 每次重试都会重新调 ``http_factory``，所以这里
    的 ``_step_holder`` 用 list 共享在多个 conn 实例间，模拟"每次重新建
    连接但远端按脚本演进"。
    """

    def __init__(self, script_holder, step_holder) -> None:
        self._script = script_holder
        self._step = step_holder

    def request(self, method, path, body=None, headers=None):
        idx = self._step[0]
        self._step[0] = idx + 1
        if idx >= len(self._script):
            raise _FakeTransportError(ERROR_NETWORK)
        kind = self._script[idx][0]
        if kind == "raise":
            raise self._script[idx][1]
        # status path: defer to getresponse
        self._pending = self._script[idx]

    def getresponse(self):
        kind, status, body = self._pending
        return _Resp(status, body)

    def close(self):
        pass


def _factory_for(script):
    step = [0]

    def _factory(host, port, timeout):
        return _RetryFakeConn(script, step)

    return _factory, step


# ---------------------------------------------------------------------------


def test_default_max_attempts_is_one_no_retry():
    """v1.6 默认行为兼容 v1.5：rate_limited 不会重试。"""
    factory, step = _factory_for([("status", 429, b"")])
    sleeps: list[float] = []
    t = LiveAnthropicTransport(
        _config(), live_enabled=True, live_confirmed=True,
        http_factory=factory, sleep_fn=sleeps.append,
    )
    with pytest.raises(_FakeTransportError) as ei:
        t.send({"eval_id": "x"})
    assert ei.value.error_code == ERROR_RATE_LIMITED
    assert sleeps == []
    assert len(t.last_attempts_summary) == 1
    assert t.last_attempts_summary[0]["error_code"] == ERROR_RATE_LIMITED


def test_retry_then_success_records_attempts():
    """rate_limited 2 次后 200 成功 → 返回 dict + attempts 含 3 条。"""
    factory, step = _factory_for([
        ("status", 429, b""),
        ("status", 429, b""),
        ("status", 200, b'{"passed": true, "rationale": "ok"}'),
    ])
    sleeps: list[float] = []
    t = LiveAnthropicTransport(
        _config(), live_enabled=True, live_confirmed=True,
        http_factory=factory, max_attempts=3, base_delay_s=0.1, max_delay_s=2.0,
        sleep_fn=sleeps.append,
    )
    out = t.send({"eval_id": "x"})
    assert out["passed"] is True
    # deterministic backoff: 0.1, 0.2 (后两次失败 + 第三次成功)
    assert sleeps == [pytest.approx(0.1), pytest.approx(0.2)]
    assert [a["outcome"] for a in t.last_attempts_summary] == ["error", "error", "success"]


def test_non_retryable_auth_error_never_retries():
    """auth_error 即使 max_attempts=5 也只调一次 — 治理硬约束。"""
    factory, step = _factory_for([
        ("status", 401, b""),
        ("status", 200, b'{"passed": true}'),
    ])
    sleeps: list[float] = []
    t = LiveAnthropicTransport(
        _config(), live_enabled=True, live_confirmed=True,
        http_factory=factory, max_attempts=5, base_delay_s=0.1,
        sleep_fn=sleeps.append,
    )
    with pytest.raises(_FakeTransportError) as ei:
        t.send({"eval_id": "x"})
    assert ei.value.error_code == ERROR_AUTH
    assert sleeps == []  # 永不重试 → 永不 sleep
    assert step[0] == 1  # fake connection 只被请求 1 次
    assert len(t.last_attempts_summary) == 1


def test_exhausted_retries_records_full_history_and_raises():
    """rate_limited 3/3 全失败 → 抛 + attempts_summary 长度 3。"""
    factory, _ = _factory_for([
        ("status", 429, b""), ("status", 429, b""), ("status", 429, b""),
    ])
    sleeps: list[float] = []
    t = LiveAnthropicTransport(
        _config(), live_enabled=True, live_confirmed=True,
        http_factory=factory, max_attempts=3, base_delay_s=0.5, max_delay_s=2.0,
        sleep_fn=sleeps.append,
    )
    with pytest.raises(_FakeTransportError) as ei:
        t.send({"eval_id": "x"})
    assert ei.value.error_code == ERROR_RATE_LIMITED
    # 用尽后**不**再 sleep；只 sleep 2 次
    assert sleeps == [pytest.approx(0.5), pytest.approx(1.0)]
    assert len(t.last_attempts_summary) == 3
    assert all(a["error_code"] == ERROR_RATE_LIMITED for a in t.last_attempts_summary)


def test_max_delay_caps_backoff():
    """退避被 max_delay 上限钉死：base=1.0, max=2.0, attempts=4 → [1.0, 2.0, 2.0]。"""
    factory, _ = _factory_for([
        ("status", 429, b""), ("status", 429, b""),
        ("status", 429, b""), ("status", 429, b""),
    ])
    sleeps: list[float] = []
    t = LiveAnthropicTransport(
        _config(), live_enabled=True, live_confirmed=True,
        http_factory=factory, max_attempts=4, base_delay_s=1.0, max_delay_s=2.0,
        sleep_fn=sleeps.append,
    )
    with pytest.raises(_FakeTransportError):
        t.send({"eval_id": "x"})
    assert sleeps == [pytest.approx(1.0), pytest.approx(2.0), pytest.approx(2.0)]


def test_provider_passes_attempts_summary_to_extra():
    """AnthropicCompatibleJudgeProvider 把 attempts_summary 写到 extra。"""
    factory, _ = _factory_for([("status", 429, b""), ("status", 429, b"")])
    t = LiveAnthropicTransport(
        _config(), live_enabled=True, live_confirmed=True,
        http_factory=factory, max_attempts=2, base_delay_s=0.0,
        sleep_fn=lambda _x: None,
    )
    p = AnthropicCompatibleJudgeProvider(_config(), transport=t)
    res = p.judge(_Case("e1"), _Run())
    assert res.extra["error_code"] == ERROR_RATE_LIMITED
    assert "attempts_summary" in res.extra
    assert res.extra["retry_count"] == 1
    assert len(res.extra["attempts_summary"]) == 2


def test_no_secret_in_attempts_summary():
    """attempts_summary / error message 不能包含 fake key 或 fake URL 字面。"""
    factory, _ = _factory_for([("status", 429, b""), ("status", 429, b"")])
    t = LiveAnthropicTransport(
        _config(), live_enabled=True, live_confirmed=True,
        http_factory=factory, max_attempts=2, base_delay_s=0.0,
        sleep_fn=lambda _x: None,
    )
    with pytest.raises(_FakeTransportError):
        t.send({"eval_id": "x"})
    import json
    blob = json.dumps(t.last_attempts_summary)
    assert FAKE_KEY not in blob
    assert "fake-retry.example.invalid" not in blob
