"""v3.6 Demo: Tool Portfolio Review + Improvement Brief 完整演示。

演示：
1. 构造含已知结构问题的 ToolSpec 列表
2. 运行 ToolPortfolioReview（5 类检查）
3. 运行 ToolImprovementBriefGenerator（per-tool + cross-tool）
4. 渲染 Markdown 和 JSON 报告

零网络依赖，不调 LLM。
"""

from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.core_contract import RuleFinding
from agent_tool_harness.portfolio import (
    ToolImprovementBriefGenerator,
    ToolPortfolioReview,
)
from agent_tool_harness.portfolio.render import (
    render_improvement_brief_markdown,
    render_portfolio_analysis_json,
    render_portfolio_review_markdown,
)


def build_demo_tool_specs() -> list[ToolSpec]:
    """构造含已知结构问题的工具列表。

    场景:
    - search / read / write 无 namespace（触发 namespacing_consistency）
    - search_files 与 search_file 名称仅差 1 字符（触发 overlapping_tools）
    - get_data 描述空洞（触发 shallow_wrappers）
    - 其余工具正常
    """
    tools_data = [
        {
            "name": "search", "namespace": "",
            "description": "Search for documents.",
        },
        {
            "name": "read", "namespace": "",
            "description": "Read document content.",
        },
        {
            "name": "write", "namespace": "",
            "description": "Write data to storage.",
        },
        {
            "name": "search_files", "namespace": "fs",
            "description": "Search filesystem for files matching criteria.",
        },
        {
            "name": "search_file", "namespace": "fs",
            "description": "Search filesystem for a file matching criteria.",
        },
        {
            "name": "get_data", "namespace": "",
            "description": "Get the data.",
        },
        {
            "name": "doc_index", "namespace": "doc",
            "description": "Index documents for full-text search.",
        },
        {
            "name": "doc_query", "namespace": "doc",
            "description": "Query indexed documents with filter support.",
        },
    ]

    specs = []
    for td in tools_data:
        specs.append(ToolSpec.from_dict({
            "name": td["name"],
            "namespace": td["namespace"],
            "version": "0.1",
            "description": td["description"],
            "when_to_use": "Use when appropriate.",
            "when_not_to_use": "Do not use otherwise.",
            "input_schema": {"type": "object", "properties": {}},
            "output_contract": {"required_fields": ["result"]},
            "token_policy": {"max_output_tokens": 1000},
            "side_effects": {"destructive": False},
            "executor": {
                "type": "python", "path": "demo.py",
                "function": td["name"],
            },
        }))
    return specs


def build_demo_findings() -> list[RuleFinding]:
    """构造 v3.1-v3.5 累积 findings。"""
    return [
        RuleFinding(
            finding_id="f-search-bloat",
            severity="warning",
            category="rule",
            message="search 工具响应膨胀",
            evidence_ref="tool:search",
            rule_type="context.response_bloat",
            rule_passed=False,
        ),
        RuleFinding(
            finding_id="f-search-pagination",
            severity="medium",
            category="rule",
            message="search 工具缺少分页参数",
            evidence_ref="tool:search",
            rule_type="context.missing_pagination",
            rule_passed=False,
        ),
        RuleFinding(
            finding_id="tqj-chained-0",
            severity="info",
            category="judge",
            message="2 tool pair(s) appear repeatedly: 'search→read' (4x)",
            evidence_ref="trace.tool_calls[*].tool_name",
            rule_type="frequently_chained_tools",
            rule_passed=False,
        ),
        RuleFinding(
            finding_id="tqj-chained-1",
            severity="info",
            category="judge",
            message="1 tool pair(s) appear repeatedly: 'read→write' (3x)",
            evidence_ref="trace.tool_calls[*].tool_name",
            rule_type="frequently_chained_tools",
            rule_passed=False,
        ),
        RuleFinding(
            finding_id="tqj-chained-2",
            severity="info",
            category="judge",
            message="1 tool pair(s) appear repeatedly: 'search→write' (3x)",
            evidence_ref="trace.tool_calls[*].tool_name",
            rule_type="frequently_chained_tools",
            rule_passed=False,
        ),
        RuleFinding(
            finding_id="ts-retry",
            severity="warning",
            category="transcript",
            message="search 重复调用 3 次",
            evidence_ref="tool:search",
            rule_type="transcript.repeated_tool_retry_loop",
            rule_passed=False,
        ),
    ]


def main():
    tools = build_demo_tool_specs()
    findings = build_demo_findings()

    print(f"工具数: {len(tools)}")
    print(f"Findings 数: {len(findings)}")
    print()

    # 1. 运行 ToolPortfolioReview
    print("=" * 60)
    print("ToolPortfolioReview 结果")
    print("=" * 60)
    review = ToolPortfolioReview()
    portfolio_findings = review.review(tools, findings=findings)
    for pf in portfolio_findings:
        print(f"  [{pf.severity}] {pf.check_name}: {pf.description}")
        if pf.affected_tools:
            print(f"    受影响: {', '.join(pf.affected_tools[:3])}")

    print()

    # 2. 运行 ToolImprovementBriefGenerator (per-tool)
    print("=" * 60)
    print("ToolImprovementBriefGenerator (per-tool) 结果")
    print("=" * 60)
    generator = ToolImprovementBriefGenerator()
    for tool_name in ["search", "get_data", "read"]:
        brief = generator.generate_per_tool(tool_name, findings=findings)
        if brief:
            print(f"  [{brief.priority}] {brief.tool_name}: {brief.current_state}")
            print(f"    建议: {brief.recommended_state}")
            print(f"    工作: {brief.effort_estimate}")
        else:
            print(f"  {tool_name}: 无足够证据生成建议")

    print()

    # 3. 运行 ToolImprovementBriefGenerator (cross-tool)
    print("=" * 60)
    print("ToolImprovementBriefGenerator (cross-tool) 结果")
    print("=" * 60)
    cross_briefs = generator.generate_cross_tool(
        portfolio_findings=portfolio_findings,
    )
    for b in cross_briefs:
        print(f"  [{b.priority}] {b.tool_name}: {b.current_state[:80]}...")

    print()

    # 4. 渲染 Markdown 报告
    print("=" * 60)
    print("Markdown 报告 (Portfolio Review)")
    print("=" * 60)
    print(render_portfolio_review_markdown(portfolio_findings))

    print("=" * 60)
    print("Markdown 报告 (Improvement Briefs)")
    print("=" * 60)
    all_briefs = [
        b for b in (
            generator.generate_per_tool(t, findings=findings)
            for t in ["search", "get_data", "read", "write"]
        )
        if b is not None
    ]
    print(render_improvement_brief_markdown(all_briefs))

    # 5. JSON 报告
    print("=" * 60)
    print("JSON 报告")
    print("=" * 60)
    import json
    json_report = render_portfolio_analysis_json(
        portfolio_findings, all_briefs + cross_briefs,
    )
    print(json.dumps(json_report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
