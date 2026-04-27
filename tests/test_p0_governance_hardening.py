"""本轮 review 引入的 P0/P1 治理硬化测试集合。

为什么单独成文件：
- 这些测试的目标不是覆盖率，而是把"上一版本能绕过的 audit / judge 漏洞"显式钉死。
- 如果未来有人把治理逻辑回退（例如把 must_use_evidence 的短串过滤删掉、把
  multi-rule tautological 检测改回单条 must_call_tool 限定），这里会立刻红灯。
- 与现有 `test_governance_discipline.py` / `test_anti_patch.py` 互补：那两个查
  代码层禁用语，本文件查"行为/根因层"——同一根因换个写法不能再次绕过。

文件不在范围内的：
- 不验证 LLM Judge / 真实 adapter（P2，写在 ROADMAP）；
- 不验证 ToolDesignAuditor 语义级重叠（已被 strict xfail 钉住）。
"""

from __future__ import annotations

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor
from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.judges.rule_judge import RuleJudge


def _eval_from(
    *,
    user_prompt: str = "A real user reports an issue and asks the agent to diagnose it.",
    rules: list[dict] | None = None,
    required_tools: list[str] | None = None,
    verifiable_outcome: dict | None = None,
    realism_level: str = "regression",
) -> EvalSpec:
    """构造 EvalSpec 的最小工厂。

    EvalSpec 是 frozen dataclass、所有字段必填；本工厂用 ``from_dict`` 走和真实
    YAML 加载相同的规范化路径，避免在测试里一处一处写默认值。
    """

    return EvalSpec.from_dict(
        {
            "id": "case_under_test",
            "name": "case under test",
            "category": "demo",
            "split": "regression",
            "realism_level": realism_level,
            "complexity": "multi_step",
            "source": "hand_authored",
            "user_prompt": user_prompt,
            "initial_context": {"trace_id": "trace-001"},
            "verifiable_outcome": (
                verifiable_outcome
                if verifiable_outcome is not None
                else {"expected_root_cause": "input_boundary", "evidence_ids": ["ev-17"]}
            ),
            "success_criteria": ["Cite evidence."],
            "expected_tool_behavior": {"required_tools": required_tools or []},
            "judge": {"rules": rules or []},
            "runnable": True,
        }
    )


def _eval(rules: list[dict], required_tools: list[str]) -> EvalSpec:
    return _eval_from(rules=rules, required_tools=required_tools)


# ---------------------------------------------------------------------------
# P0-1: tautological judge 检测必须覆盖 multi-rule 场景
# ---------------------------------------------------------------------------


def test_audit_flags_multi_must_call_tool_as_tautological():
    """多条 must_call_tool 全覆盖 required_tools 时仍属 tautological。

    场景：审核者把 judge 写成"对每个 required_tool 都加一条 must_call_tool"。
    旧版 audit 只钉单条 must_call_tool，会放过这种等价绕过；本测试钉住根因层
    判定——只要全部规则都是结构性 must_call_tool/must_call_one_of，且没有任何
    一条行为语义规则，就必须报 tautological。
    """

    rules = [
        {"type": "must_call_tool", "tool": "alpha"},
        {"type": "must_call_tool", "tool": "beta"},
        {"type": "must_call_tool", "tool": "gamma"},
    ]
    case = _eval(rules, required_tools=["alpha", "beta", "gamma"])

    audited = EvalQualityAuditor().audit_eval(case)
    rule_ids = {f.rule_id for f in audited.findings}

    assert "judge.tautological_must_call_tool" in rule_ids


def test_audit_does_not_flag_when_semantic_rule_present():
    """有任意一条行为语义规则就不应再报 tautological。

    这是 P0-1 修复的"反向用例"：避免新规则误伤合理 judge——只要 judge 包含
    must_use_evidence / expected_root_cause_contains 等真正校验 Agent 行为的
    规则，多条 must_call_tool 仍属合法用法。
    """

    rules = [
        {"type": "must_call_tool", "tool": "alpha"},
        {"type": "must_call_tool", "tool": "beta"},
        {"type": "must_use_evidence"},
    ]
    case = _eval(rules, required_tools=["alpha", "beta"])

    audited = EvalQualityAuditor().audit_eval(case)
    rule_ids = {f.rule_id for f in audited.findings}

    assert "judge.tautological_must_call_tool" not in rule_ids


# ---------------------------------------------------------------------------
# P0-2: must_use_evidence 必须忽略短 evidence id，避免 substring 假阳
# ---------------------------------------------------------------------------


def test_must_use_evidence_ignores_short_ids_to_avoid_false_positive():
    """evidence id 长度 < 3 时不能让任何 final_answer 都"自然命中"。

    场景：工具实现里 evidence id 写成 ``"1"`` / ``"id"`` / ``"a"``——substring
    匹配几乎对所有英文/中文回答都为真，judge 会误 PASS。本测试构造一条**没有
    引用任何具体证据**的 final_answer，配上短 evidence id，必须 FAIL。
    """

    case = _eval_from(
        rules=[{"type": "must_use_evidence"}],
        required_tools=[],
        verifiable_outcome={},
    )
    run = AgentRunResult(
        eval_id=case.id,
        # final_answer 自然包含字符 "1"——旧版会因为 substring 匹配 evidence id="1"
        # 而误判通过；本断言确保新版严格判 FAIL。
        final_answer="evidence shows the user issue happened on 2024-01 boundary.",
        tool_calls=[],
        tool_responses=[
            {"response": {"success": True, "content": {"evidence": [{"id": "1"}]}}}
        ],
    )

    result = RuleJudge().judge(case, run)
    assert result.passed is False


def test_must_use_evidence_still_passes_when_real_id_is_cited():
    """长度 ≥ 3 的真实 id 被引用时必须 PASS。

    P0-2 修复的"反向用例"：避免短 id 过滤把合理用例误伤。``ev-17`` 长度 5，
    必须仍能被识别。
    """

    case = _eval_from(
        rules=[{"type": "must_use_evidence"}],
        required_tools=[],
        verifiable_outcome={},
    )
    run = AgentRunResult(
        eval_id=case.id,
        final_answer="Evidence: ev-17 confirms the input_boundary issue.",
        tool_calls=[],
        tool_responses=[
            {"response": {"success": True, "content": {"evidence": [{"id": "ev-17"}]}}}
        ],
    )

    assert RuleJudge().judge(case, run).passed is True


# ---------------------------------------------------------------------------
# P0-3: 空 audit 输入必须在 JSON summary 里写显式 warning
# ---------------------------------------------------------------------------


def test_tool_audit_emits_empty_input_warning_in_summary():
    """空 tools 时 audit_tools.json 必须显式警告，而不是看起来"通过"。

    场景：CI / 远程 pipeline 只消费 JSON artifact，看不到 stderr。如果空输入
    没有写进 summary.warnings，整条 pipeline 会以为 audit 已经跑通。
    """

    result = ToolDesignAuditor().audit([])

    warnings = result["summary"].get("warnings") or []
    assert any("empty_input" in w for w in warnings), warnings


def test_eval_audit_emits_empty_input_warning_in_summary():
    """空 evals 时 audit_evals.json 必须同样显式警告。"""

    result = EvalQualityAuditor().audit([])

    warnings = result["summary"].get("warnings") or []
    assert any("empty_input" in w for w in warnings), warnings


# ---------------------------------------------------------------------------
# P1-2: cheating prompt 启发式必须覆盖更多等价表达
# ---------------------------------------------------------------------------


def test_audit_flags_extended_cheating_phrases():
    """除原有"请调用 / please call"外，常见等价表达也必须被钉。

    覆盖：use the X tool / call the X tool / 使用工具 / 请使用 / invoke the X tool。
    任何一条都应该报 ``realism.cheating_prompt``，避免审核者用同义词绕过。
    """

    cheating_prompts = [
        "Please use the runtime_trace_event_chain tool to find the root cause for the user.",
        "Call the runtime_inspect_checkpoint tool and tell the user the root cause.",
        "请使用 runtime_trace_event_chain 工具帮用户分析问题并给出根因结论说明。",
        "Invoke the tui_inspect_snapshot tool to confirm the visible terminal state for user.",
        "请直接使用工具拿到证据后告诉用户根因结论以及下一步处理建议步骤。",
    ]
    for prompt in cheating_prompts:
        case = _eval_from(
            user_prompt=prompt,
            rules=[{"type": "must_use_evidence"}],
            required_tools=["runtime_trace_event_chain"],
        )
        audited = EvalQualityAuditor().audit_eval(case)
        rule_ids = {f.rule_id for f in audited.findings}
        assert "realism.cheating_prompt" in rule_ids, prompt


def test_audit_does_not_flag_legit_prompt_as_cheating():
    """合理用户提问不能被新启发式误伤。

    P1-2 修复的"反向用例"：题面只描述用户现象，不出现工具名/调用动作时，
    必须不报 cheating_prompt。
    """

    case = _eval_from(
        user_prompt=(
            "After a checkpoint restore, the runtime accepts stale TUI input. "
            "Please diagnose what is going wrong and explain the next action."
        ),
        rules=[{"type": "must_use_evidence"}],
        required_tools=["runtime_trace_event_chain"],
    )

    audited = EvalQualityAuditor().audit_eval(case)
    rule_ids = {f.rule_id for f in audited.findings}
    assert "realism.cheating_prompt" not in rule_ids
