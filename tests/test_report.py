from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.config.loader import load_evals, load_project, load_tools
from agent_tool_harness.reports.markdown_report import MarkdownReport
from agent_tool_harness.runner.eval_runner import EvalRunner


def test_report_contains_required_sections(tmp_path):
    EvalRunner().run(
        load_project("examples/runtime_debug/project.yaml"),
        load_tools("examples/runtime_debug/tools.yaml"),
        load_evals("examples/runtime_debug/evals.yaml"),
        MockReplayAdapter("good"),
        tmp_path,
    )

    report = (tmp_path / "report.md").read_text(encoding="utf-8")

    assert "Tool Design Audit" in report
    assert "Eval Quality Audit" in report
    assert "Agent Tool-Use Eval" in report
    assert "Transcript-derived Diagnosis" in report
    assert "Improvement Suggestions" in report


def test_report_good_path_shows_per_eval_details_and_caveats(tmp_path):
    """good path 报告必须包含可行动信息：

    - Methodology Caveats 段提醒读者 RuleJudge / MockReplayAdapter / Tool Design Audit 的边界；
    - Per-Eval Details 段把每条 eval 单独展开；
    - 实际 tool sequence 出现，避免读者只看 PASS 不看证据；
    - required tools 显示 OK 状态。
    """

    EvalRunner().run(
        load_project("examples/runtime_debug/project.yaml"),
        load_tools("examples/runtime_debug/tools.yaml"),
        load_evals("examples/runtime_debug/evals.yaml"),
        MockReplayAdapter("good"),
        tmp_path,
    )
    report = (tmp_path / "report.md").read_text(encoding="utf-8")

    assert "## Methodology Caveats" in report
    assert "RuleJudge" in report
    assert "MockReplayAdapter" in report
    assert "Tool Design Audit 当前只做 structural" in report
    assert "## Per-Eval Details" in report
    assert "runtime_input_boundary_regression — PASS" in report
    assert "runtime_trace_event_chain" in report
    assert "Tool sequence:" in report
    assert "Required tools:" in report
    assert "OK" in report
    assert "ARTIFACTS.md" in report


def test_report_bad_path_surfaces_missing_required_and_forbidden_first(tmp_path):
    """bad path 报告必须把失败现场说清楚：

    - status 为 FAIL；
    - tool sequence 显式出现错误的首个工具；
    - Required tools 行标 Missing 而不是 OK；
    - Forbidden first tool triggered 行明确给出触发信息；
    - Next steps 指引读者去 transcript / tool_calls / tool_responses 三件套排查。
    """

    EvalRunner().run(
        load_project("examples/runtime_debug/project.yaml"),
        load_tools("examples/runtime_debug/tools.yaml"),
        load_evals("examples/runtime_debug/evals.yaml"),
        MockReplayAdapter("bad"),
        tmp_path,
    )
    report = (tmp_path / "report.md").read_text(encoding="utf-8")

    assert "runtime_input_boundary_regression — FAIL" in report
    assert "tui_inspect_snapshot" in report
    assert "Forbidden first tool triggered" in report
    assert "Missing" in report
    assert "Next steps:" in report
    assert "transcript" in report.lower() or "tool_calls" in report


def test_report_renders_skipped_status_for_runner_skipped_eval():
    """直接调用 MarkdownReport 验证 SKIPPED 状态渲染。

    用 fake judge_results / diagnosis 模拟 runner 把 eval 判为不可运行后写入的伪规则
    (eval_not_runnable)。这样不依赖跑真实 evals，仅验证报告对 SKIPPED 的呈现。
    """

    judge_payload = {
        "results": [
            {
                "eval_id": "fake-eval",
                "passed": False,
                "checks": [
                    {
                        "rule": {"type": "eval_not_runnable"},
                        "passed": False,
                        "message": "EvalQualityAuditor marked this eval as not runnable.",
                    }
                ],
            }
        ]
    }
    diag_payload = {
        "results": [
            {
                "eval_id": "fake-eval",
                "passed": False,
                "tool_sequence": [],
                "missing_required_tools": [],
                "issues": [],
                "summary": "skipped",
            }
        ]
    }
    report = MarkdownReport().render(
        project={"name": "fake"},
        metrics={
            "total_evals": 1,
            "passed": 0,
            "failed": 0,
            "skipped_evals": 1,
            "error_evals": 0,
            "total_tool_calls": 0,
            "signal_quality": "tautological_replay",
            "signal_quality_note": "test",
        },
        audit_tools={"summary": {"tool_count": 0, "average_score": 0, "low_score_tools": []}},
        audit_evals={
            "summary": {"eval_count": 1, "average_score": 0, "not_runnable": ["fake-eval"]}
        },
        judge_results=judge_payload,
        diagnosis=diag_payload,
    )

    assert "fake-eval — SKIPPED" in report
    assert "Runtime / skipped reason" in report
    assert "audit_evals.json" in report


def test_report_renders_error_status_for_adapter_failure():
    """验证 adapter 抛异常路径在报告中显示为 ERROR 而不是 FAIL。

    用 fake judge_results 模拟 runner 在 adapter_execution_failed 路径塞入的伪规则。
    避免读者把链路异常误读为 Agent 工具选择失败。
    """

    judge_payload = {
        "results": [
            {
                "eval_id": "fake-eval",
                "passed": False,
                "checks": [
                    {
                        "rule": {"type": "adapter_execution_failed"},
                        "passed": False,
                        "message": "boom",
                    }
                ],
            }
        ]
    }
    diag_payload = {"results": [{"eval_id": "fake-eval", "passed": False, "tool_sequence": []}]}
    report = MarkdownReport().render(
        project={"name": "fake"},
        metrics={
            "total_evals": 1,
            "passed": 0,
            "failed": 1,
            "skipped_evals": 0,
            "error_evals": 1,
            "total_tool_calls": 0,
            "signal_quality": "tautological_replay",
            "signal_quality_note": "test",
        },
        audit_tools={"summary": {"tool_count": 0, "average_score": 0, "low_score_tools": []}},
        audit_evals={"summary": {"eval_count": 1, "average_score": 0, "not_runnable": []}},
        judge_results=judge_payload,
        diagnosis=diag_payload,
    )

    assert "fake-eval — ERROR" in report
    assert "Runtime / skipped reason" in report
    assert "runner_error" in report


# ---------------------------------------------------------------------------
# render_from_core — Core Flow 报告渲染
# ---------------------------------------------------------------------------


def test_render_from_core_produces_valid_markdown():
    """render_from_core() 产出有效的 Markdown 报告。"""
    results = [
        {
            "eval_id": "test-eval-1",
            "passed": True,
            "findings": [
                {
                    "rule_type": "must_call_tool",
                    "rule_passed": True,
                    "message": "must call tool: kb.search.search_articles",
                }
            ],
            "summary": "all good",
        }
    ]
    report_summary = {
        "total_scenarios": 1,
        "passed": 1,
        "failed": 0,
        "errors": 0,
        "generated_at": "2025-01-01T00:00:00Z",
    }
    report = MarkdownReport().render_from_core(
        results=results,
        report_summary=report_summary,
        signal_quality="tautological_replay",
    )

    assert "Agent Tool Harness Report (Core Flow)" in report
    assert "## Signal Quality" in report
    assert "## Methodology Caveats" in report
    assert "## Agent Tool-Use Eval (Core Flow)" in report
    assert "## Per-Eval Details" in report
    assert "## Review Decision" in report
    assert "## Artifacts" in report
    assert "test-eval-1: PASS" in report
    assert "tautological_replay" in report


def test_render_from_core_no_review_decision():
    """render_from_core() 不自动生成 ReviewDecision。"""
    report = MarkdownReport().render_from_core(
        results=[],
        report_summary={
            "total_scenarios": 0,
            "passed": 0,
            "failed": 0,
            "errors": 0,
            "generated_at": "",
        },
        signal_quality="tautological_replay",
    )

    assert "ReviewDecision 未生成" in report
    assert "机器评分" in report
    assert "人工审核结论" in report
    # 不应生成 Decision: approved / Decision: needs_revision 等裁决行
    assert "Decision:" not in report


def test_render_from_core_shows_failed_finding():
    """render_from_core() 正确展示 FAIL 的 finding。"""
    results = [
        {
            "eval_id": "fail-eval",
            "passed": False,
            "findings": [
                {
                    "rule_type": "evidence_from_required_tools",
                    "rule_passed": False,
                    "message": "cited evidence only from non-required tools",
                }
            ],
            "summary": "1/1 规则未通过",
        }
    ]
    report = MarkdownReport().render_from_core(
        results=results,
        report_summary={
            "total_scenarios": 1,
            "passed": 0,
            "failed": 1,
            "errors": 0,
            "generated_at": "",
        },
        signal_quality="tautological_replay",
    )

    assert "fail-eval: FAIL" in report
    assert "❌" in report
    assert "evidence_from_required_tools" in report
