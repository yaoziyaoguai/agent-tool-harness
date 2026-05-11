"""Runtime assembly 层 — Demo/Core/Real 边界的第一道闸门。

当前只支持 demo/mock runtime。
未来 RealAgentAdapter / JudgeProvider / ProviderConfig 必须通过这里显式 opt-in 接入。

架构边界：
- **负责**：把 CLI 参数转成 AgentAdapter 实例，隐藏具体 adapter 类型。
- **不负责**：不实现真实 Agent、不读取 .env、不调用外部 API。
- **为什么 CLI 不应该直接硬编码 MockReplayAdapter**：
  CLI 是 Core 的装配层，不应直接依赖 Demo 实现。
  通过 assembly 函数接入，让未来 Real Integration 可以替换 adapter 而不修改 CLI 结构。
"""

from __future__ import annotations

from pathlib import Path

from agent_tool_harness.agents.agent_adapter_base import AgentAdapter


def build_demo_runtime(mock_path: str = "good") -> AgentAdapter:
    """装配当前 demo/mock runtime 的 AgentAdapter。

    当前实现：返回 MockReplayAdapter，按 good/bad 分支回放工具调用。
    signal_quality = tautological_replay。

    未来 Real Integration 必须：
    - 通过独立的 factory 函数接入（如 build_real_runtime）
    - 显式 opt-in（--live --confirm-i-have-real-key）
    - 不通过此函数混入 demo path
    """
    from agent_tool_harness.agents.mock_replay_adapter import (
        MockReplayAdapter,
    )

    return MockReplayAdapter(mock_path)


def build_replay_runtime(source_run: str | Path) -> AgentAdapter:
    """装配历史轨迹重放 runtime 的 AgentAdapter。

    当前实现：返回 TranscriptReplayAdapter，按历史 transcript 重放。
    signal_quality = recorded_trajectory。
    """
    from agent_tool_harness.agents.transcript_replay_adapter import (
        TranscriptReplayAdapter,
    )

    return TranscriptReplayAdapter(source_run)
