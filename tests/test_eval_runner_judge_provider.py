"""EvalRunner × JudgeProvider 集成测试（v1.1 第二轮）。

测试纪律说明
============
本文件钉死的边界（任何回归都会立即失败）：

1. **默认行为不变**：未注入 dry-run provider 时，
   ``judge_results.json`` **不**含 ``dry_run_provider`` 字段——v1.0
   消费者完全字节兼容；
2. **dry-run 不覆盖 deterministic**：即便 RecordedJudgeProvider 的
   recording 全部 PASS，``results[].passed`` 仍由 RuleJudge 决定——
   绝不允许 advisory provider 假成功；
3. **缺 recording 必须可见**：RecordedJudgeProvider 没有对应 eval_id 时，
   ``dry_run_provider.results[]`` 中那条 entry 必须含 ``error`` 字段，
   读者一眼能看到，绝不静默；
4. **report 必须显示 advisory disclaimer**：``report.md`` 在
   ``## Dry-run JudgeProvider (advisory only)`` 段必须显式写明
   "DO NOT change deterministic pass/fail"；
5. **CLI 缺 --judge-recording 必须报可行动错**：而**不**是悄悄走默认路径
   或抛 traceback。

mock/fixture 边界
================
本文件不联网、不调真实 LLM，全部用 in-process 字典 / tmp_path 写小 yaml
fixture；与 v1.0 deterministic baseline 测试在同一个进程里跑，确保
"v1.0 测试不退化"也能在 CI 里同时验证。
"""

from __future__ import annotations

import json

from agent_tool_harness.cli import main as cli_main

EXAMPLE_PROJECT = "examples/runtime_debug/project.yaml"
EXAMPLE_TOOLS = "examples/runtime_debug/tools.yaml"
EXAMPLE_EVALS = "examples/runtime_debug/evals.yaml"


def _run_cli(args: list[str], capsys) -> int:
    """调 CLI main 并返回 exit code，便于断言可行动错误路径。

    ``capsys`` 让 stderr 内容可被测试断言——这是钉死"错误信息必须告诉
    用户怎么修"的关键工具。
    """

    return cli_main(args)


def test_default_runner_writes_no_dry_run_provider_field(tmp_path):
    """钉死：未注入 dry-run provider 时，judge_results.json 与 v1.0 字节兼容。

    防回归：未来若有人把 ``dry_run_provider`` 字段写成"始终存在"，
    本测试立即失败——v1.0 下游消费者依赖该字段缺省。
    """

    out = tmp_path / "default_run"
    rc = _run_cli(
        [
            "run",
            "--project", EXAMPLE_PROJECT,
            "--tools", EXAMPLE_TOOLS,
            "--evals", EXAMPLE_EVALS,
            "--out", str(out),
            "--mock-path", "bad",
        ],
        None,
    )
    assert rc == 0
    judge = json.loads((out / "judge_results.json").read_text(encoding="utf-8"))
    assert "results" in judge
    assert "dry_run_provider" not in judge


def test_recorded_provider_does_not_override_deterministic_fail(tmp_path):
    """钉死：即使 recording 写 passed=True，deterministic FAIL 仍然 FAIL。

    bad path 在 v1.0 deterministic 下必 FAIL；这里 fixture 故意写 PASS+
    高 confidence，模拟"未来 LLM judge 想给 advisory PASS"的场景。
    contract：``results[].passed`` 仍来自 RuleJudge，``dry_run_provider``
    只多带 advisory 信息。
    """

    fixture = tmp_path / "rec.yaml"
    fixture.write_text(
        "judgments:\n"
        "  runtime_input_boundary_regression:\n"
        "    passed: true\n"
        "    rationale: 'mock LLM thinks the answer is fine'\n"
        "    confidence: 0.95\n"
        "    rubric: 'evidence-grounded'\n",
        encoding="utf-8",
    )
    out = tmp_path / "rec_run"
    rc = _run_cli(
        [
            "run",
            "--project", EXAMPLE_PROJECT,
            "--tools", EXAMPLE_TOOLS,
            "--evals", EXAMPLE_EVALS,
            "--out", str(out),
            "--mock-path", "bad",
            "--judge-provider", "recorded",
            "--judge-recording", str(fixture),
        ],
        None,
    )
    assert rc == 0
    judge = json.loads((out / "judge_results.json").read_text(encoding="utf-8"))
    # deterministic 仍 FAIL：这是 ground truth。
    assert all(r["passed"] is False for r in judge["results"]), judge["results"]
    # dry_run_provider 段必须存在且记录 advisory PASS + agrees=False。
    assert "dry_run_provider" in judge
    entries = judge["dry_run_provider"]["results"]
    assert entries, "dry_run_provider.results must not be empty when fixture matches"
    e = entries[0]
    assert e["provider"] == "recorded"
    assert e["mode"] == "dry_run"
    assert e["passed"] is True
    assert e["deterministic_passed"] is False
    assert e["agrees_with_deterministic"] is False
    assert e["rationale"] == "mock LLM thinks the answer is fine"
    assert e["confidence"] == 0.95
    # report.md 必须显示 advisory disclaimer。
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "Dry-run JudgeProvider (advisory only)" in report
    assert "DO NOT change deterministic pass/fail" in report


def test_recorded_provider_records_missing_recording_as_error(tmp_path):
    """钉死：recording 缺失 → entry.error 必现，绝不静默 PASS。

    fixture 故意只给一个不相关的 eval_id；真实 eval runtime_input_boundary_regression 会触发
    MissingRecordingError，被 EvalRunner 捕获写进 dry_run_provider 段。
    deterministic baseline 不受影响。
    """

    fixture = tmp_path / "rec.yaml"
    fixture.write_text(
        "judgments:\n"
        "  some-other-eval:\n"
        "    passed: true\n",
        encoding="utf-8",
    )
    out = tmp_path / "miss_run"
    rc = _run_cli(
        [
            "run",
            "--project", EXAMPLE_PROJECT,
            "--tools", EXAMPLE_TOOLS,
            "--evals", EXAMPLE_EVALS,
            "--out", str(out),
            "--mock-path", "bad",
            "--judge-provider", "recorded",
            "--judge-recording", str(fixture),
        ],
        None,
    )
    assert rc == 0
    judge = json.loads((out / "judge_results.json").read_text(encoding="utf-8"))
    entries = judge["dry_run_provider"]["results"]
    assert entries
    e = entries[0]
    assert "error" in e
    assert e["error"]["type"] == "missing_recording"
    # passed 字段不应被 fabricate 出来
    assert "passed" not in e
    # deterministic FAIL 仍是 ground truth
    assert all(r["passed"] is False for r in judge["results"])


def test_cli_recorded_without_recording_path_returns_actionable_error(capsys):
    """钉死：``--judge-provider recorded`` 缺 ``--judge-recording`` 必须 exit 2 + 可行动 hint。

    防止：未来有人为了"少打一个参数"在 CLI 里加 silent default 路径。
    """

    rc = _run_cli(
        [
            "run",
            "--project", EXAMPLE_PROJECT,
            "--tools", EXAMPLE_TOOLS,
            "--evals", EXAMPLE_EVALS,
            "--out", "/tmp/should-not-be-created",
            "--mock-path", "bad",
            "--judge-provider", "recorded",
        ],
        capsys,
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "--judge-recording" in err
    assert "judgments" in err  # hint 提到 fixture 顶层字段


def test_cli_recorded_with_missing_fixture_file_returns_actionable_error(capsys):
    """钉死：fixture 文件不存在 → exit 2，绝不抛 traceback 或当 0 PASS 处理。"""

    rc = _run_cli(
        [
            "run",
            "--project", EXAMPLE_PROJECT,
            "--tools", EXAMPLE_TOOLS,
            "--evals", EXAMPLE_EVALS,
            "--out", "/tmp/should-not-be-created",
            "--mock-path", "bad",
            "--judge-provider", "recorded",
            "--judge-recording", "/nonexistent/recording.yaml",
        ],
        capsys,
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "judge recording fixture not found" in err


def test_cli_recorded_with_malformed_fixture_returns_actionable_error(tmp_path, capsys):
    """钉死：fixture 缺 ``judgments`` 顶层字段 → exit 2 + 指向 schema 文档。"""

    fixture = tmp_path / "bad.json"
    fixture.write_text(json.dumps({"not_judgments": {}}), encoding="utf-8")
    rc = _run_cli(
        [
            "run",
            "--project", EXAMPLE_PROJECT,
            "--tools", EXAMPLE_TOOLS,
            "--evals", EXAMPLE_EVALS,
            "--out", "/tmp/should-not-be-created",
            "--mock-path", "bad",
            "--judge-provider", "recorded",
            "--judge-recording", str(fixture),
        ],
        capsys,
    )
    assert rc == 2
    err = capsys.readouterr().err
    assert "judgments" in err
