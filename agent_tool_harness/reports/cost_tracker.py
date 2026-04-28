"""LLM 成本聚合 — v1.6 + v1.8 第一项。

中文学习型说明
==============
本模块负责什么
--------------
- 把 ``judge_results.json::dry_run_provider.results[]`` 中每条 entry 的
  ``usage`` / ``attempts_summary`` / ``retry_count`` 聚合成 ``llm_cost.json``；
- 输出对所有 provider mode（recorded / fake_transport / offline_fixture /
  composite_dry_run / live transport future）一致的 schema；
- 当 entry 没有 ``usage`` 时，**不**编造数字，而是显式记录
  ``cost_unknown_reason``（如 ``"recorded mode does not report token usage"``、
  ``"fake transport fixture missing usage field"``）；
- v1.8 起：当用户在 ``project.yaml`` 显式声明 ``pricing`` 时，按
  ``input_per_1k`` / ``output_per_1k`` 计算 advisory 级 ``estimated_cost_usd``；
  当用户声明 ``budget`` 时，按 ``per_eval`` 维度判定
  ``budget_status ∈ {ok, exceeded, not_applicable}``，超额 eval 写入
  ``cap_breached_by``，让 reviewer 在 ``llm_cost.json`` 与
  ``report.md::Cost Summary`` 一眼看出"哪条 eval 烧超了"；
- 提供给 :class:`MarkdownReport` 一个简洁的 totals 摘要，让 reviewer 不
  需要打开 JSON 就能看到"本 run 是否调用了 retry / 是否有 advisory 错误
  消耗了 attempts"。

本模块**不**负责什么
--------------------
- **不**真实计费——v1.8 引入 advisory pricing 后，``estimated_cost_usd``
  仍然是 advisory-only：``estimated_cost_note`` 永远显式声明这一点，
  禁止任何"真实账单 / billing / invoice / authoritative" 类措辞；
- **不**做隐式默认价格——只接受用户显式声明的 ``pricing.models``；
  没声明的 model 视为 unknown，不编造价格；
- **不**做 anomaly detection / dashboard 聚合——v1.8 只覆盖单 run 单
  eval 维度；跨 run dashboard 留 v2.0 候选；
- **不**做 hard abort——budget exceeded 是 advisory finding，不会
  中断当前 run；CI 可基于 ``llm_cost.json::totals.budget_exceeded_count``
  自己决定是否 fail。

artifact 排查路径
-----------------
- ``runs/<dir>/llm_cost.json``：本模块写出的核心 artifact；
- ``runs/<dir>/judge_results.json::dry_run_provider``：本模块的输入；
- ``runs/<dir>/report.md::Cost Summary``：本模块 totals 的可读渲染。

未来扩展点
----------
- 多 currency 自动换算（v1.8 只支持单一 USD，混 currency 时拒绝估算并
  写 unknown reason）；
- 跨多 run 聚合（``runs/<*>/llm_cost.json`` → 项目级 cost dashboard）；
- per-eval-budget 强制 abort（v1.8 仅 advisory，未来可在 project.yaml
  开启 ``hard_abort: true`` 让 EvalRunner 立即停掉对应 eval）；
- per-suite / per-tag budget cap。
"""

from __future__ import annotations

from typing import Any

# v1.8：schema_version 升 2，主要变化：
# - per_eval 增加 estimated_cost_usd / budget_status / cap_breached_by；
# - totals 增加 estimated_cost_usd / budget_exceeded_count / pricing_unknown_count；
# - 顶层 estimated_cost_usd 仍为 None（保留 v1.6 字节兼容时的"不要把这个数当账单"
#   提示）；当用户配置了 pricing 时实际数字写在 totals.estimated_cost_usd，
#   reviewer 心智更清晰：顶层 None 永远是"框架不替你报账"承诺，totals 才是聚合。
COST_SCHEMA_VERSION = 2


def _extract_usage_from_entry(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """把单条 dry-run entry 拆成 0..N 条 advisory-level usage 子条目。

    设计取舍：单 advisory entry 顶层有 ``usage`` / ``attempts_summary``；
    多 advisory entry 的 ``advisory_results`` 列表里每条 advisory 各有自己
    的 ``usage`` / ``attempts_summary``。这里把它们规范化成统一形态，
    让聚合逻辑只关心一种形状。
    """

    items: list[dict[str, Any]] = []
    eval_id = entry.get("eval_id", "?")
    advisories = entry.get("advisory_results")
    if isinstance(advisories, list) and advisories:
        for adv in advisories:
            items.append(
                {
                    "eval_id": eval_id,
                    "provider": adv.get("provider"),
                    "mode": adv.get("mode"),
                    "model": adv.get("model"),
                    "usage": adv.get("usage"),
                    "attempts_summary": adv.get("attempts_summary"),
                    "retry_count": adv.get("retry_count", 0),
                    "error_code": adv.get("error_code"),
                }
            )
        return items
    items.append(
        {
            "eval_id": eval_id,
            "provider": entry.get("provider"),
            "mode": entry.get("mode"),
            "model": entry.get("model"),
            "usage": entry.get("usage"),
            "attempts_summary": entry.get("attempts_summary"),
            "retry_count": entry.get("retry_count", 0),
            "error_code": (entry.get("error") or {}).get("type")
            if entry.get("error")
            else None,
        }
    )
    return items


def _coerce_int(value: Any) -> int:
    """安全把 usage 中的字段转 int；非法值返回 0 而不是抛异常。"""
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _coerce_float(value: Any) -> float | None:
    """安全把 pricing/budget 中的浮点字段转 float；非法值返回 None。"""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v < 0:
        return None
    return v


def _lookup_model_price(
    pricing: dict[str, Any] | None, model: str | None
) -> tuple[dict[str, Any] | None, str | None]:
    """查找单 model 的 pricing 条目；返回 ``(price_dict, unknown_reason)``。

    返回值有且仅有一种"成功"形态：``price_dict`` 不为 None 且 unknown_reason
    为 None。其它情况都返回 ``(None, reason)``，让上层把 reason 写进
    ``cost_unknown_reasons``。这个分裂式返回故意不抛异常——本模块的契约
    是"永不编造"，但允许"显式说不知道"。
    """
    if not pricing or not isinstance(pricing, dict):
        return None, None  # 用户没配 pricing，根本不该进入"估算"路径
    models = pricing.get("models")
    if not isinstance(models, dict):
        return None, "pricing.models missing or not a dict"
    if not model:
        return None, "advisory has no model field; cannot look up price"
    price = models.get(model)
    if not isinstance(price, dict):
        return None, f"no pricing entry for model={model!r}"
    currency = price.get("currency", "USD")
    # MVP：只支持 USD；其它 currency 拒绝估算，让用户自己换算或显式声明 USD。
    # 不偷偷换算的根因：汇率漂移会让 advisory 数字误导 reviewer。
    if currency != "USD":
        return None, (
            f"model={model!r} pricing currency={currency!r} not supported "
            f"(MVP only USD); refusing to estimate"
        )
    in_per_1k = _coerce_float(price.get("input_per_1k"))
    out_per_1k = _coerce_float(price.get("output_per_1k"))
    if in_per_1k is None or out_per_1k is None:
        return None, (
            f"model={model!r} pricing has invalid input_per_1k / output_per_1k"
        )
    return {
        "input_per_1k": in_per_1k,
        "output_per_1k": out_per_1k,
        "currency": "USD",
        "effective_date": str(price.get("effective_date", "")) or None,
    }, None


def _evaluate_per_eval_budget(
    budget: dict[str, Any] | None,
    tokens_total: int,
    cost_usd: float | None,
) -> tuple[str, list[str]]:
    """对单 eval 应用 per_eval budget cap；返回 ``(status, breached_caps)``。

    status 取值：
    - ``"not_applicable"``：用户没声明 budget.per_eval；
    - ``"ok"``：所有 cap 都没超；
    - ``"exceeded"``：至少一项 cap 被突破；breached_caps 列出哪几项。

    设计取舍：cap 是"或"关系——任意一项被破就 exceeded；不实现"与"组合，
    避免给用户埋一层不直观的 truthtable。
    """
    if not budget or not isinstance(budget, dict):
        return "not_applicable", []
    per_eval = budget.get("per_eval")
    if not isinstance(per_eval, dict):
        return "not_applicable", []
    breached: list[str] = []
    cap_tokens = per_eval.get("max_tokens_total")
    if isinstance(cap_tokens, int) and cap_tokens > 0 and tokens_total > cap_tokens:
        breached.append(
            f"max_tokens_total={cap_tokens} (actual={tokens_total})"
        )
    cap_cost = _coerce_float(per_eval.get("max_cost_usd"))
    if cap_cost is not None and cost_usd is not None and cost_usd > cap_cost:
        breached.append(
            f"max_cost_usd={cap_cost} (actual={cost_usd:.6f})"
        )
    if breached:
        return "exceeded", breached
    return "ok", []


def build_llm_cost_artifact(
    dry_run_results: list[dict[str, Any]] | None,
    *,
    pricing: dict[str, Any] | None = None,
    budget: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """从 dry_run_results 聚合 ``llm_cost.json`` payload。

    返回 dict 顶层结构（v1.8 schema_version=2）：
    - ``schema_version``：本 artifact schema 版本，"只增不删"承诺；
    - ``totals``：本 run 跨所有 advisory 的合计，含 advisory-only
      ``estimated_cost_usd`` 与 ``budget_exceeded_count``；
    - ``per_eval``：按 eval_id 分组的 advisory 列表，含 per-eval
      ``estimated_cost_usd`` / ``budget_status`` / ``cap_breached_by``；
    - ``cost_unknown_reasons``：去重后的"为什么没法算 cost"原因清单——
      包括 v1.6 的 mode-based 原因 + v1.8 的 pricing-lookup 失败原因；
    - ``estimated_cost_usd``：**永远 None**，与 v1.6 兼容。真实聚合数
      字写在 ``totals.estimated_cost_usd``，让顶层永远是"框架不替你报
      账"承诺；
    - ``estimated_cost_note``：永远含 advisory-only 措辞。

    pricing / budget 任一为空都不影响其它字段，只是相应的 cost / budget
    字段会变成 None / not_applicable。
    """

    rows: list[dict[str, Any]] = []
    for entry in dry_run_results or []:
        rows.extend(_extract_usage_from_entry(entry))

    totals = {
        "advisory_count": len(rows),
        "tokens_in": 0,
        "tokens_out": 0,
        "retry_count_total": 0,
        "error_count": 0,
        "with_usage_count": 0,
        # v1.8 新增：advisory-only 估算成本聚合 + budget exceeded 统计。
        "estimated_cost_usd": None,
        "pricing_unknown_count": 0,
        "budget_exceeded_count": 0,
    }
    cost_unknown_reasons: dict[str, int] = {}
    per_eval_rows: dict[str, list[dict[str, Any]]] = {}
    per_eval_cost: dict[str, float | None] = {}
    per_eval_tokens: dict[str, int] = {}

    pricing_provided = bool(pricing) and isinstance(pricing, dict)

    for row in rows:
        eval_id = row["eval_id"]
        per_eval_rows.setdefault(eval_id, []).append(row)
        per_eval_tokens.setdefault(eval_id, 0)
        per_eval_cost.setdefault(eval_id, None)

        totals["retry_count_total"] += _coerce_int(row.get("retry_count"))
        if row.get("error_code"):
            totals["error_count"] += 1
        usage = row.get("usage")
        adv_tokens_in = 0
        adv_tokens_out = 0
        adv_cost: float | None = None
        if isinstance(usage, dict):
            totals["with_usage_count"] += 1
            adv_tokens_in = _coerce_int(
                usage.get("input_tokens", usage.get("prompt_tokens"))
            )
            adv_tokens_out = _coerce_int(
                usage.get("output_tokens", usage.get("completion_tokens"))
            )
            totals["tokens_in"] += adv_tokens_in
            totals["tokens_out"] += adv_tokens_out
            per_eval_tokens[eval_id] += adv_tokens_in + adv_tokens_out

            # v1.8：只有用户显式声明 pricing 才尝试估算；不编造默认价格。
            if pricing_provided:
                price, reason = _lookup_model_price(pricing, row.get("model"))
                if price is None:
                    totals["pricing_unknown_count"] += 1
                    if reason:
                        cost_unknown_reasons[reason] = (
                            cost_unknown_reasons.get(reason, 0) + 1
                        )
                else:
                    adv_cost = round(
                        adv_tokens_in / 1000.0 * price["input_per_1k"]
                        + adv_tokens_out / 1000.0 * price["output_per_1k"],
                        6,
                    )
                    if per_eval_cost[eval_id] is None:
                        per_eval_cost[eval_id] = 0.0
                    per_eval_cost[eval_id] += adv_cost
                    if totals["estimated_cost_usd"] is None:
                        totals["estimated_cost_usd"] = 0.0
                    totals["estimated_cost_usd"] += adv_cost
        else:
            mode = row.get("mode") or "unknown"
            if row.get("error_code"):
                reason = f"advisory errored ({row['error_code']}); no usage available"
            elif mode == "recorded":
                reason = "recorded mode does not report token usage"
            elif mode == "offline_fixture":
                reason = "offline_fixture without usage field"
            elif mode == "fake_transport":
                reason = "fake_transport response missing usage field"
            else:
                reason = f"no usage reported by provider mode={mode}"
            cost_unknown_reasons[reason] = cost_unknown_reasons.get(reason, 0) + 1
        # 把 advisory-level 字段回写，让 per_eval JSON 有可复盘明细。
        row["advisory_estimated_cost_usd"] = adv_cost

    # 进一步对 totals.estimated_cost_usd 做 round，避免浮点尾巴 noise。
    if isinstance(totals["estimated_cost_usd"], float):
        totals["estimated_cost_usd"] = round(totals["estimated_cost_usd"], 6)

    per_eval_payload: list[dict[str, Any]] = []
    for eid, items in per_eval_rows.items():
        eval_cost = per_eval_cost.get(eid)
        if isinstance(eval_cost, float):
            eval_cost = round(eval_cost, 6)
        eval_tokens_total = per_eval_tokens.get(eid, 0)
        budget_status, breached = _evaluate_per_eval_budget(
            budget, eval_tokens_total, eval_cost
        )
        if budget_status == "exceeded":
            totals["budget_exceeded_count"] += 1
        per_eval_payload.append(
            {
                "eval_id": eid,
                "advisories": items,
                "estimated_cost_usd": eval_cost,
                "tokens_total": eval_tokens_total,
                "budget_status": budget_status,
                "cap_breached_by": breached,
            }
        )

    return {
        "schema_version": COST_SCHEMA_VERSION,
        "totals": totals,
        "per_eval": per_eval_payload,
        "cost_unknown_reasons": [
            {"reason": r, "count": c} for r, c in sorted(cost_unknown_reasons.items())
        ],
        # 顶层永远 None，承诺"框架本身不报账"；真实聚合数字看 totals.estimated_cost_usd。
        "estimated_cost_usd": None,
        "estimated_cost_note": (
            "v1.8 advisory-only deterministic stats; even when pricing is configured, "
            "totals.estimated_cost_usd is an advisory estimate and MUST NOT be used as "
            "a billing source or invoice. Use the provider's official console for "
            "authoritative numbers."
        ),
        # v1.8：把 pricing/budget 当时的有效配置回写，方便 reviewer 复盘
        # "这次估算用了哪份价格表 / 哪份预算"。注意只回写用户输入的字典，
        # 不做任何隐式默认补全。
        "pricing_config": dict(pricing) if pricing_provided else None,
        "budget_config": dict(budget) if budget else None,
    }
