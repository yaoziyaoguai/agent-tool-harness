"""Tests pinning V2_X_RELEASE_CANDIDATE_NOTES.md as封板判断包契约。

中文学习型说明
==============
本测试只对运营文档做静态字符串校验，钉死 5 条不可逆纪律：

1. 文档必须列出 4 条 tag 触发条件 + tag 还需"被试用过"语义；
2. 必须明确"未 tag"原因 + 真实反馈数 0/3；
3. 必须列出 v3.0 启动 gate 4 条；
4. 必须有"v3.0 不在 v2.x 范围"段；
5. 不能含真实 secret / endpoint。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTES = REPO_ROOT / "docs" / "V2_X_RELEASE_CANDIDATE_NOTES.md"


def _read() -> str:
    assert NOTES.is_file()
    return NOTES.read_text(encoding="utf-8")


def test_notes_short_one_page():
    text = _read()
    assert 2000 < len(text) < 7000, f"RC notes 长度 {len(text)} 超出一页预算"


def test_notes_pin_tag_gated_by_first_real_feedback():
    text = _read()
    assert "未 tag" in text or "未 tag" in text
    assert "真实" in text and "反馈" in text


def test_notes_list_four_tag_trigger_conditions():
    """4 条 tag 触发条件必须显式列出。"""
    text = _read()
    must_contain = (
        "≥1 份真实",  # condition 1
        "security blocker",  # condition 2
        "FEEDBACK_TRIAGE_WORKFLOW",  # condition 3 link
        "v2.x patch",  # condition 4
    )
    for k in must_contain:
        assert k in text, f"RC notes 缺 tag 触发条件关键字 {k!r}"


def test_notes_pin_v3_gate_with_three_real_feedback_same_root_cause():
    text = _read()
    assert "v3.0" in text
    assert "≥3" in text or "3 份" in text
    assert "同一类根因" in text or "同根因" in text


def test_notes_pin_v3_capabilities_still_backlog():
    """v3.0 backlog 列表必须含 MCP / Web UI / multi-format provider 等。"""
    text = _read()
    for cap in ("MCP", "Web UI", "HTTP", "Shell", "Multi-format", "企业平台"):
        assert cap in text, f"RC notes 缺 v3.0 backlog 项 {cap!r}"


def test_notes_pin_real_feedback_count_zero():
    text = _read()
    assert "0 / 3" in text or "0/3" in text


def test_notes_no_real_secret_or_endpoint_shape():
    text = _read()
    forbidden = (
        re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
        re.compile(r"Bearer [A-Za-z0-9._\-]{16,}"),
        re.compile(r"https://api\.(anthropic|openai)\.com"),
    )
    for pat in forbidden:
        m = pat.search(text)
        assert m is None, f"RC notes 含敏感字面 {m.group(0) if m else ''!r}"
