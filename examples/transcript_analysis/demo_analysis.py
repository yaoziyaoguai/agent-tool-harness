"""v3.5 Demo: Transcript + Context Analysis 完整演示。

此脚本演示：
1. 构造含已知 confusion/inefficiency pattern 的 ExecutionTrace
2. 运行 TranscriptPatternAnalyzer 和 ContextEfficiencyAnalyzer
3. 渲染 Markdown 和 JSON 报告

零网络依赖，不调 LLM。
"""

from agent_tool_harness.analysis import (
    ContextEfficiencyAnalyzer,
    TranscriptPatternAnalyzer,
    render_analysis_json,
    render_analysis_markdown,
)
from agent_tool_harness.core_contract import ExecutionTrace, ToolCall, ToolResult


def build_demo_trace() -> ExecutionTrace:
    """构造含 3 种 confusion + 2 种 inefficiency pattern 的演示 trace。

    场景: Agent 试图搜索错误信息 → 反复重试同一查询 → 在两个工具间切来切去 →
         最终答案缺乏工具支撑。
    """
    calls = [
        # 正常搜索
        ToolCall(tool_name="search", arguments={"query": "disk full error"}, call_id="c1"),
        # 开始重复重试（3 次相同 args）
        ToolCall(tool_name="search", arguments={"query": "disk full error"}, call_id="c2"),
        ToolCall(tool_name="search", arguments={"query": "disk full error"}, call_id="c3"),
        ToolCall(tool_name="search", arguments={"query": "disk full error"}, call_id="c4"),
        # 在 search / read 间切来切去
        ToolCall(tool_name="read", arguments={"path": "/var/log/syslog"}, call_id="c5"),
        ToolCall(tool_name="search", arguments={"query": "error log"}, call_id="c6"),
        ToolCall(tool_name="read", arguments={"path": "/var/log/auth.log"}, call_id="c7"),
        ToolCall(tool_name="search", arguments={"query": "auth failure"}, call_id="c8"),
        # 微调参数重试
        ToolCall(tool_name="grep", arguments={"pattern": "Error 500"}, call_id="c9"),
        ToolCall(tool_name="grep", arguments={"pattern": "Error 500."}, call_id="c10"),
        # 搜索范围越来越大
        ToolCall(tool_name="search", arguments={"query": "null pointer exception in auth"}, call_id="c11"),
        ToolCall(tool_name="search", arguments={"query": "null pointer"}, call_id="c12"),
        ToolCall(tool_name="search", arguments={"query": "error"}, call_id="c13"),
    ]

    results = [
        ToolResult(call_id="c1", tool_name="search", output={"matches": ["syslog"]}),
        ToolResult(call_id="c2", tool_name="search", output={"matches": ["syslog"]}),
        ToolResult(call_id="c3", tool_name="search", output={"matches": ["syslog"]}),
        ToolResult(call_id="c4", tool_name="search", output={"matches": ["syslog"]}),
        ToolResult(call_id="c5", tool_name="read", output={
            "content": "normal log entry", "lines": 500,
        }),
        ToolResult(call_id="c6", tool_name="search", output={"matches": ["auth.log"]}),
        ToolResult(call_id="c7", tool_name="read", output={
            "content": "auth failure at 03:15", "lines": 200,
        }),
        ToolResult(call_id="c8", tool_name="search", output={
            "matches": ["result"] * 30,  # 30 条结果，无分页
        }),
        ToolResult(call_id="c9", tool_name="grep", output={"found": False}),
        ToolResult(call_id="c10", tool_name="grep", output={"found": False}),
        ToolResult(call_id="c11", tool_name="search", output={"matches": []}),
        ToolResult(call_id="c12", tool_name="search", output={"matches": []}),
        ToolResult(call_id="c13", tool_name="search", output={
            "matches": ["result"] * 25,  # 25 条结果，无分页
        }),
    ]

    return ExecutionTrace(
        scenario_id="demo_confusion_trace",
        tool_calls=calls,
        tool_results=results,
        messages=[],
        final_answer=(
            "The application crashed because the database connection pool "
            "was exhausted and the system failed to allocate memory buffers "
            "during the peak load period"
        ),
    )


def main():
    trace = build_demo_trace()
    print(f"场景: {trace.scenario_id}")
    print(f"Tool 调用次数: {len(trace.tool_calls)}")
    print(f"Tool 返回次数: {len(trace.tool_results)}")
    print()

    # 运行 TranscriptPatternAnalyzer
    print("=" * 60)
    print("TranscriptPatternAnalyzer 结果")
    print("=" * 60)
    tpa = TranscriptPatternAnalyzer()
    transcript_findings = tpa.analyze(trace)
    for f in transcript_findings:
        print(f"  [{f.severity}] {f.rule_type}: {f.message}")

    print()

    # 运行 ContextEfficiencyAnalyzer
    print("=" * 60)
    print("ContextEfficiencyAnalyzer 结果")
    print("=" * 60)
    cea = ContextEfficiencyAnalyzer()
    context_findings = cea.analyze(trace)
    for f in context_findings:
        print(f"  [{f.severity}] {f.rule_type}: {f.message}")

    print()

    # 合并 findings 并渲染报告
    all_findings = transcript_findings + context_findings
    print("=" * 60)
    print("Markdown 报告")
    print("=" * 60)
    print(render_analysis_markdown(all_findings))

    print("=" * 60)
    print("JSON 报告")
    print("=" * 60)
    import json
    json_report = render_analysis_json(all_findings)
    print(json.dumps(json_report, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
