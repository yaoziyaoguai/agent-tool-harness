"""TranscriptReplayAdapter 测试（v0.3 第一项）。

这些测试不是为了凑通过率，而是要钉死下面这些**真实风险**：
1. replay 必须**不调用** ``registry.execute`` —— 否则一旦工具有副作用或网络
   依赖，replay 就会污染历史；
2. 源 run 缺关键 JSONL 时必须 fail-fast，给出可行动错误，而不是写一份空 run；
3. 某条 eval 在源 run 中没记录时，必须 deterministic 走 FAIL 路径并写
   ``runner.replay_warning``，绝不能"看起来通过"；
4. signal_quality 必须是 ``recorded_trajectory``——否则 metrics/report 会把
   replay 误标成 mock 或真实 Agent；
5. replay 出来的 run 仍能被下游 EvalRunner / RuleJudge / TraceSignalAnalyzer
   消费，证明 adapter 的写入协议与 MockReplayAdapter 完全兼容；
6. CLI 友好错误：``replay-run`` 在源目录不存在时打印 hint，不抛 traceback。

所有 fixture 都是临时目录，绝不依赖 examples/ 真实 runs。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.agents.transcript_replay_adapter import (
    TranscriptReplayAdapter,
    TranscriptReplaySourceError,
)
from agent_tool_harness.cli import main
from agent_tool_harness.config.loader import load_evals, load_project, load_tools
from agent_tool_harness.runner.eval_runner import EvalRunner
from agent_tool_harness.signal_quality import RECORDED_TRAJECTORY


def _make_source_run(tmp_path: Path, mock_path: str) -> Path:
    """先用 MockReplayAdapter 跑一次 examples/runtime_debug，得到一份"录像带"。

    这是测试的标准 fixture：用 mock 跑出 9 个 artifact 的源 run 目录，
    后续 replay 测试都从这里读。
    """
    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")
    evals = load_evals("examples/runtime_debug/evals.yaml")
    out = tmp_path / f"source_{mock_path}"
    EvalRunner().run(project, tools, evals, MockReplayAdapter(mock_path), out)
    return out


def test_replay_constructor_fails_fast_when_source_missing(tmp_path):
    """源目录不存在 → 必须立刻抛 TranscriptReplaySourceError。

    模拟边界：用户拼错路径或源 run 还没生成。绝不允许静默继续到 EvalRunner。
    """
    with pytest.raises(TranscriptReplaySourceError):
        TranscriptReplayAdapter(tmp_path / "does_not_exist")


def test_replay_constructor_fails_fast_when_source_has_no_artifacts(tmp_path):
    """源目录存在但里面没有任何 tool_calls/tool_responses → fail-fast。

    模拟边界：用户传错目录（例如指向 docs/ 或一份空 runs 子目录）。
    """
    empty = tmp_path / "empty_run"
    empty.mkdir()
    with pytest.raises(TranscriptReplaySourceError):
        TranscriptReplayAdapter(empty)


def test_replay_signal_quality_is_recorded_trajectory():
    """SIGNAL_QUALITY 必须是 RECORDED_TRAJECTORY，而不是 mock 或 real_agent。

    这条断言钉死信号披露契约，避免未来重构时静默把 replay 误标成
    ``REAL_AGENT``——那会让真实团队把"复刻 PASS"误读成"模型/工具好用"。
    """
    assert TranscriptReplayAdapter.SIGNAL_QUALITY == RECORDED_TRAJECTORY


def test_replay_does_not_call_registry_execute(tmp_path, monkeypatch):
    """replay 必须**不调用** registry.execute；工具响应来自源历史。

    这是 v0.3 第一项最重要的边界：replay = 只读重放，不重新执行工具。
    用 monkeypatch 让 ToolRegistry.execute 一旦被调用就直接抛错，replay
    跑完整条 eval 都不应触发它。
    """
    source = _make_source_run(tmp_path, "good")

    from agent_tool_harness.tools import registry as registry_module

    def _fail_execute(self, name, arguments):  # noqa: ARG001
        raise AssertionError(
            "TranscriptReplayAdapter must NOT call registry.execute; "
            f"got call to {name!r}"
        )

    monkeypatch.setattr(
        registry_module.ToolRegistry, "execute", _fail_execute
    )

    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")
    evals = load_evals("examples/runtime_debug/evals.yaml")
    out = tmp_path / "replayed"
    EvalRunner().run(project, tools, evals, TranscriptReplayAdapter(source), out)


def test_replay_reproduces_good_path_artifacts(tmp_path):
    """完整 replay 一份 good run，新 run 应该有 9 个 artifact 且 judge 通过。

    钉死"replay 输出与 MockReplay 输出在结构上等价"。
    """
    source = _make_source_run(tmp_path, "good")

    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")
    evals = load_evals("examples/runtime_debug/evals.yaml")
    out = tmp_path / "replayed_good"
    result = EvalRunner().run(project, tools, evals, TranscriptReplayAdapter(source), out)

    for artifact in EvalRunner.REQUIRED_ARTIFACTS:
        assert (out / artifact).exists(), f"missing {artifact}"

    metrics = result["metrics"]
    assert metrics["signal_quality"] == RECORDED_TRAJECTORY
    judge = json.loads((out / "judge_results.json").read_text())
    assert judge["results"][0]["passed"] is True

    transcript = (out / "transcript.jsonl").read_text()
    assert "runner.replay_summary" in transcript
    assert "replayed_from" in transcript


def test_replay_bad_path_preserves_failure_evidence(tmp_path):
    """replay 一份 bad run，失败应该被忠实复刻：

    - judge FAIL；
    - diagnosis 仍有 ``missing_required_tools`` / ``first_tool``；
    - TraceSignalAnalyzer 仍能从复刻出来的 tool_calls 派生
      ``tool_selected_in_when_not_to_use_context`` 信号。

    这条测试钉住"replay 输出能继续被下游派生分析消费"——这是 adapter 写入
    协议与 recorder 兼容性的根本契约。
    """
    source = _make_source_run(tmp_path, "bad")

    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")
    evals = load_evals("examples/runtime_debug/evals.yaml")
    out = tmp_path / "replayed_bad"
    EvalRunner().run(project, tools, evals, TranscriptReplayAdapter(source), out)

    judge = json.loads((out / "judge_results.json").read_text())
    diagnosis = json.loads((out / "diagnosis.json").read_text())

    assert judge["results"][0]["passed"] is False
    assert diagnosis["results"][0]["missing_required_tools"]
    bad_signal_types = {s["signal_type"] for s in diagnosis["results"][0]["tool_use_signals"]}
    assert "tool_selected_in_when_not_to_use_context" in bad_signal_types


def test_replay_missing_eval_records_warning(tmp_path):
    """源 run 没覆盖某条 eval 时，必须写 runner.replay_warning + 走 FAIL。

    模拟边界：用户用 evals.yaml v2（多了一条新 eval）去 replay 旧 run。
    新 eval 在源里找不到记录时，绝不允许 adapter 凭空伪造 PASS。
    """
    # 先用 good 跑出源 run
    source = _make_source_run(tmp_path, "good")

    # 构造一份 evals.yaml：在原 evals 基础上新增一条不在源 run 里的 eval
    original_evals = (Path("examples/runtime_debug/evals.yaml")).read_text()
    extra_eval = """  - id: never_replayed_eval
    description: only exists to expose missing source records
    user_prompt: dummy
    initial_context:
      pid: 999
    expected_tool_behavior:
      required_tools: [tui_query_events]
    verifiable_outcome:
      expected_root_cause: dummy
      evidence_ids: []
    judge:
      rules: []
    runnable: true
"""
    evals_with_gap = tmp_path / "evals_with_gap.yaml"
    # 原文件以 ``evals:`` 为顶层 key + 列表项缩进 2；新增条目直接追加到列表尾即可。
    evals_with_gap.write_text(original_evals.rstrip() + "\n" + extra_eval)

    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")
    evals = load_evals(str(evals_with_gap))
    out = tmp_path / "replay_with_gap"
    EvalRunner().run(project, tools, evals, TranscriptReplayAdapter(source), out)

    transcript = (out / "transcript.jsonl").read_text()
    assert "runner.replay_warning" in transcript
    judge = json.loads((out / "judge_results.json").read_text())
    # 新增那条没有源记录的 eval 必须 FAIL
    new_eval_judge = next(r for r in judge["results"] if r["eval_id"] == "never_replayed_eval")
    assert new_eval_judge["passed"] is False


def test_replay_cli_actionable_error_when_source_missing(tmp_path, capsys):
    """CLI: replay-run 源目录不存在时退出码 2 并打印可行动 hint，不抛 traceback。

    模拟边界：用户拼错 --source-run 路径，是真实 onboarding 高频错误。
    """
    rc = main([
        "replay-run",
        "--source-run", str(tmp_path / "nope"),
        "--project", "examples/runtime_debug/project.yaml",
        "--tools", "examples/runtime_debug/tools.yaml",
        "--evals", "examples/runtime_debug/evals.yaml",
        "--out", str(tmp_path / "out"),
    ])
    captured = capsys.readouterr()
    assert rc == 2
    assert "replay source" in captured.err.lower() or "file not found" in captured.err.lower()


def test_replay_cli_full_smoke(tmp_path, capsys):
    """CLI smoke：先用 run 生成源，再用 replay-run 跑出新 9-artifact 目录。

    钉死 ``replay-run`` 这条 CLI 端到端可用，不靠内部 API。
    """
    source = _make_source_run(tmp_path, "good")
    out = tmp_path / "cli_replay_out"
    rc = main([
        "replay-run",
        "--source-run", str(source),
        "--project", "examples/runtime_debug/project.yaml",
        "--tools", "examples/runtime_debug/tools.yaml",
        "--evals", "examples/runtime_debug/evals.yaml",
        "--out", str(out),
    ])
    captured = capsys.readouterr()
    assert rc == 0
    for artifact in EvalRunner.REQUIRED_ARTIFACTS:
        assert (out / artifact).exists(), f"missing {artifact}"
    assert "recorded_trajectory" in captured.out


def test_replay_cli_accepts_run_alias(tmp_path, capsys):
    """CLI: replay-run 必须接受 ``--run`` 作为 ``--source-run`` 的别名。

    模拟边界：用户从 ``analyze-artifacts --run`` 复制粘贴到 ``replay-run``。
    历史上 replay-run 只暴露 ``--source-run``，造成 CLI 体验不一致；本断言钉死
    别名兼容，防止后续重构静默删别名（删别名不是 bug-fix，是契约破坏）。
    """
    source = _make_source_run(tmp_path, "good")
    out = tmp_path / "cli_alias_out"
    rc = main([
        "replay-run",
        "--run", str(source),
        "--project", "examples/runtime_debug/project.yaml",
        "--tools", "examples/runtime_debug/tools.yaml",
        "--evals", "examples/runtime_debug/evals.yaml",
        "--out", str(out),
    ])
    captured = capsys.readouterr()
    assert rc == 0
    assert "recorded_trajectory" in captured.out
