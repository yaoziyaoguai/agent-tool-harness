"""P4: Task Outcome 报告渲染测试。

测试覆盖：
- render_task_outcome_markdown: PASS/FAIL/INCONCLUSIVE 状态行、verifier 表、
  final answer 引用块、空 outcome 防御
- render_task_outcome_text: 单行摘要格式
- task_outcome_to_json_dict: JSON 序列化形状、空 outcome 防御、非 TaskOutcome 输入

架构语义保护：
- 渲染函数不修改 TaskOutcome——纯函数
- Markdown 输出可直接嵌入已有报告
- JSON 输出与 ReportInsight JSON 兼容
"""

from __future__ import annotations

from agent_tool_harness.task_eval.render import (
    render_task_outcome_markdown,
    render_task_outcome_text,
    task_outcome_to_json_dict,
)
from agent_tool_harness.task_eval.task_evaluator import TaskOutcome
from agent_tool_harness.task_eval.verifiers import VerifierResult

# ============================================================================
# render_task_outcome_markdown
# ============================================================================


class TestRenderTaskOutcomeMarkdown:
    def test_success_outcome_markdown(self):
        """PASS 状态 Markdown 包含 case_id、PASS 图标、verifier 表。"""
        outcome = TaskOutcome(
            case_id="ks-001",
            status="success",
            verifier_results=[
                VerifierResult(
                    verifier_name="composite",
                    passed=True,
                    matched=["root cause"],
                    missing=[],
                    details="mode=all; contains_required_facts: PASS",
                ),
            ],
            final_answer="Root cause is network timeout.",
            details="mode=all; contains_required_facts: PASS",
            matched=["root cause"],
            missing=[],
        )
        md = render_task_outcome_markdown(outcome)
        assert "ks-001" in md
        assert "**PASS**" in md
        assert "PASS" in md
        assert "composite" in md
        assert "root cause" in md
        assert "Root cause is network timeout." in md

    def test_failed_outcome_markdown(self):
        """FAIL 状态 Markdown 包含 FAIL 图标和 missing 信息。"""
        outcome = TaskOutcome(
            case_id="ks-002",
            status="failed",
            verifier_results=[
                VerifierResult(
                    verifier_name="composite",
                    passed=False,
                    matched=["root cause"],
                    missing=["fix recommendation"],
                    details="mode=all; contains_required_facts: FAIL",
                ),
            ],
            final_answer="Root cause is timeout.",
            details="mode=all; contains_required_facts: FAIL",
            matched=["root cause"],
            missing=["fix recommendation"],
        )
        md = render_task_outcome_markdown(outcome)
        assert "**FAIL**" in md
        assert "fix recommendation" in md

    def test_inconclusive_outcome_markdown(self):
        """INCONCLUSIVE 状态 —— 无 verifier 表。"""
        outcome = TaskOutcome(
            case_id="ks-003",
            status="inconclusive",
            details="无可自动判定的验证条件",
        )
        md = render_task_outcome_markdown(outcome)
        assert "**INCONCLUSIVE**" in md
        assert "ks-003" in md
        # 无 verifier_results → 不渲染表格
        assert "| Verifier" not in md

    def test_markdown_without_final_answer(self):
        """空 final_answer → 不渲染引用块。"""
        outcome = TaskOutcome(
            case_id="ks-004",
            status="success",
            details="all good",
        )
        md = render_task_outcome_markdown(outcome)
        assert "**Final Answer:**" not in md

    def test_non_task_outcome_input(self):
        """非 TaskOutcome 输入 → 返回空字符串，不 crash。"""
        assert render_task_outcome_markdown(None) == ""
        assert render_task_outcome_markdown("not an outcome") == ""


# ============================================================================
# render_task_outcome_text
# ============================================================================


class TestRenderTaskOutcomeText:
    def test_pass_one_liner(self):
        """PASS 单行摘要。"""
        outcome = TaskOutcome(
            case_id="ks-001",
            status="success",
            details="matched 2/2 required facts",
        )
        text = render_task_outcome_text(outcome)
        assert text == "[PASS] ks-001: matched 2/2 required facts"

    def test_fail_one_liner(self):
        """FAIL 单行摘要。"""
        outcome = TaskOutcome(
            case_id="ks-002",
            status="failed",
            details="matched 1/2 required facts",
        )
        text = render_task_outcome_text(outcome)
        assert text == "[FAIL] ks-002: matched 1/2 required facts"

    def test_inconclusive_one_liner(self):
        """INCONCLUSIVE 单行摘要。"""
        outcome = TaskOutcome(
            case_id="ks-003",
            status="inconclusive",
        )
        text = render_task_outcome_text(outcome)
        assert text == "[INCONCLUSIVE] ks-003: no details"


# ============================================================================
# task_outcome_to_json_dict
# ============================================================================


class TestTaskOutcomeToJsonDict:
    def test_success_outcome_json(self):
        """TaskOutcome → JSON dict 包含所有预期字段。"""
        outcome = TaskOutcome(
            case_id="ks-001",
            status="success",
            verifier_results=[
                VerifierResult(
                    verifier_name="composite",
                    passed=True,
                    matched=["root cause"],
                    missing=[],
                    details="mode=all; contains_required_facts: PASS",
                ),
            ],
            final_answer="Root cause is timeout.",
            details="mode=all; contains_required_facts: PASS",
            matched=["root cause"],
            missing=[],
        )
        d = task_outcome_to_json_dict(outcome)
        assert d["case_id"] == "ks-001"
        assert d["status"] == "success"
        assert d["final_answer"] == "Root cause is timeout."
        assert len(d["verifier_results"]) == 1
        assert d["verifier_results"][0]["passed"] is True
        assert d["verifier_results"][0]["verifier_name"] == "composite"
        assert "root cause" in d["matched"]
        assert d["missing"] == []

    def test_failed_outcome_json(self):
        """失败 TaskOutcome 的 JSON 包含 missing 信息。"""
        outcome = TaskOutcome(
            case_id="ks-002",
            status="failed",
            missing=["fix recommendation"],
            details="matched 1/2 required facts",
        )
        d = task_outcome_to_json_dict(outcome)
        assert d["status"] == "failed"
        assert "fix recommendation" in d["missing"]

    def test_non_task_outcome_json(self):
        """非 TaskOutcome 输入 → 空 dict，不 crash。"""
        assert task_outcome_to_json_dict(None) == {}
        assert task_outcome_to_json_dict("not an outcome") == {}
