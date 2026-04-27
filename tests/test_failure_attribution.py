"""Failure attribution 行为测试。

为什么这套测试存在：
- 单看 PASS/FAIL 不足以指导团队修工具，本轮强化的 ``TranscriptAnalyzer`` 与
  ``MarkdownReport`` 必须真的把 11 类 finding 中至少 5 类落到 diagnosis.json
  与 report.md 里。这里覆盖：
    1. ``forbidden_first_tool`` —— Agent 工具选择类
    2. ``missing_required_tool`` —— Agent 工具选择类
    3. ``no_evidence_grounding`` —— Agent 工具选择类（最终回答号称引用 evidence
       但 tool_responses 没有任何 evidence 字段）
    4. ``runtime_error`` —— runtime 类（adapter 抛错）
    5. ``skipped_non_runnable`` —— eval_definition 类（initial_context 缺失）

测试纪律：
- 每条用例都同时检查 ``diagnosis.json`` 中存在该类型 finding，**并且** ``report.md``
  里出现可读 attribution + Suggested fix。两边一起断言能阻止"只改一边、另一边
  忘了"的 regression。
- 这些用例不依赖 demo 工具命名，主要靠 EvalSpec / 自定义 adapter 触发场景；
  ``forbidden_first_tool`` / ``missing_required_tool`` 复用 demo 配置（bad path
  本身的语义就是触发这类失败），但断言只看通用的 finding 字段，不绑定具体 demo
  工具名。
- 不允许通过删 finding、降低 severity 或把 PASS/FAIL 改弱来"修通过率"。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.loader import load_evals, load_project, load_tools
from agent_tool_harness.recorder.run_recorder import RunRecorder
from agent_tool_harness.runner.eval_runner import EvalRunner


# === helpers ===
def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text())


def _diagnosis_for(out_dir: Path, eval_id: str) -> dict[str, Any]:
    diag = _read_json(out_dir / "diagnosis.json")
    matches = [r for r in diag["results"] if r["eval_id"] == eval_id]
    assert matches, f"diagnosis missing eval_id={eval_id}"
    return matches[0]


def _finding_types(diag_result: dict[str, Any]) -> list[str]:
    return [f["type"] for f in diag_result.get("findings", [])]


def _finding_of_type(diag_result: dict[str, Any], finding_type: str) -> dict[str, Any]:
    for f in diag_result.get("findings", []):
        if f["type"] == finding_type:
            return f
    raise AssertionError(
        f"finding type={finding_type} not found in {_finding_types(diag_result)}"
    )


# === adapters ===
class FailingAdapter:
    """模拟 adapter 在 tool 调用前抛错——用于触发 runtime_error 归因。

    它代表真实团队接入 LLM/MCP 后最常见的失败：解析/参数构造/上下文丢失。我们要
    确保 EvalRunner 仍写完整 artifacts，并且 analyzer 把它归到 ``runtime`` 而不是
    ``agent_tool_choice``，避免读者误以为是 Agent 选错工具。
    """

    def run(self, case, registry, recorder):  # noqa: ANN001
        raise RuntimeError(f"adapter exploded for {case.id}")


class FakeEvidenceFreeAdapter:
    """模拟 Agent "嘴上说有 evidence、实际 tool_responses 为空" 的反模式。

    它故意在 final_answer 里写 ``evidence`` 关键字，但不调用任何工具。这样 RuleJudge
    的 ``must_use_evidence`` 会失败，analyzer 归因为 ``no_evidence_grounding``。
    这类反模式正是 Anthropic 文章中"工具必须返回 meaningful context、Agent 必须
    grounding 在 evidence 上"的反例，应该被 deterministic heuristic 抓到。
    """

    SIGNAL_QUALITY = "tautological_replay"

    def run(self, case: EvalSpec, registry, recorder: RunRecorder) -> AgentRunResult:  # noqa: ANN001
        recorder.record_transcript(
            case.id,
            {
                "role": "assistant",
                "type": "final_answer",
                "content": "I have evidence to confirm the conclusion.",
            },
        )
        return AgentRunResult(
            eval_id=case.id,
            tool_calls=[],
            tool_responses=[],
            final_answer="I have evidence to confirm the conclusion.",
        )


# === fixtures ===
@pytest.fixture()
def demo_configs():
    return (
        load_project("examples/runtime_debug/project.yaml"),
        load_tools("examples/runtime_debug/tools.yaml"),
        load_evals("examples/runtime_debug/evals.yaml"),
    )


# === 1. forbidden_first_tool ===
def test_forbidden_first_tool_attribution_in_diagnosis_and_report(tmp_path, demo_configs):
    """bad path 第一步命中 forbidden_first_tool；finding 必须出现在 diagnosis 与 report。"""

    project, tools, evals = demo_configs
    EvalRunner().run(project, tools, evals, MockReplayAdapter("bad"), tmp_path)
    diag = _diagnosis_for(tmp_path, "runtime_input_boundary_regression")

    finding = _finding_of_type(diag, "forbidden_first_tool")
    assert finding["category"] == "agent_tool_choice"
    assert finding["severity"] == "high"
    assert finding["evidence_refs"], "evidence_refs must reference judge/tool_calls"
    assert finding["suggested_fix"], "suggested_fix must not be empty"

    report = (tmp_path / "report.md").read_text()
    assert "forbidden_first_tool" in report
    assert "Suggested fix" in report


# === 2. missing_required_tool ===
def test_missing_required_tool_attribution_in_diagnosis_and_report(tmp_path, demo_configs):
    """bad path 不会调用任何 required_tool；至少有一条 missing_required_tool finding。"""

    project, tools, evals = demo_configs
    EvalRunner().run(project, tools, evals, MockReplayAdapter("bad"), tmp_path)
    diag = _diagnosis_for(tmp_path, "runtime_input_boundary_regression")

    finding = _finding_of_type(diag, "missing_required_tool")
    assert finding["category"] == "agent_tool_choice"
    assert finding["related_tool_or_eval"], "应该绑定到具体缺失工具名以便定位"

    report = (tmp_path / "report.md").read_text()
    assert "missing_required_tool" in report
    # 工具名必须出现在报告里（不硬编码具体 demo 名，使用 finding 自带值）
    assert finding["related_tool_or_eval"] in report


# === 3. no_evidence_grounding ===
def test_no_evidence_grounding_when_tool_responses_lack_evidence(tmp_path, demo_configs):
    """final_answer 声称有 evidence 但 tool_responses 为空——必须归因为 no_evidence_grounding。"""

    project, tools, evals = demo_configs
    EvalRunner().run(project, tools, evals, FakeEvidenceFreeAdapter(), tmp_path)
    diag = _diagnosis_for(tmp_path, "runtime_input_boundary_regression")

    finding = _finding_of_type(diag, "no_evidence_grounding")
    assert finding["category"] == "agent_tool_choice"
    assert finding["severity"] == "high"

    report = (tmp_path / "report.md").read_text()
    assert "no_evidence_grounding" in report
    assert "Suggested fix" in report


# === 4. runtime_error ===
def test_runtime_error_attribution_uses_runtime_category(tmp_path, demo_configs):
    """adapter 抛错 → analyzer 归因到 runtime category，而不是 agent_tool_choice。"""

    project, tools, evals = demo_configs
    EvalRunner().run(project, tools, evals, FailingAdapter(), tmp_path)
    diag = _diagnosis_for(tmp_path, "runtime_input_boundary_regression")

    finding = _finding_of_type(diag, "runtime_error")
    assert finding["category"] == "runtime"
    # runtime/skipped 时不应再生成 agent_tool_choice 类 finding，避免误导
    agent_choice_types = {
        "missing_required_tool",
        "forbidden_first_tool",
        "wrong_first_tool",
        "no_evidence_grounding",
        "redundant_tool_calls",
    }
    leaked = [t for t in _finding_types(diag) if t in agent_choice_types]
    assert not leaked, (
        f"runtime 失败时不应再生成 agent_tool_choice findings，但出现了 {leaked}"
    )

    report = (tmp_path / "report.md").read_text()
    assert "runtime_error" in report
    assert "Category: runtime" in report or "[high/runtime]" in report


# === 5. skipped_non_runnable ===
def test_skipped_non_runnable_attribution_uses_eval_definition_category(
    tmp_path, demo_configs
):
    """initial_context 为空 → audit 判 not runnable → analyzer 归因为 skipped_non_runnable。"""

    project, tools, evals = demo_configs
    # 复制一份 eval，把 initial_context 清空 + 把 user_prompt 也清空，让 audit 判定 not runnable
    case = evals[0]
    broken = EvalSpec(
        id=case.id,
        name=case.name,
        category=case.category,
        split=case.split,
        realism_level=case.realism_level,
        complexity=case.complexity,
        source=case.source,
        user_prompt="",
        initial_context={},
        verifiable_outcome=case.verifiable_outcome,
        success_criteria=case.success_criteria,
        expected_tool_behavior=case.expected_tool_behavior,
        missing_context=case.missing_context,
        judge=case.judge,
        runnable=case.runnable,
    )

    EvalRunner().run(project, tools, [broken], MockReplayAdapter("good"), tmp_path)
    diag = _diagnosis_for(tmp_path, broken.id)

    finding = _finding_of_type(diag, "skipped_non_runnable")
    assert finding["category"] == "eval_definition"

    report = (tmp_path / "report.md").read_text()
    assert "skipped_non_runnable" in report
    assert "eval_definition" in report


# === aggregate / methodology ===
def test_report_includes_failure_attribution_section_and_heuristic_disclaimer(
    tmp_path, demo_configs
):
    """报告必须包含顶层 Failure Attribution 段以及 heuristic 声明。"""

    project, tools, evals = demo_configs
    EvalRunner().run(project, tools, evals, MockReplayAdapter("bad"), tmp_path)
    report = (tmp_path / "report.md").read_text()

    assert "## Failure Attribution" in report
    assert "deterministic heuristic" in report
    assert "Root cause hypothesis" in report
    assert "What to check next" in report
