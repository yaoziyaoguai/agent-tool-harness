"""Fake CLI agent —— 用于验证 CLIAgentAdapter → Core Flow 端到端闭环。

读取 Agent2Harness 生成的 scenario input JSON，模拟工具调用，产出 native
ExecutionTrace JSON。所有行为 deterministic，零网络依赖。

用法:
    python fake_agent.py --input scenario_input.json --trace-out trace_output.json

架构边界:
- **负责**: 模拟一次 Agent 工具调用链路
- **不负责**: 真实 LLM 推理、真实工具执行、真实 API 调用
- 仅用于集成测试，不作为真实 Agent 评测材料
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def run(scenario_input: Path, trace_output: Path) -> None:
    """读取 scenario input，模拟工具调用，写入 trace output。"""
    if not scenario_input.exists():
        print(f"ERROR: scenario input file not found: {scenario_input}", file=sys.stderr)
        sys.exit(2)

    data = json.loads(scenario_input.read_text(encoding="utf-8"))
    scenario_id = data.get("scenario_id", "unknown")
    available_tools = data.get("available_tools", [])
    ts = datetime.now(UTC).isoformat()

    # 模拟：对 available_tools 中的每个工具发起一次调用
    tool_calls = []
    tool_results = []
    for i, tool_name in enumerate(available_tools):
        call_id = f"c{i + 1}"
        tool_calls.append({
            "call_id": call_id,
            "tool_name": tool_name,
            "arguments": {"scenario": scenario_id},
            "timestamp": ts,
        })
        tool_results.append({
            "call_id": call_id,
            "tool_name": tool_name,
            "status": "success",
            "output": {
                "evidence": [{"id": f"ev-{i + 1:03d}", "label": f"evidence from {tool_name}"}],
                "summary": f"simulated {tool_name} result",
            },
            "error": None,
        })

    evidence_ids = ", ".join(
        eid for tr in tool_results
        for eid_obj in tr.get("output", {}).get("evidence", [])
        for eid in [eid_obj.get("id", "")]
    )

    final_answer = (
        f"Root cause: timeout. Evidence: {evidence_ids}. "
        f"Fake agent executed {len(tool_calls)} tool(s) for scenario '{scenario_id}': "
        + ", ".join(tc["tool_name"] for tc in tool_calls)
        + ". All tools returned success."
    )

    trace = {
        "scenario_id": scenario_id,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "final_answer": final_answer,
    }

    trace_output.parent.mkdir(parents=True, exist_ok=True)
    trace_output.write_text(json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Fake agent completed: {len(tool_calls)} tool call(s), trace → {trace_output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Fake CLI agent for Agent2Harness testing")
    parser.add_argument("--input", required=True, dest="input_path", help="Scenario input JSON")
    parser.add_argument("--trace-out", required=True, dest="trace_output", help="Trace output JSON")
    args = parser.parse_args()

    run(Path(args.input_path), Path(args.trace_output))


if __name__ == "__main__":
    main()
