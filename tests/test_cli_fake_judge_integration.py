"""--core-flow --judge-provider fake 集成测试。

测试纪律：
- 所有测试零网络依赖
- 不读取 .env / os.environ
- 不调用真实 LLM
- FakeJudgeProvider 是默认 judge provider
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agent_tool_harness.config.loader import load_evals, load_tools
from agent_tool_harness.core_contract import JudgeFinding

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _load_knowledge_search_fixtures():
    """加载 knowledge_search example 的 tools + evals。"""
    base = Path("examples/knowledge_search")
    tools = load_tools(str(base / "tools.yaml"))
    evals = load_evals(str(base / "evals.yaml"))
    return tools, evals


# ---------------------------------------------------------------------------
# 1. --core-flow --judge-provider fake 端到端
# ---------------------------------------------------------------------------


def test_core_flow_with_fake_judge_provider():
    """--core-flow --judge-provider fake 通过 _run_core_flow() 端到端运行。"""
    from agent_tool_harness.cli import _run_core_flow

    tools, evals = _load_knowledge_search_fixtures()
    with tempfile.TemporaryDirectory() as tmpdir:
        exit_code = _run_core_flow(
            tools=tools,
            evals=evals[:1],  # 只跑第一个 eval 加速
            out=tmpdir,
            mock_path="good",
            judge_provider="fake",
        )
        assert exit_code == 0


# ---------------------------------------------------------------------------
# 2. evaluation_result.json 包含 JudgeFinding
# ---------------------------------------------------------------------------


def test_evaluation_result_contains_judge_finding():
    """evaluation_result.json 同时包含 RuleFinding 和 JudgeFinding。"""
    from agent_tool_harness.cli import _run_core_flow

    tools, evals = _load_knowledge_search_fixtures()
    eval_spec = evals[0]
    with tempfile.TemporaryDirectory() as tmpdir:
        _run_core_flow(
            tools=tools,
            evals=[eval_spec],
            out=tmpdir,
            mock_path="good",
            judge_provider="fake",
        )
        eval_json = json.loads(
            Path(tmpdir, f"evaluation_result_{eval_spec.id}.json").read_text(encoding="utf-8")
        )
        findings = eval_json.get("findings", [])
        categories = [f.get("category") for f in findings]
        assert "rule" in categories, "应包含 RuleFinding"
        assert "judge" in categories, "应包含 JudgeFinding"


# ---------------------------------------------------------------------------
# 3. passed 仍由 RuleJudge 决定
# ---------------------------------------------------------------------------


def test_passed_still_determined_by_rule_judge():
    """JudgeFinding 不改变 RuleJudge 的 passed 判定。"""
    from agent_tool_harness.cli import _run_core_flow

    tools, evals = _load_knowledge_search_fixtures()
    eval_spec = evals[0]
    with tempfile.TemporaryDirectory() as tmpdir:
        # good path
        _run_core_flow(
            tools=tools,
            evals=[eval_spec],
            out=Path(tmpdir) / "good",
            mock_path="good",
            judge_provider="fake",
        )
        good_path = Path(tmpdir) / "good" / f"evaluation_result_{eval_spec.id}.json"
        good_result = json.loads(good_path.read_text(encoding="utf-8"))
        # bad path
        _run_core_flow(
            tools=tools,
            evals=[eval_spec],
            out=Path(tmpdir) / "bad",
            mock_path="bad",
            judge_provider="fake",
        )
        bad_path = Path(tmpdir) / "bad" / f"evaluation_result_{eval_spec.id}.json"
        bad_result = json.loads(bad_path.read_text(encoding="utf-8"))
        assert good_result["passed"] is True, "good path 应为 passed"
        assert bad_result["passed"] is False, "bad path 应为 failed"
        # 两者都有 JudgeFinding
        good_categories = [f.get("category") for f in good_result["findings"]]
        bad_categories = [f.get("category") for f in bad_result["findings"]]
        assert "judge" in good_categories
        assert "judge" in bad_categories


# ---------------------------------------------------------------------------
# 4. 无 --judge-provider fake 时不含 JudgeFinding
# ---------------------------------------------------------------------------


def test_core_flow_without_fake_judge_provider_no_judge_finding():
    """不传 judge_provider 时 evaluation_result.json 不含 JudgeFinding。"""
    from agent_tool_harness.cli import _run_core_flow

    tools, evals = _load_knowledge_search_fixtures()
    eval_spec = evals[0]
    with tempfile.TemporaryDirectory() as tmpdir:
        _run_core_flow(
            tools=tools,
            evals=[eval_spec],
            out=tmpdir,
            mock_path="good",
            judge_provider=None,
        )
        eval_json = json.loads(
            Path(tmpdir, f"evaluation_result_{eval_spec.id}.json").read_text(encoding="utf-8")
        )
        categories = [f.get("category") for f in eval_json.get("findings", [])]
        assert "judge" not in categories, "不应包含 JudgeFinding"


# ---------------------------------------------------------------------------
# 5. REVIEW_DECISION_NOT_GENERATED.txt 仍然存在
# ---------------------------------------------------------------------------


def test_review_decision_not_generated_txt_present():
    """REVIEW_DECISION_NOT_GENERATED.txt 仍然写入。"""
    from agent_tool_harness.cli import _run_core_flow

    tools, evals = _load_knowledge_search_fixtures()
    with tempfile.TemporaryDirectory() as tmpdir:
        _run_core_flow(
            tools=tools,
            evals=evals[:1],
            out=tmpdir,
            mock_path="good",
            judge_provider="fake",
        )
        txt_path = Path(tmpdir) / "REVIEW_DECISION_NOT_GENERATED.txt"
        assert txt_path.exists(), "应写入 REVIEW_DECISION_NOT_GENERATED.txt"


# ---------------------------------------------------------------------------
# 6. FakeJudgeProvider 不读 .env / os.environ
# ---------------------------------------------------------------------------


def test_fake_judge_provider_no_env():
    """FakeJudgeProvider 通过 _run_core_flow 运行时仍然不读 os.environ。"""
    from agent_tool_harness.fake_judge import FakeJudgeProvider

    p = FakeJudgeProvider()
    assert p.name == "fake"
    assert p.mode == "fake"

    from agent_tool_harness.core_contract import Evidence, ExecutionTrace

    trace = ExecutionTrace(
        scenario_id="s1",
        tool_calls=[],
        tool_results=[],
        final_answer="test",
    )
    evidence = Evidence(trace=trace, signal_quality="fake")
    findings = p.evaluate(evidence)
    assert isinstance(findings, list)
    assert len(findings) >= 1
    for f in findings:
        assert isinstance(f, JudgeFinding)


# ---------------------------------------------------------------------------
# 7. --core-flow 不含 --judge-provider 时正常运行（向后兼容）
# ---------------------------------------------------------------------------


def test_core_flow_without_judge_provider_still_works():
    """--core-flow 不传 --judge-provider 时仍正常运行（向后兼容）。"""
    from agent_tool_harness.cli import _run_core_flow

    tools, evals = _load_knowledge_search_fixtures()
    with tempfile.TemporaryDirectory() as tmpdir:
        exit_code = _run_core_flow(
            tools=tools,
            evals=evals[:1],
            out=tmpdir,
            mock_path="good",
        )
        assert exit_code == 0
        # 确认 artifacts 写入
        assert (Path(tmpdir) / "report.md").exists()
        assert (Path(tmpdir) / "metrics.json").exists()
