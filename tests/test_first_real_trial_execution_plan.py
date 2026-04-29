"""Tests pinning the first-real-trial execution plan contract.

中文学习型说明
==============
本测试**不**调真实 LLM、**不**联网、**不**模拟试用执行。它对
``docs/FIRST_REAL_TRIAL_EXECUTION_PLAN.md`` 做静态字符串契约校验，
确保维护者后续编辑这份"邀请第一位真实试用者前的运营自检包"时不会
**无意中**：

1. 把"试用目标"扩展成验证 v3.0 能力（试用就退化成需求会）；
2. 把"工具选择标准 13 条"压缩，让试用者选了需要 secret/network/database
   的工具（leak 风险陡升）；
3. 把 7 步路径里的 ``--strict-reviewed`` 拿掉（broken refs 直接进 run）；
4. 把"绝不让试用者跑 --live"改成"建议试用者也开 --live"（bad_response
   误读概率陡升）；
5. 把"反馈结束后等 1 份真实反馈再 tag"改成"试用结束就 tag"（tag 失去
   真实反馈语义）；
6. 把"v3.0 Gate 仍关闭"删掉（v3.0 状态漂移）。

为什么这是 v2.x 内部试用前的 release-readiness gate
--------------------------------------------------
执行包是真实试用的"最后一公里"。文档里**任何一处措辞松动**都会被
试用者按字面意思执行，进而直接污染反馈质量、安全边界、v3.0 触发
条件。把契约写成测试 = 把不可逆纪律写成 CI 兜底。

未来扩展点（**不**在本测试里实现）
--------------------------------
- 把 7 步路径做成可执行的 dry-run CLI（v3.0+ 候选）；
- 用 markdown AST 校验章节结构（v3.0+ 候选，避免引入新依赖）；
- LLM 协助生成执行包：永远不做（违反 deterministic / replay-first）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLAN = REPO_ROOT / "docs" / "FIRST_REAL_TRIAL_EXECUTION_PLAN.md"


def _read() -> str:
    assert PLAN.is_file(), f"{PLAN} 必须存在（v2.x 试用前运营自检包）"
    return PLAN.read_text(encoding="utf-8")


def test_plan_short_enough_for_one_page():
    """执行包不能膨胀成长篇产品文档（保 1 页可执行）。"""
    text = _read()
    assert 3000 < len(text) < 9000, (
        f"FIRST_REAL_TRIAL_EXECUTION_PLAN 长度 {len(text)} 不在 3000-9000 区间"
    )


def test_plan_objective_does_not_validate_v3_capabilities():
    """试用目标必须显式排除 live / MCP / Web UI / multi-format provider。

    模拟边界：维护者把"也顺便看看 live judge 能不能跑"加进试用目标，
    试用就退化成 v3.0 需求会。
    """
    text = _read()
    # 不验证段必须显式列出
    assert "不验证" in text or "**不验证**" in text
    for cap in ("live judge", "MCP", "Web UI", "HTTP-Shell"):
        assert cap in text, f"试用目标排除清单缺 {cap!r}"


def test_plan_tool_selection_lists_13_hard_constraints():
    """第一个工具选择标准必须列出 13 条（少 1 条就有可能让试用者选 leak 工具）。"""
    text = _read()
    must_have = (
        "单一工具",
        "不依赖真实 secret",
        "不需要联网",
        "不需要数据库",
        "不需要真实用户数据",
        "可以 mock",
        "deterministic eval",
        "不涉及真实公司敏感",
        "不涉及真实请求体",
        "不需要 HTTP",
        "不需要 MCP",
        "不需要 live LLM judge",
    )
    for c in must_have:
        assert c in text, f"工具选择标准缺关键约束 {c!r}"


def test_plan_seven_steps_use_real_cli_command_names():
    """7 步路径里的 CLI 命令名必须与 agent_tool_harness/cli.py 一致。

    模拟边界：维护者把 ``validate-generated`` 写成 ``validate-evals`` /
    把 ``replay-run`` 写成 ``replay``——试用者按文档跑会立刻 ``unrecognized
    command`` 失败。
    """
    text = _read()
    for cmd in (
        "bootstrap",
        "validate-generated",
        "--bootstrap-dir",
        "--strict-reviewed",
        "run",
        "--mock-path good",
    ):
        assert cmd in text, f"7 步路径缺真实 CLI 关键字 {cmd!r}"


def test_plan_explicitly_forbids_live_for_first_trial():
    """必须显式禁止"让试用者跑 --live"。

    模拟边界：维护者觉得"也让试用者体验完整能力"——试用者第一次开
    --live 看到 bad_response 就会误判 v2.x 不可用。
    """
    text = _read()
    assert "--live" in text
    assert "绝不" in text or "不要" in text


def test_plan_pins_security_immediate_blocker_path():
    """failure 排查必须含 security-blocker 立刻处置的入口。"""
    text = _read()
    assert "security" in text.lower()
    assert "立即" in text or "立刻" in text


def test_plan_pins_tag_after_first_real_feedback_only():
    """必须明确"第一份真实反馈到位后才考虑 tag"。

    模拟边界：试用刚结束维护者就 tag v2.1，让 tag 失去"真实试用过的版本"语义。
    """
    text = _read()
    assert "tag" in text.lower()
    assert "1 份真实反馈" in text or "第 1 份真实反馈" in text or "1 份真实" in text


def test_plan_pins_v3_gate_still_closed():
    """v3.0 Gate 仍关闭，反馈数 0/3。"""
    text = _read()
    assert "v3.0" in text
    assert "0 / 3" in text or "0/3" in text
    assert "not started" in text or "仍关闭" in text


def test_plan_does_not_invent_nonexistent_cli_subcommands():
    """文档不应引用不存在的子命令（防止维护者编造命令名）。

    根据 agent_tool_harness/cli.py 实际 subparsers 列表，凡是出现在 §5
    7 步路径中的 CLI 命令必须是真实命令；本测试反向 grep 几个**不**
    应出现的拼写错误。
    """
    text = _read()
    forbidden_typos = (
        "validate-evals",
        "validate-bootstrap",
        "scaffold-all",
        "trial-run",
        "auto-run",
    )
    for typo in forbidden_typos:
        assert typo not in text, f"文档出现可能的命令拼写错误 {typo!r}"


def test_plan_no_real_secret_or_endpoint_shape():
    """执行包不能含真实 sk- / Bearer / 真实 endpoint。"""
    text = _read()
    forbidden = (
        re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
        re.compile(r"Bearer [A-Za-z0-9._\-]{16,}"),
        re.compile(r"https://api\.(anthropic|openai)\.com"),
    )
    for pat in forbidden:
        m = pat.search(text)
        assert m is None, f"执行包含疑似真实敏感字面量 {m.group(0) if m else ''!r}"


def test_plan_references_real_supporting_docs_not_invented():
    """执行包关联的 4 份文档必须真实存在（防止链接漂移）。"""
    text = _read()
    for doc in (
        "FIRST_INTERNAL_TRIAL_HANDOFF.md",
        "INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md",
        "FEEDBACK_TRIAGE_WORKFLOW.md",
        "PUSH_PREFLIGHT_CHECKLIST.md",
    ):
        assert doc in text, f"执行包未引用配套文档 {doc!r}"
        assert (REPO_ROOT / "docs" / doc).is_file(), (
            f"执行包引用了不存在的文档 {doc!r}"
        )
