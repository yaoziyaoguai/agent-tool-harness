"""LiveAnthropicTransport 契约测试（v1.4 第一项）。

中文学习型说明
==============
本文件钉死的边界（任何回归都会立即失败）：

1. **默认完全 disabled**：``LiveAnthropicTransport(config)`` 无 opt-in 时
   ``send()`` 必抛 ``_FakeTransportError(ERROR_DISABLED_LIVE)``——**不**
   触碰任何 socket / http.client；
2. **单 ``--live`` 不够**：``live_enabled=True, live_confirmed=False`` 仍
   归 ``disabled_live_provider``；
3. **完整 opt-in 但缺 config**：``live_enabled=True, live_confirmed=True``
   且 base_url / api_key / model 任一缺失 → ``ERROR_MISSING_CONFIG``，
   绝不进入 connection 构造；
4. **fake connection 200 OK** → 返回 4 字段 dict；不夹带 raw response；
5. **HTTP 401/429/5xx/timeout/network/坏 JSON** → 一一映射到 8 类
   ``error_code``；
6. **任何异常路径**下，base_url / api_key / 完整 URL / Authorization
   header 都**不**出现在 ``_FakeTransportError`` 的 message 或 ``__cause__``
   里——拿一个故意写错的 fake key/url 反复触发各类错误，扫描异常文
   本不含 fake key 字面值；
7. **AnthropicCompatibleJudgeProvider + LiveAnthropicTransport** 端到端：
   provider 应能把 transport 抛出的 ``_FakeTransportError`` 转成
   ``ProviderJudgeResult.extra.error_code`` + 脱敏 message，**不**泄漏 key；
8. **multi-advisory composition**：把 LiveAnthropicTransport-backed provider
   放进 ``CompositeJudgeProvider`` 的 advisory 列表，聚合契约（
   vote_distribution.error 计数）仍然成立。

mock/fixture 边界
================
全部用 in-process fake connection；本测试**绝不**联网、**绝不**调真实
``http.client.HTTPSConnection``。``http_factory`` 注入 fake 让 LiveAnthropicTransport
的 HTTP 路径在 CI 中可重放、可断言。``FAKE_KEY`` / ``FAKE_BASE_URL`` 是显
眼可识别的字符串，便于 grep 验证"任何路径下都不会泄漏"。
"""

from __future__ import annotations

import socket

import pytest

from agent_tool_harness.judges.provider import (
    ERROR_AUTH,
    ERROR_BAD_RESPONSE,
    ERROR_DISABLED_LIVE,
    ERROR_MISSING_CONFIG,
    ERROR_NETWORK,
    ERROR_PROVIDER,
    ERROR_RATE_LIMITED,
    ERROR_TIMEOUT,
    AnthropicCompatibleConfig,
    AnthropicCompatibleJudgeProvider,
    LiveAnthropicTransport,
    RuleJudgeProvider,
    _FakeTransportError,
)

FAKE_KEY = "sk-fake-live-transport-DO-NOT-USE-IN-PROD"
FAKE_BASE_URL = "https://fake-anthropic-compat.live.example.invalid/v1/messages"
FAKE_MODEL = "fake-live-model"


def _full_config() -> AnthropicCompatibleConfig:
    return AnthropicCompatibleConfig(
        provider="anthropic_compatible",
        base_url=FAKE_BASE_URL,
        api_key=FAKE_KEY,
        model=FAKE_MODEL,
    )


# ---------------------------------------------------------------------------
# Fake HTTP connection — 模拟 http.client.HTTPSConnection 接口
# ---------------------------------------------------------------------------


class _FakeResp:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body


class _FakeConn:
    """注入到 LiveAnthropicTransport.http_factory 的 fake connection。

    模拟边界：仅响应 ``request()`` / ``getresponse()`` / ``close()``——
    不打开任何 socket，不读取真实环境变量；用 ``raise_on_request`` 模
    拟"已经建联但请求阶段炸"的边界。
    """

    def __init__(self, status: int = 200, body: bytes = b'{"passed": true}',
                 raise_on_request: Exception | None = None) -> None:
        self._status = status
        self._body = body
        self._raise = raise_on_request
        self.closed = False

    def request(self, method, path, body=None, headers=None):  # noqa: D401
        if self._raise is not None:
            raise self._raise

    def getresponse(self):
        return _FakeResp(self._status, self._body)

    def close(self):
        self.closed = True


def _factory_returning(conn: _FakeConn):
    def _factory(host, port, timeout):
        return conn
    return _factory


# ---------------------------------------------------------------------------
# Test cases
# ---------------------------------------------------------------------------


def test_live_transport_default_disabled_no_socket(monkeypatch):
    """默认无 opt-in → DISABLED_LIVE；socket banned 也不会被触发。"""

    class _Banned:
        def __init__(self, *a, **kw):
            raise RuntimeError("socket banned in default-disabled test")

    monkeypatch.setattr(socket, "socket", _Banned)
    t = LiveAnthropicTransport(_full_config())
    assert t.is_live_ready is False
    with pytest.raises(_FakeTransportError) as ei:
        t.send({"eval_id": "x"})
    assert ei.value.error_code == ERROR_DISABLED_LIVE


def test_live_transport_single_flag_still_disabled():
    """只传 live_enabled 不传 live_confirmed → 仍 DISABLED_LIVE。"""

    t = LiveAnthropicTransport(
        _full_config(), live_enabled=True, live_confirmed=False
    )
    assert t.is_live_ready is False
    with pytest.raises(_FakeTransportError) as ei:
        t.send({"eval_id": "x"})
    assert ei.value.error_code == ERROR_DISABLED_LIVE


def test_live_transport_full_optin_missing_config_returns_missing_config():
    """完整 opt-in 但 config 缺 → MISSING_CONFIG，不构造 connection。"""

    cfg = AnthropicCompatibleConfig(
        provider="anthropic_compatible",
        base_url=None,  # 缺
        api_key=FAKE_KEY,
        model=FAKE_MODEL,
    )
    # http_factory 故意会爆——确认 transport 在 missing_config 阶段就退出，
    # 不会调到 factory。
    def _bomb_factory(host, port, timeout):
        raise RuntimeError("factory must not be reached when config missing")

    t = LiveAnthropicTransport(
        cfg, live_enabled=True, live_confirmed=True,
        http_factory=_bomb_factory,
    )
    assert t.is_live_ready is True  # opt-in OK，但 config 仍不全
    with pytest.raises(_FakeTransportError) as ei:
        t.send({"eval_id": "x"})
    assert ei.value.error_code == ERROR_MISSING_CONFIG


def test_live_transport_fake_200_returns_four_fields():
    """200 OK + 合法 JSON → 返回 4 字段 dict（passed/rationale/confidence/rubric）。"""

    conn = _FakeConn(
        status=200,
        body=(
            b'{"passed": true, "rationale": "ok",'
            b' "confidence": 0.9, "rubric": "rule-x", "extra_garbage": "..."}'
        ),
    )
    t = LiveAnthropicTransport(
        _full_config(), live_enabled=True, live_confirmed=True,
        http_factory=_factory_returning(conn),
    )
    out = t.send({"eval_id": "x"})
    assert out == {
        "passed": True,
        "rationale": "ok",
        "confidence": 0.9,
        "rubric": "rule-x",
    }
    assert conn.closed is True


@pytest.mark.parametrize(
    "status,expected_code",
    [
        (401, ERROR_AUTH),
        (403, ERROR_AUTH),
        (429, ERROR_RATE_LIMITED),
        (500, ERROR_PROVIDER),
        (503, ERROR_PROVIDER),
        (302, ERROR_BAD_RESPONSE),  # 非 2xx 也非已分类 → bad_response
    ],
)
def test_live_transport_status_to_error_code(status, expected_code):
    conn = _FakeConn(status=status, body=b"{}")
    t = LiveAnthropicTransport(
        _full_config(), live_enabled=True, live_confirmed=True,
        http_factory=_factory_returning(conn),
    )
    with pytest.raises(_FakeTransportError) as ei:
        t.send({"eval_id": "x"})
    assert ei.value.error_code == expected_code


def test_live_transport_timeout_maps_to_timeout_error_code():
    conn = _FakeConn(raise_on_request=TimeoutError("synthetic"))
    t = LiveAnthropicTransport(
        _full_config(), live_enabled=True, live_confirmed=True,
        http_factory=_factory_returning(conn),
    )
    with pytest.raises(_FakeTransportError) as ei:
        t.send({"eval_id": "x"})
    assert ei.value.error_code == ERROR_TIMEOUT


def test_live_transport_oserror_maps_to_network_error_code():
    conn = _FakeConn(raise_on_request=OSError("synthetic socket failure"))
    t = LiveAnthropicTransport(
        _full_config(), live_enabled=True, live_confirmed=True,
        http_factory=_factory_returning(conn),
    )
    with pytest.raises(_FakeTransportError) as ei:
        t.send({"eval_id": "x"})
    assert ei.value.error_code == ERROR_NETWORK


def test_live_transport_invalid_json_maps_to_bad_response():
    conn = _FakeConn(status=200, body=b"<not json>")
    t = LiveAnthropicTransport(
        _full_config(), live_enabled=True, live_confirmed=True,
        http_factory=_factory_returning(conn),
    )
    with pytest.raises(_FakeTransportError) as ei:
        t.send({"eval_id": "x"})
    assert ei.value.error_code == ERROR_BAD_RESPONSE


def test_live_transport_missing_passed_field_maps_to_bad_response():
    conn = _FakeConn(status=200, body=b'{"rationale": "no passed key"}')
    t = LiveAnthropicTransport(
        _full_config(), live_enabled=True, live_confirmed=True,
        http_factory=_factory_returning(conn),
    )
    with pytest.raises(_FakeTransportError) as ei:
        t.send({"eval_id": "x"})
    assert ei.value.error_code == ERROR_BAD_RESPONSE


def test_live_transport_invalid_base_url_maps_to_network_without_leak():
    """base_url 解析失败时只暴露 error_code，不泄漏原始 URL。"""

    cfg = AnthropicCompatibleConfig(
        provider="anthropic_compatible",
        base_url="not-a-url-with-no-host",
        api_key=FAKE_KEY,
        model=FAKE_MODEL,
    )
    t = LiveAnthropicTransport(
        cfg, live_enabled=True, live_confirmed=True,
        http_factory=lambda h, p, to: _FakeConn(),  # 不应被调用
    )
    with pytest.raises(_FakeTransportError) as ei:
        t.send({"eval_id": "x"})
    assert ei.value.error_code == ERROR_NETWORK
    # 异常 message 必须只是 error_code slug，不能含原始 url 字面值。
    assert FAKE_KEY not in str(ei.value)
    assert "not-a-url-with-no-host" not in str(ei.value)


def test_live_transport_does_not_leak_secret_in_any_error_path():
    """对所有错误路径反复扫一遍：异常 str 中绝不含 FAKE_KEY / FAKE_BASE_URL。"""

    scenarios = [
        _FakeConn(status=200, body=b'{"passed": true}'),  # 正常路径不抛
        _FakeConn(status=401, body=b"{}"),
        _FakeConn(status=429, body=b"{}"),
        _FakeConn(status=500, body=b"{}"),
        _FakeConn(status=200, body=b"<bad json>"),
        _FakeConn(raise_on_request=TimeoutError()),
        _FakeConn(raise_on_request=OSError("oops")),
    ]
    for conn in scenarios:
        t = LiveAnthropicTransport(
            _full_config(), live_enabled=True, live_confirmed=True,
            http_factory=_factory_returning(conn),
        )
        try:
            t.send({"eval_id": "x"})
        except _FakeTransportError as e:
            blob = repr(e) + " " + str(e) + " " + str(e.__cause__)
            assert FAKE_KEY not in blob
            assert FAKE_BASE_URL not in blob
            # __cause__ 已被 raise from None 截断；不应包含原异常 repr
            assert "oops" not in blob
            assert "synthetic" not in blob


def test_provider_with_live_transport_disabled_writes_safe_artifact_extra():
    """端到端：provider + disabled live transport → extra.error_code = disabled_live_provider。"""

    from agent_tool_harness.config.eval_spec import EvalSpec  # noqa: I001

    cfg = _full_config()
    transport = LiveAnthropicTransport(cfg)  # 默认 disabled
    provider = AnthropicCompatibleJudgeProvider(config=cfg, transport=transport)
    case = EvalSpec(
        id="x", name="x", category="x", split="x",
        realism_level="x", complexity="x", source="x",
        user_prompt="", initial_context={}, verifiable_outcome={},
        success_criteria=[], expected_tool_behavior={}, judge={},
    )
    from agent_tool_harness.agents.agent_adapter_base import AgentRunResult

    run = AgentRunResult(
        eval_id="x", final_answer="", tool_calls=[], tool_responses=[],
    )
    result = provider.judge(case, run)
    assert result.extra["error_code"] == ERROR_DISABLED_LIVE
    # 脱敏 message 不含 FAKE_KEY / FAKE_BASE_URL
    msg = result.extra.get("error_message", "")
    assert FAKE_KEY not in msg
    assert FAKE_BASE_URL not in msg


def test_multi_advisory_composition_with_live_transport_disabled():
    """multi-advisory list 里包含 disabled live transport-backed provider →
    vote_distribution.error += 1，绝不计入 pass/fail 投票。
    """

    from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
    from agent_tool_harness.config.eval_spec import EvalSpec
    from agent_tool_harness.judges.provider import (
        CompositeJudgeProvider as _CMP,
    )

    # 复用上面 multi-advisory test 的 stub deterministic / advisory；
    # 这里两个 stub 都接受 case/run 但忽略，简化构造。
    class _FixedDet:
        name = "rule_judge"
        mode = "deterministic"
        def judge(self, case, run):
            from agent_tool_harness.judges.provider import ProviderJudgeResult
            from agent_tool_harness.judges.rule_judge import JudgeResult
            return ProviderJudgeResult(
                inner=JudgeResult(eval_id="x", passed=True, checks=[]),
                provider=self.name, mode=self.mode,
            )

    class _FixedAdv:
        def __init__(self, passed): self._p = passed
        name = "stub"
        mode = "stub"
        def judge(self, case, run):
            from agent_tool_harness.judges.provider import ProviderJudgeResult
            from agent_tool_harness.judges.rule_judge import JudgeResult
            return ProviderJudgeResult(
                inner=JudgeResult(eval_id="x", passed=self._p, checks=[]),
                provider=self.name, mode=self.mode,
            )

    cfg = _full_config()
    live_provider = AnthropicCompatibleJudgeProvider(
        config=cfg,
        transport=LiveAnthropicTransport(cfg),  # disabled
    )
    case = EvalSpec(
        id="x", name="x", category="x", split="x",
        realism_level="x", complexity="x", source="x",
        user_prompt="", initial_context={}, verifiable_outcome={},
        success_criteria=[], expected_tool_behavior={}, judge={},
    )
    run = AgentRunResult(eval_id="x", final_answer="", tool_calls=[], tool_responses=[])
    composite = _CMP(
        deterministic=_FixedDet(),
        advisory=[_FixedAdv(True), _FixedAdv(True), live_provider],
    )
    result = composite.judge(case, run)
    vd = result.extra["vote_distribution"]
    assert vd["pass"] == 2
    assert vd["fail"] == 0
    assert vd["error"] == 1  # live disabled provider 走 error 桶
    assert vd["total"] == 3
    assert result.extra["majority_passed"] is True


def test_rule_judge_default_path_unchanged_by_v14():
    """v1.4 不应触动 RuleJudgeProvider 默认路径——构造、调 judge 仍正常。"""

    from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
    from agent_tool_harness.config.eval_spec import EvalSpec

    rj = RuleJudgeProvider()
    case = EvalSpec(
        id="x", name="x", category="x", split="x",
        realism_level="x", complexity="x", source="x",
        user_prompt="", initial_context={}, verifiable_outcome={},
        success_criteria=[], expected_tool_behavior={}, judge={},
    )
    run = AgentRunResult(eval_id="x", final_answer="", tool_calls=[], tool_responses=[])
    result = rj.judge(case, run)
    # Rule 默认不强制 must_call_any_of 时 PASS；这里只钉返回了 ProviderJudgeResult。
    assert result.provider == "rule"
    assert isinstance(result.passed, bool)
