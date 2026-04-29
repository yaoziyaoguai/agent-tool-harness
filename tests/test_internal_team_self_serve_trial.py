"""v2.x patch — Internal Team Self-Serve Trial Pack 防回归测试。

中文学习型说明
==============
本文件**钉死**的边界
--------------------
``docs/INTERNAL_TEAM_SELF_SERVE_TRIAL.md`` 与
``docs/templates/INTERNAL_TRIAL_REQUEST_TEMPLATE.md`` 是 v2.x patch
"内部小组自助试用入口"的两份文档。它们的承诺是：

- 内部小组**不依赖** maintainer 就能自助试用（不需要先开会、不需要
  先发邮件）；
- 试用全程**离线 / 不调真实 LLM / 不联网 / 不需要密钥**；
- redaction confirmation 是**强制项**，不允许默认勾选；
- 反馈分类含 D 类**安全/泄漏风险**最高优先级处理；
- v3.0 仍**不会**因为单次试用反馈启动；本登记单**不计入** v3.0 触发门槛。

本文件钉死的具体契约：

1. self-serve doc 必须存在并含 10 个问题段；
2. self-serve doc 必须含 no-leak / redaction / offline / deterministic
   边界声明；
3. self-serve doc 必须显式说明 v3.0 不会因单次反馈启动；
4. trial request template 必须存在且**不**默认勾选 redaction；
5. trial request template 必须含 4 类反馈分类（含 D 类安全 / 泄漏）；
6. README + LAUNCH_PACK §2 必须导航到 self-serve doc + template；
7. 反馈三类分流必须扩展为 4 类（A/B/C/D），D 类先于 A/B/C 处理；
8. 文档不得出现"v3.0 已开始 / MCP 已开始 / Web UI 已开始 /
   live LLM Judge 默认启用"等误导性表述。

本文件**不**负责什么
--------------------
- 不验证 maintainer 实际怎么处理 D 类（那是 maintainer SOP）；
- 不验证试用者真的脱敏了（那是试用者自我承诺）；
- 不重复 ``test_internal_trial_launch_pack.py`` 已经钉过的 launch pack
  9 区块结构。

防回归价值
----------
真实可能的 bug：
- 有人删除 self-serve doc 的 §10 安全红线 → 内部小组把真实 key 粘进
  fixture；
- 有人把 trial request template 的 redaction 改成默认 ✅ → 试用者
  机械点击不真做脱敏；
- 有人把反馈分类从 4 类改回 3 类 → D 类安全 / 泄漏被误归到 C 类
  "信息不完整"，泄漏处理被延迟；
- 有人在 self-serve doc 中暗示"试用一次就能启动 v3.0" → 内部小组
  对 v3.0 启动门槛预期错配；
- 有人新增 self-serve doc 但忘了从 README / LAUNCH_PACK §2 链接
  过去 → 自助入口隐藏。

为什么这不是 v3.0 功能
----------------------
本测试只钉死**文档**契约，不引入任何执行器、judge、live 调用、MCP /
Web UI / HTTP / Shell；与 v3.0 backlog 完全隔离。
"""

from __future__ import annotations

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SELF_SERVE_DOC = REPO_ROOT / "docs" / "INTERNAL_TEAM_SELF_SERVE_TRIAL.md"
TRIAL_REQUEST_TEMPLATE = (
    REPO_ROOT / "docs" / "templates" / "INTERNAL_TRIAL_REQUEST_TEMPLATE.md"
)
README = REPO_ROOT / "README.md"
LAUNCH_PACK = REPO_ROOT / "docs" / "INTERNAL_TRIAL_LAUNCH_PACK.md"
FEEDBACK_SUMMARY = REPO_ROOT / "docs" / "INTERNAL_TRIAL_FEEDBACK_SUMMARY.md"


def _read(p: Path) -> str:
    """读取 UTF-8 文档；缺失视为契约破坏，给出根因说明。"""
    assert p.exists(), f"必须存在：{p}（请勿删除/重命名 v2.x patch 内部试用文档）"
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# self-serve doc 存在性 + 10 问 Q&A 结构
# ---------------------------------------------------------------------------


def test_self_serve_doc_exists() -> None:
    """self-serve doc 必须存在，是 v2.x patch 内部小组自助试用入口。"""
    assert SELF_SERVE_DOC.exists(), (
        "docs/INTERNAL_TEAM_SELF_SERVE_TRIAL.md 必须存在；它是面向内部"
        "小组试用者（不是 maintainer）的自助入口，删除等于让内部团队"
        "重新依赖 maintainer 才能开始试用。"
    )


def test_self_serve_doc_has_ten_questions() -> None:
    """self-serve doc 必须含 10 个 Q&A 段（## 1. ... ## 10.）。"""
    text = _read(SELF_SERVE_DOC)
    missing = [n for n in range(1, 11) if f"## {n}." not in text]
    assert not missing, (
        f"self-serve doc 必须含 ## 1. ... ## 10. 共 10 个 Q&A 段；"
        f"缺：{missing}。删除任何一段都会让内部小组在自助试用时"
        "卡住对应问题。"
    )


# ---------------------------------------------------------------------------
# self-serve doc no-leak / redaction / offline / deterministic 边界
# ---------------------------------------------------------------------------


def test_self_serve_doc_has_no_leak_red_lines() -> None:
    """self-serve doc §10 必须列出至少 6 条 no-leak / redaction 红线。"""
    text = _read(SELF_SERVE_DOC)
    must_warn_about = [
        "API key",
        "Authorization",
        "请求体",
        "响应体",
        "base_url",
        "用户隐私",
        "未脱敏",
    ]
    missing = [k for k in must_warn_about if k not in text]
    assert not missing, (
        f"self-serve doc §10 安全 / 泄漏硬红线必须覆盖关键风险类，缺：{missing}"
    )


def test_self_serve_doc_states_offline_deterministic() -> None:
    """self-serve doc 必须显式声明全程 offline / deterministic / 不调真实 LLM。"""
    text = _read(SELF_SERVE_DOC)
    assert "离线" in text and "不联网" in text, (
        "self-serve doc 必须显式声明全程离线 / 不联网。"
    )
    assert "deterministic" in text.lower() or "确定性" in text, (
        "self-serve doc 必须显式提到 deterministic（确定性）评估边界。"
    )
    assert "不调真实 LLM" in text or "不需要密钥" in text, (
        "self-serve doc 必须显式声明默认不调真实 LLM / 不需要密钥。"
    )


def test_self_serve_doc_does_not_promise_v3_from_single_feedback() -> None:
    """self-serve doc 不得暗示'单次反馈就能启动 v3.0'。"""
    text = _read(SELF_SERVE_DOC)
    assert "v3.0" in text, (
        "self-serve doc 必须显式提到 v3.0 状态（避免内部小组对启动条件"
        "预期错配）。"
    )
    # 必须明确"单次反馈不会让 v3.0 启动"
    assert "单次反馈不会" in text or "至少 3 份" in text or ">= 3" in text, (
        "self-serve doc 必须明确单次试用反馈不会让 v3.0 启动；"
        "v3.0 仍需 ≥3 份不同团队反馈 + 4 项硬约束。"
    )


# ---------------------------------------------------------------------------
# trial request template 存在 + redaction 强制项
# ---------------------------------------------------------------------------


def test_trial_request_template_exists() -> None:
    """trial request template 必须存在，用于内部小组对外登记试用。"""
    assert TRIAL_REQUEST_TEMPLATE.exists(), (
        "docs/templates/INTERNAL_TRIAL_REQUEST_TEMPLATE.md 必须存在；"
        "它是内部小组发给 maintainer 的 trial 登记单。"
    )


def test_trial_request_template_redaction_is_unchecked_by_default() -> None:
    """trial request template 中所有 redaction confirmation 必须默认 [ ]，**不允许** [x]。

    根因：redaction 是强制项；如果默认勾选，试用者机械跳过等于零保护。
    """
    text = _read(TRIAL_REQUEST_TEMPLATE)
    # 检查 Redaction confirmation 段中没有任何 [x]（区分大小写）
    # 简化：在整个 redaction confirmation 段后到下一个 ## 段之间不能有 [x]
    start = text.find("Redaction confirmation")
    assert start >= 0, (
        "trial request template 必须含 'Redaction confirmation' 段。"
    )
    # 找下一个二级或三级标题
    end = text.find("\n## ", start)
    if end < 0:
        end = len(text)
    section = text[start:end]
    assert "[x]" not in section.lower(), (
        "Redaction confirmation 段不允许默认勾选 [x] / [X]；试用者"
        "必须手动逐项确认。"
    )
    # 必须含至少 6 项 redaction checkbox
    checkbox_count = section.count("- [ ]")
    assert checkbox_count >= 6, (
        f"Redaction confirmation 必须列出至少 6 项手动确认 checkbox，"
        f"当前 {checkbox_count} 项。"
    )


def test_trial_request_template_has_four_feedback_categories() -> None:
    """trial request template 反馈分类必须含 4 类（A/B/C/D），其中 D = 安全/泄漏。"""
    text = _read(TRIAL_REQUEST_TEMPLATE)
    must_have = [
        "A 类",
        "B 类",
        "C 类",
        "D 类",
        "v2.x patch",
        "v3.0 backlog",
        "信息不完整",
        "安全",
    ]
    missing = [k for k in must_have if k not in text]
    assert not missing, (
        f"trial request template 反馈分类必须含 4 类（A/B/C/D），缺：{missing}"
    )


def test_trial_request_template_does_not_count_toward_v3_gate() -> None:
    """trial request template 必须明确**不计入** v3.0 触发门槛。"""
    text = _read(TRIAL_REQUEST_TEMPLATE)
    assert "不计入" in text and "v3.0" in text, (
        "trial request template 必须明确**不计入** v3.0 触发门槛——"
        "登记单只是登记，v3.0 启动条件仍由 feedback summary 中真实"
        "反馈数量 + 4 项硬约束决定。"
    )


# ---------------------------------------------------------------------------
# 导航：README + LAUNCH_PACK §2 必须链接 self-serve doc + template
# ---------------------------------------------------------------------------


def test_readme_links_to_self_serve_doc() -> None:
    """README 必须导航到 self-serve doc，让内部小组 30 秒内找到入口。"""
    text = _read(README)
    assert "INTERNAL_TEAM_SELF_SERVE_TRIAL.md" in text, (
        "README 必须含 self-serve doc 链接，否则内部小组找不到自助入口。"
    )


def test_readme_links_to_trial_request_template() -> None:
    """README 必须导航到 trial request template。"""
    text = _read(README)
    assert "INTERNAL_TRIAL_REQUEST_TEMPLATE.md" in text, (
        "README 必须含 trial request template 链接，否则内部小组不知道"
        "正式登记单在哪。"
    )


def test_launch_pack_section_2_links_self_serve_and_template() -> None:
    """LAUNCH_PACK §2 接入路径必须同时引用 self-serve doc + template。"""
    text = _read(LAUNCH_PACK)
    # 必须含 self-serve doc 链接
    assert "INTERNAL_TEAM_SELF_SERVE_TRIAL.md" in text, (
        "LAUNCH_PACK §2 必须链接 self-serve doc。"
    )
    # 必须含 template 链接
    assert "INTERNAL_TRIAL_REQUEST_TEMPLATE.md" in text, (
        "LAUNCH_PACK §2 必须链接 trial request template。"
    )


# ---------------------------------------------------------------------------
# feedback summary 反馈三类分流必须扩展为 4 类，D 类先于 A/B/C
# ---------------------------------------------------------------------------


def test_feedback_summary_triage_extended_to_four_classes_with_d_first() -> None:
    """feedback summary 反馈分类必须含 D 类（安全 / 泄漏），且明确先于 A/B/C 处理。"""
    text = _read(FEEDBACK_SUMMARY)
    # 必须存在 D 类
    assert "### D" in text or "§D" in text or "D 类" in text, (
        "feedback summary 反馈分类必须扩展含 D 类（安全 / 泄漏风险）。"
    )
    # 必须明确 D 类最高优先级 / 先于 A/B/C
    assert "最高优先级" in text or "先于" in text or "first" in text.lower(), (
        "feedback summary 必须明确 D 类（安全 / 泄漏风险）最高优先级，"
        "先于 A/B/C 处理；否则真实泄漏会被错归到 C 类'信息不完整'。"
    )
    # 必须含阻断 / 净化 / 登记三步处理
    assert "阻断" in text and "净化" in text, (
        "D 类处理必须含'阻断 → 净化 → 登记'流程；缺失任一步会让"
        "maintainer 在真实泄漏发生时手忙脚乱。"
    )


# ---------------------------------------------------------------------------
# 不得出现误导性表述
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "doc_path",
    [SELF_SERVE_DOC, TRIAL_REQUEST_TEMPLATE],
    ids=["self_serve_doc", "trial_request_template"],
)
def test_self_serve_pack_does_not_overpromise_v3_capabilities(doc_path: Path) -> None:
    """self-serve pack 不得暗示 v3.0/MCP/Web UI/live LLM Judge 已默认启用。

    根因：用户硬约束 = 当前不进入 v3.0；任何"v3.0 已开始 / MCP 已
    开始 / Web UI 已开始 / live LLM Judge 默认启用"等表述都会误导
    内部小组对 v2.0 范围的预期。
    """
    text = _read(doc_path)
    forbidden = [
        "v3.0 已开始",
        "v3.0 已启动",
        "MCP 已开始",
        "MCP 已启动",
        "Web UI 已开始",
        "live LLM Judge 默认启用",
        "live judge 默认启用",
        "默认 live",
    ]
    hits = [w for w in forbidden if w in text]
    assert not hits, (
        f"self-serve pack 出现误导性表述（这些功能在 v2.0 不做 / 严格"
        f" backlog）：{hits}"
    )
