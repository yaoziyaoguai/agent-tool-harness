"""Toy CLI agent —— 用于 C10 Level 2 dogfood 的最小非私密 CLI agent。

与 fake_agent.py 的区别：
- fake_agent: 对 available_tools 中每个工具都发调用（全量调用）
- toy_agent: 根据 scenario goal 决定调用哪些工具（模拟"按需选工具"）

行为:
- 读取 scenario input JSON（scenario_id + goal + available_tools）
- 根据 goal 关键词选择工具:
  - goal 含 "search"/"搜索"/"查找" → 调用 knowledge.search
  - goal 含 "trace"/"lookup"/"查询" → 调用 trace.lookup
  - goal 含 "both"/"both-tools"/"双工具" → 调用两者
  - 默认 → 调用 available_tools 中的第一个
- 产出 native ExecutionTrace JSON

所有行为 deterministic，零网络依赖，不读 .env，不调用真实 LLM。

用法:
    python toy_agent.py --input scenario_input.json --trace-out trace_output.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path


def _select_tools(goal: str, available_tools: list[str]) -> list[str]:
    """根据 goal 关键词选择工具——deterministic 规则。"""
    goal_lower = goal.lower()
    selected: list[str] = []

    if any(kw in goal_lower for kw in ("both", "both-tools", "双工具")):
        return [t for t in available_tools]

    has_search = any(kw in goal_lower for kw in ("search", "搜索", "查找"))
    has_trace = any(kw in goal_lower for kw in ("trace", "lookup", "查询", "追踪"))

    if has_search:
        for t in available_tools:
            if "search" in t:
                selected.append(t)
                break
    if has_trace or not selected:
        for t in available_tools:
            if "lookup" in t or "trace" in t.split("."):
                selected.append(t)
                break

    if not selected and available_tools:
        selected.append(available_tools[0])

    return selected


def run(scenario_input: Path, trace_output: Path) -> None:
    if not scenario_input.exists():
        print(f"ERROR: scenario input file not found: {scenario_input}", file=sys.stderr)
        sys.exit(2)

    data = json.loads(scenario_input.read_text(encoding="utf-8"))
    scenario_id = data.get("scenario_id", "unknown")
    goal = data.get("goal", "")
    available_tools = data.get("available_tools", [])
    ts = datetime.now(UTC).isoformat()

    selected = _select_tools(goal, available_tools)

    tool_calls = []
    tool_results = []
    for i, tool_name in enumerate(selected):
        call_id = f"tc{i + 1}"
        tool_calls.append({
            "call_id": call_id,
            "tool_name": tool_name,
            "arguments": {"scenario": scenario_id, "goal": goal},
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
        f"Toy agent selected {len(selected)}/{len(available_tools)} tools "
        f"based on goal '{goal[:60]}'."
    )

    trace = {
        "scenario_id": scenario_id,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "final_answer": final_answer,
    }

    trace_output.parent.mkdir(parents=True, exist_ok=True)
    trace_output.write_text(
        json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"Toy agent: {len(tool_calls)} tool call(s) based on goal, trace → {trace_output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Toy CLI agent for C10 Level 2 dogfood")
    parser.add_argument("--input", required=True, dest="input_path")
    parser.add_argument("--trace-out", required=True, dest="trace_output")
    args = parser.parse_args()
    run(Path(args.input_path), Path(args.trace_output))


if __name__ == "__main__":
    main()
