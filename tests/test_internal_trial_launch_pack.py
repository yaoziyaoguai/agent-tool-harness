"""v2.x patch — Internal Trial Launch Pack 文档诚实性防回归。

中文学习型说明
==============
本文件**钉死**的边界
--------------------
``docs/INTERNAL_TRIAL_LAUNCH_PACK.md`` 是给内部小团队第一次试用时
"一份就能找全所有东西"的 umbrella 导航页。它对内部团队的承诺是：
**9 个区块全部都能从一页内导航到位**，且不能在某次"美化"提交里被
偷偷削弱。

本测试钉的 9 个固定区块来自 v2.x patch 的 launch pack 任务规格：

1. 项目一句话定位（offline-first / deterministic / replay-first）；
2. 10-15 分钟 Quickstart 入口；
3. 使用自己项目的最小路径；
4. 如何看结果（report / artifact / failure attribution）；
5. 失败排查顺序（按证据链，不是先猜）；
6. 关键命令入口（含 audit-tools / replay-run / analyze-artifacts /
   judge-provider-preflight / audit-judge-prompts / pricing/budget）；
7. 反馈闭环（链接反馈模板）；
8. 明确不包含能力（Web UI / MCP / HTTP/Shell / 多租户 / 企业 RBAC /
   托管 LLM Judge 等）；
9. v3.0 触发条件（**至少 3 份反馈** + **deterministic/offline 不够的
   具体业务原因**）；
10. 安全 / no-leak 硬约束（key / Authorization / 完整请求体响应体禁止
    入 git/runs/artifacts）。

本文件**不**负责什么
--------------------
- 不验证文档实际命令是否能跑通（已由 ``test_docs_cli_snippets.py`` /
  ``test_docs_cli_schema_drift.py`` 覆盖）；
- 不限制行数 / 排版（长度 P1 由人工 review）；
- 不验证 launch pack 内的所有链接 URL 都返回 200（这是 doc 工具的事）；
- 不重复 ``test_internal_trial_readiness.py`` 已经钉过的"v2.0 不包含 +
  MockReplayAdapter 边界 + cost advisory"等约束。

防回归价值
----------
真实可能的 bug：
- 有人为了"看起来更厉害"删除"明确不包含能力"段；
- 有人删除 v3.0 触发条件，让某次反馈就能启动 v3.0；
- 有人删除安全 / no-leak 硬约束段，试用者把真实 key 粘进 launch pack
  示例；
- 有人删除关键命令入口的某条命令（比如 judge-provider-preflight），
  让试用者忘记在 live opt-in 前跑 readiness gate；
- 有人把 launch pack 的链接断掉，README 说"见 launch pack" 但点进去
  404 / 无内容。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LAUNCH_PACK = REPO_ROOT / "docs" / "INTERNAL_TRIAL_LAUNCH_PACK.md"
README = REPO_ROOT / "README.md"
INTERNAL_TRIAL = REPO_ROOT / "docs" / "INTERNAL_TRIAL.md"
INTERNAL_TRIAL_QUICKSTART = REPO_ROOT / "docs" / "INTERNAL_TRIAL_QUICKSTART.md"
FEEDBACK_TEMPLATE = REPO_ROOT / "docs" / "INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_launch_pack_exists() -> None:
    """Launch pack 必须存在，作为内部团队 umbrella 入口。"""
    assert LAUNCH_PACK.exists(), (
        "docs/INTERNAL_TRIAL_LAUNCH_PACK.md 必须存在，作为内部小团队"
        "第一次试用的 umbrella 启动包入口。"
    )


def test_launch_pack_is_referenced_from_readme_and_internal_trial() -> None:
    """Launch pack 必须从 README + INTERNAL_TRIAL 完整版可达，否则等于
    隐藏入口，试用者根本不知道有这份 umbrella。"""
    assert "INTERNAL_TRIAL_LAUNCH_PACK.md" in _read(README), (
        "README 必须链接 launch pack，否则试用者找不到 umbrella 入口。"
    )
    assert "INTERNAL_TRIAL_LAUNCH_PACK.md" in _read(INTERNAL_TRIAL), (
        "INTERNAL_TRIAL.md 顶部 TL;DR 必须链接 launch pack。"
    )


def test_launch_pack_contains_all_nine_required_blocks() -> None:
    """Launch pack 必须包含 9 个固定区块，每段都有标题锚点。

    用 ``in`` 校验 substring 而不是行精确匹配，是因为允许给标题前后加
    emoji / 序号微调，但**关键词必须存在**。这样既能防止有人把整段
    删掉，又不会卡住合理的措辞润色。
    """
    text = _read(LAUNCH_PACK)
    required_block_keywords = [
        "一句话定位",  # §0
        "10-15 分钟 Quickstart",  # §1（指向 QUICKSTART 一页版）
        "接入你自己项目",  # §2（自己的工具/eval 最小路径）
        "如何看结果",  # §3
        "失败排查顺序",  # §4
        "关键命令入口",  # §5
        "反馈闭环",  # §6
        "不**包含的能力",  # §7（Markdown 的 **不** 加粗形式）
        "v3.0 触发条件",  # §8
        "安全 / no-leak",  # §9
    ]
    missing = [k for k in required_block_keywords if k not in text]
    assert not missing, (
        f"Launch pack 缺失必备区块关键词 {missing}；"
        "9 区块结构是 v2.x patch 内部试用启动包的契约，不能被某次"
        "'美化提交'偷偷删除。"
    )


def test_launch_pack_lists_all_critical_command_entries() -> None:
    """关键命令入口段必须列出 v2.0 试用闭环涉及的全部 CLI 子命令。

    缺任何一条都会让试用者在某个环节"不知道下一步该敲什么"。
    """
    text = _read(LAUNCH_PACK)
    required_commands = [
        "audit-tools",
        "audit-evals",
        "run",
        "replay-run",
        "analyze-artifacts",
        "judge-provider-preflight",
        "audit-judge-prompts",
    ]
    missing = [c for c in required_commands if c not in text]
    assert not missing, (
        f"Launch pack 缺失关键命令 {missing}；"
        "试用者按文档跑闭环时会卡在缺失命令处。"
    )


def test_launch_pack_quickstart_link_uses_15_minute_window() -> None:
    """Launch pack 必须明确"10-15 分钟"窗口，与 Quickstart 文档一致。

    防回归：有人把窗口写成"30 分钟"或"1 小时"——既会让试用者预期被
    拉低，又会让 Quickstart 文档与 launch pack 互相矛盾。
    """
    text = _read(LAUNCH_PACK)
    assert "10-15 分钟" in text, (
        "Launch pack 必须出现'10-15 分钟'字样，与 Quickstart 文档窗口对齐。"
    )


def test_launch_pack_v3_trigger_requires_three_feedbacks_and_concrete_reason() -> None:
    """v3.0 触发条件必须**同时**要求：≥3 份反馈 + deterministic/offline
    不够的具体业务原因；任一条件被删除都会让 v3.0 太容易被启动。"""
    text = _read(LAUNCH_PACK)
    assert "至少收集 3 份" in text or "至少 3 份" in text, (
        "Launch pack v3.0 触发条件必须要求'至少 3 份'反馈，"
        "防止 v3.0 被单方面诉求启动。"
    )
    assert "deterministic" in text and "offline" in text, (
        "Launch pack v3.0 触发条件必须要求反馈说明 deterministic / "
        "offline 能力为什么不够。"
    )


def test_launch_pack_excludes_v3_capabilities_explicitly() -> None:
    """Launch pack §7 必须显式列出"不包含"清单，与 ROADMAP v2.0 不
    包含段对齐。任何一条缺失都会让试用者错把 v3.0 能力当 v2.0 承诺。"""
    text = _read(LAUNCH_PACK)
    must_explicitly_exclude = [
        "Web UI",
        "MCP",
        "HTTP",  # HTTP / Shell executor
        "Shell",
        "多租户",
        "RBAC",  # 企业 RBAC / SSO
        "托管 LLM Judge",  # 真实托管 LLM Judge 自动评估服务
    ]
    missing = [k for k in must_explicitly_exclude if k not in text]
    assert not missing, (
        f"Launch pack §7 不包含清单缺 {missing}；"
        "缺失会让试用者错把 v3.0 能力当 v2.0 承诺。"
    )


def test_launch_pack_safety_section_pins_no_leak_constraints() -> None:
    """安全段必须显式禁止把 key / Authorization / 完整请求/响应体写进
    任何受控产物（代码 / 文档 / 测试 / runs / artifacts / report /
    metrics / judge_results / diagnosis / git）。"""
    text = _read(LAUNCH_PACK)
    must_have = [
        "key",
        "Authorization",
        "完整请求体",
        "完整响应体",
        "runs/",
        "report",
    ]
    missing = [k for k in must_have if k not in text]
    assert not missing, (
        f"Launch pack 安全段缺 {missing}；"
        "安全约束被削弱时，试用者可能把真实 key 粘进反馈或 PR。"
    )


def test_launch_pack_does_not_overpromise_enterprise_grade() -> None:
    """Launch pack 不得在'当前能力'语境出现过度承诺词。

    与 test_internal_trial_readiness.py::test_no_overpromise_words_in_governance_docs
    同策略：词可以出现，但必须在否定语境（"不"/"否"/"范围外"/"❌"）
    附近 80 字符内。
    """
    text = _read(LAUNCH_PACK)
    overpromise_words = ["企业级", "生产级 SaaS", "托管 LLM"]
    failures: list[str] = []
    for word in overpromise_words:
        idx = 0
        while True:
            pos = text.find(word, idx)
            if pos < 0:
                break
            window = text[max(0, pos - 80):pos + len(word) + 80]
            if (
                "不" not in window
                and "否" not in window
                and "范围外" not in window
                and "❌" not in window
            ):
                failures.append(
                    f"launch pack contains '{word}' without nearby "
                    f"negation; context: {window!r}"
                )
            idx = pos + len(word)
    assert not failures, (
        "Launch pack 出现过度承诺词且没有否定上下文：\n"
        + "\n".join(failures)
        + "\nv2.0 是 Internal Trial Ready，禁止把当前能力宣传成企业级。"
    )
