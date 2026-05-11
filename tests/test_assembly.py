"""assembly 层测试 — 验证 Demo/Core 边界解耦。

测试纪律：
- 不允许为了绿而放宽断言。
- 如果未来 Real Integration 接入，assembly 的 factory 函数需要独立测试。
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_tool_harness.assembly import build_demo_runtime, build_replay_runtime

SIGNAL_TAUTOLOGICAL = "tautological_replay"
SIGNAL_RECORDED = "recorded_trajectory"


def test_build_demo_runtime_returns_agent_adapter():
    """build_demo_runtime 返回 MockReplayAdapter，signal_quality = tautological_replay。"""
    adapter = build_demo_runtime("good")
    assert hasattr(adapter, "run")
    assert hasattr(adapter, "SIGNAL_QUALITY")
    assert adapter.SIGNAL_QUALITY == SIGNAL_TAUTOLOGICAL, (
        f"signal quality 退化：{adapter.SIGNAL_QUALITY}，预期 {SIGNAL_TAUTOLOGICAL}"
    )


def test_build_demo_runtime_default_is_good():
    """默认参数等价于 build_demo_runtime('good')。"""
    a1 = build_demo_runtime()
    a2 = build_demo_runtime("good")
    assert type(a1) is type(a2)


def _make_minimal_replay_source(tmpdir: Path) -> Path:
    """在临时目录中创建一份最小 replay source——包含一条 tool_calls.jsonl。"""
    (tmpdir / "tool_calls.jsonl").write_text(
        '{"eval_id": "fake_001", "tool": "test"}\n', encoding="utf-8"
    )
    return tmpdir


def test_build_replay_runtime_accepts_str_and_path():
    """build_replay_runtime 接受 str 和 Path，返回 recorded_trajectory adapter。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        src = _make_minimal_replay_source(Path(tmpdir))
        a1 = build_replay_runtime(str(src))
        a2 = build_replay_runtime(src)
        assert a1.SIGNAL_QUALITY == SIGNAL_RECORDED
        assert a2.SIGNAL_QUALITY == SIGNAL_RECORDED
        assert type(a1) is type(a2)


def test_build_replay_runtime_signal_quality_is_recorded():
    with tempfile.TemporaryDirectory() as tmpdir:
        src = _make_minimal_replay_source(Path(tmpdir))
        adapter = build_replay_runtime(src)
        assert adapter.SIGNAL_QUALITY == SIGNAL_RECORDED, (
            f"replay runtime 必须标记 recorded_trajectory，实际 {adapter.SIGNAL_QUALITY}"
        )


def test_cli_does_not_directly_import_mock_replay_adapter():
    """cli.py 不应直接 import MockReplayAdapter 或 TranscriptReplayAdapter。

    解耦后 CLI 走 assembly 层，不再硬编码具体 adapter 类型。
    """
    cli_text = Path("agent_tool_harness/cli.py").read_text(encoding="utf-8")
    assert "from agent_tool_harness.agents.mock_replay_adapter import" not in cli_text, (
        "cli.py 仍直接 import MockReplayAdapter，应该走 assembly 层"
    )
    assert "from agent_tool_harness.agents.transcript_replay_adapter import" not in cli_text, (
        "cli.py 仍直接 import TranscriptReplayAdapter，应该走 assembly 层"
    )


def test_assembly_is_the_only_non_agent_module_importing_adapters():
    """assembly.py 是 agents/ 外唯一直接 import adapter 实现的模块。

    这是设计的正确状态：assembly 是 Demo 材料接入 Core 的唯一闸门。
    其他 Core 模块不得直接依赖 concrete adapter。
    """
    core_modules = [
        p
        for p in Path("agent_tool_harness").rglob("*.py")
        if p.name not in ("__init__.py", "assembly.py") and "agents" not in str(p).split("/")
    ]

    offenders = []
    for mod in core_modules:
        text = mod.read_text(encoding="utf-8")
        if "from agent_tool_harness.agents.mock_replay_adapter import" in text:
            offenders.append(str(mod))
        if "from agent_tool_harness.agents.transcript_replay_adapter import" in text:
            offenders.append(str(mod))

    assert not offenders, (
        "以下 Core 模块直接 import adapter 实现，必须走 assembly 层：\n  " + "\n  ".join(offenders)
    )
