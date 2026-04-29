"""Tests pinning the push preflight + first trial operator pack.

中文学习型说明
==============
本测试**不**调真实 LLM、**不**联网、**不**读 .env、**不**执行 git
push。它对 ``docs/PUSH_PREFLIGHT_CHECKLIST.md`` 做静态字符串契约校验，
确保维护者改这份文档时**不会无意中**破坏几条不可逆的运营纪律：

1. **push 前自检 9 行命令必须显式列出**：删任何一行都会让维护者跳过
   一类风险（runs/ 入 commit / .env tracked / pytest 红 / ruff 红 /
   sensitive 字面量泄漏）；
2. **IM 模板必须保留 4 条安全红线 + "不要开 --live" + "不是 v3.0
   需求会"**：私聊里贴敏感数据 / 试用者把 bad_response 误读成 v2.x
   bug / 试用者把任何不便包装成 v3.0 求救信号——这 3 类都会被红线
   拦下；
3. **operator checklist 必须有 ≥3 真实反馈 + 具体根因 v3.0 触发条件**：
   v3.0 gate 的唯一守门员就是这条；
4. **failure handling guide 必须显式禁止 5 类危险动作**（把 bad_response
   改 PASS / 启动 v3.0 / 让试用者贴敏感数据 / maintainer 自跑算反馈 /
   一次失败就修 transport）。

为什么把"运营文档契约"也写成 pytest？
- 与 ``tests/test_first_internal_trial_handoff.py`` 同一治理思路：
  release gate 上的硬约束必须有自动化兜底，否则维护者在压力下"顺手
  改一下"会立刻让边界倒退；
- 静态字符串校验**不能**捕捉所有问题（措辞改了但语义还对），但能
  钉死关键名词，让任何"为了 PASS 而改文档"的尝试在 PR review 时
  立刻可见。

未来扩展点（**不**在本测试里实现）：
- 用 markdown AST 解析校验章节结构（v3.0+ 才考虑，避免引入新依赖）；
- 用 LLM 做语义检查（永远不在 v2.x 主线）。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC = REPO_ROOT / "docs" / "PUSH_PREFLIGHT_CHECKLIST.md"


def _read() -> str:
    assert DOC.is_file(), f"{DOC} 必须存在（v2.x 运营交付物）"
    return DOC.read_text(encoding="utf-8")


def test_doc_short_enough_for_5_min_execution():
    """运营文档不能膨胀成长篇 release note。

    上限 8000 字符 ≈ 5 分钟阅读 + 5 分钟执行。超出上限说明在变成产品
    文档（违反"5 分钟可执行"目标）。
    """
    text = _read()
    assert 2000 < len(text) < 9000, (
        f"PUSH_PREFLIGHT_CHECKLIST.md 长度 {len(text)} 字符不在 2000-9000 区间"
    )


def test_push_preflight_lists_all_critical_commands():
    """push 前 9 行命令必须**全部**出现，缺一不可。

    模拟边界：维护者觉得"几行差不多重复"就删一行——结果跳过了
    runs/ scan 或 .env track scan，下次 push 就漏 secret。
    """
    text = _read()
    required = (
        "git status --short",
        "git rev-list --left-right --count origin/main...HEAD",
        "ruff check .",
        "pytest -q",
        "git --no-pager log --oneline origin/main..HEAD",
        "runs/",
        "git ls-files .env",
    )
    for cmd in required:
        assert cmd in text, f"push 前自检缺关键命令/检查 {cmd!r}"


def test_im_template_safety_red_lines_present():
    """IM 模板必须保留 4 条 no-leak 红线。

    模拟边界：维护者改 IM 措辞时把"不要贴 API key"压缩成"注意安全"
    ——试用者就有可能在私聊里贴 key。
    """
    text = _read()
    for kw in ("API key", "Authorization", "完整请求体", "完整响应体"):
        assert kw in text, f"IM 模板缺安全红线关键词 {kw!r}"


def test_im_template_pins_no_live_for_first_trial():
    """IM 模板必须显式告诉同事"第一轮不要开 --live"。

    防止试用者按"看起来更全面"的心理开 --live，触发 bad_response 又
    误读为 v2.x bug。
    """
    text = _read()
    assert "--live" in text
    assert "不要开" in text or "不开" in text


def test_im_template_states_not_v3_collection_meeting():
    """IM 必须明确"这不是 v3.0 需求收集会"，避免泛泛 v3.0 求救信号涌入。"""
    text = _read()
    assert "v3.0" in text
    assert "需求收集" in text or "需求会" in text


def test_operator_checklist_pins_three_real_feedback_v3_gate():
    """operator checklist 必须显式声明 ≥3 真实反馈 + ≥1 具体根因 才考虑 v3.0。"""
    text = _read()
    assert "≥ 3" in text or "3 份" in text
    assert "v3.0" in text
    assert "具体" in text


def test_operator_checklist_defers_tag_until_real_feedback():
    """operator checklist 必须明确"tag 等真实反馈后再打"。

    防止维护者在 push 完就立刻 tag，让 tag 失去"试用过的版本"语义。
    """
    text = _read()
    assert "tag" in text.lower()
    assert "等" in text and "反馈" in text


def test_failure_guide_forbids_dangerous_shortcuts():
    """failure handling guide 必须显式禁止 5 类危险动作。

    模拟边界：试用者第一次失败 → 维护者"为了让试用通过"做出的 5 种
    最常见错误反应。如果文档不显式拦下来，维护者在压力下很容易做。
    """
    text = _read()
    forbidden_actions = (
        "因为一次失败就启动 v3.0",
        "bad_response",  # 必须出现在"不要做"段
        "改成 PASS",  # 不要把 bad_response 改成 PASS 的 hack
        "maintainer 自己复跑",  # 不要把自跑当反馈
    )
    for action in forbidden_actions:
        assert action in text, f"failure guide 缺禁止动作描述 {action!r}"


def test_failure_guide_demands_artifact_first_not_code_first():
    """failure handling guide 必须明确"先看 artifact，不要先看代码"。

    这是 agent-tool-harness 的设计哲学之一：所有诊断从 9-10 件 artifact
    出发，避免维护者在不看证据的情况下凭直觉改代码。
    """
    text = _read()
    assert "先看 artifact" in text or "先看 artifacts" in text


def test_doc_has_no_real_secret_or_endpoint_shape():
    """运营文档不能出现疑似真实 key / 真实 endpoint URL / 完整 Bearer token。"""
    import re

    text = _read()
    forbidden = (
        re.compile(r"\bsk-[A-Za-z0-9]{12,}"),
        re.compile(r"\bsk_[A-Za-z0-9]{12,}"),
        re.compile(r"https://[A-Za-z0-9.-]+\.aliyuncs\.com"),
        re.compile(r"https://api\.anthropic\.com"),
        re.compile(r"https://api\.openai\.com"),
        re.compile(r"Bearer [A-Za-z0-9._\-]{12,}"),
    )
    for pat in forbidden:
        m = pat.search(text)
        assert m is None, (
            f"PUSH_PREFLIGHT_CHECKLIST 出现疑似真实敏感字面量：{m.group(0) if m else ''!r}"
        )
