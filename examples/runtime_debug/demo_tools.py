from __future__ import annotations

from typing import Any


def runtime_trace_event_chain(args: dict[str, Any]) -> dict[str, Any]:
    """Demo trace 工具。

    这个文件属于 example，不属于框架核心。它模拟用户项目提供的确定性工具，供
    PythonToolExecutor 调用并产出 recorder/judge 可验证的 evidence。
    """

    trace_id = args["trace_id"]
    return {
        "summary": "Trace shows a boundary mismatch before the next agent step.",
        "technical_id": trace_id,
        "evidence": [
            {
                "id": "ev-17",
                "type": "trace_event",
                "label": "Input accepted after checkpoint restore boundary",
                "root_cause_hint": "input_boundary",
                "checkpoint_id": "ckpt-input-17",
            }
        ],
        "next_action": "Inspect checkpoint ckpt-input-17 to confirm stale input buffer state.",
    }


def runtime_inspect_checkpoint(args: dict[str, Any]) -> dict[str, Any]:
    """Demo checkpoint 工具，返回可验证 checkpoint evidence。"""

    checkpoint_id = args["checkpoint_id"]
    return {
        "summary": "Checkpoint contains a stale input buffer carried across restore.",
        "technical_id": checkpoint_id,
        "evidence": [
            {
                "id": checkpoint_id,
                "type": "checkpoint_state",
                "label": "stale_input_buffer=true",
                "root_cause_hint": "input_boundary",
            }
        ],
        "next_action": "Fix boundary validation and clear stale input on restore.",
    }


def tui_inspect_snapshot(args: dict[str, Any]) -> dict[str, Any]:
    """Demo TUI snapshot 工具。

    它只能证明 UI 症状，不能证明 runtime root cause。bad path 会故意只调用这个工具。
    """

    session_id = args["session_id"]
    return {
        "summary": "Snapshot shows stale text still visible in the terminal pane.",
        "technical_id": session_id,
        "evidence": [
            {
                "id": "snap-03",
                "type": "tui_snapshot",
                "label": "visible stale terminal text",
                "root_cause_hint": "ui_rendering",
            }
        ],
        "next_action": "Use runtime trace evidence before assigning root cause.",
    }
