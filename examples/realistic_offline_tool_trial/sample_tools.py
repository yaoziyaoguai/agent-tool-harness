"""realistic_offline_tool_trial sample tools —— 真实感更强的 offline 试用工具样例。

存在意义
--------
为 v2.x Realistic Offline Tool Trial 节点提供"比 toy lookup 更接近真实
内部工作流，但完全 offline、deterministic、fake data"的 sample tools，
让 maintainer 和后续第一批内部同事能用一个**像样**的样例走完整 7 步路径
（bootstrap → REVIEW_CHECKLIST → modify TODO → validate-generated
 --bootstrap-dir → --strict-reviewed → run --mock-path good → 看
artifacts → 填 feedback），而不是只能用 `lookup_user_status` 这种 toy
函数证明 chain 通了。

为什么还是必须 offline / fake
--------------------------------
- v2.x 的核心安全契约是 **no secrets read / no network / no live LLM /
  no untrusted code execution**；
- 真实公司工具一旦引入就需要真实 key、真实账号、真实数据，超出 v2.x 范围；
- offline + fake data 的样例既能让 reviewer 体会到"接真实工具"的字段填写
  心智成本（when_to_use / when_not_to_use / output_contract /
  side_effects 都要真实业务语义），又不会让任何 sample 无意中变成"通过
  仓库泄漏出去的真实业务逻辑或敏感数据"；
- 这与 v3.0 的 MCP / HTTP / Shell executor / live LLM Judge 路线**不冲突**：
  v3.0 才解决"真的接外部世界"，v2.x 只解决"接的姿势是否正确"。

边界（v2.x，不是 v3.0）
-----------------------
- 纯函数 / 零 IO / 零网络 / 零 .env 读取；
- 不调真实 LLM；
- 不 import 任何不可信代码；
- 模块顶层**绝不** raise（与 tests/fixtures/sample_tool_project/
  tools_unsafe.py 完全相反，本文件是 production-imitation 的安全示例）；
- fake data 全部硬编码；不会触发任何外部服务。

如何用 artifacts 排查问题
--------------------------
deterministic run 会把每次工具调用写到 `tool_calls.jsonl` /
`tool_responses.jsonl`，把 judge 决策写到 `judge_results.json`，
把 root-cause 推断写到 `diagnosis.json`，把分数与 mock 警示写到
`metrics.json`，最后汇总到 `report.md`。任何一步不符合 reviewer 的
心智模型，都应该回到 `tool_calls.jsonl` 找证据，而不是只看 report。
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Fake knowledge base —— 完全硬编码的 deterministic 数据。
#
# 为什么用硬编码 dict 而不是读文件 / 读 sqlite：
# - sample 必须 zero-IO；
# - reviewer 在 audit-tools 时不应该被"工具读了什么文件"分散注意力；
# - 后续第一个真实内部同事如果要把这个 sample 替换成"真的查内部 KB"，
#   他需要做的就是把 _FAKE_KB 替换成真实 retriever，并填好 token_policy /
#   side_effects（这是 reviewer 字段填写心智成本的真正来源）。
# ---------------------------------------------------------------------------
_FAKE_KB: list[dict[str, Any]] = [
    {
        "doc_id": "kb-101",
        "title": "How retries interact with idempotency keys",
        "snippet": (
            "When a tool retries on transient errors, the idempotency key "
            "must remain stable."
        ),
        "score_seed": 9,
    },
    {
        "doc_id": "kb-102",
        "title": "Token budget exhaustion on long traces",
        "snippet": "Large stack traces can exceed max_output_tokens; truncate before returning.",
        "score_seed": 7,
    },
    {
        "doc_id": "kb-103",
        "title": "Boundary violation between session and user scopes",
        "snippet": "Session-scope writes must not bleed into user-global state.",
        "score_seed": 8,
    },
    {
        "doc_id": "kb-104",
        "title": "YAML config drift between draft and reviewed",
        "snippet": "Draft files keep TODO placeholders; reviewed files must replace them.",
        "score_seed": 6,
    },
]


def search_fake_knowledge_base(query: str, top_k: int = 3) -> dict[str, Any]:
    """搜 fake 知识库，返回 ToolSpec output_contract 字段（deterministic）。

    设计理念
    ---------
    - 输入只两个参数（query / top_k），故意控制在 ≤3：复合 First Tool
      Suitability Checklist 第 2 条（输入参数 ≤3）；
    - 评分用 `score_seed - len(query) % 3` 做 deterministic 打分，
      保证同一 query 多次调用结果完全相同（offline harness 的核心契约）；
    - evidence 用 doc_id 做稳定 id，让 RuleJudge `must_use_evidence` 能匹配；
    - next_action 写自然语言指引，模拟"真的有人接手分析"的心智模型。

    不负责 / 不会做的事
    ---------------------
    - **不**联网；
    - **不**调用任何 embedding / LLM；
    - **不**根据语义排序——只是 deterministic 模拟，方便 reviewer 看证据链；
    - **不**对 query 做 SQL/正则/过滤；reviewer 如果想加 filter，需要
      在 reviewed tools.yaml 显式声明 supports_filtering=true 并补
      input_schema 字段。
    """
    if not isinstance(query, str) or not query.strip():
        return {
            "summary": "empty query",
            "cause": "query must be a non-empty string",
            "retryable": False,
            "suggested_fix": "Pass a non-empty natural-language query.",
        }
    if not isinstance(top_k, int) or top_k <= 0:
        top_k = 3
    top_k = min(top_k, len(_FAKE_KB))

    seed_offset = len(query) % 3
    ranked = sorted(
        _FAKE_KB,
        key=lambda doc: (doc["score_seed"] - seed_offset),
        reverse=True,
    )
    hits = ranked[:top_k]

    return {
        "summary": f"Found {len(hits)} fake KB hits for query={query!r}.",
        "evidence": [
            {"id": hit["doc_id"], "label": hit["title"]} for hit in hits
        ],
        "next_action": (
            "Read top hit's snippet; if not relevant, narrow query and retry."
        ),
        "technical_id": hits[0]["doc_id"] if hits else "kb-empty",
        "raw_hits": [
            {"doc_id": hit["doc_id"], "title": hit["title"], "snippet": hit["snippet"]}
            for hit in hits
        ],
    }


# ---------------------------------------------------------------------------
# Fake failure classifier —— 根据 error_message 关键字做 deterministic 分类。
#
# 为什么不用真实 ML 模型：
# - sample 必须 deterministic；
# - 分类规则故意写得简单透明，让 reviewer 一眼就能看出"哦这只是关键字匹配
#   的 MVP，未来如果要接真实 classifier 我得在 when_to_use / output_contract
#   写清楚什么场景适用、什么不适用"。
# ---------------------------------------------------------------------------
_FAILURE_RULES: list[tuple[str, str]] = [
    ("timeout", "transient_network"),
    ("connection refused", "transient_network"),
    ("permission denied", "auth_or_permission"),
    ("unauthorized", "auth_or_permission"),
    ("yaml", "config_schema"),
    ("schema", "config_schema"),
    ("nonetype", "code_logic"),
    ("attributeerror", "code_logic"),
    ("keyerror", "code_logic"),
]


def classify_fake_tool_failure(error_message: str, trace_excerpt: str = "") -> dict[str, Any]:
    """根据 error_message + trace_excerpt 做 deterministic 失败归类。

    返回 ToolSpec output_contract 要求的 summary / evidence / next_action /
    technical_id。reviewer 接真实 classifier 时只需要替换 _FAILURE_RULES
    与匹配逻辑即可，**不需要**改 ToolSpec 字段。

    不负责
    -------
    - **不**做真实根因分析（真实 RCA 需要 transcript + repo + LLM judge，
      属于 v3.0 backlog）；
    - **不**根据 trace 行号定位代码（需要 source map / repo 上下文）；
    - **不**做严重度评估（需要 SLO / 业务上下文）。
    """
    if not isinstance(error_message, str) or not error_message.strip():
        return {
            "summary": "empty error_message",
            "cause": "error_message is required",
            "retryable": False,
            "suggested_fix": "Pass the first line of the failing tool's stderr.",
        }

    lower_msg = error_message.lower()
    lower_trace = trace_excerpt.lower() if isinstance(trace_excerpt, str) else ""
    matched_categories: list[str] = []
    matched_keywords: list[str] = []
    for keyword, category in _FAILURE_RULES:
        if keyword in lower_msg or keyword in lower_trace:
            matched_keywords.append(keyword)
            if category not in matched_categories:
                matched_categories.append(category)
    if not matched_categories:
        matched_categories = ["unknown"]

    primary = matched_categories[0]
    evidence_dicts: list[dict[str, str]] = (
        [{"id": f"failure-keyword-{kw}", "label": kw} for kw in matched_keywords]
        if matched_keywords
        else [{"id": f"failure-unknown-{len(error_message)}", "label": "unknown"}]
    )
    return {
        "summary": f"Classified failure as '{primary}'.",
        "evidence": evidence_dicts,
        "next_action": {
            "transient_network": "Retry once with backoff; verify outbound network policy.",
            "auth_or_permission": "Check the tool's token / role binding; do NOT auto-retry.",
            "config_schema": "Open the failing yaml; look for unresolved TODO placeholders.",
            "code_logic": "Open the file pointed to by the trace; this is not transient.",
            "unknown": "Capture more trace context before deciding to retry.",
        }[primary],
        "technical_id": f"failure-{primary}",
        "categories": matched_categories,
    }


# ---------------------------------------------------------------------------
# Fake config-snippet validator —— 简单 yaml 关键字检查（不真的 parse）。
#
# 为什么不调 yaml.safe_load：
# - 我们要 sample 完全 stdlib 化、零依赖（offline contract）；
# - 真实 reviewer 接手时如果要做严格 schema 校验，会用 jsonschema /
#   pydantic / 项目自有 validate-generated；这个 fake 只是做"看上去像
#   validator"的样例，让 reviewer 思考 token_policy / error_shape 怎么写。
# ---------------------------------------------------------------------------
def validate_fake_config_snippet(yaml_text: str) -> dict[str, Any]:
    """对 yaml 片段做 deterministic、纯关键字级的 fake validation。

    检查 3 类常见 reviewed-config 漏洞：
    1. 残留 TODO 占位 → 进入 strict 之前必须修；
    2. runnable=true 但同一片段里仍有 TODO → 最危险；
    3. 既没有 'tools:' 也没有 'evals:' → 大概率不是 ATH 的 yaml。

    不负责
    -------
    - **不**做真正的 yaml parse；
    - **不**校验 schema；
    - **不**关心字段值是否业务上正确（业务正确性必须 reviewer 自己看）。
    """
    if not isinstance(yaml_text, str):
        return {
            "summary": "yaml_text must be a string",
            "cause": "non-string input",
            "retryable": False,
            "suggested_fix": "Pass the file content as a UTF-8 string.",
        }

    issues: list[str] = []
    evidence_dicts: list[dict[str, str]] = []

    if "TODO" in yaml_text:
        issues.append("residual_todo")
        evidence_dicts.append({"id": "yaml-contains-TODO", "label": "residual TODO placeholder"})
    if "runnable: true" in yaml_text and "TODO" in yaml_text:
        issues.append("runnable_with_todo")
        evidence_dicts.append({"id": "runnable-true-and-TODO", "label": "runnable+TODO coexist"})
    if "tools:" not in yaml_text and "evals:" not in yaml_text:
        issues.append("not_an_ath_yaml")
        evidence_dicts.append({
            "id": "no-tools-or-evals-key",
            "label": "missing tools:/evals: root",
        })

    if not issues:
        evidence_dicts.append({"id": "yaml-no-known-issues", "label": "fake validator clean"})

    return {
        "summary": (
            f"Found {len(issues)} potential issue(s): {issues}"
            if issues
            else "No known issues detected by the fake validator."
        ),
        "evidence": evidence_dicts,
        "next_action": (
            "Strip residual TODO placeholders before promoting to reviewed config."
            if issues
            else "Snippet looks structurally OK; reviewer must still verify business semantics."
        ),
        "technical_id": (
            f"fake-validate-{issues[0]}" if issues else "fake-validate-clean"
        ),
        "issues": issues,
    }
