"""OpenAI transport 测试。

测试纪律：
- 所有测试零网络依赖
- 不读取 .env / os.environ
- 不调用真实 LLM
- 通过 http_factory 注入 fake connection
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_tool_harness.openai_transport import (
    ERROR_AUTH,
    ERROR_BAD_RESPONSE,
    ERROR_DISABLED_LIVE,
    ERROR_MISSING_CONFIG,
    ERROR_NETWORK,
    ERROR_PROVIDER,
    ERROR_RATE_LIMITED,
    ERROR_TIMEOUT,
    OpenAITransport,
    _safe_message,
    _TransportError,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fake_conn_factory(response_dict: dict, status: int = 200):
    """创建一个返回指定响应的 fake connection factory。"""
    def factory(host, port, timeout):
        conn = MagicMock()
        resp = MagicMock()
        resp.status = status
        import json
        resp.read.return_value = json.dumps(response_dict).encode("utf-8")
        conn.getresponse.return_value = resp
        return conn
    return factory


def _make_transport(**kwargs) -> OpenAITransport:
    defaults = dict(
        api_key="test-key",
        model="gpt-4",
        base_url="https://api.openai.com",
        live_enabled=True,
        live_confirmed=True,
    )
    defaults.update(kwargs)
    return OpenAITransport(**defaults)


# ---------------------------------------------------------------------------
# 1. safety gates
# ---------------------------------------------------------------------------


def test_disabled_live_blocks_send():
    """live_enabled=False 时 send 抛 _TransportError(ERROR_DISABLED_LIVE)。"""
    t = _make_transport(live_enabled=False, live_confirmed=False)
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_DISABLED_LIVE


def test_live_confirmed_only_blocks_send():
    """只有 live_confirmed 没有 live_enabled 时 send 抛 disabled_live。"""
    t = _make_transport(live_enabled=False, live_confirmed=True)
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_DISABLED_LIVE


def test_live_enabled_only_blocks_send():
    """只有 live_enabled 没有 live_confirmed 时 send 抛 disabled_live。"""
    t = _make_transport(live_enabled=True, live_confirmed=False)
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_DISABLED_LIVE


def test_missing_api_key_blocked():
    """api_key 为空时 send 抛 missing_config。"""
    t = _make_transport(api_key="")
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_MISSING_CONFIG


def test_missing_model_blocked():
    """model 为空时 send 抛 missing_config。"""
    t = _make_transport(model="")
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_MISSING_CONFIG


# ---------------------------------------------------------------------------
# 2. is_live_ready
# ---------------------------------------------------------------------------


def test_is_live_ready_true():
    """双标志齐备时 is_live_ready 返回 True。"""
    t = _make_transport(live_enabled=True, live_confirmed=True)
    assert t.is_live_ready is True


def test_is_live_ready_false():
    """双标志任一缺失时 is_live_ready 返回 False。"""
    t = _make_transport(live_enabled=True, live_confirmed=False)
    assert t.is_live_ready is False


# ---------------------------------------------------------------------------
# 3. successful response parsing
# ---------------------------------------------------------------------------


def test_successful_send():
    """正常响应的解析。"""
    response = {
        "choices": [
            {
                "message": {
                    "content": '{"passed": true, "rationale": "good", "confidence": 0.9}'
                }
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    result = t.send({"messages": [{"role": "user", "content": "test"}]})
    assert result["passed"] is True
    assert result["rationale"] == "good"
    assert result["confidence"] == 0.9
    assert result["usage"] == {"prompt_tokens": 10, "completion_tokens": 5}


def test_failed_judge_response():
    """passed=False 的响应。"""
    response = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"passed": false, "rationale": "bad tool choice", "confidence": 0.95}'
                    )
                }
            }
        ],
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    result = t.send({"messages": []})
    assert result["passed"] is False
    assert result["rationale"] == "bad tool choice"


def test_response_with_rubric():
    """带 rubric 的响应。"""
    response = {
        "choices": [
            {
                "message": {
                    "content": (
                        '{"passed": true, "rationale": "ok", "rubric": "tool selection rubric v1"}'
                    )
                }
            }
        ],
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    result = t.send({"messages": []})
    assert result["rubric"] == "tool selection rubric v1"


def test_non_json_content_fallback():
    """非 JSON content 回退到关键词启发式。"""
    response = {
        "choices": [
            {"message": {"content": "The agent passed the test successfully."}}
        ],
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    result = t.send({"messages": []})
    assert result["passed"] is True


def test_model_injection():
    """request 中未指定 model 时注入 transport 的 model。"""
    captured_request = {}

    def fake_factory(host, port, timeout):
        conn = MagicMock()
        conn.request = lambda method, path, body, headers: captured_request.update(
            {"body": body}
        )
        resp = MagicMock()
        resp.status = 200
        import json
        resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": '{"passed": true, "rationale": "ok"}'}}]
        }).encode()
        conn.getresponse.return_value = resp
        return conn

    t = _make_transport(http_factory=fake_factory)
    t.send({"messages": []})
    import json
    sent = json.loads(captured_request["body"])
    assert sent["model"] == "gpt-4"


# ---------------------------------------------------------------------------
# 4. HTTP error mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected_error",
    [
        (401, ERROR_AUTH),
        (403, ERROR_AUTH),
        (429, ERROR_RATE_LIMITED),
        (500, ERROR_PROVIDER),
        (502, ERROR_PROVIDER),
        (503, ERROR_PROVIDER),
        (404, ERROR_BAD_RESPONSE),
    ],
)
def test_http_error_mapping(status, expected_error):
    """HTTP 状态码正确映射到 8 类错误。"""
    t = _make_transport(http_factory=_fake_conn_factory({}, status=status))
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == expected_error


# ---------------------------------------------------------------------------
# 5. bad response parsing
# ---------------------------------------------------------------------------


def test_empty_choices_errors():
    """空 choices 列表 → bad_response。"""
    response = {"choices": []}
    t = _make_transport(http_factory=_fake_conn_factory(response))
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_BAD_RESPONSE


def test_non_dict_response_errors():
    """响应非 dict → bad_response。"""
    t = _make_transport(http_factory=_fake_conn_factory([1, 2, 3]))
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_BAD_RESPONSE


def test_missing_passed_field_errors():
    """content 非 JSON 且不含 pass/fail → 回退解析。"""
    response = {
        "choices": [{"message": {"content": "unclear response"}}]
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    result = t.send({"messages": []})
    # "fail" not in "unclear response", "pass" not in "unclear response" → passed=False
    assert result["passed"] is False


# ---------------------------------------------------------------------------
# 6. safe messages
# ---------------------------------------------------------------------------


def test_safe_messages_no_secrets():
    """_safe_message 不包含 key/base_url。"""
    for code in [
        ERROR_AUTH, ERROR_RATE_LIMITED, ERROR_NETWORK,
        ERROR_TIMEOUT, ERROR_BAD_RESPONSE, ERROR_PROVIDER,
        ERROR_MISSING_CONFIG, ERROR_DISABLED_LIVE,
    ]:
        msg = _safe_message(code)
        assert "sk-" not in msg.lower()
        assert "api.openai.com" not in msg


# ---------------------------------------------------------------------------
# 7. retry / backoff
# ---------------------------------------------------------------------------


def test_retry_on_rate_limited():
    """rate_limited 会重试，最终成功返回。"""
    call_count = [0]
    response_ok = {
        "choices": [{"message": {"content": '{"passed": true, "rationale": "ok"}'}}]
    }

    def factory(host, port, timeout):
        conn = MagicMock()
        if call_count[0] < 2:
            resp = MagicMock()
            resp.status = 429
            resp.read.return_value = b"{}"
            conn.getresponse.return_value = resp
        else:
            resp = MagicMock()
            resp.status = 200
            import json
            resp.read.return_value = json.dumps(response_ok).encode()
            conn.getresponse.return_value = resp
        call_count[0] += 1
        return conn

    sleep_log = []
    t = _make_transport(
        http_factory=factory,
        max_attempts=3,
        base_delay_s=0.5,
        sleep_fn=lambda s: sleep_log.append(s),
    )
    result = t.send({"messages": []})
    assert result["passed"] is True
    assert call_count[0] == 3
    assert len(sleep_log) == 2
    assert t.last_attempts_summary[0]["outcome"] == "error"
    assert t.last_attempts_summary[2]["outcome"] == "success"


def test_non_retryable_error_immediate():
    """auth_error 不重试，立即抛出。"""
    t = _make_transport(
        http_factory=_fake_conn_factory({}, status=401),
        max_attempts=3,
    )
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_AUTH
    assert len(t.last_attempts_summary) == 1


# ---------------------------------------------------------------------------
# 8. timeout handling
# ---------------------------------------------------------------------------


def test_timeout_mapped():
    """TimeoutError 映射到 ERROR_TIMEOUT。"""
    def factory(host, port, timeout):
        conn = MagicMock()
        conn.request.side_effect = TimeoutError("timed out")
        return conn

    t = _make_transport(http_factory=factory)
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_TIMEOUT


# ---------------------------------------------------------------------------
# 9. network error handling
# ---------------------------------------------------------------------------


def test_oserror_mapped():
    """OSError 映射到 ERROR_NETWORK。"""
    def factory(host, port, timeout):
        conn = MagicMock()
        conn.request.side_effect = OSError("connection refused")
        return conn

    t = _make_transport(http_factory=factory)
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_NETWORK
