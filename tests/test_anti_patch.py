"""反补丁/根因治理测试。

为什么需要这组测试：在第二阶段反补丁审计中我们发现，**让代码长期保持“没有补丁、
没有 demo bleed、没有 tautological eval”需要把这些边界写成回归测试**——靠人脑
review 在 commit 多了之后必然漏。本文件把审计中识别出的 P0/P1 根因都钉成断言，
任何一条都失败立刻红，强制改回根因方向而不是再加补丁。

测试纪律：
- 不允许通过放宽断言或在被测代码里加 demo allowlist 的方式来追求绿。
- 如确实需要修改 fixture / 修改断言，必须先给出根因解释（写进 ROADMAP）。
"""

from __future__ import annotations

from pathlib import Path

from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor
from agent_tool_harness.config.eval_spec import EvalSpec

PKG = Path(__file__).resolve().parent.parent / "agent_tool_harness"


def test_core_package_has_no_demo_tool_name_bleed():
    """核心包不允许出现 examples/runtime_debug 业务符号。

    模拟的真实 bug：早期 audit 建议文案里曾硬编码 ``runtime_trace_event_chain`` 这种
    demo 工具名。一旦文档/审计指向某个具体业务名，框架就会被悄悄耦合到 demo，
    其它项目接入时会看到莫名其妙的工具名建议。这条测试遍历 .py 源码做 substring 检查。
    """

    forbidden = [
        "runtime_trace_event_chain",
        "lookup_session_failure",
        "session_failure",
        # runtime_debug 作为 demo 项目目录名只能出现在 docstring/comment 中
        # 用于解释“demo 在哪”，但不应作为代码逻辑的硬编码值。这里仍允许它在
        # 注释和路径字符串中出现（grep 不区分），所以单独检查具体业务符号即可。
    ]
    offenders: list[str] = []
    for path in PKG.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            if token in text:
                offenders.append(f"{path.relative_to(PKG.parent)}: {token}")
    assert not offenders, (
        "核心包出现 demo 工具名硬编码（demo bleed）：\n  "
        + "\n  ".join(offenders)
        + "\n根因方向：把建议文案改成通用占位（如 <domain>_<resource>_<action>）。"
    )


def test_eval_quality_auditor_flags_tautological_must_call_tool():
    """auditor 必须识别 tautological judge：must_call_tool 单规则且指向 required_tools[0]。

    模拟的真实 bug：用户跑 `generate-evals` 拿到候选，没改 judge.rules 就转正。
    候选默认 judge 只有一条 ``must_call_tool=tool_self_name``，在 MockReplayAdapter
    回放 expected_tool_behavior 的链路下**结构性必过**——这是最危险的“看似通过”，
    比 RuleJudge 误判更难被发现，因为 metrics.json 会显示 PASS。
    """

    case = EvalSpec(
        id="tauto",
        name="tautological",
        category="r",
        split="training",
        realism_level="synthetic_realistic",
        complexity="multi_step",
        source="incident",
        user_prompt="用户报告系统在 checkpoint 恢复后接受了过期输入，请定位根因。" * 1,
        initial_context={"trace_id": "t1"},
        verifiable_outcome={"expected_root_cause": "boundary"},
        success_criteria=["结论必须引用 evidence"],
        expected_tool_behavior={"required_tools": ["lookup"]},
        judge={"rules": [{"type": "must_call_tool", "tool": "lookup"}]},
    )

    audit = EvalQualityAuditor().audit_eval(case)
    rule_ids = {f.rule_id for f in audit.findings}
    assert "judge.tautological_must_call_tool" in rule_ids, rule_ids


def test_eval_quality_auditor_does_not_flag_multi_rule_judge_as_tautological():
    """对照测试：当 judge 同时包含 must_use_evidence / root_cause_contains 等语义规则时，
    auditor 不应误报 tautological——避免“为了通过一条新测试把别处都标错”的反补丁陷阱。"""

    case = EvalSpec(
        id="multi",
        name="multi-rule",
        category="r",
        split="training",
        realism_level="synthetic_realistic",
        complexity="multi_step",
        source="incident",
        user_prompt="用户报告系统在 checkpoint 恢复后接受了过期输入，请定位根因。",
        initial_context={"trace_id": "t1"},
        verifiable_outcome={"expected_root_cause": "boundary"},
        success_criteria=["结论必须引用 evidence"],
        expected_tool_behavior={"required_tools": ["lookup"]},
        judge={
            "rules": [
                {"type": "must_call_tool", "tool": "lookup"},
                {"type": "must_use_evidence"},
                {"type": "expected_root_cause_contains"},
            ]
        },
    )

    audit = EvalQualityAuditor().audit_eval(case)
    rule_ids = {f.rule_id for f in audit.findings}
    assert "judge.tautological_must_call_tool" not in rule_ids, rule_ids


def test_from_tools_candidate_carries_anti_tautology_review_note():
    """generate-evals from_tools 必须在 review_notes 显式提醒 must_call_tool 的 tautology
    风险，否则审核者会把候选直接转正得到结构性必过的 eval。"""

    from agent_tool_harness.config.loader import load_project, load_tools
    from agent_tool_harness.eval_generation.generator import EvalGenerator

    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")
    candidates = EvalGenerator().from_tools(project, tools)

    assert candidates, "需要至少一个候选才能验证 anti-tautology 警告"
    for candidate in candidates:
        notes_text = " | ".join(candidate["review_notes"])
        assert "tautological" in notes_text or "must_call_tool" in notes_text, (
            f"候选 {candidate['id']} 缺 anti-tautology 提醒：{notes_text}"
        )
