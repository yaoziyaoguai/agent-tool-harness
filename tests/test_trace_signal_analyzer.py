"""TraceSignalAnalyzer (v0.2 第三轮) 防回归测试。

为什么单独成文件：
- 这一组测试钉的是"trace-derived deterministic 信号"——即直接从
  raw ``tool_calls.jsonl`` / ``tool_responses.jsonl`` payload + ToolSpec
  契约复盘出来的可疑模式，与 ``test_eval_runner_artifacts`` 的端到端
  行为契约和 ``test_failure_attribution`` 的 rule-derived finding 测试
  正交。
- 任何一类 signal 的字段契约（``signal_type`` / ``severity`` /
  ``evidence_refs`` / ``related_tool`` / ``related_eval`` /
  ``why_it_matters`` / ``suggested_fix``）一旦被悄悄改名或删除，下游
  ``report.md`` / 远程 dashboard / CI bot 都会立刻失能；本文件覆盖每一
  类 signal 的最小正/反向断言。

fake/mock 边界：
- 本文件**不**调用 EvalRunner / Adapter / Judge——它直接构造最小
  ToolSpec 与最小 tool_calls / tool_responses dict，专测 analyzer 本身。
  这样既能 deterministic 触发每一类 signal，也避免依赖 demo 业务实现。
- 反向断言（"合法场景不应触发"）和正向断言一样多——确保阈值调整时
  能立刻发现误伤。

测试纪律：
- 不允许通过提高阈值或弱化 ``why_it_matters`` 文案让失败测试通过；
  必须通过修改 analyzer 的判定逻辑或 ToolSpec 真实契约。
- 不允许把"signal 触发数 ≥ X"改成 "≥ 0"——这会让 analyzer 整个失能
  也不被发现。
"""

from __future__ import annotations

from typing import Any

from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.diagnose.trace_signal_analyzer import (
    TraceSignalAnalyzer,
    analyze_run_dir,
)

# ---------------------------------------------------------------------------
# 工厂：最小 ToolSpec / call / response。命名要保持工具感（不是 demo 业务），
# 不允许把 runtime_debug / knowledge_search 业务符号泄漏进来。
# ---------------------------------------------------------------------------


def _spec(
    *,
    name: str = "alpha_lookup",
    when_not_to_use: str = "Do not use for unrelated lookups.",
    output_contract: dict[str, Any] | None = None,
    token_policy: dict[str, Any] | None = None,
) -> ToolSpec:
    """构造最小 ToolSpec，所有字段齐全但只针对一个变量做反例。"""

    return ToolSpec(
        name=name,
        namespace="alpha.tools",
        version="0.1",
        description=f"{name} tool used for trace signal analyzer testing.",
        when_to_use=f"Use {name} when the user provides the relevant id.",
        when_not_to_use=when_not_to_use,
        input_schema={
            "type": "object",
            "required": ["resource_id"],
            "properties": {"resource_id": {"type": "string"}},
        },
        output_contract=output_contract
        or {
            "required_fields": ["summary", "evidence", "next_action", "technical_id"],
        },
        token_policy=token_policy or {"max_output_tokens": 800},
        side_effects={"destructive": False, "open_world_access": False},
        executor={"type": "python", "module": "demo", "function": name},
    )


def _call(
    tool_name: str,
    *,
    call_id: str = "c1",
    eval_id: str = "e1",
    arguments: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "eval_id": eval_id,
        "tool_name": tool_name,
        "arguments": arguments or {"resource_id": "r-1"},
    }


def _response(
    tool_name: str,
    *,
    call_id: str = "c1",
    eval_id: str = "e1",
    content: dict[str, Any] | None = None,
    success: bool = True,
) -> dict[str, Any]:
    return {
        "call_id": call_id,
        "eval_id": eval_id,
        "tool_name": tool_name,
        "response": {
            "success": success,
            "content": content if content is not None else {},
            "error": None,
            "metadata": {},
        },
    }


def _make_analyzer(*tools: ToolSpec) -> TraceSignalAnalyzer:
    by_name: dict[str, ToolSpec] = {}
    for t in tools:
        by_name[t.name] = t
        by_name[t.qualified_name] = t
    return TraceSignalAnalyzer(by_name)


# ---------------------------------------------------------------------------
# 公共字段契约：每条 signal 都必须带这 7 个字段。
# 任何字段缺失都说明 analyzer 偷工减料，下游消费者会失能。
# ---------------------------------------------------------------------------

_REQUIRED_SIGNAL_FIELDS = {
    "signal_type",
    "severity",
    "evidence_refs",
    "related_tool",
    "related_eval",
    "why_it_matters",
    "suggested_fix",
}


def _assert_signal_contract(signal: dict[str, Any]) -> None:
    missing = _REQUIRED_SIGNAL_FIELDS - set(signal.keys())
    assert not missing, f"signal missing required fields: {missing}; got {signal}"
    assert signal["signal_type"], "signal_type must be non-empty"
    assert signal["severity"] in {"high", "medium", "info"}
    assert isinstance(signal["evidence_refs"], list) and signal["evidence_refs"]
    assert signal["related_eval"], "related_eval must be set"
    assert signal["why_it_matters"], "why_it_matters must be a learning explanation"
    assert signal["suggested_fix"], "suggested_fix must be actionable"


# ---------------------------------------------------------------------------
# 1) tool_result_no_evidence：契约声明返回 evidence，但响应里缺失/为空。
# ---------------------------------------------------------------------------


def test_signal_no_evidence_when_required_field_evidence_is_missing():
    """模拟工具实现 bug：output_contract 声明返回 evidence 但实际响应里没给。

    这是 v0.1 的一个真实漏洞——只看 RuleJudge 的 must_use_evidence 时，
    Agent 的 final_answer 没引用 evidence 就会 FAIL，但我们看不到"是不是
    工具根本没返回 evidence"。trace signal 把这一层证据放出来。
    """

    tool = _spec(name="alpha_lookup")
    analyzer = _make_analyzer(tool)
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="Look up resource r-1 details.",
        tool_calls=[_call("alpha_lookup")],
        tool_responses=[
            _response("alpha_lookup", content={"summary": "ok", "next_action": "ok"})
        ],
    )
    types = [s["signal_type"] for s in signals]
    assert "tool_result_no_evidence" in types
    no_ev = next(s for s in signals if s["signal_type"] == "tool_result_no_evidence")
    _assert_signal_contract(no_ev)
    assert no_ev["severity"] == "high"
    assert no_ev["related_tool"] == "alpha_lookup"


def test_signal_no_evidence_negative_when_evidence_present():
    """反例：evidence 字段存在且非空时不应触发。

    这条用来防止 analyzer 退化为"任何响应都报"的噪声源。如果误报，
    用户会很快忽略所有 signal——失去复盘价值。
    """

    tool = _spec(name="alpha_lookup")
    analyzer = _make_analyzer(tool)
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="Look up resource r-1 details.",
        tool_calls=[_call("alpha_lookup")],
        tool_responses=[
            _response(
                "alpha_lookup",
                content={
                    "summary": "ok",
                    "evidence": [{"id": "ev-1", "label": "found"}],
                    "next_action": "done",
                    "technical_id": "r-1",
                },
            )
        ],
    )
    assert "tool_result_no_evidence" not in [s["signal_type"] for s in signals]


def test_signal_no_evidence_when_evidence_is_empty_list():
    """反向技巧：用 ``"evidence": []`` 蒙混 contract 不应被放过。"""

    tool = _spec(name="alpha_lookup")
    analyzer = _make_analyzer(tool)
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="Look up resource r-1.",
        tool_calls=[_call("alpha_lookup")],
        tool_responses=[
            _response(
                "alpha_lookup",
                content={"summary": "ok", "evidence": [], "next_action": "done"},
            )
        ],
    )
    assert "tool_result_no_evidence" in [s["signal_type"] for s in signals]


# ---------------------------------------------------------------------------
# 2) tool_result_missing_next_action：契约要 next_action，响应没给。
# ---------------------------------------------------------------------------


def test_signal_missing_next_action_when_contract_requires_it():
    tool = _spec(name="alpha_lookup")
    analyzer = _make_analyzer(tool)
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="Look up r-1.",
        tool_calls=[_call("alpha_lookup")],
        tool_responses=[
            _response(
                "alpha_lookup",
                content={
                    "summary": "ok",
                    "evidence": [{"id": "ev-1"}],
                    "technical_id": "r-1",
                },
            )
        ],
    )
    types = [s["signal_type"] for s in signals]
    assert "tool_result_missing_next_action" in types
    sig = next(s for s in signals if s["signal_type"] == "tool_result_missing_next_action")
    _assert_signal_contract(sig)
    assert sig["severity"] == "medium"


def test_signal_missing_next_action_negative_when_contract_does_not_require_it():
    """反例：如果工具自己 contract 就没声明 next_action，缺失不应被报。

    这条钉死"signal 必须以契约为准"，不允许偷偷把"评估者认为应该有"
    硬编码进 analyzer。
    """

    tool = _spec(
        name="alpha_lookup",
        output_contract={"required_fields": ["summary", "technical_id"]},
    )
    analyzer = _make_analyzer(tool)
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="Look up r-1.",
        tool_calls=[_call("alpha_lookup")],
        tool_responses=[
            _response("alpha_lookup", content={"summary": "ok", "technical_id": "r-1"})
        ],
    )
    assert "tool_result_missing_next_action" not in [s["signal_type"] for s in signals]


# ---------------------------------------------------------------------------
# 3) large_or_truncated_tool_response_without_guidance：大响应/截断且无指引。
# ---------------------------------------------------------------------------


def test_signal_large_response_without_next_action_or_truncation_guidance():
    """模拟 dump 大量字段、又不给 next_action 的工具实现。

    这是 Anthropic 文章里"工具应有 token-aware 响应 + truncation guidance"
    原则的反例；本 signal 强制工具实现暴露这个问题。
    """

    tool = _spec(
        name="alpha_lookup",
        token_policy={"max_output_tokens": 800},  # 注意：无 truncation_guidance
        output_contract={"required_fields": ["summary"]},
    )
    analyzer = _make_analyzer(tool)
    huge_payload = {"summary": "x" * 3000}
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="Look up r-1.",
        tool_calls=[_call("alpha_lookup")],
        tool_responses=[_response("alpha_lookup", content=huge_payload)],
    )
    assert "large_or_truncated_tool_response_without_guidance" in [
        s["signal_type"] for s in signals
    ]


def test_signal_large_response_negative_when_token_policy_has_truncation_guidance():
    """反例：工具自己声明了 truncation_guidance 时，大响应不应被误报。"""

    tool = _spec(
        name="alpha_lookup",
        token_policy={
            "max_output_tokens": 800,
            "truncation_guidance": "Narrow by resource_id range.",
        },
        output_contract={"required_fields": ["summary"]},
    )
    analyzer = _make_analyzer(tool)
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="Look up r-1.",
        tool_calls=[_call("alpha_lookup")],
        tool_responses=[_response("alpha_lookup", content={"summary": "x" * 3000})],
    )
    assert "large_or_truncated_tool_response_without_guidance" not in [
        s["signal_type"] for s in signals
    ]


def test_signal_truncated_response_marker_triggers():
    """显式截断标记触发 signal——即使响应不大。"""

    tool = _spec(
        name="alpha_lookup",
        token_policy={"max_output_tokens": 800},
        output_contract={"required_fields": ["summary"]},
    )
    analyzer = _make_analyzer(tool)
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="Look up r-1.",
        tool_calls=[_call("alpha_lookup")],
        tool_responses=[
            _response(
                "alpha_lookup",
                content={"summary": "abc...(truncated)", "truncated": True},
            )
        ],
    )
    assert "large_or_truncated_tool_response_without_guidance" in [
        s["signal_type"] for s in signals
    ]


# ---------------------------------------------------------------------------
# 4) repeated_low_value_tool_call：同 (tool_name, args) 调 ≥2 次。
# ---------------------------------------------------------------------------


def test_signal_repeated_call_same_args():
    tool = _spec(name="alpha_lookup")
    analyzer = _make_analyzer(tool)
    args = {"resource_id": "r-1"}
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="Look up r-1.",
        tool_calls=[
            _call("alpha_lookup", call_id="c1", arguments=args),
            _call("alpha_lookup", call_id="c2", arguments=args),
        ],
        tool_responses=[
            _response(
                "alpha_lookup",
                call_id="c1",
                content={
                    "summary": "ok",
                    "evidence": [{"id": "ev"}],
                    "next_action": "done",
                    "technical_id": "r-1",
                },
            ),
            _response(
                "alpha_lookup",
                call_id="c2",
                content={
                    "summary": "ok",
                    "evidence": [{"id": "ev"}],
                    "next_action": "done",
                    "technical_id": "r-1",
                },
            ),
        ],
    )
    types = [s["signal_type"] for s in signals]
    assert "repeated_low_value_tool_call" in types


def test_signal_repeated_call_negative_when_args_differ():
    """反例：同工具不同参数（例如不同 trace_id）是合法分析模式，不应触发。"""

    tool = _spec(name="alpha_lookup")
    analyzer = _make_analyzer(tool)
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="Look up multiple resources.",
        tool_calls=[
            _call("alpha_lookup", call_id="c1", arguments={"resource_id": "r-1"}),
            _call("alpha_lookup", call_id="c2", arguments={"resource_id": "r-2"}),
        ],
        tool_responses=[
            _response(
                "alpha_lookup",
                call_id="c1",
                content={
                    "summary": "ok",
                    "evidence": [{"id": "ev"}],
                    "next_action": "done",
                    "technical_id": "r-1",
                },
            ),
            _response(
                "alpha_lookup",
                call_id="c2",
                content={
                    "summary": "ok",
                    "evidence": [{"id": "ev"}],
                    "next_action": "done",
                    "technical_id": "r-2",
                },
            ),
        ],
    )
    assert "repeated_low_value_tool_call" not in [s["signal_type"] for s in signals]


# ---------------------------------------------------------------------------
# 5) tool_selected_in_when_not_to_use_context：when_not_to_use 关键词与
#    user_prompt 高重叠。
# ---------------------------------------------------------------------------


def test_signal_when_not_to_use_keyword_overlap_with_prompt():
    """模拟 Agent 把"明确禁止"的工具用在 prompt 描述的场景里。

    这是真实"工具诱饵"案例的复盘版——以前只能靠 forbidden_first_tool
    rule（要 eval 作者预先写出禁止规则）才能发现；trace signal 让它能
    从 raw artifact + ToolSpec 自动浮出。
    """

    tool = _spec(
        name="snapshot_inspector",
        when_not_to_use=(
            "Do not use for runtime causal evidence or checkpoint boundary "
            "investigations; this only shows visual symptoms."
        ),
    )
    analyzer = _make_analyzer(tool)
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt=(
            "User reports a runtime issue and needs the causal evidence to "
            "explain the checkpoint boundary failure."
        ),
        tool_calls=[_call("snapshot_inspector")],
        tool_responses=[
            _response(
                "snapshot_inspector",
                content={
                    "summary": "ok",
                    "evidence": [{"id": "snap-1"}],
                    "next_action": "ok",
                    "technical_id": "s-1",
                },
            )
        ],
    )
    types = [s["signal_type"] for s in signals]
    assert "tool_selected_in_when_not_to_use_context" in types
    sig = next(
        s for s in signals if s["signal_type"] == "tool_selected_in_when_not_to_use_context"
    )
    _assert_signal_contract(sig)
    assert sig["severity"] == "high"


def test_signal_when_not_to_use_negative_with_unrelated_prompt():
    """反例：prompt 不命中 when_not_to_use 关键词时不应触发——避免假阳性。"""

    tool = _spec(
        name="snapshot_inspector",
        when_not_to_use="Do not use for runtime causal evidence investigations.",
    )
    analyzer = _make_analyzer(tool)
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="Check the layout of the home page header.",
        tool_calls=[_call("snapshot_inspector")],
        tool_responses=[
            _response(
                "snapshot_inspector",
                content={
                    "summary": "ok",
                    "evidence": [{"id": "snap-1"}],
                    "next_action": "ok",
                    "technical_id": "s-1",
                },
            )
        ],
    )
    assert "tool_selected_in_when_not_to_use_context" not in [
        s["signal_type"] for s in signals
    ]


def test_signal_when_not_to_use_negative_with_single_keyword_hit():
    """反例：只命中一个关键词不触发——单词撞车率太高，会假阳性。

    钉死 ``len(hits) >= 2`` 阈值。如果未来调整阈值，必须同步更新本测试
    并解释为什么调整不会让 examples/runtime_debug 被误伤。
    """

    tool = _spec(
        name="snapshot_inspector",
        when_not_to_use="Do not use for runtime causal evidence.",
    )
    analyzer = _make_analyzer(tool)
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="Show me the runtime version banner.",  # 只命中 'runtime'
        tool_calls=[_call("snapshot_inspector")],
        tool_responses=[
            _response(
                "snapshot_inspector",
                content={
                    "summary": "ok",
                    "evidence": [{"id": "snap-1"}],
                    "next_action": "ok",
                    "technical_id": "s-1",
                },
            )
        ],
    )
    assert "tool_selected_in_when_not_to_use_context" not in [
        s["signal_type"] for s in signals
    ]


# ---------------------------------------------------------------------------
# 6) failure isolation：未知工具 / 缺 ToolSpec 不应让 analyzer 崩溃。
# ---------------------------------------------------------------------------


def test_unknown_tool_does_not_crash_analyzer():
    """模拟 adapter 调用了 ToolSpec 列表里没有的工具（registry mismatch）。

    analyzer 应静默跳过 contract 类信号（无契约可对照），但其他信号
    （重复调用 / when_not_to_use）也不应崩溃。
    """

    analyzer = TraceSignalAnalyzer({})
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="anything",
        tool_calls=[_call("ghost_tool")],
        tool_responses=[_response("ghost_tool", content={"summary": "ok"})],
    )
    # 不要求一定有信号；要求不抛异常 + 返回 list。
    assert isinstance(signals, list)


def test_failed_tool_response_does_not_trigger_contract_signal():
    """工具返回 success=false 时不在 contract 信号范围内。

    这类失败应由 TranscriptAnalyzer.tool_error 归因；trace signal 不应
    重复报"contract 没满足"——避免给同一根因双重打标。
    """

    tool = _spec(name="alpha_lookup")
    analyzer = _make_analyzer(tool)
    signals = analyzer.analyze_eval(
        eval_id="e1",
        user_prompt="Look up r-1.",
        tool_calls=[_call("alpha_lookup")],
        tool_responses=[
            _response("alpha_lookup", success=False, content={}),
        ],
    )
    types = [s["signal_type"] for s in signals]
    assert "tool_result_no_evidence" not in types
    assert "tool_result_missing_next_action" not in types


# ---------------------------------------------------------------------------
# 7) 磁盘 helper：从已写好的 run 目录复盘等价于 in-memory 分析。
# ---------------------------------------------------------------------------


def test_analyze_run_dir_replays_signals_from_disk(tmp_path):
    """钉死 analyze_run_dir 与 analyze_eval 的等价性。

    用途：未来若新增 ``analyze-artifacts`` CLI（v0.2 backlog），它会调用
    本函数；CI / 复盘工具也会用它扫历史 runs/。一旦 in-memory 与磁盘
    入口分歧，两边产出会不一致，复盘判断不可信。
    """

    import json

    run = tmp_path / "run"
    run.mkdir()
    tool = _spec(name="alpha_lookup")
    call = _call("alpha_lookup")
    resp = _response(
        "alpha_lookup",
        content={"summary": "ok", "next_action": "ok"},  # 缺 evidence
    )
    (run / "tool_calls.jsonl").write_text(json.dumps(call) + "\n", encoding="utf-8")
    (run / "tool_responses.jsonl").write_text(json.dumps(resp) + "\n", encoding="utf-8")

    by_eval = analyze_run_dir(run, tools=[tool], user_prompts_by_eval={"e1": "Look up r-1."})
    assert "e1" in by_eval
    assert "tool_result_no_evidence" in [s["signal_type"] for s in by_eval["e1"]]
