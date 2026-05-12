"""LLMJudgeProvider 测试。

测试纪律：
- 所有测试零网络依赖
- 不读取 .env / os.environ
- 不调用真实 LLM
- 使用 fake transport 注入
"""

from __future__ import annotations

from agent_tool_harness.core_contract import (
    Evidence,
    ExecutionTrace,
    JudgeFinding,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.llm_judge import LLMJudgeProvider

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


class _FakeTransport:
    """注入式 fake transport，不调任何外部 API。"""

    def __init__(self, response=None, raise_error=None):
        self._response = response or {"passed": True, "rationale": "fake ok"}
        self._raise_error = raise_error
        self.last_attempts_summary = []
        self.is_live_ready = True

    def send(self, request):
        if self._raise_error:
            raise self._raise_error
        return dict(self._response)


def _make_evidence(scenario_id="test-1", final_answer="42", tool_calls=None):
    if tool_calls is None:
        tool_calls = [
            ToolCall(
                tool_name="search",
                arguments={"query": "test"},
                call_id="c1",
                timestamp="2026-01-01T00:00:00Z",
            )
        ]
    tool_results = [
        ToolResult(
            call_id="c1",
            tool_name="search",
            status="success",
            output={"results": ["a", "b"]},
        )
    ]
    trace = ExecutionTrace(
        scenario_id=scenario_id,
        tool_calls=tool_calls,
        tool_results=tool_results,
        final_answer=final_answer,
    )
    return Evidence(trace=trace, signal_quality="tautological_replay")


# ---------------------------------------------------------------------------
# 1. basic evaluation
# ---------------------------------------------------------------------------


def test_llm_judge_provider_evaluate_passed():
    """LLMJudgeProvider 通过 fake transport 返回 passed finding。"""
    transport = _FakeTransport(
        response={"passed": True, "rationale": "correct tool usage", "confidence": 0.95}
    )
    provider = LLMJudgeProvider(
        transport=transport,
        provider_name="openai-native",
        model="gpt-4.1-mini",
    )
    evidence = _make_evidence()
    findings = provider.evaluate(evidence)
    assert len(findings) == 1
    f = findings[0]
    assert isinstance(f, JudgeFinding)
    assert f.category == "judge"
    assert f.provider == "openai-native"
    assert f.model == "gpt-4.1-mini"
    assert "correct tool usage" in f.rationale


def test_llm_judge_provider_evaluate_failed():
    """LLMJudgeProvider 返回 failed finding。"""
    transport = _FakeTransport(
        response={"passed": False, "rationale": "wrong tool selected", "confidence": 0.9}
    )
    provider = LLMJudgeProvider(
        transport=transport,
        provider_name="anthropic-native",
        model="claude-sonnet-4-6",
    )
    findings = provider.evaluate(_make_evidence())
    assert len(findings) == 1
    f = findings[0]
    assert f.provider == "anthropic-native"
    assert f.model == "claude-sonnet-4-6"


def test_llm_judge_provider_evaluate_with_usage():
    """带 usage 的响应正确传递。"""
    transport = _FakeTransport(
        response={
            "passed": True,
            "rationale": "ok",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }
    )
    provider = LLMJudgeProvider(
        transport=transport,
        provider_name="test",
        model="test-model",
    )
    findings = provider.evaluate(_make_evidence())
    assert findings[0].usage == {"prompt_tokens": 100, "completion_tokens": 50}


# ---------------------------------------------------------------------------
# 2. error handling
# ---------------------------------------------------------------------------


def test_transport_error_produces_error_finding():
    """transport 抛异常时返回 error finding 而非崩掉。"""

    class FakeError(Exception):
        error_code = "auth_error"

    transport = _FakeTransport(raise_error=FakeError("auth failed"))
    provider = LLMJudgeProvider(
        transport=transport,
        provider_name="test",
        model="test-model",
    )
    findings = provider.evaluate(_make_evidence())
    assert len(findings) == 1
    f = findings[0]
    assert "transport error" in f.rationale
    assert "auth_error" in f.message


# ---------------------------------------------------------------------------
# 3. mode property
# ---------------------------------------------------------------------------


def test_mode_live_when_transport_ready():
    """transport.is_live_ready=True 时 mode 为 live。"""
    transport = _FakeTransport()
    provider = LLMJudgeProvider(
        transport=transport,
        provider_name="test",
        model="test",
    )
    assert provider.mode == "live"


def test_mode_disabled_when_transport_not_ready():
    """transport.is_live_ready=False 时 mode 为 disabled。"""
    transport = _FakeTransport()
    transport.is_live_ready = False
    provider = LLMJudgeProvider(
        transport=transport,
        provider_name="test",
        model="test",
    )
    assert provider.mode == "disabled"


# ---------------------------------------------------------------------------
# 4. prompt construction
# ---------------------------------------------------------------------------


def test_prompt_includes_tool_calls():
    """prompt 包含工具调用信息。"""
    transport = _FakeTransport()
    provider = LLMJudgeProvider(
        transport=transport,
        provider_name="test",
        model="test",
    )
    evidence = _make_evidence(
        tool_calls=[
            ToolCall(
                tool_name="get_weather",
                arguments={"city": "Beijing"},
                call_id="c1",
            )
        ]
    )
    request = provider._build_request(evidence)
    user_msg = request["messages"][1]["content"]
    assert "get_weather" in user_msg
    assert "Beijing" in user_msg


def test_prompt_includes_final_answer():
    """prompt 包含 final_answer。"""
    transport = _FakeTransport()
    provider = LLMJudgeProvider(
        transport=transport,
        provider_name="test",
        model="test",
    )
    evidence = _make_evidence(final_answer="The answer is 42.")
    request = provider._build_request(evidence)
    user_msg = request["messages"][1]["content"]
    assert "The answer is 42" in user_msg


def test_prompt_handles_no_tool_calls():
    """无工具调用时 prompt 仍可构建。"""
    transport = _FakeTransport()
    provider = LLMJudgeProvider(
        transport=transport,
        provider_name="test",
        model="test",
    )
    evidence = _make_evidence(tool_calls=[])
    evidence.trace.tool_results = []
    request = provider._build_request(evidence)
    user_msg = request["messages"][1]["content"]
    assert "no tool calls" in user_msg.lower()


# ---------------------------------------------------------------------------
# 5. CoreJudgeProvider Protocol compliance
# ---------------------------------------------------------------------------


def test_protocol_compliance():
    """LLMJudgeProvider 满足 CoreJudgeProvider Protocol。"""
    provider = LLMJudgeProvider(
        transport=_FakeTransport(),
        provider_name="test",
        model="test",
    )
    assert hasattr(provider, "name")
    assert hasattr(provider, "mode")
    assert callable(provider.evaluate)
    evidence = _make_evidence()
    findings = provider.evaluate(evidence)
    assert isinstance(findings, list)
    for f in findings:
        assert isinstance(f, JudgeFinding)
