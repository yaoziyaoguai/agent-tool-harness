"""docs/TRY_IT.md 必须呈现完整 v0.2 试用闭环。

测试动机（不是为了通过率，而是为了发现真实 bug）：
=================================================
v0.2 第三轮加了 ``analyze-artifacts`` CLI，本意是让用户能复盘 trace 信号；
但如果 TRY_IT.md 里漏掉这条命令，或漏掉前置的 ``run --mock-path bad``，
用户照着抄就**永远走不到** trace 信号——v0.2 第三轮的能力对真人用户等于不存在。

这份测试钉死的不变量：``docs/TRY_IT.md`` 必须按顺序包含完整 v0.2 试用链路
里 7 个核心子命令调用，**且** ``analyze-artifacts`` 一定在 ``run --mock-path bad``
之后（否则没有 artifacts 可复盘）。

它**会发现**的真实 bug：
- 有人 PR 把 TRY_IT 简化成只剩 ``run``，吃掉了 v0.2 新能力的演示；
- 有人调换顺序，把 ``analyze-artifacts`` 排到 ``run`` 之前；
- 有人删掉 ``run --mock-path bad``，让用户只看到 happy path；
- 有人把 ``analyze-artifacts`` 用错 ``--out`` 名字导致后续步骤指不上。

它**不**负责：
- 验证命令真的能跑通 → 那是 CI smoke / 端到端 fixture 的事；
- 验证文档措辞 / 章节顺序；
- 验证 knowledge_search 路径 B 的存在性（它是可选对照，不在闭环内）。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
TRY_IT = REPO_ROOT / "docs" / "TRY_IT.md"

# 7 个核心子命令调用片段，按用户应执行的顺序排列。每条 substring 必须在
# TRY_IT.md 中出现，且 ``analyze-artifacts`` 必须排在 ``run --mock-path bad``
# 之后。判断方式刻意使用 substring 而非完整 argv，让 reviewer 能改文案 /
# 加换行 / 加注释，但不能去掉关键命令骨架。
REQUIRED_SUBCOMMANDS_IN_ORDER = [
    "audit-tools",
    "generate-evals",
    "promote-evals",
    "audit-evals",
    "--mock-path good",
    "--mock-path bad",
    "analyze-artifacts",
]


def test_try_it_contains_full_v0_2_loop_in_correct_order() -> None:
    """TRY_IT.md 必须按正确顺序覆盖完整 v0.2 试用闭环。"""

    assert TRY_IT.exists(), "docs/TRY_IT.md 必须存在——它是 v0.2 product trial 路径的入口"
    text = TRY_IT.read_text(encoding="utf-8")

    cursor = 0
    last_token = ""
    for token in REQUIRED_SUBCOMMANDS_IN_ORDER:
        idx = text.find(token, cursor)
        assert idx != -1, (
            f"docs/TRY_IT.md 缺少 v0.2 闭环命令 '{token}'（要求出现在 '{last_token}' 之后）。"
            "如果你简化了 TRY_IT，请确认 v0.2 第三轮 analyze-artifacts 仍能被用户走到。"
        )
        cursor = idx + len(token)
        last_token = token


def test_try_it_passes_evals_to_analyze_artifacts() -> None:
    """analyze-artifacts 必须传 --evals 才能复出 when_not_to_use 信号。

    根因：trace_signal_analyzer 的 ``tool_selected_in_when_not_to_use_context``
    依赖 user_prompt（只有 evals.yaml 提供），不传 --evals 该信号被跳过——
    那么用户跑完 TRY_IT 看不到 v0.2 第三轮最具代表性的 high severity 信号。
    """

    text = TRY_IT.read_text(encoding="utf-8")
    # 找到 analyze-artifacts 命令所在的代码块片段（粗粒度即可）。
    idx = text.find("analyze-artifacts")
    assert idx != -1
    snippet = text[idx : idx + 600]
    assert "--evals" in snippet, (
        "TRY_IT.md 中 analyze-artifacts 未传 --evals，会导致 when_not_to_use "
        "信号被跳过；用户复制后看不到 v0.2 第三轮关键信号。"
    )
