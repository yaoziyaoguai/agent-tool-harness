"""LLM cost tracker 聚合契约测试（v1.6 第二项）。

中文学习型说明
==============
本文件钉死的边界：

1. **空输入 → 空 totals**：``build_llm_cost_artifact(None)`` /
   ``[]`` 都返回 ``schema_version`` + 全 0 totals + 空 reasons；
2. **单 advisory 有 usage** → totals.tokens_in / tokens_out 累加；
3. **单 advisory 无 usage 且 mode=recorded** → cost_unknown_reasons 出现
   ``"recorded mode does not report token usage"``，**且**永远不
   fabricate 一个 token 数；
4. **多 advisory（advisory_results）** → 每条 advisory 独立累加，
   error_code advisory 计入 error_count 且不算 token；
5. **retry_count 累加**：单 advisory entry 的 retry_count + 多 advisory 中
   每条 advisory 的 retry_count 都进 totals.retry_count_total；
6. **estimated_cost_usd 永远 None**（v1.6 不暴露 price table）+ 必带
   "advisory-only" note；
7. **MarkdownReport._render_cost_summary** 在 totals.advisory_count=0 时
   不渲染（保持 v1.5 字节兼容）；
8. **schema_version=1**：未来"只增不删"。

mock/fixture 边界
================
所有输入都是手工构造的 dict，不依赖真实 EvalRunner 跑 run；这样测试
聚焦于"把 dry_run_results 转成 llm_cost.json"的纯函数语义。
"""

from __future__ import annotations

from agent_tool_harness.reports.cost_tracker import (
    COST_SCHEMA_VERSION,
    build_llm_cost_artifact,
)
from agent_tool_harness.reports.markdown_report import MarkdownReport


def test_empty_input_returns_zero_totals():
    out = build_llm_cost_artifact(None)
    assert out["schema_version"] == COST_SCHEMA_VERSION
    assert out["totals"]["advisory_count"] == 0
    assert out["totals"]["tokens_in"] == 0
    assert out["per_eval"] == []
    assert out["estimated_cost_usd"] is None
    assert "advisory-only" in out["estimated_cost_note"]


def test_single_advisory_with_usage_aggregates():
    """单 advisory entry 的 usage 累加到 totals。"""
    entries = [
        {
            "eval_id": "e1",
            "provider": "anthropic_compatible",
            "mode": "fake_transport",
            "model": "fake-x",
            "usage": {"input_tokens": 100, "output_tokens": 20},
            "retry_count": 2,
        }
    ]
    out = build_llm_cost_artifact(entries)
    assert out["totals"]["tokens_in"] == 100
    assert out["totals"]["tokens_out"] == 20
    assert out["totals"]["with_usage_count"] == 1
    assert out["totals"]["retry_count_total"] == 2
    assert out["totals"]["error_count"] == 0
    assert out["cost_unknown_reasons"] == []


def test_recorded_mode_without_usage_records_reason():
    """recorded mode 不报 usage → cost_unknown_reasons 出现明确原因。

    防回归：禁止把 None token 数 fabricate 成 0 后偷偷算成 cost——
    本测试钉住"宁缺毋滥"的成本治理边界。
    """
    entries = [
        {"eval_id": "e1", "mode": "recorded", "provider": "recorded_dry_run"},
        {"eval_id": "e2", "mode": "recorded", "provider": "recorded_dry_run"},
    ]
    out = build_llm_cost_artifact(entries)
    assert out["totals"]["tokens_in"] == 0
    assert out["totals"]["with_usage_count"] == 0
    reasons = {r["reason"]: r["count"] for r in out["cost_unknown_reasons"]}
    assert reasons["recorded mode does not report token usage"] == 2


def test_multi_advisory_aggregates_per_advisory():
    """多 advisory entry：每条 advisory 各自累加；error 单独计数。"""
    entries = [
        {
            "eval_id": "e1",
            "advisory_results": [
                {
                    "provider": "p1",
                    "mode": "fake_transport",
                    "usage": {"input_tokens": 50, "output_tokens": 10},
                    "retry_count": 1,
                },
                {
                    "provider": "p2",
                    "mode": "fake_transport",
                    "error_code": "rate_limited",
                },
                {
                    "provider": "p3",
                    "mode": "recorded",
                },
            ],
        }
    ]
    out = build_llm_cost_artifact(entries)
    assert out["totals"]["advisory_count"] == 3
    assert out["totals"]["tokens_in"] == 50
    assert out["totals"]["tokens_out"] == 10
    assert out["totals"]["retry_count_total"] == 1
    assert out["totals"]["error_count"] == 1
    reasons = {r["reason"]: r["count"] for r in out["cost_unknown_reasons"]}
    assert "advisory errored (rate_limited); no usage available" in reasons
    assert "recorded mode does not report token usage" in reasons


def test_estimated_cost_remains_none_v16():
    """v1.6 不暴露 price 注入；estimated_cost_usd 永远是 None。"""
    entries = [
        {"eval_id": "e1", "mode": "fake_transport",
         "usage": {"input_tokens": 1_000_000, "output_tokens": 500_000}},
    ]
    out = build_llm_cost_artifact(entries)
    assert out["estimated_cost_usd"] is None


def test_report_skips_cost_section_when_no_advisories():
    """没有 advisory → MarkdownReport 不渲染 Cost Summary 段。"""
    report = MarkdownReport()
    md = report.render(
        project={"name": "p"},
        metrics={"total_evals": 0, "passed": 0, "failed": 0,
                 "skipped_evals": 0, "error_evals": 0, "total_tool_calls": 0},
        audit_tools={"summary": {"tool_count": 0, "average_score": 0,
                                 "low_score_tools": []}},
        audit_evals={"summary": {"eval_count": 0, "average_score": 0,
                                 "not_runnable": []}},
        judge_results={"results": []},
        diagnosis={"results": []},
        llm_cost=build_llm_cost_artifact(None),
    )
    assert "Cost Summary" not in md


def test_report_renders_cost_section_when_advisories_present():
    """有 advisory → Cost Summary 段必须出现 + 必带 advisory-only 文案。"""
    cost = build_llm_cost_artifact([
        {"eval_id": "e1", "mode": "fake_transport", "provider": "p1",
         "usage": {"input_tokens": 12, "output_tokens": 3}},
    ])
    report = MarkdownReport()
    md = report.render(
        project={"name": "p"},
        metrics={"total_evals": 0, "passed": 0, "failed": 0,
                 "skipped_evals": 0, "error_evals": 0, "total_tool_calls": 0},
        audit_tools={"summary": {"tool_count": 0, "average_score": 0,
                                 "low_score_tools": []}},
        audit_evals={"summary": {"eval_count": 0, "average_score": 0,
                                 "not_runnable": []}},
        judge_results={"results": []},
        diagnosis={"results": []},
        llm_cost=cost,
    )
    assert "Cost Summary (advisory-only, deterministic)" in md
    assert "12" in md and "3" in md
    assert "advisory-only" in md or "不是真实账单" in md
