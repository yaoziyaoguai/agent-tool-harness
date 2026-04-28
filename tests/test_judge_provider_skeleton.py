"""JudgeProvider 契约测试（v1.1 第一项受控启动）。

测试纪律说明
============
本文件**不**试图测真实 LLM judge——v1.1 第一轮明确不接外部服务。
这里所有 fake/recording/fixture 都是 in-process deterministic，目的：

1. 钉死"默认 provider 就是 RuleJudgeProvider，行为与直接用 RuleJudge 完全一致"
   ——防止未来重构悄悄改了 EvalRunner 默认；
2. 钉死"RecordedJudgeProvider 找不到 recording 必须抛
   :class:`MissingRecordingError`，绝不静默 PASS"——防止"recording 缺失 →
   假成功"成为新的吞异常路径；
3. 钉死"两个 provider 都是 zero-network、zero-side-effect"——防止未来真实
   LLM provider 落地时被悄悄 wire 进 deterministic baseline。

测试**不**钉 EvalRunner 集成，因为本轮明确**不**改 EvalRunner / 不改
``judge_results.json`` schema；那是 v1.1 后续轮的 scope。
"""

from __future__ import annotations

import socket
from typing import Any

import pytest

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.judges.provider import (
    PROVIDER_SCHEMA_VERSION,
    MissingRecordingError,
    ProviderJudgeResult,
    RecordedJudgeProvider,
    RuleJudgeProvider,
)
from agent_tool_harness.judges.rule_judge import RuleJudge


def _eval(eval_id: str = "case_1") -> EvalSpec:
    """构造最小 EvalSpec 用于 provider 契约测试。

    fake 边界：字段全部用占位值；judge.rules 故意只放一条 deterministic
    ``must_use_tools``，让 RuleJudge 在不同 ``run`` 输入下能出现 PASS / FAIL
    两种状态——便于断言 RuleJudgeProvider 真的透传了底层判定，而不是恒
    返回固定值。
    """

    return EvalSpec(
        id=eval_id,
        name=eval_id,
        category="generic",
        split="regression",
        realism_level="regression",
        complexity="single_step",
        source="unit_test_inline",
        user_prompt="placeholder",
        initial_context={},
        verifiable_outcome={"expected_root_cause": "placeholder", "evidence_ids": []},
        success_criteria=[],
        expected_tool_behavior={"required_tools": ["foo"], "allowed_alternatives": []},
        judge={"rules": [{"type": "must_call_tool", "tool": "foo"}]},
    )


def _run(*, called_foo: bool) -> AgentRunResult:
    """构造最小 AgentRunResult。

    通过 ``called_foo`` 切换 ``tool_calls`` 是否包含 ``foo``，从而让
    ``must_use_tools`` 规则在两种输入下出现不同结果——这是验证
    "provider 真的透传 RuleJudge 判定"的关键边界。
    """

    tool_calls: list[dict[str, Any]] = [{"tool_name": "foo"}] if called_foo else []
    return AgentRunResult(
        eval_id="case_1",
        final_answer="placeholder",
        tool_calls=tool_calls,
        tool_responses=[],
    )


def test_rule_judge_provider_passes_through_deterministic_pass(monkeypatch):
    """RuleJudgeProvider 必须与直接调 RuleJudge 行为完全一致（PASS 路径）。

    防止：未来有人在 provider 里加"默认 PASS"或"额外宽松规则"等 hack。
    """

    inner_judge = RuleJudge()
    expected = inner_judge.judge(_eval(), _run(called_foo=True))

    provider = RuleJudgeProvider(judge=inner_judge)
    result = provider.judge(_eval(), _run(called_foo=True))

    assert isinstance(result, ProviderJudgeResult)
    assert result.provider == "rule"
    assert result.mode == "deterministic"
    assert result.passed is True
    assert result.passed == expected.passed
    # 透传 checks 内容：不能丢失 deterministic 证据。
    assert [c.passed for c in result.inner.checks] == [c.passed for c in expected.checks]


def test_rule_judge_provider_passes_through_deterministic_fail():
    """RuleJudgeProvider 必须保留 FAIL，不允许"善意"翻成 PASS。

    防止：provider 包装层把 deterministic FAIL "降级"成 warning 假成功。
    """

    provider = RuleJudgeProvider()
    result = provider.judge(_eval(), _run(called_foo=False))

    assert result.passed is False
    assert any(c.passed is False for c in result.inner.checks)


def test_recorded_judge_provider_returns_recording_without_calling_rule_judge():
    """RecordedJudgeProvider 不应该调用 RuleJudge——它代表未来 LLM judge 的 dry-run 视角。

    fixture 边界：``recordings`` 显式声明 passed=True 但 _run(called_foo=False)
    在 RuleJudge 下会 FAIL，因此这条测试也间接验证 RecordedJudgeProvider
    并未偷偷把 RuleJudge 的结论盖在自己身上。
    """

    recordings = {
        "case_1": {
            "passed": True,
            "rationale": "dry-run mock: trajectory looks aligned with required_tools",
            "confidence": 0.9,
            "rubric": "evidence-grounded answer",
        }
    }
    provider = RecordedJudgeProvider(recordings=recordings)

    # 用 called_foo=False 保证 RuleJudge 会判 FAIL；如果 RecordedJudgeProvider
    # 偷偷调了 RuleJudge，passed 会被覆盖成 False，本断言就会失败。
    result = provider.judge(_eval(), _run(called_foo=False))

    assert result.passed is True
    assert result.provider == "recorded"
    assert result.mode == "dry_run"
    assert result.rationale == recordings["case_1"]["rationale"]
    assert result.confidence == 0.9
    assert result.rubric == "evidence-grounded answer"
    # 占位 check 必须明确标 rule.type=recorded_judge，而不是冒充 RuleJudge 规则。
    assert result.inner.checks[0].rule["type"] == "recorded_judge"


def test_recorded_judge_provider_raises_on_missing_recording():
    """recording 缺失必须抛 MissingRecordingError，绝不静默 PASS。

    这是关键反 hack 边界：如果将来有人为了"让 CI 跑过"把这里改成
    return PASS，整个 dry-run judge contract 就破了。
    """

    provider = RecordedJudgeProvider(recordings={})
    with pytest.raises(MissingRecordingError):
        provider.judge(_eval(), _run(called_foo=True))


def test_provider_metadata_carries_schema_version():
    """provider metadata 必须带 schema_version，便于未来 EvalRunner 识别格式。

    防止：未来 EvalRunner 写入 judge_results.json 时漏掉 schema_version
    字段，导致下游消费者无法判断是否能识别 provider 字段。
    """

    provider = RuleJudgeProvider()
    result = provider.judge(_eval(), _run(called_foo=True))

    metadata = result.metadata()
    assert metadata["provider"] == "rule"
    assert metadata["mode"] == "deterministic"
    assert metadata["schema_version"] == PROVIDER_SCHEMA_VERSION


def test_providers_do_not_open_network_sockets(monkeypatch):
    """两个 provider 在 judge 期间都不能开网络 socket。

    通过 monkeypatch 把 ``socket.socket`` 替成抛错版本，如果 provider 内部
    悄悄调了 LLM API / HTTP / DNS，本测试会立即失败。这是钉死"v1.1 第一轮
    所有 provider 都是 offline / deterministic"的核心边界。
    """

    real_socket = socket.socket

    def _no_socket(*args, **kwargs):  # pragma: no cover - 仅在违反契约时触发
        raise AssertionError(
            "JudgeProvider tried to open a network socket; v1.1 contract forbids it."
        )

    monkeypatch.setattr(socket, "socket", _no_socket)
    try:
        RuleJudgeProvider().judge(_eval(), _run(called_foo=True))
        RecordedJudgeProvider(recordings={"case_1": {"passed": True}}).judge(
            _eval(), _run(called_foo=True)
        )
    finally:
        monkeypatch.setattr(socket, "socket", real_socket)
