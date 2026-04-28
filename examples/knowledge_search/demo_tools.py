"""knowledge_search 第二 example 的 demo 工具实现。

这个文件属于 example，**不属于** ``agent_tool_harness`` 框架核心。它存在的意义有三个：

1. 给 ``PythonToolExecutor`` 一组确定性可调用函数，让 ``MockReplayAdapter`` 在 good/bad
   两条路径上都能真实地走 recorder → tool_calls → tool_responses → judge 链路。
2. 证明 harness 的核心代码不依赖任何特定业务（runtime_debug 是 trace/checkpoint/ui，
   knowledge_search 是 KB 检索/文章/canned reply），同一份 ``MockReplayAdapter`` /
   ``RuleJudge`` / ``TranscriptAnalyzer`` 可以无缝复用——任何"框架核心硬编码本 example
   工具名 / 字段名"的反模式都会立刻导致这条 demo 跑不通。
3. 给真实接入者一份**最小**的 Python 工具样例：每个函数都是 ``def f(args: dict) -> dict``
   形态，不导入框架内部模块，不依赖 LLM/网络/磁盘——读者把它复制到自己的项目里只需要
   替换 evidence 数据即可。

这一层负责什么、不负责什么：
- **负责**：返回与 ``tools.yaml`` 中 ``output_contract.required_fields``
  （summary / evidence / next_action / technical_id）一致的 dict，让 RuleJudge
  ``must_use_evidence`` 等规则能拿到可验证的 evidence id。
- **不负责**：真实检索、真实 KB 数据、ranking、缓存、权限校验。这些都是用户自己的
  生产实现要做的事；example 在这里只用 deterministic 字典模拟。

哪些只是 MVP / mock / demo（防止读者误用）：
- 这里的 "kb-sso-014" 等字符串是为了让 ``MockReplayAdapter`` 能命中并产出可被
  RuleJudge 验证的 evidence；它们不是真实 KB id。
- ``suggest_canned_response`` 故意不返回任何 article id，正是用来在 bad path 演示
  "跳过 evidence 直接给 canned reply" 这种 Agent 工具选择失败模式。

如何通过 artifacts 查问题：
- 这些函数的返回值会被 ``RunRecorder`` 写入 ``runs/<dir>/tool_responses.jsonl``；
  ``RuleJudge.must_use_evidence`` 会要求 final answer 至少引用其中一个 evidence id；
  ``TranscriptAnalyzer`` 会把 "调用了 canned 但没调 search/fetch" 归到
  ``agent_tool_choice`` category。读者排查时按 ``transcript.jsonl`` →
  ``tool_calls.jsonl`` → ``tool_responses.jsonl`` → ``judge_results.json`` →
  ``diagnosis.json`` → ``report.md`` 的顺序看即可。

未来扩展点（仅 ROADMAP 想法，不在本 example 实现）：
- 接真实 KB 后端（OpenSearch / Postgres FTS / 向量检索）；
- 接 canned response 审批工作流；
- 引入多语种文章 + 语种识别。
本 example 故意保持极小，避免把"演示"变成另一份生产代码。
"""

from __future__ import annotations

from typing import Any

# ---------------------------------------------------------------------------
# Demo 数据。把所有"假数据"集中在这里而不是散落在函数里，是为了让真实接入者一眼
# 看到"这块是 MVP 演示用，不要直接用在生产"。
# ---------------------------------------------------------------------------

_DEMO_ARTICLES: dict[str, dict[str, Any]] = {
    "kb-sso-014": {
        "title": "SAML SP-initiated session loss after a few minutes",
        "category": "sso_misconfiguration",
        "summary_label": "AssertionConsumerService 未对齐导致 session cookie 被丢弃",
        "next_action_label": (
            "在 IdP 与 SP 端对齐 ACS URL 与 NameID format，"
            "并放行 SameSite cookie。"
        ),
    },
}


def search_articles(args: dict[str, Any]) -> dict[str, Any]:
    """模拟 KB 全文检索。

    输入：``query``（必填）、``top_k``（可选，默认 3）。
    输出：与 ``output_contract.required_fields`` 对齐的 dict——必带
    ``summary`` / ``evidence`` / ``next_action`` / ``technical_id``。
    每条 evidence 都带 ``id``、``label``、``root_cause_hint``，让 RuleJudge 的
    ``must_use_evidence`` / ``expected_root_cause_contains`` 能验证 final answer。
    """

    query = args["query"]
    matches: list[dict[str, Any]] = []
    for article_id, article in _DEMO_ARTICLES.items():
        matches.append(
            {
                "id": article_id,
                "type": "article_match",
                "label": article["title"],
                "root_cause_hint": article["category"],
            }
        )
    return {
        "summary": f"Found {len(matches)} candidate article(s) for query: {query}.",
        "technical_id": f"search:{query}",
        "evidence": matches,
        "next_action": (
            "Fetch the top candidate article in full via kb.article.fetch_article "
            "before drafting the user-facing reply."
        ),
    }


def fetch_article(args: dict[str, Any]) -> dict[str, Any]:
    """按 article_id 取回完整文章。

    返回结构与 search_articles 对齐（同 4 必填字段）。这里把文章 id 重新作为 evidence id
    暴露出来，是为了让 ``MockReplayAdapter._evidence_ids`` 能从 verifiable_outcome 与工具
    响应两路汇总到同一个引用，避免 good path 凭空捏 id。
    """

    article_id = args["article_id"]
    article = _DEMO_ARTICLES.get(article_id)
    if article is None:
        # 缺失 id 仍返回 actionable error，而不是抛异常——artifact 里就能看到失败证据。
        return {
            "summary": f"Article {article_id} not found in the demo index.",
            "technical_id": article_id,
            "evidence": [],
            "next_action": "Re-run kb.search.search_articles with a refined query.",
        }
    return {
        "summary": article["summary_label"],
        "technical_id": article_id,
        "evidence": [
            {
                "id": article_id,
                "type": "article_body",
                "label": article["title"],
                "root_cause_hint": article["category"],
            }
        ],
        "next_action": article["next_action_label"],
    }


def suggest_canned_response(args: dict[str, Any]) -> dict[str, Any]:
    """返回 canned reply 模板。

    刻意**不**返回任何 article id 类的 evidence——这正是 bad path 想暴露的失败模式：
    Agent 跳过 search/fetch，直接拿 canned 回答用户，最终在 ``judge_results.json``
    会因 ``must_use_evidence`` / ``forbidden_first_tool`` 双重失败。
    """

    category = args["category"]
    return {
        "summary": (
            f"Canned response template for category '{category}' "
            "(no article evidence cited)."
        ),
        "technical_id": f"canned:{category}",
        "evidence": [
            {
                "id": f"canned:{category}",
                "type": "canned_template",
                "label": "Generic apology + escalation template",
            }
        ],
        "next_action": (
            "Do not ship this template alone—first run kb.search.search_articles "
            "and kb.article.fetch_article to attach a real article citation."
        ),
    }
