"""Anthropic transport 测试。

测试纪律：
- 所有测试零网络依赖
- 不读取 .env / os.environ
- 不调用真实 LLM
- 通过 http_factory 注入 fake connection
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from agent_tool_harness.anthropic_transport import (
    ERROR_AUTH,
    ERROR_BAD_RESPONSE,
    ERROR_DISABLED_LIVE,
    ERROR_MISSING_CONFIG,
    ERROR_NETWORK,
    ERROR_PROVIDER,
    ERROR_RATE_LIMITED,
    ERROR_TIMEOUT,
    AnthropicTransport,
    _extract_text_from_content_blocks,
    _parse_judge_content,
    _safe_message,
    _TransportError,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _fake_conn_factory(response_dict: dict, status: int = 200):
    def factory(host, port, timeout):
        conn = MagicMock()
        resp = MagicMock()
        resp.status = status
        import json
        resp.read.return_value = json.dumps(response_dict).encode("utf-8")
        conn.getresponse.return_value = resp
        return conn
    return factory


def _make_transport(**kwargs) -> AnthropicTransport:
    defaults = dict(
        api_key="test-key",
        model="claude-sonnet-4-6",
        base_url="https://api.anthropic.com",
        live_enabled=True,
        live_confirmed=True,
    )
    defaults.update(kwargs)
    return AnthropicTransport(**defaults)


# ---------------------------------------------------------------------------
# 1. safety gates
# ---------------------------------------------------------------------------


def test_disabled_live_blocks_send():
    t = _make_transport(live_enabled=False, live_confirmed=False)
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_DISABLED_LIVE


def test_single_flag_blocks_send():
    """任一标志缺失都 block。"""
    t = _make_transport(live_enabled=True, live_confirmed=False)
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_DISABLED_LIVE

    t2 = _make_transport(live_enabled=False, live_confirmed=True)
    with pytest.raises(_TransportError) as exc:
        t2.send({"messages": []})
    assert exc.value.error_code == ERROR_DISABLED_LIVE


# ---------------------------------------------------------------------------
# 2. successful response parsing
# ---------------------------------------------------------------------------


def test_successful_send():
    """Anthropic Messages 格式正常响应。"""
    response = {
        "content": [{
            "type": "text",
            "text": '{"passed": true, "rationale": "correct tool use", "confidence": 0.92}',
        }],
        "usage": {"input_tokens": 50, "output_tokens": 30},
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    result = t.send({"messages": [{"role": "user", "content": "test"}]})
    assert result["passed"] is True
    assert result["rationale"] == "correct tool use"
    assert result["confidence"] == 0.92
    assert result["usage"] == {"input_tokens": 50, "output_tokens": 30}


def test_failed_judge_response():
    response = {
        "content": [{
            "type": "text",
            "text": '{"passed": false, "rationale": "wrong tool", "confidence": 0.88}',
        }],
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    result = t.send({"messages": []})
    assert result["passed"] is False


def test_rubric_in_response():
    response = {
        "content": [{
            "type": "text",
            "text": '{"passed": true, "rationale": "ok", "rubric": "safety rubric"}',
        }],
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    result = t.send({"messages": []})
    assert result["rubric"] == "safety rubric"


def test_model_and_max_tokens_injection():
    """未指定 model/max_tokens 时注入默认值。"""
    captured = {}

    def factory(host, port, timeout):
        conn = MagicMock()
        def _capture_and_return(method, path, body, headers):
            captured["body"] = body
        conn.request = _capture_and_return
        resp = MagicMock()
        resp.status = 200
        import json
        resp.read.return_value = json.dumps({
            "content": [{"type": "text", "text": '{"passed": true, "rationale": "ok"}'}]
        }).encode()
        conn.getresponse.return_value = resp
        return conn

    t = _make_transport(http_factory=factory)
    t.send({"messages": []})
    import json
    sent = json.loads(captured["body"])
    assert sent["model"] == "claude-sonnet-4-6"
    assert sent["max_tokens"] == 1024


# ---------------------------------------------------------------------------
# 3. HTTP error mapping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "status,expected_error",
    [
        (401, ERROR_AUTH),
        (403, ERROR_AUTH),
        (429, ERROR_RATE_LIMITED),
        (500, ERROR_PROVIDER),
        (503, ERROR_PROVIDER),
        (404, ERROR_BAD_RESPONSE),
    ],
)
def test_http_error_mapping(status, expected_error):
    t = _make_transport(http_factory=_fake_conn_factory({}, status=status))
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == expected_error


# ---------------------------------------------------------------------------
# 4. bad response
# ---------------------------------------------------------------------------


def test_empty_content_errors():
    t = _make_transport(http_factory=_fake_conn_factory({"content": []}))
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_BAD_RESPONSE


def test_non_list_content_errors():
    t = _make_transport(http_factory=_fake_conn_factory({"content": "not a list"}))
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_BAD_RESPONSE


# ---------------------------------------------------------------------------
# 5. safe messages
# ---------------------------------------------------------------------------


def test_safe_messages_no_secrets():
    for code in [
        ERROR_AUTH, ERROR_RATE_LIMITED, ERROR_NETWORK,
        ERROR_TIMEOUT, ERROR_BAD_RESPONSE, ERROR_PROVIDER,
        ERROR_MISSING_CONFIG, ERROR_DISABLED_LIVE,
    ]:
        msg = _safe_message(code)
        assert "sk-ant" not in msg.lower()
        assert "api.anthropic.com" not in msg


# ---------------------------------------------------------------------------
# 5b. non-JSON fallback heuristic — negative matching
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "content,expected_passed",
    [
        ("This does not pass the evaluation.", False),
        ("The task did not pass the safety check.", False),
        ("It didn't pass the review.", False),
        ("The agent does not pass on correctness.", False),
        ("Task failed due to wrong tool selection.", False),
        ("The evaluation shows failure in tool usage.", False),
        ("The agent should fail this scenario.", False),
        ("Result: not successful.", False),
        ("The evaluation passed all checks.", True),
        ("The agent succeeded in completing the task.", True),
        ("Tool usage was a success.", True),
        ("ambiguous unclear text with no clear signal", False),
    ],
)
def test_fallback_negative_matching(content, expected_passed):
    """_parse_judge_content fallback 正确识别负向短语。"""
    result = _parse_judge_content(content)
    assert result["passed"] is expected_passed, (
        f"content={content!r} → passed={result['passed']}, expected={expected_passed}"
    )


# ---------------------------------------------------------------------------
# 6. timeout / network
# ---------------------------------------------------------------------------


def test_timeout_retryable():
    """Timeout 默认可重试。"""
    call_count = [0]

    def factory(host, port, timeout):
        if call_count[0] < 1:
            call_count[0] += 1
            raise TimeoutError("timed out")
        call_count[0] += 1
        return _fake_conn_factory({
            "content": [{"type": "text", "text": '{"passed": true, "rationale": "ok"}'}]
        })(host, port, timeout)

    sleep_log = []
    t = _make_transport(
        http_factory=factory,
        max_attempts=2,
        base_delay_s=0.1,
        sleep_fn=lambda s: sleep_log.append(s),
    )
    result = t.send({"messages": []})
    assert result["passed"] is True
    assert len(sleep_log) == 1


def test_non_retryable_auth_error():
    t = _make_transport(
        http_factory=_fake_conn_factory({}, status=401),
        max_attempts=2,
    )
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_AUTH
    assert len(t.last_attempts_summary) == 1


# ---------------------------------------------------------------------------
# 7. content blocks parsing — thinking + text, only thinking, multi-text
# ---------------------------------------------------------------------------


class TestExtractTextFromContentBlocks:
    """_extract_text_from_content_blocks 单元测试。"""

    def test_extracts_text_from_text_block(self):
        """标准 text block 提取。"""
        blocks = [{"type": "text", "text": "hello world"}]
        assert _extract_text_from_content_blocks(blocks) == "hello world"

    def test_skips_thinking_extracts_text(self):
        """跳过 thinking block，提取后面的 text block（kimi-k2.5 典型响应）。"""
        blocks = [
            {"type": "thinking", "thinking": "", "signature": ""},
            {"type": "text", "text": '{"passed": true, "rationale": "ok"}'},
        ]
        assert _extract_text_from_content_blocks(blocks) == '{"passed": true, "rationale": "ok"}'

    def test_only_thinking_returns_none(self):
        """只有 thinking 没有 text → None。"""
        blocks = [
            {"type": "thinking", "thinking": "some reasoning", "signature": ""},
        ]
        assert _extract_text_from_content_blocks(blocks) is None

    def test_multiple_text_blocks_concatenated(self):
        """多个 text block → 拼接。"""
        blocks = [
            {"type": "text", "text": "part1 "},
            {"type": "text", "text": "part2"},
        ]
        assert _extract_text_from_content_blocks(blocks) == "part1 part2"

    def test_empty_text_skipped(self):
        """空 text 跳过，只拼接非空文本。"""
        blocks = [
            {"type": "text", "text": ""},
            {"type": "text", "text": "actual content"},
        ]
        assert _extract_text_from_content_blocks(blocks) == "actual content"

    def test_all_empty_text_returns_none(self):
        """所有 text 块都为空 → None。"""
        blocks = [
            {"type": "text", "text": ""},
            {"type": "text", "text": ""},
        ]
        assert _extract_text_from_content_blocks(blocks) is None

    def test_non_dict_blocks_skipped(self):
        """非 dict block 跳过。"""
        blocks = [
            "not a dict",
            {"type": "text", "text": "found"},
        ]
        assert _extract_text_from_content_blocks(blocks) == "found"


# ---------------------------------------------------------------------------
# 8. integration: thinking + text via transport.send
# ---------------------------------------------------------------------------


def test_send_with_thinking_then_text_block():
    """HTTP 200 返回 thinking + text blocks → 正确提取 text block。"""
    response = {
        "content": [
            {"type": "thinking", "thinking": "", "signature": ""},
            {"type": "text", "text": '{"passed": false, "rationale": "wrong tool choice"}'},
        ],
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    result = t.send({"messages": []})
    assert result["passed"] is False
    assert result["rationale"] == "wrong tool choice"


def test_send_with_only_thinking_errors():
    """只有 thinking 没有 text → bad_response。"""
    response = {
        "content": [
            {"type": "thinking", "thinking": "reasoning...", "signature": ""},
        ],
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    with pytest.raises(_TransportError) as exc:
        t.send({"messages": []})
    assert exc.value.error_code == ERROR_BAD_RESPONSE


# ---------------------------------------------------------------------------
# 9. User-Agent header
# ---------------------------------------------------------------------------


def test_user_agent_header_sent():
    """验证 transport 发送 User-Agent header。"""
    captured = {}

    def factory(host, port, timeout):
        conn = MagicMock()
        def _capture(method, path, body, headers):
            captured["headers"] = headers
        conn.request = _capture
        resp = MagicMock()
        resp.status = 200
        import json
        resp.read.return_value = json.dumps({
            "content": [{"type": "text", "text": '{"passed": true, "rationale": "ok"}'}]
        }).encode()
        conn.getresponse.return_value = resp
        return conn

    t = _make_transport(http_factory=factory)
    t.send({"messages": []})
    assert captured["headers"].get("User-Agent") == "agent-tool-harness/3.0"
