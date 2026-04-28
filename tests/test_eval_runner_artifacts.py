import json

from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.config.loader import load_evals, load_project, load_tools
from agent_tool_harness.runner.eval_runner import EvalRunner


def test_eval_runner_good_and_bad_paths_generate_required_artifacts(tmp_path):
    project = load_project("examples/runtime_debug/project.yaml")
    tools = load_tools("examples/runtime_debug/tools.yaml")
    evals = load_evals("examples/runtime_debug/evals.yaml")

    good = EvalRunner().run(project, tools, evals, MockReplayAdapter("good"), tmp_path / "good")
    bad = EvalRunner().run(project, tools, evals, MockReplayAdapter("bad"), tmp_path / "bad")

    for run_name, result in {"good": good, "bad": bad}.items():
        out_dir = tmp_path / run_name
        for artifact in EvalRunner.REQUIRED_ARTIFACTS:
            path = out_dir / artifact
            assert path.exists(), f"missing {artifact}"
            assert path.stat().st_size > 0, f"empty {artifact}"
        assert result["metrics"]["executed_evals"] == 1

    good_judge = json.loads((tmp_path / "good" / "judge_results.json").read_text())
    bad_judge = json.loads((tmp_path / "bad" / "judge_results.json").read_text())
    bad_diagnosis = json.loads((tmp_path / "bad" / "diagnosis.json").read_text())

    assert good_judge["results"][0]["passed"] is True
    assert bad_judge["results"][0]["passed"] is False
    assert bad_diagnosis["results"][0]["first_tool"] == "tui_inspect_snapshot"
    assert bad_diagnosis["results"][0]["missing_required_tools"]

    # v0.2 第三轮：runner 必须把 TraceSignalAnalyzer 输出落到每条 diagnosis 的
    # ``tool_use_signals`` 字段；bad path 上 tui_inspect_snapshot 的
    # when_not_to_use 与 user_prompt 至少命中两个关键词，应触发
    # ``tool_selected_in_when_not_to_use_context``。这条断言钉死 runner 与
    # analyzer 的集成不会被未来重构悄悄断开。good path 不应触发任何 signal——
    # 反向断言保证 analyzer 没有退化为"任何 run 都报"的噪声源。
    good_diagnosis = json.loads((tmp_path / "good" / "diagnosis.json").read_text())
    assert "tool_use_signals" in good_diagnosis["results"][0]
    assert good_diagnosis["results"][0]["tool_use_signals"] == []

    bad_signals = bad_diagnosis["results"][0]["tool_use_signals"]
    assert isinstance(bad_signals, list) and bad_signals
    bad_signal_types = {s["signal_type"] for s in bad_signals}
    assert "tool_selected_in_when_not_to_use_context" in bad_signal_types
