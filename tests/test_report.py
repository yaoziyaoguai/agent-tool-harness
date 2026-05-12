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


# ---------------------------------------------------------------------------
# render_from_core — judge_provider_kind 条件化 caveats
# ---------------------------------------------------------------------------


def test_judge_provider_kind_none_caveat_says_no_real_llm():
    """judge_provider_kind=none 时 caveat 声明不调用真实 LLM。"""
    report = MarkdownReport().render_from_core(
        results=[],
        report_summary=_empty_summary(),
        signal_quality="tautological_replay",
        judge_provider_kind="none",
    )
    assert "不调用真实 LLM" in report


def test_judge_provider_kind_fake_caveat_says_fake_judge():
    """judge_provider_kind=fake 时 caveat 说明使用 FakeJudgeProvider，不调用真实 LLM。"""
    report = MarkdownReport().render_from_core(
        results=[],
        report_summary=_empty_summary(),
        signal_quality="tautological_replay",
        judge_provider_kind="fake",
    )
    assert "FakeJudgeProvider" in report
    assert "不调用真实 LLM" in report


def test_judge_provider_kind_llm_caveat_says_real_llm_judge():
    """judge_provider_kind=llm 时 caveat 说明真实 LLM judge 已启用，JudgeFinding advisory only。"""
    report = MarkdownReport().render_from_core(
        results=[],
        report_summary=_empty_summary(),
        signal_quality="tautological_replay",
        judge_provider_kind="llm",
    )
    assert "opt-in 真实 LLM JudgeProvider" in report
    assert "JudgeFinding 为 advisory only" in report
    assert "不自动生成 ReviewDecision" in report
    # 不应出现 "不调用真实 LLM" 的错误声明
    assert "不调用真实 LLM" not in report


# ---------------------------------------------------------------------------
# render_from_core — JudgeFinding metadata 展示
# ---------------------------------------------------------------------------


def test_judge_finding_metadata_in_report():
    """JudgeFinding 的 provider/model/confidence/rationale 进入报告。"""
    results = [
        {
            "eval_id": "test-judge",
            "passed": True,
            "findings": [
                {
                    "finding_id": "j1",
                    "severity": "info",
                    "category": "judge",
                    "message": "tool selection was appropriate",
                    "evidence_ref": "judge_results.json",
                    "rule_type": "",
                    "rule_passed": None,
                    "provider": "openai-native",
                    "model": "gpt-4.1-mini",
                    "confidence": 0.85,
                    "rationale": "The agent correctly chose the search tool.",
                }
            ],
            "summary": "judge finding test",
        }
    ]
    report = MarkdownReport().render_from_core(
        results=results,
        report_summary=_empty_summary(),
        signal_quality="tautological_replay",
        judge_provider_kind="llm",
    )

    # provider/model 应出现
    assert "openai-native" in report
    assert "gpt-4.1-mini" in report
    # confidence 应展示
    assert "0.85" in report
    # rationale 应展示
    assert "The agent correctly chose the search tool." in report


def test_judge_finding_transport_error_not_rule_failure():
    """transport error JudgeFinding 不显示为 ✅/❌ 普通 rule failure。"""
    results = [
        {
            "eval_id": "transport-error-test",
            "passed": True,
            "findings": [
                {
                    "finding_id": "te1",
                    "severity": "info",
                    "category": "judge",
                    "message": "[openai-compatible] transport error: bad_response — bad_response",
                    "evidence_ref": "evidence.json",
                    "rule_type": "",
                    "rule_passed": None,
                    "provider": "openai-compatible",
                    "model": "deepseek-v3",
                }
            ],
            "summary": "transport error test",
        }
    ]
    report = MarkdownReport().render_from_core(
        results=results,
        report_summary=_empty_summary(),
        signal_quality="tautological_replay",
        judge_provider_kind="llm",
    )

    # transport error 不应显示为 ✅/❌
    assert "✅" not in report
    assert "❌" not in report
    # 应有 transport error 特定标签
    assert "transport/parsing error" in report


def test_rule_finding_unaffected_by_judge_metadata():
    """RuleFinding 不受 JudgeFinding metadata 逻辑影响，仍显示 ✅/❌。"""
    results = [
        {
            "eval_id": "rule-only",
            "passed": True,
            "findings": [
                {
                    "finding_id": "r1",
                    "severity": "info",
                    "category": "rule",
                    "message": "must call tool: kb.search.search_articles",
                    "evidence_ref": "judge_results.json",
                    "rule_type": "must_call_tool",
                    "rule_passed": True,
                }
            ],
            "summary": "rule only",
        }
    ]
    report = MarkdownReport().render_from_core(
        results=results,
        report_summary=_empty_summary(),
        signal_quality="tautological_replay",
        judge_provider_kind="none",
    )

    # RuleFinding 用 ✅ 表示通过
    assert "✅" in report
    assert "must_call_tool" in report
    # 不应有 judge-specific 标签
    assert "advisory" not in report


# ---------------------------------------------------------------------------
# core_report_bridge — JudgeFinding metadata 透传
# ---------------------------------------------------------------------------


def test_evaluation_result_to_report_dict_includes_judge_metadata():
    """evaluation_result_to_report_dict 透传 JudgeFinding 特有字段。"""
    from agent_tool_harness.core_contract import (
        EvaluationResult,
        JudgeFinding,
    )
    from agent_tool_harness.core_report_bridge import (
        evaluation_result_to_report_dict,
    )

    jf = JudgeFinding(
        finding_id="j1",
        severity="info",
        category="judge",
        message="advisory finding",
        evidence_ref="ref",
        provider="openai-native",
        model="gpt-4",
        confidence=0.9,
        rubric="scoring rubric text",
        rationale="rationale text",
        usage={"prompt_tokens": 100, "completion_tokens": 50},
    )
    result = EvaluationResult(
        scenario_id="test",
        findings=[jf],
        passed=True,
        summary="all good",
    )

    d = evaluation_result_to_report_dict(result)
    f = d["findings"][0]
    assert f["provider"] == "openai-native"
    assert f["model"] == "gpt-4"
    assert f["confidence"] == 0.9
    assert f["rubric"] == "scoring rubric text"
    assert f["rationale"] == "rationale text"
    assert f["usage"] == {"prompt_tokens": 100, "completion_tokens": 50}


def test_evaluation_result_to_report_dict_rule_finding_no_judge_fields():
    """RuleFinding 不受 JudgeFinding metadata 逻辑影响。"""
    from agent_tool_harness.core_contract import (
        EvaluationResult,
        RuleFinding,
    )
    from agent_tool_harness.core_report_bridge import (
        evaluation_result_to_report_dict,
    )

    rf = RuleFinding(
        finding_id="r1",
        severity="info",
        category="rule",
        message="must call tool",
        evidence_ref="ref",
        rule_type="must_call_tool",
        rule_passed=True,
    )
    result = EvaluationResult(
        scenario_id="test",
        findings=[rf],
        passed=True,
        summary="ok",
    )

    d = evaluation_result_to_report_dict(result)
    f = d["findings"][0]
    # RuleFinding 不应包含 JudgeFinding 特有字段
    assert "provider" not in f
    assert "model" not in f
    assert "confidence" not in f


def test_evaluation_result_passed_not_affected_by_judge_finding():
    """EvaluationResult.passed 不受 JudgeFinding 影响。"""
    from agent_tool_harness.core_contract import (
        EvaluationResult,
        JudgeFinding,
    )
    from agent_tool_harness.core_report_bridge import (
        evaluation_result_to_report_dict,
    )

    jf = JudgeFinding(
        finding_id="j1",
        severity="high",
        category="judge",
        message="LLM thinks this is bad",
        evidence_ref="ref",
        provider="openai-native",
        model="gpt-4",
        confidence=0.95,
        rationale="bad tool choice",
    )
    # passed 明确设为 True，即使 JudgeFinding severity=high
    result = EvaluationResult(
        scenario_id="test",
        findings=[jf],
        passed=True,
        summary="jury still out",
    )
    assert result.passed is True

    d = evaluation_result_to_report_dict(result)
    assert d["passed"] is True


def test_report_dict_does_not_contain_api_key():
    """evaluation_result_to_report_dict 不包含 api_key 字段。"""
    from agent_tool_harness.core_contract import (
        EvaluationResult,
        JudgeFinding,
    )
    from agent_tool_harness.core_report_bridge import (
        evaluation_result_to_report_dict,
    )

    jf = JudgeFinding(
        finding_id="j1",
        severity="info",
        category="judge",
        message="ok",
        evidence_ref="ref",
        provider="openai-native",
        model="gpt-4",
    )
    result = EvaluationResult(
        scenario_id="test",
        findings=[jf],
        passed=True,
        summary="ok",
    )

    d = evaluation_result_to_report_dict(result)
    _assert_no_api_key(d)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _empty_summary():
    return {
        "total_scenarios": 0,
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "generated_at": "",
    }


def _assert_no_api_key(obj):
    """递归检查 dict/list/str 中不含明显 api key。"""
    if isinstance(obj, dict):
        for k, v in obj.items():
            assert "api_key" not in k.lower(), f"api_key-like key: {k}"
            _assert_no_api_key(v)
    elif isinstance(obj, list):
        for item in obj:
            _assert_no_api_key(item)
    elif isinstance(obj, str):
        assert "sk-" not in obj.lower() or "sk-" not in obj, (
            f"potential key leak: {obj[:50]}"
        )
