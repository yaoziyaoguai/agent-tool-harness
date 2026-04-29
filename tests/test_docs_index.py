"""Tests pinning docs/INDEX.md as the single navigation hub.

中文学习型说明
==============
本测试**不**联网、**不**读 .env，只对 ``docs/INDEX.md`` 做静态字符串
校验，确保维护者改导航页时不会**无意中**：

1. 删掉 4 个角色路由中的任一个（导致试用者重新迷路）；
2. 把 canonical 文档替换成历史层文档（引导新读者去过时的入口）；
3. 留下断链（指向不存在的文档）；
4. 让 INDEX 自身膨胀成又一份长文档（违反"导航不是手册"原则）。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX = REPO_ROOT / "docs" / "INDEX.md"


def _read() -> str:
    assert INDEX.is_file()
    return INDEX.read_text(encoding="utf-8")


def test_index_is_short_navigation_not_a_manual():
    """INDEX 是导航不是手册，必须 <3000 字符。"""
    text = _read()
    assert 800 < len(text) < 3000, f"INDEX 长度 {len(text)} 超出导航预算"


def test_index_lists_four_roles():
    """4 个角色路由必须全部出现。"""
    text = _read()
    for role in (
        "试用者",
        "发邀请",
        "做分流",
        "tag",
    ):
        assert role in text, f"INDEX 缺角色路由 {role!r}"


def test_index_canonical_docs_all_exist():
    """INDEX 引用的所有 canonical 文档必须真实存在（防断链）。"""
    text = _read()
    canonical = (
        "INTERNAL_TRIAL_QUICKSTART.md",
        "INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md",
        "FIRST_REAL_TRIAL_EXECUTION_PLAN.md",
        "PUSH_PREFLIGHT_CHECKLIST.md",
        "FEEDBACK_TRIAGE_WORKFLOW.md",
        "INTERNAL_TRIAL_FEEDBACK_SUMMARY.md",
        "V2_X_RELEASE_CANDIDATE_NOTES.md",
        "ROADMAP.md",
        "ARCHITECTURE.md",
        "ARTIFACTS.md",
        "TESTING.md",
        "ONBOARDING.md",
    )
    for doc in canonical:
        assert doc in text, f"INDEX 缺 canonical 文档 {doc!r}"
        assert (REPO_ROOT / "docs" / doc).is_file(), f"INDEX 指向不存在文档 {doc!r}"


def test_index_does_not_link_canonical_to_legacy_docs():
    """canonical 路由必须指向 canonical 文档，不能误指向历史层。

    模拟边界：维护者把试用者 canonical 改回 INTERNAL_TRIAL_LAUNCH_PACK.md
    （15KB 的旧 launch pack）→ 试用者又被淹没。
    """
    text = _read()
    # 找"角色 → 看 1 份 canonical"那张表的第一列条目
    # 简单约束：QUICKSTART 必须出现在试用者那一行附近
    # 保守做法：要求 QUICKSTART 出现在 LAUNCH_PACK 之前
    qs = text.find("INTERNAL_TRIAL_QUICKSTART.md")
    lp = text.find("INTERNAL_TRIAL_LAUNCH_PACK.md")
    if lp != -1:
        assert qs != -1 and qs < lp, "QUICKSTART 必须先于 LAUNCH_PACK 引用"


def test_readme_points_to_index():
    """README 必须有指向 docs/INDEX.md 的链接（避免读者直接被淹没）。"""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "docs/INDEX.md" in readme, "README 必须指向 docs/INDEX.md 作角色路由入口"


def test_index_no_real_secret_or_endpoint_shape():
    text = _read()
    forbidden = (
        re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
        re.compile(r"Bearer [A-Za-z0-9._\-]{16,}"),
        re.compile(r"https://api\.(anthropic|openai)\.com"),
    )
    for pat in forbidden:
        m = pat.search(text)
        assert m is None, f"INDEX 含敏感字面 {m.group(0) if m else ''!r}"
