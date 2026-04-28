"""LLM 成本聚合 — v1.6 第二项。

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
- 提供给 :class:`MarkdownReport` 一个简洁的 totals 摘要，让 reviewer 不
  需要打开 JSON 就能看到"本 run 是否调用了 retry / 是否有 advisory 错误
  消耗了 attempts"。

本模块**不**负责什么
--------------------
- **不**真实计费——所有 ``estimated_cost_usd`` 字段当前默认 ``None``；
  只在用户显式提供 price 表时才计算（v1.6 不暴露 CLI flag，预留给 v1.7+）；
- **不**做 anomaly detection / budget alerting；
- **不**承诺与 provider 真实账单一致——这只是 advisory-only 的
  deterministic 复盘，提醒用户"按这次运行 token 量级估个量级"，绝不能
  当报账依据。

artifact 排查路径
-----------------
- ``runs/<dir>/llm_cost.json``：本模块写出的核心 artifact；
- ``runs/<dir>/judge_results.json::dry_run_provider``：本模块的输入；
- ``runs/<dir>/report.md::Cost Summary``：本模块 totals 的可读渲染。

未来扩展点
----------
- price table 注入（按 model 计费；token / 1k 单价表）；
- 跨多 run 聚合（``runs/<*>/llm_cost.json`` → 项目级 cost dashboard）；
- per-eval-budget 强制 cap（超额自动 abort）。
"""

from __future__ import annotations

from typing import Any

COST_SCHEMA_VERSION = 1


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


def build_llm_cost_artifact(
    dry_run_results: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """从 dry_run_results 聚合 ``llm_cost.json`` payload。

    返回 dict 顶层结构：
    - ``schema_version``：本 artifact schema 版本，"只增不删"承诺；
    - ``totals``：本 run 跨所有 advisory 的合计；
    - ``per_eval``：按 eval_id 分组的 advisory 列表；
    - ``cost_unknown_reasons``：去重后的"为什么没法算 cost"原因清单——
      reviewer 一眼能看出"本 run 主要是 recorded mode 所以没 token 数"
      还是"fake fixture 漏写 usage"。
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
    }
    cost_unknown_reasons: dict[str, int] = {}
    per_eval: dict[str, list[dict[str, Any]]] = {}

    for row in rows:
        eval_id = row["eval_id"]
        per_eval.setdefault(eval_id, []).append(row)
        totals["retry_count_total"] += _coerce_int(row.get("retry_count"))
        if row.get("error_code"):
            totals["error_count"] += 1
        usage = row.get("usage")
        if isinstance(usage, dict):
            totals["with_usage_count"] += 1
            totals["tokens_in"] += _coerce_int(
                usage.get("input_tokens", usage.get("prompt_tokens"))
            )
            totals["tokens_out"] += _coerce_int(
                usage.get("output_tokens", usage.get("completion_tokens"))
            )
        else:
            mode = row.get("mode") or "unknown"
            # 一句话原因：reviewer 通过原因字符串就能定位到 provider mode
            # 是否本身就不报 usage（recorded）还是 fixture 漏字段（fake）。
            # 注意：如果本条 advisory 出错（error_code 非空），优先记录
            # "advisory errored ..." 原因——避免把"错误也算成 mode 漏字段"。
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

    return {
        "schema_version": COST_SCHEMA_VERSION,
        "totals": totals,
        "per_eval": [
            {"eval_id": eid, "advisories": items} for eid, items in per_eval.items()
        ],
        "cost_unknown_reasons": [
            {"reason": r, "count": c} for r, c in sorted(cost_unknown_reasons.items())
        ],
        "estimated_cost_usd": None,
        "estimated_cost_note": (
            "v1.6 deterministic stats only; price table injection is v1.7+ backlog. "
            "These numbers are advisory-only and MUST NOT be used as a billing source."
        ),
    }
