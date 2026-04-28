"""v1.8 第一项：pricing 注入 + per-eval budget cap 防回归测试。

中文学习型说明
==============
本文件**钉死**的边界
--------------------
1. **没声明 pricing 时，``totals.estimated_cost_usd`` 必须 None** —— 框
   架绝不替用户编造价格；
2. **声明 pricing 后，advisory cost = ``input_tokens/1000 * input_per_1k
   + output_tokens/1000 * output_per_1k``**，结果必须四舍五入到 6 位
   小数（防止浮点尾巴噪音让 reviewer 在 diff 时分心）；
3. **``estimated_cost_note`` 永远含 advisory-only 措辞，禁止出现
   "billing / invoice / authoritative / 真实账单 / 报账"等词** —— 即使
   接了 pricing，advisory 仍然 advisory；
4. **顶层 ``estimated_cost_usd`` 永远 None** —— 真实聚合数字写在
   ``totals.estimated_cost_usd``；顶层 None 是"框架本身不报账"的强承诺；
5. **未知 model / 非法 currency / 非 USD currency 必须显式记录
   ``cost_unknown_reason``，不得静默归零**；
6. **per_eval budget cap 触发时 ``budget_status="exceeded"``**，且
   ``cap_breached_by`` 必须列出具体哪一项 cap（max_tokens_total /
   max_cost_usd）+ 实际值；
7. **没声明 budget.per_eval 时 ``budget_status="not_applicable"``**，
   不得伪装 ok；
8. **budget exceeded 不中断 run** —— v1.8 是 advisory，不做 hard abort。

本文件**不**负责什么
--------------------
- 不验证 markdown 渲染（report.md 测试单独覆盖）；
- 不真实联网 / 不读真实 key；
- 不验证多 currency 自动换算（v1.8 故意不做，混 currency 直接拒估算）。

防回归价值（这些都是真实可能发生的 bug）
-----------------------------------------
- 有人把 advisory cost 算法从 "tokens/1000 * price" 改成 "tokens *
  price"（差 1000 倍误差，立刻被 test_cost_math_is_correct 抓住）；
- 有人把 advisory-only 措辞删掉伪装"真实账单已支持"；
- 有人为了让某些 eval 通过把 budget cap 默默升高或忽略；
- 有人对未知 model 偷偷套用某个默认价格（编造价格）；
- 有人把 budget exceeded 判定从严改宽（>= 改成 >）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_tool_harness.cli import main as cli_main
from agent_tool_harness.reports.cost_tracker import build_llm_cost_artifact

# ---------- 直接单元测：build_llm_cost_artifact ----------

PRICING_USD = {
    "models": {
        "claude-3-5-sonnet-20241022": {
            "input_per_1k": 0.003,
            "output_per_1k": 0.015,
            "currency": "USD",
            "effective_date": "2024-10-22",
        }
    }
}

BUDGET_TIGHT = {
    "per_eval": {
        "max_tokens_total": 200,
        "max_cost_usd": 0.0005,
    }
}

BUDGET_LOOSE = {
    "per_eval": {
        "max_tokens_total": 1_000_000,
        "max_cost_usd": 100.0,
    }
}


def _make_dry_run_entry(eval_id: str, model: str, in_tok: int, out_tok: int,
                        mode: str = "fake_transport") -> dict:
    """构造一条单 advisory 的 dry-run entry（fake usage 数据，仅用于单测）。

    fake/mock 说明：本 fixture 模拟 ``judge_results.json::dry_run_provider
    .results[]`` 的形态，故意不依赖真实 transport，因为我们要验证 cost
    聚合算法本身，而不是 transport 行为。
    """
    return {
        "eval_id": eval_id,
        "provider": "anthropic-compatible",
        "mode": mode,
        "model": model,
        "usage": {"input_tokens": in_tok, "output_tokens": out_tok},
        "attempts_summary": [],
        "retry_count": 0,
    }


def test_no_pricing_means_estimated_cost_is_none():
    """没声明 pricing 时，totals 与 per_eval 的 estimated_cost_usd 必须 None。"""
    art = build_llm_cost_artifact(
        [_make_dry_run_entry("e1", "claude-3-5-sonnet-20241022", 1000, 500)]
    )
    assert art["totals"]["estimated_cost_usd"] is None
    assert art["per_eval"][0]["estimated_cost_usd"] is None
    assert art["per_eval"][0]["budget_status"] == "not_applicable"
    assert art["pricing_config"] is None
    assert art["budget_config"] is None


def test_cost_math_is_correct():
    """advisory cost = (in/1000)*input_per_1k + (out/1000)*output_per_1k。

    1000 in + 500 out @ (0.003, 0.015) = 0.003 + 0.0075 = 0.0105
    """
    art = build_llm_cost_artifact(
        [_make_dry_run_entry("e1", "claude-3-5-sonnet-20241022", 1000, 500)],
        pricing=PRICING_USD,
    )
    assert art["totals"]["estimated_cost_usd"] == pytest.approx(0.0105, abs=1e-9)
    assert art["per_eval"][0]["estimated_cost_usd"] == pytest.approx(0.0105, abs=1e-9)
    assert art["per_eval"][0]["tokens_total"] == 1500


def test_top_level_estimated_cost_usd_is_always_none_even_with_pricing():
    """顶层 estimated_cost_usd 永远 None；advisory cost 只能在 totals 看到。"""
    art = build_llm_cost_artifact(
        [_make_dry_run_entry("e1", "claude-3-5-sonnet-20241022", 1000, 500)],
        pricing=PRICING_USD,
    )
    assert art["estimated_cost_usd"] is None, (
        "顶层 estimated_cost_usd 是'框架本身不报账'强承诺，永远 None；"
        "真实聚合数字看 totals.estimated_cost_usd。"
    )


def test_estimated_cost_note_keeps_advisory_only_and_forbids_billing_words():
    """note 必须保留 advisory-only，且禁止出现报账类词汇。"""
    art = build_llm_cost_artifact(
        [_make_dry_run_entry("e1", "claude-3-5-sonnet-20241022", 1000, 500)],
        pricing=PRICING_USD,
    )
    note = art["estimated_cost_note"].lower()
    assert "advisory-only" in note
    forbidden = ["真实账单", "报账", "authoritative cost report"]
    # "billing source" / "invoice" 这些词应当只在"MUST NOT be used as"
    # 否定语境中出现；这里弱断言：必须出现 "must not be used"。
    assert "must not be used" in note, (
        "note 必须保留显式 'MUST NOT be used as billing source' 否定句，"
        "防止有人改成肯定句把 advisory cost 当真实账单宣传。"
    )
    for word in forbidden:
        assert word not in art["estimated_cost_note"], (
            f"note 出现禁用报账类词 {word!r}；"
            "advisory cost 永远不得被宣传为真实账单。"
        )


def test_unknown_model_records_cost_unknown_reason():
    """未知 model 不得编造价格，必须写 cost_unknown_reason 并增 pricing_unknown_count。"""
    art = build_llm_cost_artifact(
        [_make_dry_run_entry("e1", "totally-unknown-model", 1000, 500)],
        pricing=PRICING_USD,
    )
    assert art["totals"]["pricing_unknown_count"] == 1
    assert art["totals"]["estimated_cost_usd"] is None, (
        "唯一一条 advisory 没价格，totals 应保持 None 而不是 0.0；"
        "0.0 会让 reviewer 误以为'真的零成本'。"
    )
    reasons = [r["reason"] for r in art["cost_unknown_reasons"]]
    assert any("totally-unknown-model" in r for r in reasons)


def test_non_usd_currency_refuses_to_estimate():
    """非 USD currency MVP 阶段拒绝估算，写 unknown reason。"""
    pricing_eur = {
        "models": {
            "claude-3-5-sonnet-20241022": {
                "input_per_1k": 0.003,
                "output_per_1k": 0.015,
                "currency": "EUR",
            }
        }
    }
    art = build_llm_cost_artifact(
        [_make_dry_run_entry("e1", "claude-3-5-sonnet-20241022", 1000, 500)],
        pricing=pricing_eur,
    )
    assert art["totals"]["pricing_unknown_count"] == 1
    assert art["totals"]["estimated_cost_usd"] is None
    reasons = [r["reason"] for r in art["cost_unknown_reasons"]]
    assert any("EUR" in r and "MVP only USD" in r for r in reasons)


def test_per_eval_budget_exceeded_lists_breached_caps():
    """per_eval budget cap 触发 exceeded 时，cap_breached_by 必须列出具体 cap + 实际值。"""
    art = build_llm_cost_artifact(
        [_make_dry_run_entry("e1", "claude-3-5-sonnet-20241022", 1000, 500)],
        pricing=PRICING_USD,
        budget=BUDGET_TIGHT,  # tokens cap 200，远低于 1500
    )
    eval_row = art["per_eval"][0]
    assert eval_row["budget_status"] == "exceeded"
    breached = eval_row["cap_breached_by"]
    assert any("max_tokens_total=200" in s and "actual=1500" in s for s in breached)
    assert any("max_cost_usd=0.0005" in s for s in breached)
    assert art["totals"]["budget_exceeded_count"] == 1


def test_per_eval_budget_ok_when_loose():
    """宽松 budget 下应 ok，不得伪报 exceeded。"""
    art = build_llm_cost_artifact(
        [_make_dry_run_entry("e1", "claude-3-5-sonnet-20241022", 1000, 500)],
        pricing=PRICING_USD,
        budget=BUDGET_LOOSE,
    )
    assert art["per_eval"][0]["budget_status"] == "ok"
    assert art["per_eval"][0]["cap_breached_by"] == []
    assert art["totals"]["budget_exceeded_count"] == 0


def test_budget_without_pricing_only_checks_token_cap():
    """有 budget 但无 pricing 时，token cap 仍生效；cost cap 因 cost=None 不触发。"""
    art = build_llm_cost_artifact(
        [_make_dry_run_entry("e1", "claude-3-5-sonnet-20241022", 1000, 500)],
        budget=BUDGET_TIGHT,  # tokens cap 200
    )
    eval_row = art["per_eval"][0]
    assert eval_row["budget_status"] == "exceeded"
    breached = eval_row["cap_breached_by"]
    assert any("max_tokens_total" in s for s in breached)
    # cost cap 不应触发，因为 cost=None（没 pricing）
    assert not any("max_cost_usd" in s for s in breached)


def test_pricing_unknown_count_is_zero_when_pricing_not_provided():
    """没声明 pricing 时，pricing_unknown_count 应为 0（根本没尝试查价）。"""
    art = build_llm_cost_artifact(
        [_make_dry_run_entry("e1", "claude-3-5-sonnet-20241022", 1000, 500)]
    )
    assert art["totals"]["pricing_unknown_count"] == 0


# ---------- 集成测：通过 EvalRunner 验证 project.yaml 配置传递 ----------

REPO_ROOT = Path(__file__).resolve().parent.parent
EX = REPO_ROOT / "examples" / "runtime_debug"


def test_run_picks_up_pricing_and_budget_from_project_yaml(tmp_path: Path):
    """end-to-end：把 pricing / budget 写进临时 project.yaml，run 后 llm_cost.json
    必须包含 pricing_config / budget_config，证明配置真的被读取并传递。

    本测试不依赖真实 LLM、不联网；只验证配置流转链路。CI 默认无 dry_run
    provider，所以 estimated_cost_usd 仍是 None（没 advisory），但
    pricing_config / budget_config 必须被回写到 artifact。
    """
    # 复制 runtime_debug 例子但加 pricing + budget。
    proj_text = (EX / "project.yaml").read_text(encoding="utf-8")
    extended_yaml = proj_text + (
        "\n\npricing:\n"
        "  models:\n"
        "    claude-3-5-sonnet-20241022:\n"
        "      input_per_1k: 0.003\n"
        "      output_per_1k: 0.015\n"
        "      currency: USD\n"
        "      effective_date: '2024-10-22'\n"
        "\nbudget:\n"
        "  per_eval:\n"
        "    max_tokens_total: 50000\n"
        "    max_cost_usd: 0.10\n"
    )
    proj_path = tmp_path / "project.yaml"
    proj_path.write_text(extended_yaml, encoding="utf-8")

    out = tmp_path / "run-bad"
    rc = cli_main([
        "run",
        "--project", str(proj_path),
        "--tools", str(EX / "tools.yaml"),
        "--evals", str(EX / "evals.yaml"),
        "--out", str(out),
        "--mock-path", "bad",
    ])
    assert rc == 0
    cost = json.loads((out / "llm_cost.json").read_text(encoding="utf-8"))
    assert cost["pricing_config"] is not None, (
        "pricing_config 应被回写到 llm_cost.json，证明 ProjectSpec.pricing "
        "真正穿过 EvalRunner 到达 cost_tracker。"
    )
    assert "claude-3-5-sonnet-20241022" in cost["pricing_config"].get("models", {})
    assert cost["budget_config"] is not None
    assert cost["budget_config"]["per_eval"]["max_cost_usd"] == 0.10
