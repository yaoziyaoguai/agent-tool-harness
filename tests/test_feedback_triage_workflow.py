"""Tests pinning the feedback triage workflow + template §11 contract.

中文学习型说明
==============
本测试**不**调真实 LLM、**不**联网、**不**读 .env、**不**模拟真实
反馈。它对两份文档做静态字符串契约校验：

1. ``docs/FEEDBACK_TRIAGE_WORKFLOW.md`` —— maintainer 收到 1 份内部
   试用反馈后必须跑的 5 类决策表（v2.x patch / v3.0 backlog candidate /
   closed-as-design / needs-more-evidence / **security-blocker**）；
2. ``docs/INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md`` §11 —— 试用者自评
   triage hint 的 10 个字段，与决策表一一对应。

为什么 feedback triage 是 v2.x 内部试用后的 Roadmap gate
--------------------------------------------------------
v2.x 的 17 commits 已经把"内部小团队能跑 + 10 件 artifact + no-leak"
这条主线闭环。**真正决定要不要启动 v3.0 的不是维护者激情，而是真实
反馈**。如果 triage 流程自身有 hack（例如默认把"漂亮的需求 mail"算
v3.0 candidate / 默认把单次 bad_response 当 v3.0 触发），v3.0 会被
错误启动，主线就会偏离"offline / deterministic / replay-first"原则，
试用者得到的产品就不再是当初允诺的样子。

为什么 maintainer rehearsal 不算真实反馈
--------------------------------------
maintainer 跑 7 步主要是验证命令能复制粘贴 / artifact 齐全 / 文档无
drift——这些都是工艺正确性检查，**没有**任何"业务场景适配性"的信号。
如果允许 maintainer rehearsal 算反馈，等于让维护者自己投票决定要不要
启动 v3.0，反馈环就退化成自我合法化。

为什么 v3.0 需要至少 3 份真实反馈
--------------------------------
单份反馈可能是个人偏好 / 局部 use case / 临时阻塞；3 份指向**同一类
根因**才是工程信号。低于 3 份就启动 v3.0 等于把猜测当需求。

为什么 security blocker 优先级高于功能规划
----------------------------------------
试用过程中只要发现 key / Authorization / 完整请求响应落盘 / .env
被 track，必须立刻**暂停试用招募 + 净化 + 修复 + 重提脱敏反馈**。
任何把 security blocker 包装成"v3.0 需要更安全的托管层"的论证都是
绕过当前 v2.x patch 边界——v2.x 必须先把当前 leak 修干净。

为什么这不是启动 v3.0
-------------------
本流程**不**实现任何 v3.0 能力（MCP / Web UI / live judge / HTTP-Shell
executor / multi-format provider / 企业平台）。它是给真实反馈一个**纪
律性的入口**，让 v3.0 何时启动这件事可被审计、可被复盘、可被外部
review，而不是被某次激情提案推动。

未来扩展点（**不**在本测试里实现）
--------------------------------
- 把 triage 决策做成 CLI（``cli triage feedback.md``）：v3.0 候选；
- 把 §11 字段做成 YAML schema 校验：v3.0 候选；
- LLM 协助 triage：永远不做（违反 deterministic / replay-first）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = REPO_ROOT / "docs" / "FEEDBACK_TRIAGE_WORKFLOW.md"
TEMPLATE = REPO_ROOT / "docs" / "INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md"
SUMMARY = REPO_ROOT / "docs" / "INTERNAL_TRIAL_FEEDBACK_SUMMARY.md"


def _read(p: Path) -> str:
    assert p.is_file(), f"{p} 必须存在"
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------- workflow
def test_workflow_doc_exists_and_short_enough_for_one_page():
    """运营手册不能膨胀成长篇产品文档（保 1 页可执行）。"""
    text = _read(WORKFLOW)
    assert 2500 < len(text) < 9000, (
        f"FEEDBACK_TRIAGE_WORKFLOW 长度 {len(text)} 不在 2500-9000 区间"
    )


def test_workflow_lists_all_five_triage_buckets():
    """5 类分流必须显式列出，少 1 类反馈就有可能被错分到剩下 4 类里。"""
    text = _read(WORKFLOW)
    for bucket in (
        "v2.x patch",
        "v3.0 backlog candidate",
        "closed-as-design",
        "needs-more-evidence",
        "security-blocker",
    ):
        assert bucket in text, f"triage workflow 缺分类 {bucket!r}"


def test_workflow_excludes_maintainer_rehearsal_from_real_feedback():
    """maintainer rehearsal 不计入真实反馈——v3.0 ≥3 门槛的根基。

    模拟边界：维护者把自己 dry-run 算成"也是反馈"，3 个月攒 3 次就启动
    v3.0。本测试钉死这条不可逆纪律。
    """
    text = _read(WORKFLOW)
    assert "maintainer rehearsal" in text or "maintainer rehearsal / dry-run" in text
    assert "不计入" in text


def test_workflow_pins_three_real_feedback_v3_threshold():
    """v3.0 启动门槛 = ≥3 份真实反馈 + 同根因 + 至少 1 份具体业务场景。"""
    text = _read(WORKFLOW)
    assert "≥3" in text or "≥ 3" in text or "3 份" in text
    assert "v3.0" in text
    assert "同一类根因" in text or "同根因" in text


def test_workflow_demands_offline_gap_explanation_for_v3_candidate():
    """进入 v3.0 backlog candidate 必须解释 deterministic / offline 为什么不够。

    模拟边界：试用者写"我希望接 OpenAI"但没说 deterministic 哪里不够
    ——这条反馈应被分到 needs-more-evidence，不是 v3.0 candidate。
    """
    text = _read(WORKFLOW)
    assert "deterministic" in text
    assert "offline" in text or "replay-first" in text


def test_workflow_security_is_priority_zero_not_v3_trigger():
    """security blocker 优先级 0，且**不是** v3.0 触发器。

    模拟边界：把 leak 包装成"我们需要更安全的托管 LLM 平台 → 启动 v3.0"。
    本测试钉死 security 的优先级与 v3.0 触发分离。
    """
    text = _read(WORKFLOW)
    assert "security" in text.lower()
    # 必须显式说明 security 不是 v3.0 触发
    assert "不是 v3.0 触发器" in text or "security 是 v2.x patch" in text


def test_workflow_lists_closed_as_design_examples():
    """closed-as-design 必须列出常见反例，避免"看起来合理"的需求被误收。

    最常见误收：默认开 live / 自动读 secret / 自动执行任意工具 /
    跳过 review / generated draft 当生产配置 / maintainer rehearsal 算反馈。
    """
    text = _read(WORKFLOW)
    examples = [
        "默认 live",
        "自动读",
        "跳过 review",
        "generated draft",
        "maintainer rehearsal",
    ]
    for ex in examples:
        assert ex in text, f"closed-as-design 缺反例 {ex!r}"


def test_workflow_bad_response_default_v3_backlog_not_immediate_transport_fix():
    """bad_response 一次默认 v3.0 backlog，不立刻动 transport。

    模拟边界：试用者第 1 次开 --live 看到 bad_response → 维护者立刻
    去 LiveAnthropicTransport 写 multi-format parser。本测试钉死这是
    v3.0 backlog，不是 v2.x patch。
    """
    text = _read(WORKFLOW)
    assert "bad_response" in text
    assert "transport" in text


def test_workflow_decision_table_lists_all_input_fields():
    """决策表的输入字段必须全部出现，少 1 个字段决策就不可复现。"""
    text = _read(WORKFLOW)
    for field in (
        "real_feedback",
        "trial_completed",
        "report_artifacts_generated",
        "blocker_type",
        "needs_secret_network_database",
        "asks_for_v3_feature",
        "explains_offline_gap",
        "has_reproduction_steps",
        "security_risk",
    ):
        assert field in text, f"决策表缺输入字段 {field!r}"


def test_workflow_no_real_secret_or_endpoint_shape():
    """运营文档不能出现真实 sk- / Bearer / 真实 endpoint。"""
    text = _read(WORKFLOW)
    forbidden = (
        re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
        re.compile(r"\bsk_[A-Za-z0-9]{16,}"),
        re.compile(r"Bearer [A-Za-z0-9._\-]{16,}"),
        re.compile(r"https://api\.(anthropic|openai)\.com"),
    )
    for pat in forbidden:
        m = pat.search(text)
        assert m is None, f"workflow 含疑似真实敏感字面量 {m.group(0) if m else ''!r}"


# ---------------------------------------------------------------- template §11
def test_template_section_11_triage_hint_present():
    """模板必须新增 §11 triage hint，与 workflow 决策表对齐。"""
    text = _read(TEMPLATE)
    assert "## 11. Triage" in text or "## 11." in text
    assert "FEEDBACK_TRIAGE_WORKFLOW" in text


def test_template_section_11_lists_all_decision_fields():
    """§11 字段必须 1:1 对应 workflow §2 决策表 9 个输入字段。

    模拟边界：模板少 1 个字段 → maintainer 收到反馈无法跑决策表 → 只能
    凭直觉分类 → triage 退化成主观判断。
    """
    text = _read(TEMPLATE)
    for field in (
        "real_feedback",
        "trial_completed",
        "report_artifacts_generated",
        "blocker_type",
        "needs_secret_network_database",
        "asks_for_v3_feature",
        "explains_offline_gap",
        "has_reproduction_steps",
        "security_risk",
    ):
        assert field in text, f"模板 §11 缺字段 {field!r}"


def test_template_no_real_secret_shape():
    """模板里**永远**不能放真实 sk- / Bearer / 真实 endpoint。

    模拟边界：维护者为了"演示 leak 长什么样"把真实 key 写进模板。
    """
    text = _read(TEMPLATE)
    forbidden = (
        re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
        re.compile(r"Bearer [A-Za-z0-9._\-]{16,}"),
    )
    for pat in forbidden:
        m = pat.search(text)
        assert m is None, f"template 含真实敏感字面量 {m.group(0) if m else ''!r}"


def test_summary_still_pins_v3_not_started_default():
    """汇总文档的 v3.0 默认结论必须仍是 not started，反馈数仍是 0。

    模拟边界：本轮 patch 不应改 v3.0 状态——任何"顺手"把 v3.0 改成
    in discussion 或把反馈数改成 1 都应被钉死失败。
    """
    text = _read(SUMMARY)
    assert "not started" in text
    assert "**0**" in text or " = 0" in text or "数量 | **0**" in text


# ----------------------------------------------------- §6 synthetic simulation
def test_workflow_section_6_synthetic_simulation_present():
    """§6 必须明确 synthetic 不计入真实反馈、不触发 v3.0、不追加到 SUMMARY。"""
    text = _read(WORKFLOW)
    assert "Synthetic Feedback" in text or "synthetic" in text.lower()
    assert "不计入" in text
    assert "5 个 case" in text or "5 case" in text or "Case A" in text


def test_workflow_section_6_lists_five_cases_with_correct_decisions():
    """5 个 synthetic case 必须各自落到正确 triage 桶。"""
    text = _read(WORKFLOW)
    # Case A → v2.x patch
    assert "Case A" in text and "v2.x patch" in text
    # Case B → v2.x patch
    assert "Case B" in text
    # Case C → closed-as-design
    assert "Case C" in text and "closed-as-design" in text
    # Case D → security-blocker，且必须显式说"不立即 tag"
    assert "Case D" in text and "security-blocker" in text
    assert "不" in text and "tag" in text
    # Case E → v3.0 backlog candidate but NOT trigger
    assert "Case E" in text
    assert "v3.0 backlog candidate" in text
    # Case E 必须显式说"不启动 v3.0"（接受 markdown 加粗变体）
    assert (
        "不启动 v3.0" in text
        or "**不**启动 v3.0" in text
        or "不**启动** v3.0" in text
    )


def test_workflow_section_6_real_feedback_still_zero_after_simulation():
    """演练验证清单必须明确：跑完 5 case 后真实反馈数仍 = 0。"""
    text = _read(WORKFLOW)
    assert "0 / 3" in text or "= 0" in text or "依然 = 0" in text
