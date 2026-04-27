"""收紧 EvalQualityAuditor.runnable 与 RuleJudge.must_use_evidence 的回归测试。

为什么需要这组测试：第三阶段反补丁审计发现两个真实接入坑——
1) ``runnable`` 只看 ``bool(field)``，``initial_context: {trace_id: ""}`` 这种
   "看似配齐"的 eval 会被标可运行；
2) ``must_use_evidence`` 之前只要 final_answer 含 ``evidence`` 单词就放行，
   工具返回再也没 evidence id 也能通过。

本文件把"穿透字段层只看实际值"和"必须真的引用工具返回 id"两个根因边界钉成
回归测试，任何放宽都会立刻红。
"""

from __future__ import annotations

import pytest

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.judges.rule_judge import RuleJudge


def _eval(
    *,
    initial_context=None,
    verifiable_outcome=None,
    expected_tool_behavior=None,
    success_criteria=None,
    judge=None,
    runnable=True,
):
    return EvalSpec(
        id="x",
        name="x",
        category="r",
        split="training",
        realism_level="synthetic_realistic",
        complexity="multi_step",
        source="incident",
        user_prompt="用户报告系统在 checkpoint 恢复后接受了过期输入，请定位根因。",
        initial_context={"trace_id": "t1"} if initial_context is None else initial_context,
        verifiable_outcome=(
            {"expected_root_cause": "boundary"}
            if verifiable_outcome is None
            else verifiable_outcome
        ),
        success_criteria=(
            ["结论必须引用 evidence"] if success_criteria is None else success_criteria
        ),
        expected_tool_behavior=(
            {"required_tools": ["lookup"]}
            if expected_tool_behavior is None
            else expected_tool_behavior
        ),
        judge={"rules": [{"type": "must_use_evidence"}]} if judge is None else judge,
        runnable=runnable,
    )


# ---------- EvalQualityAuditor.runnable 收紧 ----------


@pytest.mark.parametrize(
    "field_name,bad_value,expected_rule_id",
    [
        ("initial_context", {"trace_id": ""}, "fixture.empty_initial_context_values"),
        ("initial_context", {"trace_id": "   "}, "fixture.empty_initial_context_values"),
        ("verifiable_outcome", {"expected_root_cause": ""},
         "verifiability.empty_verifiable_outcome_values"),
        ("expected_tool_behavior", {"required_tools": []},
         "multi_step.missing_expected_tool_behavior"),
    ],
)
def test_auditor_marks_eval_with_empty_values_as_not_runnable(
    field_name, bad_value, expected_rule_id,
):
    """模拟真实坑：用户写 ``initial_context: {trace_id: ""}`` 这种"字段在但值空"
    的 fixture，期望 auditor 仍然标 not_runnable 并给出针对性 finding，而不是
    糊弄过去让 runner 拿空值跑出空 artifacts。"""

    case = _eval(**{field_name: bad_value})

    audit = EvalQualityAuditor().audit_eval(case)
    rule_ids = {f.rule_id for f in audit.findings}
    assert audit.runnable is False, audit.findings
    assert expected_rule_id in rule_ids, rule_ids
    assert "fixture.not_runnable" in rule_ids


def test_auditor_flags_missing_expected_root_cause_even_if_other_keys_present():
    """``verifiable_outcome`` 有其它键但缺 ``expected_root_cause`` 且无 evidence_ids
    时，judge 没有可校验目标——必须给 ``verifiability.missing_expected_root_cause``
    并标 not_runnable。"""

    case = _eval(verifiable_outcome={"some_other_field": "value"})

    audit = EvalQualityAuditor().audit_eval(case)
    rule_ids = {f.rule_id for f in audit.findings}
    assert audit.runnable is False
    assert "verifiability.missing_expected_root_cause" in rule_ids, rule_ids


def test_auditor_accepts_evidence_ids_as_substitute_for_root_cause():
    """``evidence_ids`` 也是合法可验证目标——只有它而没 expected_root_cause 不应
    被误标 not_runnable。这是反补丁对照测试：防止上一条断言被收紧到误伤合理配置。"""

    case = _eval(
        verifiable_outcome={"evidence_ids": ["ev-1"]},
        judge={"rules": [{"type": "must_use_evidence"}]},
    )

    audit = EvalQualityAuditor().audit_eval(case)
    rule_ids = {f.rule_id for f in audit.findings}
    assert audit.runnable is True, audit.findings
    assert "verifiability.missing_expected_root_cause" not in rule_ids


# ---------- RuleJudge.must_use_evidence 加固 ----------


def _run(*, final_answer: str, tool_responses=None, tool_calls=None) -> AgentRunResult:
    return AgentRunResult(
        eval_id="x",
        final_answer=final_answer,
        tool_calls=tool_calls or [],
        tool_responses=tool_responses or [],
    )


def test_must_use_evidence_rejects_answer_without_evidence_word():
    """模拟坑：final_answer 只写"shows / based on / 调查显示"，没有 evidence/证据，
    且 tool_responses 也没 evidence id——必须 FAIL。"""

    case = _eval(judge={"rules": [{"type": "must_use_evidence"}]})
    run = _run(final_answer="Based on what shows here, the cause is X.")
    result = RuleJudge().judge(case, run)
    assert result.passed is False


def test_must_use_evidence_rejects_evidence_word_without_tool_response_id():
    """final_answer 写了 "evidence" 但 tool_responses 完全没 evidence——必须 FAIL，
    防止"模板化提到 evidence 一词就通过"的 false positive。"""

    case = _eval(judge={"rules": [{"type": "must_use_evidence"}]})
    run = _run(
        final_answer="Evidence supports the cause.",
        tool_responses=[{"call_id": "c1", "response": {"success": True, "content": {}}}],
    )
    result = RuleJudge().judge(case, run)
    assert result.passed is False


def test_must_use_evidence_passes_when_answer_cites_real_id():
    """tool_responses 有 ev-17，final_answer 写 "evidence ev-17"——应通过。"""

    case = _eval(judge={"rules": [{"type": "must_use_evidence"}]})
    run = _run(
        final_answer="Root cause: boundary. Evidence: ev-17.",
        tool_responses=[
            {
                "call_id": "c1",
                "response": {
                    "success": True,
                    "content": {"evidence": [{"id": "ev-17", "label": "boundary log"}]},
                },
            }
        ],
    )
    result = RuleJudge().judge(case, run)
    assert result.passed is True


def test_must_use_evidence_recognizes_chinese_evidence_keyword():
    """中文路径：final_answer 用"证据 ev-17"也应通过；保证团队习惯写中文回答时
    judge 不会因 keyword 限定为英文而误失败。"""

    case = _eval(judge={"rules": [{"type": "must_use_evidence"}]})
    run = _run(
        final_answer="根因: boundary。证据: ev-17。",
        tool_responses=[
            {
                "call_id": "c1",
                "response": {
                    "success": True,
                    "content": {"evidence": [{"id": "ev-17"}]},
                },
            }
        ],
    )
    result = RuleJudge().judge(case, run)
    assert result.passed is True


def test_must_use_evidence_ignores_failed_tool_responses():
    """tool_response.success=False 的 evidence 不应被采纳——失败工具返回的 id
    本身就不可信，不能让 judge 当成有效证据。"""

    case = _eval(judge={"rules": [{"type": "must_use_evidence"}]})
    run = _run(
        final_answer="Evidence: ev-17",
        tool_responses=[
            {
                "call_id": "c1",
                "response": {
                    "success": False,
                    "content": {"evidence": [{"id": "ev-17"}]},
                },
            }
        ],
    )
    result = RuleJudge().judge(case, run)
    assert result.passed is False
