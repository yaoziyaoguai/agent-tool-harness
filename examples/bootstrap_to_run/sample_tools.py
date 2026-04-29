"""bootstrap_to_run sample tools —— 安全的纯函数 demo 工具。

存在意义
--------
为 examples/bootstrap_to_run/ sample pack 提供"reviewed 之后能真跑 run"
的工具实现。和 tests/fixtures/sample_tool_project/ 不同：

- 那个是给 scaffold-tools 静态扫描用的（含 tools_unsafe.py canary）；
- 这个是给 reviewer 跑 deterministic smoke run 用的——必须每个函数都
  返回真实 dict（含 summary / evidence / next_action 等 ToolSpec 契约
  字段），让 PythonToolExecutor 能真的 import 并调用。

边界（**v2.x**，不是 v3.0）
---------------------------
- 纯函数 / 零 IO / 零网络 / 零 .env 读取；
- 不调真实 LLM；
- 不 import 任何不可信代码；
- 模块顶层**绝不** raise（与 sample_tool_project/tools_unsafe.py 完全相反，
  本文件是 production-imitation 的安全示例）。
"""

from __future__ import annotations

from typing import Any


def lookup_user_status(user_id: str, include_recent_actions: bool = False) -> dict[str, Any]:
    """查询用户当前 status（deterministic stub）。

    返回 ToolSpec output_contract 要求的 summary / evidence / next_action 字段；
    evidence 用稳定 id 让 RuleJudge `must_use_evidence` 能匹配。
    """
    base_evidence = [f"user-status-{user_id}"]
    if include_recent_actions:
        base_evidence.append(f"recent-actions-{user_id}")
    return {
        "summary": f"User {user_id} has status=active.",
        "evidence": base_evidence,
        "next_action": (
            "如需进一步排查，请调用 inspect_user_session 看会话级信息。"
        ),
        "technical_id": f"user-status-{user_id}",
    }


def inspect_user_session(session_id: str) -> dict[str, Any]:
    """查询会话级别证据（deterministic stub）。

    与 lookup_user_status 配对，让 reviewed evals.yaml 能写出"先看 user
    status 再看 session"的多步 required_tools 链路，验证整个 bootstrap
    chain 端到端能进入 run。
    """
    return {
        "summary": f"Session {session_id} is healthy; no boundary violations.",
        "evidence": [f"session-{session_id}", "boundary-check-ok"],
        "next_action": "可以给出最终结论，无需进一步调查。",
        "technical_id": f"session-{session_id}",
    }
