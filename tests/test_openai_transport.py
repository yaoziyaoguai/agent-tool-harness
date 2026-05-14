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
    _extract_content_text,
    _extract_json_from_text,
    _parse_judge_content,
    _safe_message,
    _sanitized_response_shape,
    _TransportError,
    _try_parse_judge_dict,
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


# ===================================================================
# 10. normalization layer — _extract_content_text
# ===================================================================


def test_extract_content_text_str():
    """形态 A：content 是 str，直接返回。"""
    assert _extract_content_text('{"passed": true}') == '{"passed": true}'
    assert _extract_content_text("plain text") == "plain text"
    assert _extract_content_text("") == ""


def test_extract_content_text_dict():
    """形态 B：content 是 dict，转为 JSON 字符串。"""
    data = {"passed": True, "rationale": "good"}
    result = _extract_content_text(data)
    assert isinstance(result, str)
    assert '"passed"' in result
    assert '"rationale"' in result


def test_extract_content_text_list():
    """形态 C：content 是 content parts array，提取 text 字段拼接。"""
    parts = [
        {"type": "text", "text": '{"passed": true,'},
        {"type": "text", "text": '"rationale": "ok"}'},
    ]
    result = _extract_content_text(parts)
    assert "passed" in result
    assert "rationale" in result


def test_extract_content_text_list_filters_non_text():
    """content parts 中非 text 类型被跳过。"""
    parts = [
        {"type": "image_url", "image_url": {"url": "..."}},
        {"type": "text", "text": '{"passed": true}'},
    ]
    assert "passed" in _extract_content_text(parts)


def test_extract_content_text_none():
    """None / 空值返回空字符串，不抛异常。"""
    assert _extract_content_text(None) == ""
    assert _extract_content_text(42) == "42"


# ===================================================================
# 11. normalization layer — _extract_json_from_text
# ===================================================================


def test_extract_json_plain():
    """标准 JSON string 解析。"""
    result = _extract_json_from_text('{"passed": true, "rationale": "ok"}')
    assert result == {"passed": True, "rationale": "ok"}


def test_extract_json_fenced():
    """fenced JSON block 解析。"""
    text = """Here is my assessment:
```json
{"passed": false, "rationale": "bad tool choice"}
```
That's all."""
    result = _extract_json_from_text(text)
    assert result == {"passed": False, "rationale": "bad tool choice"}


def test_extract_json_fenced_no_lang():
    """fenced block 不带 json 标识。"""
    text = '```\n{"passed": true, "rationale": "ok"}\n```'
    result = _extract_json_from_text(text)
    assert result == {"passed": True, "rationale": "ok"}


def test_extract_json_embedded():
    """JSON 嵌在前导/尾随文本中。"""
    text = 'Some text {"passed": true, "rationale": "embedded"} more text'
    result = _extract_json_from_text(text)
    assert result == {"passed": True, "rationale": "embedded"}


def test_extract_json_no_json():
    """纯文本无 JSON → None。"""
    assert _extract_json_from_text("This is just plain text.") is None


def test_extract_json_empty():
    """空字符串 → None。"""
    assert _extract_json_from_text("") is None
    assert _extract_json_from_text("   ") is None


def test_extract_json_invalid_json():
    """无效 JSON 文本 → None。"""
    assert _extract_json_from_text("{not valid json}") is None


# ===================================================================
# 12. normalization layer — _try_parse_judge_dict
# ===================================================================


def test_try_parse_judge_dict_standard():
    """标准 passed/rationale/confidence 字段。"""
    result = _try_parse_judge_dict({
        "passed": True, "rationale": "ok", "confidence": 0.9
    })
    assert result["passed"] is True
    assert result["rationale"] == "ok"
    assert result["confidence"] == 0.9


def test_try_parse_judge_dict_findings_array():
    """findings 数组格式。"""
    result = _try_parse_judge_dict({
        "findings": [{"passed": False, "rationale": "bad", "confidence": 0.95}]
    })
    assert result["passed"] is False
    assert result["rationale"] == "bad"


def test_try_parse_judge_dict_empty():
    """空 dict → 空 dict。"""
    assert _try_parse_judge_dict({}) == {}


def test_try_parse_judge_dict_no_judge_fields():
    """无关 dict → 空 dict。"""
    assert _try_parse_judge_dict({"other": "data"}) == {}


# ===================================================================
# 13. _send_once with compatible provider shapes
# ===================================================================


def test_send_content_dict_shape():
    """形态 B：content 是 dict → 成功解析。"""
    response = {
        "choices": [{
            "message": {
                "content": {"passed": True, "rationale": "dict content ok", "confidence": 0.88}
            }
        }]
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    result = t.send({"messages": []})
    assert result["passed"] is True
    assert result["rationale"] == "dict content ok"


def test_send_content_parts_array_shape():
    """形态 C：content 是 content parts array → 成功解析。"""
    response = {
        "choices": [{
            "message": {
                "content": [
                    {"type": "text", "text": '{"passed": false,'},
                    {"type": "text", "text": '"rationale": "parts array"}'},
                ]
            }
        }]
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    result = t.send({"messages": []})
    assert result["passed"] is False
    assert result["rationale"] == "parts array"


def test_send_content_fenced_json_shape():
    """形态 D：content 包含 fenced JSON → 成功解析。"""
    response = {
        "choices": [{
            "message": {
                "content": (
                    'Sure, here is the assessment:\n'
                    '```json\n'
                    '{"passed": true, "rationale": "fenced works"}\n'
                    '```\n'
                    'Done.'
                )
            }
        }]
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    result = t.send({"messages": []})
    assert result["passed"] is True
    assert result["rationale"] == "fenced works"


def test_send_content_non_json_fallback():
    """形态 E：content 非 JSON 文本 → 回退关键词启发式，不抛 bad_response。"""
    response = {
        "choices": [{
            "message": {"content": "The agent passed all checks successfully."}
        }]
    }
    t = _make_transport(http_factory=_fake_conn_factory(response))
    result = t.send({"messages": []})
    # 回退启发式识别到 "passed" → True
    assert result["passed"] is True
    assert result["rationale"] is not None


# ===================================================================
# 14. _sanitized_response_shape — 脱敏诊断
# ===================================================================


def test_sanitized_shape_no_secrets():
    """_sanitized_response_shape 不泄露 content 全文，只返回类型和长度。"""
    shape = _sanitized_response_shape({
        "choices": [{
            "message": {
                "content": "a" * 5000
            }
        }],
        "usage": {"prompt_tokens": 10}
    })
    assert shape["content_type"] == "str"
    assert shape["content_len"] == 5000
    assert len(shape["content_preview"]) <= 200
    # 不包含完整 content
    assert "a" * 5000 not in str(shape)


def test_sanitized_shape_dict_content():
    """dict content → 返回 keys，不返回 values。"""
    shape = _sanitized_response_shape({
        "choices": [{
            "message": {
                "content": {"passed": True, "rationale": "secret info"}
            }
        }]
    })
    assert shape["content_type"] == "dict"
    assert "content_keys" in shape
    # 不包含 content 的 values
    assert "secret info" not in str(shape)


def test_sanitized_shape_empty():
    """空响应不 crash。"""
    shape = _sanitized_response_shape({})
    assert shape["top_level_keys"] == []


# ---------------------------------------------------------------------------
# 15. User-Agent header
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
            "choices": [{"message": {"content": '{"passed":true,"rationale":"ok"}'}}]
        }).encode()
        conn.getresponse.return_value = resp
        return conn

    t = _make_transport(http_factory=factory)
    t.send({"messages": []})
    assert captured["headers"].get("User-Agent") == "agent-tool-harness/3.0"
