"""Tests pinning the First Internal Trial Handoff Pack contracts.

中文学习型说明
==============
这一份测试**不**调真实 LLM、**不**联网、**不**读 .env；它只对
``docs/FIRST_INTERNAL_TRIAL_HANDOFF.md`` /
``docs/FIRST_INTERNAL_TRIAL_INVITE_TEMPLATE.md`` /
``docs/PUSH_READINESS_SUMMARY.md`` 三份文档做静态字符串契约校验，
确保未来维护者在改这三个文档时**不会无意中**：

1. 删掉"必须挑小工具 / no secret / no network / no database"硬约束；
2. 把"第一位试用者就要开 ``--live``"这种危险路径写进 7 步路径；
3. 让试用者把"维护者 rehearsal"误算成真实反馈；
4. 让 invite template 直接出现真实 key / Authorization / 完整请求响应；
5. 把 ``bad_response`` 当成阻塞主线试用的 release-blocker（实际是 v1.x
   8 类 error taxonomy 的安全失败路径）；
6. 暗示 v3.0 已经启动（应始终 still backlog / not started）。

为什么把"docs 契约"也写成 pytest？
- agent-tool-harness 的核心交付物之一就是"内部同事可以独立按文档跑通"，
  文档漂等于交付物质量倒退；和 ``tests/test_doc_cli_snippets.py`` /
  ``tests/test_internal_trial_*.py`` 同样的治理思路。
- 静态字符串校验**不能**捕捉所有问题（比如文档措辞改了但语义还对），
  但能**钉死**不可逆的硬约束（红线类）。
- 任何"为了让测试 PASS"而改文档的尝试都会被代码 review 立刻看到——
  这本身就是一种放大镜，让 maintainer 不能偷偷削弱安全边界。

未来扩展点（**不**在本测试里实现）：
- 用真实 markdown 解析器做结构验证（v3.0+ 才考虑，避免引入新依赖）；
- 用 LLM 做语义检查（永远不在 v2.x 主线）。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HANDOFF = REPO_ROOT / "docs" / "FIRST_INTERNAL_TRIAL_HANDOFF.md"
INVITE = REPO_ROOT / "docs" / "FIRST_INTERNAL_TRIAL_INVITE_TEMPLATE.md"
PUSH_READINESS = REPO_ROOT / "docs" / "PUSH_READINESS_SUMMARY.md"


def _read(path: Path) -> str:
    assert path.is_file(), f"{path} 必须存在（v2.x release gate 交付物）"
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Handoff 文档契约
# ---------------------------------------------------------------------------


def test_handoff_doc_exists_and_short_enough():
    """handoff 文档必须存在；且不能膨胀成长篇产品文档。

    为什么钉死字符上限（约 8000 字符）：维护者很容易"一看到机会就加段
    解释"，把"10 分钟可读"目标稀释掉。这条测试在合并 PR 时立刻拦下。
    """
    text = _read(HANDOFF)
    assert 1500 < len(text) < 8000, (
        f"FIRST_INTERNAL_TRIAL_HANDOFF.md 长度 {len(text)} 字符不在 1500-8000 区间；"
        "短于下限说明结构缺失，超出上限说明在变成长篇产品文档（违反"
        "'10-15 分钟可读'目标）。"
    )


def test_handoff_lists_full_seven_step_path():
    """7 步路径的关键命令名必须**全部**出现在 handoff 文档。

    模拟边界：维护者只贴了 ``bootstrap`` 和 ``run``，遗漏了
    ``validate-generated --strict-reviewed`` —— 这正是历史上漂误最多的
    那一步（commit 16f8c11 修过 TODO 注释漂；试用者最容易在这卡住）。
    """
    text = _read(HANDOFF)
    required_commands = (
        "bootstrap",
        "REVIEW_CHECKLIST",
        "validate-generated",
        "--strict-reviewed",
        "run",
        "--mock-path good",
        "report.md",
    )
    for cmd in required_commands:
        assert cmd in text, f"7 步路径缺关键命令 {cmd!r}（试用者会卡在这一步）"


def test_handoff_pins_no_secret_no_network_no_database():
    """工具选择标准必须显式拒绝 secret / network / database 工具。

    这是 release-blocking 红线：第一位试用者一旦挑了真实 API 工具，
    试用过程中可能 leak 真实 key / 联网产生真实成本 / 把生产 DB 弄脏。
    """
    text = _read(HANDOFF)
    for forbidden_class in ("secret", "network", "database", "no real user data"):
        assert forbidden_class in text.lower(), (
            f"handoff 文档未显式拒绝 {forbidden_class!r}；试用者会在工具选择"
            "时缺少明确否决条件。"
        )


def test_handoff_pins_first_trial_must_not_open_live():
    """第一位试用者**不要**开 ``--live`` 必须显式写在 §5 Live judge 段。

    模拟边界：维护者改文档时把"live 不开"轻描淡写成"可选"，让试用者
    误以为开 live 是必要步骤——这会(a) 让阿里云 gateway 的 bad_response
    被误读成 v2.x bug；(b) 在第一轮试用就引入真实成本/隐私边界。
    """
    text = _read(HANDOFF)
    assert "不要开" in text or "不开" in text, (
        "handoff 文档必须明确告诉第一位试用者 ``--live`` 不要开。"
    )
    assert "--live" in text


def test_handoff_disclaims_bad_response_does_not_block_offline():
    """``bad_response`` 不阻塞 offline 主线必须显式写出。

    模拟边界：维护者删了这段；下一位试用者看到 live judge ``bad_response``
    误以为整个项目坏掉了；触发不必要的 v3.0 求救信号。
    """
    text = _read(HANDOFF)
    assert "bad_response" in text
    assert "不阻塞" in text or "不会阻塞" in text


def test_handoff_states_v3_not_started_with_three_real_feedback_gate():
    """v3.0 still not started + 至少 3 份真实反馈 gate 必须显式声明。"""
    text = _read(HANDOFF)
    assert "v3.0" in text
    assert "not started" in text or "still backlog" in text
    assert "≥ 3" in text or "3 份" in text or "3 real" in text


def test_handoff_includes_feedback_template_with_v3_candidate_field():
    """反馈模板必须包含 v3.0 candidate / real internal feedback yes/no 两字段。

    模拟边界：维护者把模板"简化"了，删掉 v3.0 candidate 字段——以后
    再也无法从结构化反馈中识别"是否触发 v3.0"，只能凭印象判断。
    """
    text = _read(HANDOFF)
    required_fields = (
        "v3.0 candidate",
        "real internal feedback",
        "maintainer rehearsal",  # 必须显式排除
        "selected tool name",
        "needs secret",
        "strict-reviewed result",
    )
    for field in required_fields:
        assert field in text, f"反馈模板缺关键字段 {field!r}"


def test_handoff_explicitly_excludes_maintainer_rehearsal_from_real_feedback():
    """maintainer rehearsal 必须**显式**不算真实反馈（v3.0 gate 隔离）。"""
    text = _read(HANDOFF).lower()
    # 任何一种表达"maintainer rehearsal 不算 / 不计入 / 永远 no"都接受
    assert (
        "maintainer rehearsal 永远是 no" in text
        or "maintainer rehearsal 不算" in text
        or "maintainer rehearsal 不计入" in text
    ), "handoff 文档必须显式声明 maintainer rehearsal 不算真实反馈"


# ---------------------------------------------------------------------------
# Invite 模板契约（防 leak / 防误导）
# ---------------------------------------------------------------------------


def test_invite_template_no_real_secret_or_endpoint_shape():
    """邀请模板里不允许出现疑似真实 key / 真实 endpoint URL。

    模拟边界：维护者"贴心"地把自己测试用的 base_url / API key 加到
    模板里方便试用者复制——这是直接的 release-blocking leak。
    """
    import re

    text = _read(INVITE)
    forbidden_patterns = (
        re.compile(r"\bsk-[A-Za-z0-9]{8,}"),
        re.compile(r"\bsk_[A-Za-z0-9]{8,}"),
        re.compile(r"https://[A-Za-z0-9.-]+\.aliyuncs\.com"),
        re.compile(r"https://api\.anthropic\.com"),
        re.compile(r"https://api\.openai\.com"),
        re.compile(r"Bearer [A-Za-z0-9._\-]{8,}"),  # 完整 Bearer token
    )
    for pat in forbidden_patterns:
        m = pat.search(text)
        assert m is None, f"INVITE 模板出现疑似真实敏感字面量：{m.group(0) if m else ''!r}"


def test_invite_template_pins_safety_red_lines():
    """邀请模板必须把"不要贴 key / Authorization / 完整请求响应"红线写在
    收件人面前——避免试用者在私聊里贴敏感数据。"""
    text = _read(INVITE)
    for kw in ("API key", "Authorization", "完整请求", "完整响应"):
        assert kw in text, f"INVITE 模板缺安全红线关键词 {kw!r}"


def test_invite_template_states_not_v3_collection_meeting():
    """邀请模板必须明确"这不是 v3.0 需求收集会"，避免试用者把任何不便都
    包装成 v3.0 求救信号。"""
    text = _read(INVITE)
    assert "v3.0" in text
    assert "需求收集" in text or "需求收集会" in text or "not started" in text


# ---------------------------------------------------------------------------
# Push readiness summary 契约
# ---------------------------------------------------------------------------


def test_push_readiness_summary_recommends_human_review_before_push():
    """push readiness summary 必须明确"我不自动 push / 维护者人工 review"。

    模拟边界：维护者把"建议 push"改成"自动 push"——破坏了"任何 release
    gate 都需要人在回路"的 v2.x 治理边界。
    """
    text = _read(PUSH_READINESS)
    assert "不**自动 push**" in text or "不自动 push" in text or "人工" in text


def test_push_readiness_summary_defers_tag_until_real_feedback():
    """tag 必须明确"等收到真实反馈后再打"，不允许写"现在就 tag"。"""
    text = _read(PUSH_READINESS)
    assert "tag" in text.lower()
    assert "真实" in text and "反馈" in text


def test_push_readiness_summary_no_real_secret_or_endpoint():
    """push readiness 文档不允许出现疑似真实 key / 真实 endpoint URL。"""
    import re

    text = _read(PUSH_READINESS)
    forbidden = (
        re.compile(r"\bsk-[A-Za-z0-9]{8,}"),
        re.compile(r"https://[A-Za-z0-9.-]+\.aliyuncs\.com"),
        re.compile(r"Bearer [A-Za-z0-9._\-]{8,}"),
    )
    for pat in forbidden:
        m = pat.search(text)
        assert m is None, f"PUSH_READINESS 出现疑似敏感字面量：{m.group(0) if m else ''!r}"
