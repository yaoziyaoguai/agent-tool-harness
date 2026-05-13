"""Level 3 local-only dogfood adapter: my-first-agent demo → native ExecutionTrace.

架构边界（为什么 wrapper 放在 agent-tool-harness 侧）：
- my-first-agent 目前还在开发中，其 demo CLI（``main.py demo``）不输出结构化
  trace 文件，trace 格式（span-based TraceEvent）也与 agent-tool-harness native
  schema 完全不同。
- 本轮不修改 my-first-agent——只在本侧写一个 thin adapter，把 ``run_local_demo()``
  的返回值（DemoResult）转换为 native ExecutionTrace JSON。
- 这是 Level 3 local-only wrapper dogfood：不读 .env、不联网、不调真实 LLM/API。

为什么不改 my-first-agent：
- 本轮边界是 agent-tool-harness 侧能力 inspection + wrapper dogfood。
- 修改 my-first-agent 需要其自身的 Coding Agent 流程，不在本轮范围。
- 如果后续 my-first-agent 自己加 native trace 输出，本 wrapper 可退役。

wrapper 只做 schema 适配，不承担评测语义：
- 输入：ScenarioSpec JSON（scenario_id + goal/task/prompt）
- 调用：my-first-agent 的 run_local_demo()
- 输出：native ExecutionTrace JSON → trace_output_path
- RuleJudge / CoreEvaluation 仍由 agent-tool-harness Core Flow 负责

用法（由 CLIAgentAdapter subprocess 调用）:
    python adapter.py --input scenario_input.json --trace-out trace_output.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# my-first-agent 路径解析
# ---------------------------------------------------------------------------

def _resolve_agent_path() -> Path:
    """解析 my-first-agent 项目根路径。

    必须设置环境变量 MY_FIRST_AGENT_PATH，指向 my-first-agent 项目根目录。
    不提供默认值——避免将本地路径硬编码到可提交代码中。
    """
    env_path = os.getenv("MY_FIRST_AGENT_PATH", "")
    if not env_path:
        print(
            "ERROR: MY_FIRST_AGENT_PATH environment variable must be set to the "
            "my-first-agent project root directory.",
            file=sys.stderr,
        )
        sys.exit(2)
    return Path(env_path).expanduser().resolve()


# ---------------------------------------------------------------------------
# 输入解析
# ---------------------------------------------------------------------------

_REQUIRED_INPUT_KEYS = ("scenario_id",)
_GOAL_CANDIDATE_KEYS = ("goal", "task", "prompt", "user_prompt")


class AdapterInputError(ValueError):
    """wrapper 输入不合法时抛出——exit code 2，不生成伪成功 trace。"""


def _read_scenario_input(path: Path) -> dict[str, Any]:
    """读取 ScenarioSpec JSON，校验必要字段。"""
    if not path.exists():
        raise AdapterInputError(f"scenario input file not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise AdapterInputError(f"invalid JSON in scenario input: {exc}") from exc
    if not isinstance(data, dict):
        raise AdapterInputError("scenario input must be a JSON object")

    for key in _REQUIRED_INPUT_KEYS:
        if not data.get(key):
            raise AdapterInputError(
                f"scenario input missing required field: {key!r}"
            )

    goal = None
    for key in _GOAL_CANDIDATE_KEYS:
        if data.get(key):
            goal = data[key]
            break
    if not goal:
        raise AdapterInputError(
            f"scenario input must provide one of: {_GOAL_CANDIDATE_KEYS}"
        )
    data["_resolved_goal"] = goal
    return data


# ---------------------------------------------------------------------------
# DemoResult → native ExecutionTrace 转换
# ---------------------------------------------------------------------------


def _demo_result_to_native_trace(
    result: Any,  # agent.local_demo.DemoResult（避免顶层 import 用 Any）
    scenario_id: str,
) -> dict[str, Any]:
    """把 DemoResult 转换为 native ExecutionTrace JSON dict。

    映射规则：
    - 每个 DemoStep → 一对 tool_call + tool_result
    - call_id 由 wrapper 生成（c1, c2, ...）
    - tool_call.arguments ← PlannedAction.tool_input
    - tool_result.output.evidence ← 从 envelope 构造 evidence ID
    - final_answer ← DemoResult.final_answer
    - metadata 标注 source_agent / level / adapter
    """
    ts = datetime.now(UTC).isoformat()
    tool_calls: list[dict[str, Any]] = []
    tool_results: list[dict[str, Any]] = []

    for i, step in enumerate(result.steps):
        call_id = f"c{i + 1}"
        tool_name = step.action.tool_name
        arguments = dict(step.action.tool_input)

        tool_calls.append({
            "call_id": call_id,
            "tool_name": tool_name,
            "arguments": arguments,
            "timestamp": ts,
        })

        status = "success" if step.envelope.status == "executed" else "error"
        evidence_id = f"ev-{i + 1:03d}"
        output: dict[str, Any] = {
            "evidence": [
                {
                    "id": evidence_id,
                    "label": f"{tool_name}: {step.envelope.status}",
                }
            ],
            "summary": step.envelope.safe_preview,
            "content_length": step.envelope.content_length,
        }
        error = None if step.envelope.status == "executed" else (
            step.envelope.error_type or "demo_step_failed"
        )

        tool_results.append({
            "call_id": call_id,
            "tool_name": tool_name,
            "status": status,
            "output": output,
            "error": error,
        })

    evidence_ids = [
        eid
        for tr in tool_results
        for ev in tr.get("output", {}).get("evidence", [])
        for eid in [ev.get("id", "")]
    ]

    final_answer = (
        f"Root cause: demo completed. Evidence: {', '.join(evidence_ids)}. "
        f"{result.final_answer}"
    )

    return {
        "scenario_id": scenario_id,
        "tool_calls": tool_calls,
        "tool_results": tool_results,
        "final_answer": final_answer,
        "messages": [],
        "metadata": {
            "source_agent": "my-first-agent local demo",
            "level": "3 local-only wrapper dogfood",
            "adapter": "agent-tool-harness examples/my_first_agent_demo/adapter.py",
            "provider": getattr(result, "provider", "unknown"),
            "workspace": str(getattr(result, "workspace", "")),
        },
    }


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------


def run(input_path: Path, trace_output_path: Path) -> None:
    """读取 scenario input → 调用 run_local_demo() → 写入 native trace。

    不读 .env、不联网、不调真实 LLM/API。
    """
    data = _read_scenario_input(input_path)
    scenario_id = data["scenario_id"]
    goal = data["_resolved_goal"]

    agent_root = _resolve_agent_path()
    if not agent_root.exists():
        print(
            f"ERROR: my-first-agent path not found: {agent_root}\n"
            f"Set MY_FIRST_AGENT_PATH env var to the correct path.",
            file=sys.stderr,
        )
        sys.exit(2)

    # 把 my-first-agent 加入 import path（不修改 my-first-agent）
    agent_str = str(agent_root)
    if agent_str not in sys.path:
        sys.path.insert(0, agent_str)

    try:
        from agent.local_demo import run_local_demo
    except ImportError as exc:
        print(
            f"ERROR: cannot import run_local_demo from my-first-agent at {agent_root}\n"
            f"Details: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)

    # 使用 tmpdir 作为 demo workspace，避免污染 my-first-agent 项目目录
    import tempfile

    workspace = Path(tempfile.mkdtemp(prefix="agent2harness_demo_"))
    try:
        result = run_local_demo(goal, workspace=workspace)
    except Exception as exc:
        print(f"ERROR: run_local_demo() failed: {exc}", file=sys.stderr)
        sys.exit(3)

    trace = _demo_result_to_native_trace(result, scenario_id)

    trace_output_path.parent.mkdir(parents=True, exist_ok=True)
    trace_output_path.write_text(
        json.dumps(trace, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"adapter: {len(trace['tool_calls'])} tool call(s) for scenario "
        f"'{scenario_id}', trace → {trace_output_path}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Level 3 dogfood adapter: my-first-agent demo → native trace"
    )
    parser.add_argument(
        "--input", required=True, dest="input_path",
        help="ScenarioSpec JSON input path",
    )
    parser.add_argument(
        "--trace-out", required=True, dest="trace_output_path",
        help="Native ExecutionTrace JSON output path",
    )
    args = parser.parse_args()
    run(Path(args.input_path), Path(args.trace_output_path))


if __name__ == "__main__":
    main()
