"""v1.9 Internal Trial readiness 文档诚实性防回归。

中文学习型说明
==============
本文件**钉死**的边界
--------------------
1. **ROADMAP 的 v2.0 终点必须显式声明 "Internal Trial Ready"** —— 防
   止有人把主线终点偷偷升级成"企业级 SaaS / 多租户 / 真实托管 LLM
   Judge 自动评估服务"，让用户对 v2.0 的预期错配；
2. **README + ROADMAP + INTERNAL_TRIAL 必须明确列出 Web UI / MCP /
   HTTP / Shell executor / 多租户 / 企业 RBAC 是 v2.0 范围外**；
3. **INTERNAL_TRIAL.md 必须存在 + 反馈模板必须存在 + 链接互通**；
4. **INTERNAL_TRIAL 必须明确说明 MockReplayAdapter 的 PASS/FAIL 不代
   表 Agent 能力**（防止试用者把 mock 复述当真实评估）；
5. **INTERNAL_TRIAL + 反馈模板必须包含 key no-leak 提醒**（防试用者
   把真实 key 粘进反馈）；
6. **INTERNAL_TRIAL 必须显式标注 advisory-only 的 cost / advisory
   judge 不是真实账单 / 不是真实评估**；
7. **任何受控文档不得出现"企业级 / 生产级 / 多租户 / 托管 LLM Judge
   服务"等过度承诺词汇**（除非在"v2.0 不包含"语境中作为否定列出）。

本文件**不**负责什么
--------------------
- 不验证 Markdown 渲染；
- 不验证 INTERNAL_TRIAL 中的命令是否能跑通（已由 docs CLI snippet
  drift 测试覆盖）；
- 不限制 RELEASE_NOTES_v*.md 中如何描述（release notes 是历史快照，
  不是当前承诺）。

防回归价值
----------
真实可能的 bug：
- 有人为了"看起来更厉害"把 ROADMAP 的 v2.0 描述改成"企业级 SaaS"，
  让试用团队对范围的预期错配；
- 有人删除 INTERNAL_TRIAL 中"MockReplayAdapter PASS/FAIL 不代表 Agent
  能力"提醒，试用者把 mock 复述当真实评估；
- 有人删除反馈模板的 key no-leak 提醒，试用者把真实 key 粘进反馈；
- 有人新增 doc 但忘了链接互通，试用者找不到 INTERNAL_TRIAL 入口。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

ROADMAP = REPO_ROOT / "docs" / "ROADMAP.md"
README = REPO_ROOT / "README.md"
INTERNAL_TRIAL = REPO_ROOT / "docs" / "INTERNAL_TRIAL.md"
INTERNAL_TRIAL_QUICKSTART = REPO_ROOT / "docs" / "INTERNAL_TRIAL_QUICKSTART.md"
FEEDBACK_TEMPLATE = REPO_ROOT / "docs" / "INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_v2_target_is_internal_trial_ready_in_roadmap():
    """ROADMAP 必须显式把 v2.0 终点定义为 Internal Trial Ready。"""
    text = _read(ROADMAP)
    assert "Internal Trial Ready" in text, (
        "ROADMAP 必须显式声明 v2.0 = Internal Trial Ready，"
        "防止主线终点被偷偷升级到企业级 SaaS。"
    )


def test_roadmap_v2_excludes_enterprise_capabilities_explicitly():
    """ROADMAP 必须显式把企业级能力列在 v2.0 不包含范围内。"""
    text = _read(ROADMAP)
    must_explicitly_exclude = [
        "Web UI",
        "MCP executor",
        "HTTP / Shell executor",
        "多租户",
        "企业",  # 涵盖企业级 / 企业 RBAC / 企业权限
    ]
    missing = [k for k in must_explicitly_exclude if k not in text]
    assert not missing, (
        f"ROADMAP v2.0 不包含范围必须显式列出 {missing}，"
        "防止有人偷偷把这些能力 scope 进 v2.0。"
    )


def test_internal_trial_files_exist_and_link_to_each_other():
    """INTERNAL_TRIAL 与反馈模板必须存在 + 互相链接。"""
    assert INTERNAL_TRIAL.exists(), (
        "docs/INTERNAL_TRIAL.md 必须存在，作为内部小团队第一次试用入口。"
    )
    assert FEEDBACK_TEMPLATE.exists(), (
        "docs/INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md 必须存在。"
    )
    trial = _read(INTERNAL_TRIAL)
    assert "INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md" in trial, (
        "INTERNAL_TRIAL.md 必须链接到反馈模板。"
    )


def test_internal_trial_quickstart_exists_and_is_linked():
    """Quickstart 一页版必须存在 + 被 README/INTERNAL_TRIAL 引用。

    防回归价值：v2.0 Internal Usability Assessment 发现 INTERNAL_TRIAL
    完整版 290 行太长，新用户难以快速上手；Quickstart 是 P1 修复，必
    须保证不被后续提交悄悄删掉或断链。
    """
    assert INTERNAL_TRIAL_QUICKSTART.exists(), (
        "docs/INTERNAL_TRIAL_QUICKSTART.md 必须存在，作为 10-15 分钟"
        "最小闭环路径，避免新用户被 290 行完整版劝退。"
    )
    quickstart = _read(INTERNAL_TRIAL_QUICKSTART)
    # Quickstart 必须自带"5 条命令"标识与边界提醒，避免被改成无关内容。
    assert "5 条命令" in quickstart or "五条命令" in quickstart, (
        "Quickstart 必须明确告知用户'5 条命令'，否则不再是 quickstart。"
    )
    assert "MockReplayAdapter" in quickstart, (
        "Quickstart 必须包含 MockReplayAdapter 边界提醒，避免新用户"
        "把 PASS/FAIL 当真实能力。"
    )
    # 必须被 README 与 INTERNAL_TRIAL 引用，否则用户找不到入口。
    assert "INTERNAL_TRIAL_QUICKSTART.md" in _read(README), (
        "README 必须链接 Quickstart 作为内部团队首次入口。"
    )
    assert "INTERNAL_TRIAL_QUICKSTART.md" in _read(INTERNAL_TRIAL), (
        "INTERNAL_TRIAL.md 顶部 TL;DR 必须链接 Quickstart。"
    )


def test_feedback_template_has_5_minute_minimal_section():
    """反馈模板必须含 5 分钟极简版，否则新用户填不完。

    防回归价值：原模板 107 行 10 段，Internal Usability Assessment
    发现新用户填到一半放弃；5 分钟极简版是 P1 修复，必须保证不被
    后续编辑覆盖。
    """
    feedback = _read(FEEDBACK_TEMPLATE)
    assert "5 分钟极简版" in feedback or "5 分钟" in feedback, (
        "反馈模板必须含 5 分钟极简版段落，让没时间填完整版的用户也能"
        "提交关键反馈。"
    )


def test_internal_trial_warns_mock_pass_fail_is_not_agent_capability():
    """INTERNAL_TRIAL 必须明确说明 MockReplayAdapter PASS/FAIL 不代表 Agent 能力。"""
    text = _read(INTERNAL_TRIAL)
    assert "MockReplayAdapter" in text
    # 至少出现一次"不代表"或"不是"语境，提醒试用者别把 mock 当真实评估。
    assert "不代表" in text or "不是" in text, (
        "INTERNAL_TRIAL 必须显式提醒 MockReplayAdapter 的 PASS/FAIL "
        "不代表 Agent 真实能力，防止试用者把 mock 复述当真实评估。"
    )


def test_internal_trial_and_feedback_template_warn_about_key_leak():
    """INTERNAL_TRIAL 与反馈模板必须包含 key no-leak / 不要粘真实 key 提醒。"""
    trial = _read(INTERNAL_TRIAL)
    feedback = _read(FEEDBACK_TEMPLATE)
    # INTERNAL_TRIAL 至少在某处提到 key 安全或 no-leak 边界。
    assert "key" in trial.lower(), "INTERNAL_TRIAL 必须提到 key 相关边界"
    # 反馈模板必须明确"不要粘真实 key / Authorization / 完整请求体"。
    assert "不要" in feedback and ("API key" in feedback or "Authorization" in feedback), (
        "反馈模板必须明确提醒试用者不要粘真实 key / Authorization。"
    )


def test_internal_trial_marks_cost_and_judge_as_advisory():
    """INTERNAL_TRIAL 必须显式标注 cost advisory-only / advisory judge 不是真实账单/真实评估。"""
    text = _read(INTERNAL_TRIAL)
    assert "advisory" in text.lower(), (
        "INTERNAL_TRIAL 必须含 advisory 措辞，明确 cost / judge 是 advisory-only。"
    )
    assert "永远不是真实账单" in text or "不是真实账单" in text, (
        "INTERNAL_TRIAL 必须显式标注 cost 不是真实账单。"
    )


def test_no_overpromise_words_in_governance_docs():
    """ROADMAP / INTERNAL_TRIAL / README 不得在'当前能力'语境出现过度承诺词。

    词汇本身可以出现，但必须出现在'v2.0 不包含 / 不是 / 范围外'否定语
    境中。本测试用一个保守策略：如果文档出现"企业级 / 生产级 / 多租户 /
    托管 LLM"等词，必须**同时**出现"不"或"否"上下文（最近 80 字符内）。

    设计取舍：80 字符窗口宽到能容纳"v2.0 不包含 ... 多租户 ..."这类
    句式，又窄到能抓住"agent-tool-harness 是企业级多租户 SaaS"这种
    overpromise。误报时维护者可以扩大窗口或显式标注。
    """
    overpromise_words = ["企业级", "生产级 SaaS", "托管 LLM"]
    docs = [README, ROADMAP, INTERNAL_TRIAL]
    failures: list[str] = []
    for doc in docs:
        if not doc.exists():
            continue
        text = _read(doc)
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
                        f"{doc.name} contains '{word}' without nearby "
                        f"negation; context: {window!r}"
                    )
                idx = pos + len(word)
    assert not failures, (
        "受控文档出现过度承诺词且没有否定上下文：\n"
        + "\n".join(failures)
        + "\nv2.0 是 Internal Trial Ready，禁止把当前能力宣传成企业级。"
    )
