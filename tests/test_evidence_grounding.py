"""Evidence grounding 边界测试 + decoy trajectory 样本库。

模块定位（v1.0 第一项 P1 deterministic anti-decoy）：
- 本文件覆盖 RuleJudge 新规则 ``evidence_from_required_tools`` 与 TranscriptAnalyzer
  finding ``evidence_grounded_in_decoy_tool`` 的真实边界。
- 这里的"trajectory 样本库"是测试本地 builder（``_build_run`` / ``_build_eval``），
  **故意不落到 fixtures/ 目录**：避免把 decoy 业务符号泄漏到全局 fixture，导致其他
  测试无意中复用一个语义有偏的"标准 trajectory"。每个 case 内联构造，意图自证。

不负责（边界）：
- 不替代 ``test_tool_design_audit_subtle_decoy_xfail.py`` 中的 strict xfail。后者
  测的是**静态 ToolDesignAuditor 仅看 yaml 字段**就能识别 disjoint-vocabulary decoy
  的能力；本文件测的是**运行时 trajectory 已有 evidence 引用**之后能否识别 decoy
  grounding。两者维度不同，xfail 仍保留并由 ROADMAP 跟踪。
- 不验证 evidence 的语义正确性（那是真实 LLM judge 的事，v1.0 之后）。

如何用 artifacts 排查：
- ``runs/<id>/diagnosis.json`` 中查 ``findings[type=evidence_grounded_in_decoy_tool]``，
  其 ``evidence_refs`` 直接指向 tool_responses.jsonl + transcript.jsonl 中的诱饵
  工具与被引用的 evidence id。
"""

from __future__ import annotations

from typing import Any

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.diagnose.transcript_analyzer import TranscriptAnalyzer
from agent_tool_harness.judges.rule_judge import JudgeResult, RuleJudge


# --------------------------------------------------------------------- builders
def _build_eval(
    *,
    required_tools: list[str],
    rules: list[dict[str, Any]],
    eval_id: str = "decoy_case",
) -> EvalSpec:
    """构造一个最小 EvalSpec。

    fake/mock 边界：所有字段都填到刚好让 RuleJudge / TranscriptAnalyzer 不报缺字段；
    业务语义（root_cause / category 等）使用通用占位，避免让任何 example 项目的业务
    符号泄漏到测试。
    """
    return EvalSpec(
        id=eval_id,
        name=eval_id,
        category="generic",
        split="regression",
        realism_level="regression",
        complexity="multi_step",
        source="unit_test_inline",
        user_prompt="placeholder",
        initial_context={},
        verifiable_outcome={"expected_root_cause": "decoy_grounding", "evidence_ids": []},
        success_criteria=[],
        expected_tool_behavior={"required_tools": required_tools, "allowed_alternatives": []},
        judge={"rules": rules},
    )


def _tool_response(
    tool_name: str,
    *,
    evidence_ids: list[str] | None = None,
    technical_id: str | None = None,
    success: bool = True,
) -> dict[str, Any]:
    """模拟一条 tool_response 行（与 RunRecorder 写入 schema 对齐）。

    这是 deterministic mock，不模拟真实工具执行。"""
    content: dict[str, Any] = {}
    if technical_id:
        content["technical_id"] = technical_id
    if evidence_ids:
        content["evidence"] = [{"id": eid, "label": eid} for eid in evidence_ids]
    return {
        "tool_name": tool_name,
        "response": {"success": success, "content": content},
    }


def _build_run(
    *,
    eval_id: str,
    final_answer: str,
    tool_responses: list[dict[str, Any]],
    tool_calls: list[dict[str, Any]] | None = None,
) -> AgentRunResult:
    """构造 AgentRunResult，方便每个 case 表达独立 trajectory。"""
    return AgentRunResult(
        eval_id=eval_id,
        final_answer=final_answer,
        tool_calls=tool_calls or [],
        tool_responses=tool_responses,
    )


# ------------------------------------------------------- RuleJudge 直接边界测试
def _judge(case: EvalSpec, run: AgentRunResult) -> JudgeResult:
    return RuleJudge().judge(case, run)


def test_must_use_evidence_keyword_only_without_responses_fails():
    """边界：final_answer 含"evidence"字面但 tool_responses 没有 evidence id。

    模拟场景：Agent 脑补结论，套了一句"based on evidence ..."。v0.2 已加固后
    必须 FAIL，本测试钉住这条不被回归。"""
    case = _build_eval(
        required_tools=["primary_tool"],
        rules=[{"type": "must_use_evidence"}],
    )
    run = _build_run(
        eval_id=case.id,
        final_answer="Based on evidence, root cause is decoy_grounding.",
        tool_responses=[_tool_response("primary_tool")],
    )
    result = _judge(case, run)
    assert not result.passed
    assert any(
        not c.passed and c.rule.get("type") == "must_use_evidence" for c in result.checks
    )


def test_must_use_evidence_id_present_but_not_cited_fails():
    """边界：tool_responses 提供了 evidence id，但 final_answer 没引用。"""
    case = _build_eval(
        required_tools=["primary_tool"],
        rules=[{"type": "must_use_evidence"}],
    )
    run = _build_run(
        eval_id=case.id,
        final_answer="The evidence supports input_boundary as the cause.",
        tool_responses=[_tool_response("primary_tool", evidence_ids=["ev-real-17"])],
    )
    result = _judge(case, run)
    assert not result.passed


def test_must_use_evidence_passes_when_correct_id_cited():
    """正路径：evidence id 被显式引用，必须 PASS。"""
    case = _build_eval(
        required_tools=["primary_tool"],
        rules=[{"type": "must_use_evidence"}],
    )
    run = _build_run(
        eval_id=case.id,
        final_answer="Root cause: input_boundary, see evidence ev-real-17.",
        tool_responses=[_tool_response("primary_tool", evidence_ids=["ev-real-17"])],
    )
    assert _judge(case, run).passed


def test_evidence_from_required_tools_skips_when_required_undeclared():
    """规则跳过场景：未声明 required_tools 时本规则视为不适用，PASS。

    设计意图：让用户能在所有 eval 上挂这条规则而不会硬挂；真实问题留给
    must_use_evidence / must_call_tool 等更基础的规则。"""
    case = _build_eval(
        required_tools=[],
        rules=[{"type": "evidence_from_required_tools"}],
    )
    run = _build_run(
        eval_id=case.id,
        final_answer="any",
        tool_responses=[_tool_response("anything", evidence_ids=["ev-x"])],
    )
    result = _judge(case, run)
    assert result.passed


def test_evidence_from_required_tools_fails_when_only_decoy_evidence_cited():
    """**核心 anti-decoy 场景**：Agent 调了 decoy 工具收 evidence，把 decoy id
    写进 final_answer，required 工具完全没出现。

    must_use_evidence 在此会通过（因为 decoy id 被引用了），而新规则
    ``evidence_from_required_tools`` 必须把这种"看起来 grounded 实际走错路"的
    答案判 FAIL。这是 v1.0 第一项 P1 的根因修复目标。"""
    case = _build_eval(
        required_tools=["primary_tool"],
        rules=[
            {"type": "must_use_evidence"},
            {"type": "evidence_from_required_tools"},
        ],
    )
    run = _build_run(
        eval_id=case.id,
        final_answer="Decoy evidence snap-decoy-99 confirms input_boundary.",
        tool_responses=[
            _tool_response("decoy_tool", evidence_ids=["snap-decoy-99"]),
        ],
    )
    result = _judge(case, run)
    must_use = [c for c in result.checks if c.rule.get("type") == "must_use_evidence"][0]
    new_rule = [
        c for c in result.checks if c.rule.get("type") == "evidence_from_required_tools"
    ][0]
    assert must_use.passed, "must_use_evidence 仍按旧语义通过——这正是诱饵漏洞"
    assert not new_rule.passed, "新规则必须把 decoy grounding 判 FAIL"
    assert "decoy_tool" in new_rule.message


def test_evidence_from_required_tools_passes_when_required_tool_evidence_cited():
    """回归：即使 trajectory 里也调用了 decoy 工具，只要 final_answer 至少
    引用了一条来自 required 工具的 evidence id，新规则也应 PASS。

    设计意图：本规则只验"是否有正源"，不强求"独占正源"；防止过度严格惩罚那些
    Agent 同时收集多源 evidence、最后做综合的合理路径。"""
    case = _build_eval(
        required_tools=["primary_tool"],
        rules=[{"type": "evidence_from_required_tools"}],
    )
    run = _build_run(
        eval_id=case.id,
        final_answer="ev-real-17 and snap-decoy-99 both indicate input_boundary.",
        tool_responses=[
            _tool_response("primary_tool", evidence_ids=["ev-real-17"]),
            _tool_response("decoy_tool", evidence_ids=["snap-decoy-99"]),
        ],
    )
    assert _judge(case, run).passed


# ----------------------------------------- TranscriptAnalyzer finding 边界测试
def _analyze(case: EvalSpec, run: AgentRunResult) -> dict[str, Any]:
    judge = _judge(case, run)
    return TranscriptAnalyzer().analyze(case, run, judge)


def test_analyzer_emits_decoy_grounding_finding_even_without_new_rule():
    """analyzer 必须在用户**没配新规则**时也能 surface 诱饵 grounding。

    设计意图：让 deterministic 信号"自动浮现"，避免必须先教用户加规则才能看到
    问题。finding 的 evidence_refs 直接指向 transcript/tool_responses 行号语义。"""
    case = _build_eval(
        required_tools=["primary_tool"],
        rules=[{"type": "must_use_evidence"}],
    )
    run = _build_run(
        eval_id=case.id,
        final_answer="snap-decoy-99 confirms decoy_grounding.",
        tool_responses=[_tool_response("decoy_tool", evidence_ids=["snap-decoy-99"])],
    )
    diag = _analyze(case, run)
    findings = diag.get("findings", [])
    types = [f["type"] for f in findings]
    assert "evidence_grounded_in_decoy_tool" in types
    decoy = [f for f in findings if f["type"] == "evidence_grounded_in_decoy_tool"][0]
    assert "decoy_tool" in str(decoy["evidence_refs"])
    assert decoy["severity"] == "high"


def test_analyzer_does_not_fire_decoy_finding_for_clean_path():
    """回归：Agent 走正路径（required 工具返回的 evidence 被引用）时，
    decoy finding 不应触发，避免假阳。"""
    case = _build_eval(
        required_tools=["primary_tool"],
        rules=[{"type": "must_use_evidence"}],
    )
    run = _build_run(
        eval_id=case.id,
        final_answer="ev-real-17 confirms decoy_grounding.",
        tool_responses=[_tool_response("primary_tool", evidence_ids=["ev-real-17"])],
    )
    diag = _analyze(case, run)
    types = [f["type"] for f in diag.get("findings", [])]
    assert "evidence_grounded_in_decoy_tool" not in types


def test_analyzer_does_not_fire_decoy_finding_when_no_evidence_cited():
    """回归：final_answer 完全没引用任何 evidence id 时，由 no_evidence_grounding
    finding 负责报告，decoy finding 必须保持沉默——避免与 must_use_evidence 失败
    findings 重复刷屏。"""
    case = _build_eval(
        required_tools=["primary_tool"],
        rules=[{"type": "must_use_evidence"}],
    )
    run = _build_run(
        eval_id=case.id,
        final_answer="Root cause: decoy_grounding.",
        tool_responses=[_tool_response("decoy_tool", evidence_ids=["snap-decoy-99"])],
    )
    diag = _analyze(case, run)
    types = [f["type"] for f in diag.get("findings", [])]
    assert "evidence_grounded_in_decoy_tool" not in types


# --------------------- v1.0 候选 A：finding 结构化字段 + report 渲染 边界 -----
def test_no_evidence_grounding_distinguishes_when_tool_returned_evidence():
    """子场景区分：tool_responses 里有 evidence id 但 final_answer 没引用 →
    finding 必须把 ``tool_responses_had_evidence=True`` 与 ``available_evidence_refs``
    暴露出来，让 report 能告诉用户"是 prompt/Agent 没引用，不是工具没返回"。"""
    case = _build_eval(
        required_tools=["primary_tool"],
        rules=[{"type": "must_use_evidence"}],
    )
    run = _build_run(
        eval_id=case.id,
        final_answer="The evidence supports input_boundary.",
        tool_responses=[_tool_response("primary_tool", evidence_ids=["ev-real-17"])],
    )
    diag = _analyze(case, run)
    finding = next(f for f in diag["findings"] if f["type"] == "no_evidence_grounding")
    assert finding["tool_responses_had_evidence"] is True
    assert "ev-real-17" in finding["available_evidence_refs"]


def test_no_evidence_grounding_distinguishes_when_tool_returned_nothing():
    """子场景区分：tool_responses 没 evidence id → ``tool_responses_had_evidence=False``，
    并明确建议先修工具 output_contract，而不是去改 prompt。"""
    case = _build_eval(
        required_tools=["primary_tool"],
        rules=[{"type": "must_use_evidence"}],
    )
    run = _build_run(
        eval_id=case.id,
        final_answer="Based on evidence, root cause is decoy_grounding.",
        tool_responses=[_tool_response("primary_tool")],
    )
    diag = _analyze(case, run)
    finding = next(f for f in diag["findings"] if f["type"] == "no_evidence_grounding")
    assert finding["tool_responses_had_evidence"] is False
    assert finding["available_evidence_refs"] == []


def test_decoy_finding_carries_structured_cited_fields():
    """新增结构化字段：``cited_refs`` / ``cited_tools`` / ``required_tools`` 必须可程序化读取。

    这条防回归用于钉住 report 渲染契约——report 直接读字段，不解析字符串。"""
    case = _build_eval(
        required_tools=["primary_tool"],
        rules=[{"type": "must_use_evidence"}],
    )
    run = _build_run(
        eval_id=case.id,
        final_answer="snap-decoy-99 confirms decoy_grounding.",
        tool_responses=[_tool_response("decoy_tool", evidence_ids=["snap-decoy-99"])],
    )
    finding = next(
        f
        for f in _analyze(case, run)["findings"]
        if f["type"] == "evidence_grounded_in_decoy_tool"
    )
    assert finding["cited_refs"] == ["snap-decoy-99"]
    assert finding["cited_tools"] == ["decoy_tool"]
    assert finding["required_tools"] == ["primary_tool"]


def test_report_renders_evidence_grounding_details():
    """端到端：MarkdownReport 必须把 decoy finding 与 no_evidence_grounding
    的结构化字段渲染成可读 bullet。"""
    from agent_tool_harness.reports.markdown_report import MarkdownReport

    case = _build_eval(
        required_tools=["primary_tool"],
        rules=[{"type": "must_use_evidence"}],
    )
    run = _build_run(
        eval_id=case.id,
        final_answer="snap-decoy-99 confirms decoy_grounding.",
        tool_responses=[_tool_response("decoy_tool", evidence_ids=["snap-decoy-99"])],
    )
    judge = _judge(case, run)
    diag = TranscriptAnalyzer().analyze(case, run, judge)
    diagnosis_doc = {
        "results": [
            {
                "eval_id": case.id,
                "findings": diag["findings"],
            }
        ]
    }
    md = MarkdownReport().render(
        project={"name": "test"},
        metrics={
            "total_evals": 1,
            "executed_evals": 1,
            "passed": 0,
            "failed": 1,
            "skipped_evals": 0,
            "error_evals": 0,
        },
        audit_tools={"summary": {"low_score_tools": []}, "tools": []},
        audit_evals={"summary": {"not_runnable": []}, "evals": []},
        judge_results={"results": []},
        diagnosis=diagnosis_doc,
    )
    assert "evidence_grounded_in_decoy_tool" in md
    assert "snap-decoy-99" in md
    assert "decoy_tool" in md
    assert "primary_tool" in md
