"""v2.x patch — Internal Trial Dogfooding Log + Feedback Summary 防回归。

中文学习型说明
==============
本文件**钉死**的边界
--------------------
``docs/INTERNAL_TRIAL_DOGFOODING_LOG.md`` 与
``docs/INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`` 是 v2.x patch 内部试用
反馈闭环的"真实证据库"与"汇总入口"。它们对 v3.0 的承诺是：

- v3.0 **不会**因为某一次"我们要做 v3.0"的提案就被启动；
- 必须**至少 3 份**真实反馈 + **每份满足 4 项硬约束**才进入 ROADMAP
  review；
- 任何人都不能在反馈数仍为 0 时偷偷把"v3.0 状态"改成"started"或
  "in discussion"。

本文件钉死的具体契约：

1. dogfooding log 必须存在，必须含 v3.0 触发条件硬约束（至少 3 份反馈
   + deterministic/offline 不够的具体业务原因）；
2. dogfooding log 必须含"试用记录模板"段，并要求填 v3.0 4 项硬约束
   每一项；
3. dogfooding log 必须含 no-leak 自查清单（key / Authorization /
   完整请求体响应体 / base_url 敏感 query / HTTP/SDK 异常长文本）；
4. feedback summary 必须存在，必须显式声明默认结论 = **v3.0 not
   started**；
5. feedback summary 必须含 A/B/C 三类问题分类（v2.x patch / v3.0 backlog /
   反馈不完整）；
6. launch pack §6 必须同时引用 dogfooding log + feedback summary
   （否则等于隐藏入口）。

本文件**不**负责什么
--------------------
- 不验证已收录的真实反馈内容（这是反馈本身的事）；
- 不渲染 markdown；
- 不强制反馈数量上限；
- 不重复 ``test_internal_trial_launch_pack.py`` 已经钉过的 launch pack
  9 区块结构。

防回归价值
----------
真实可能的 bug：
- 有人把"v3.0 not started"偷偷改成"in progress"，让团队对主线终点
  预期错配；
- 有人把"至少 3 份反馈"改成"至少 1 份"，让 v3.0 太容易被启动；
- 有人删除 no-leak 自查清单，试用者把真实 key 粘进 dogfooding log；
- 有人删除"必须满足 4 项硬约束"段，让"我觉得需要 v3.0"也能进入 v3.0
  backlog；
- 有人新增 dogfooding log 但忘了从 launch pack §6 链接过去，反馈
  入口隐藏。
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DOGFOODING_LOG = REPO_ROOT / "docs" / "INTERNAL_TRIAL_DOGFOODING_LOG.md"
FEEDBACK_SUMMARY = REPO_ROOT / "docs" / "INTERNAL_TRIAL_FEEDBACK_SUMMARY.md"
LAUNCH_PACK = REPO_ROOT / "docs" / "INTERNAL_TRIAL_LAUNCH_PACK.md"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_dogfooding_log_exists() -> None:
    assert DOGFOODING_LOG.exists(), (
        "docs/INTERNAL_TRIAL_DOGFOODING_LOG.md 必须存在；它是 v3.0 触发"
        "条件的真实证据库，缺它意味着 v3.0 讨论没有任何客观依据。"
    )


def test_feedback_summary_exists() -> None:
    assert FEEDBACK_SUMMARY.exists(), (
        "docs/INTERNAL_TRIAL_FEEDBACK_SUMMARY.md 必须存在；它是 maintainer"
        "在收到 'v3.0 提案' 时第一步要打开的页面。"
    )


def test_dogfooding_log_pins_v3_threshold_to_at_least_three_feedbacks() -> None:
    """硬约束：dogfooding log 必须明确写'至少 3 份'反馈门槛 +
    deterministic/offline 不够的具体业务原因；任一缺失都让 v3.0 太容易
    启动。"""
    text = _read(DOGFOODING_LOG)
    assert "至少 **3 份**" in text or "至少 3 份" in text, (
        "Dogfooding log 必须钉死'至少 3 份反馈'门槛，"
        "防止 v3.0 被单方面诉求启动。"
    )
    assert "deterministic" in text and "offline" in text, (
        "Dogfooding log 必须要求反馈说明 deterministic / offline 能力"
        "为什么不够。"
    )


def test_dogfooding_log_template_requires_v3_four_hard_constraints() -> None:
    """试用记录模板必须含 v3.0 4 项硬约束区块，否则反馈即使填满也无法
    判定是否计入 v3.0 触发门槛。"""
    text = _read(DOGFOODING_LOG)
    assert "v3.0 能力诉求" in text, (
        "Dogfooding log 模板必须含 'v3.0 能力诉求' 子段。"
    )
    # 4 项硬约束在模板里以 1./2./3./4. 列表形式存在
    for marker in ["1.", "2.", "3.", "4."]:
        assert marker in text, (
            f"Dogfooding log v3.0 诉求段必须含 '{marker}' 列表项，"
            "钉死 4 项硬约束结构。"
        )


def test_dogfooding_log_has_no_leak_self_check() -> None:
    """no-leak 自查清单必须含 key / Authorization / 完整请求体 / 响应体 /
    base_url / HTTP 异常长文本，缺任一都让试用者可能把真实秘密粘入。"""
    text = _read(DOGFOODING_LOG)
    must_have = [
        "API key",
        "Authorization",
        "完整请求体",
        "完整响应体",
        "base_url",
    ]
    missing = [k for k in must_have if k not in text]
    assert not missing, (
        f"Dogfooding log no-leak 自查清单缺 {missing}；"
        "试用者可能把真实 key / 请求/响应体 / 内部地址粘入反馈。"
    )


def test_feedback_summary_default_state_is_v3_not_started() -> None:
    """feedback summary 必须显式声明 'v3.0 状态 = not started'，
    防止有人在反馈数仍为 0 时偷偷把状态改成 started / in progress。"""
    text = _read(FEEDBACK_SUMMARY)
    assert "**v3.0 状态**" in text or "v3.0 状态" in text, (
        "Feedback summary 必须含 'v3.0 状态' 字段，作为 maintainer "
        "review 入口。"
    )
    assert "not started" in text, (
        "Feedback summary 必须显式声明 'v3.0 状态 = not started'，"
        "防止状态被偷偷改成 in discussion / started。"
    )


def test_feedback_summary_has_three_category_classification() -> None:
    """问题清单必须按 A/B/C 三类分类，缺任何一类都让分类机制失效。"""
    text = _read(FEEDBACK_SUMMARY)
    must_have = [
        "可作为 v2.x patch",  # A
        "v3.0 backlog",  # B
        "反馈不完整",  # C
    ]
    missing = [k for k in must_have if k not in text]
    assert not missing, (
        f"Feedback summary 问题分类缺 {missing}；缺类会让反馈无处归类，"
        "或被错误归到 v3.0。"
    )


def test_launch_pack_section_6_links_dogfooding_log_and_summary() -> None:
    """Launch pack §6 必须同时引用 dogfooding log + feedback summary，
    否则两份新文档等于隐藏入口。"""
    text = _read(LAUNCH_PACK)
    assert "INTERNAL_TRIAL_DOGFOODING_LOG.md" in text, (
        "Launch pack §6 必须链接 dogfooding log。"
    )
    assert "INTERNAL_TRIAL_FEEDBACK_SUMMARY.md" in text, (
        "Launch pack §6 必须链接 feedback summary。"
    )


def test_dogfooding_and_summary_do_not_overpromise() -> None:
    """dogfooding log + summary 不得在'当前能力'语境出现过度承诺词。"""
    overpromise_words = ["企业级", "生产级 SaaS", "托管 LLM"]
    failures: list[str] = []
    for doc in (DOGFOODING_LOG, FEEDBACK_SUMMARY):
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
        "Dogfooding log / feedback summary 出现过度承诺词且没有否定上下文：\n"
        + "\n".join(failures)
    )


# ---------------------------------------------------------------------------
# 第二轮 dogfooding 走查发现的真实接入断点防回归测试
# ---------------------------------------------------------------------------
#
# 下面 4 条测试钉住"维护者第二轮 dogfooding 走查"中实际发现并修复的真实
# bug；任何一条回归都会让"内部小同事第一次试用"再次掉进同一个坑：
#
# 1. test_quickstart_install_command_includes_dev_extras
#    根因：Quickstart §0 写 `pip install -e .` 时 pytest 不会被装上
#    （pytest 只在 pyproject.toml 的 [project.optional-dependencies].dev
#    extras 里），紧跟一行的 `python -m pytest -q` 会直接 ModuleNotFound。
# 2. test_quickstart_cost_row_does_not_promise_unconditional_cost_summary
#    根因：MarkdownReport 的 `## Cost Summary` 段**仅当**调用方传入
#    cost data（即 project.yaml 配置了 pricing/budget）时才渲染；
#    runtime_debug 默认没配，所以 Quickstart §3 的 cost 行不能直接把
#    `report.md::Cost Summary` 写成无条件入口。
# 3. test_feedback_summary_does_not_reference_nonexistent_test_file
#    根因：feedback summary 维护说明曾引用
#    `tests/test_internal_trial_feedback_summary.py`——该文件从未存在；
#    实际钉契约的测试在 `test_internal_trial_dogfooding_log.py`。
# 4. test_summary_explicitly_excludes_maintainer_dryrun_from_v3_threshold
#    根因：用户明确要求"maintainer dry-run 不计入 3 份真实团队反馈"；
#    没有这条约束，未来任何人只要在 dogfooding log 追加几条 dry-run 就
#    可以触达 3 份门槛，等于绕过 v3.0 真实试用证据要求。

QUICKSTART = REPO_ROOT / "docs" / "INTERNAL_TRIAL_QUICKSTART.md"


def test_quickstart_install_command_includes_dev_extras() -> None:
    """Quickstart §0 必须用 `pip install -e ".[dev]"` 才能装上 pytest。"""
    text = _read(QUICKSTART)
    # 必须有带 [dev] 的安装命令
    assert 'pip install -e ".[dev]"' in text, (
        "Quickstart §0 必须用 `pip install -e \".[dev]\"`，否则紧跟的 "
        "`python -m pytest -q` 会因为 pytest 不在基础依赖里而 "
        "ModuleNotFound。"
    )
    # 必须不再含裸 `pip install -e .` 后紧跟 pytest 的破链命令
    assert "pip install -e . && python -m pytest" not in text, (
        "Quickstart §0 不允许出现 `pip install -e . && python -m pytest`：" 
        "pytest 只在 [dev] extras 里，新同事会被卡住。"
    )


def test_quickstart_cost_row_does_not_promise_unconditional_cost_summary() -> None:
    """Quickstart §3 cost 行不得把 `report.md::Cost Summary` 当无条件入口。"""
    text = _read(QUICKSTART)
    # 任何提到 `report.md::Cost Summary` 的地方，必须在附近 200 字符内
    # 同时说明"仅当"配置了 pricing / budget 才渲染。
    needle = "report.md::Cost Summary"
    idx = 0
    while True:
        pos = text.find(needle, idx)
        if pos < 0:
            break
        window = text[max(0, pos - 50):pos + len(needle) + 200]
        assert ("仅当" in window or "pricing" in window or "budget" in window), (
            f"Quickstart 在 cost 行提到 `{needle}`，但附近没有说明这一段"
            "需要配置 pricing/budget 才会渲染；新同事会去找一个不存在的"
            "段而以为框架坏了。"
        )
        idx = pos + len(needle)


def test_feedback_summary_does_not_reference_nonexistent_test_file() -> None:
    """feedback summary 维护说明不得引用不存在的测试文件。"""
    text = _read(FEEDBACK_SUMMARY)
    bad_path = "tests/test_internal_trial_feedback_summary.py"
    assert bad_path not in text, (
        f"feedback summary 引用了不存在的测试文件 `{bad_path}`；"
        f"实际钉契约的测试在 `tests/test_internal_trial_dogfooding_log.py`，"
        "请同步更新引用。"
    )
    # 必须引用真实存在的测试文件
    assert "tests/test_internal_trial_dogfooding_log.py" in text, (
        "feedback summary 必须引用真实存在的钉契约测试文件 "
        "`tests/test_internal_trial_dogfooding_log.py`。"
    )


def test_summary_explicitly_excludes_maintainer_dryrun_from_v3_threshold() -> None:
    """feedback summary + dogfooding log 必须明确 maintainer dry-run 不计入 v3.0 门槛。"""
    summary_text = _read(FEEDBACK_SUMMARY)
    log_text = _read(DOGFOODING_LOG)
    # summary 必须明确"真实团队反馈数量 = 0"或等价表述
    assert "真实" in summary_text and "0" in summary_text, (
        "feedback summary 必须显式声明当前**真实**内部团队反馈数量 = 0，"
        "防止有人把 maintainer dry-run 也算进 3 份门槛。"
    )
    # summary 必须明确 maintainer dry-run 不计入门槛
    assert "不计入" in summary_text and "dry-run" in summary_text.lower(), (
        "feedback summary 必须显式声明 maintainer dry-run **不计入** v3.0 "
        "讨论门槛的 3 份真实反馈。"
    )
    # dogfooding log 必须含 Maintainer dry-run record 段，且明确 not real team feedback
    assert "Maintainer dry-run record" in log_text, (
        "dogfooding log 必须含 'Maintainer dry-run record' 段（用于记录"
        "维护者本地 dry-run，不能伪造真实团队反馈）。"
    )
    assert "not real team feedback" in log_text.lower() or "template only" in log_text.lower(), (
        "Maintainer dry-run record 必须明确标记 'Template only — not real "
        "team feedback'，防止被误读为外部团队反馈。"
    )
    assert "不计入" in log_text, (
        "dogfooding log 的 Maintainer dry-run record 必须显式声明**不计入** "
        "v3.0 触发门槛。"
    )


# ---------------------------------------------------------------------------
# 第三轮 dogfooding（"新同事试用视角"端到端走查）防回归测试
# ---------------------------------------------------------------------------
#
# 这一轮在第二轮的 4 条接入断点测试之上，再补 5 条；目标是**新同事**而不
# 是维护者：launch pack 必须自带"关键词速懂"+"试用前自检 checklist"，
# feedback summary 必须含 maintainer release checklist + 反馈三类分流，
# dogfooding log 必须有 "Example only" 示例反馈但**不能**被混读为真实
# 团队反馈。任何一条回归都会让"新同事第一次试用"再次出现"维护者懂、新
# 同事不懂"的隐性跳步，或让 maintainer 在发布前漏检 / 反馈分类混乱 /
# v3.0 门槛被示例反馈污染。

LAUNCH_PACK = REPO_ROOT / "docs" / "INTERNAL_TRIAL_LAUNCH_PACK.md"


def test_launch_pack_has_inline_jargon_glossary_for_new_employees() -> None:
    """launch pack 必须自带"关键词速懂"段，覆盖 6 个核心 jargon。

    根因：原版 launch pack 直接用 replay-first / deterministic evidence /
    trace-derived signals / failure attribution / judge-provider-preflight /
    audit-judge-prompts / pricing-budget cap 等术语而**未解释**；
    新同事必须先翻 ARCHITECTURE 才能继续往下读，这是隐性跳步。
    """
    text = _read(LAUNCH_PACK)
    assert "关键词速懂" in text or "关键词" in text and "速懂" in text, (
        "launch pack 必须含 关键词速懂 段（位于 §0 之后），用 1-2 句话"
        "在文中就近解释 jargon，避免新同事被卡在术语上。"
    )
    must_explain_inline = [
        "replay-first",
        "deterministic evidence",
        "trace-derived signals",
        "failure attribution",
        "judge-provider-preflight",
        "audit-judge-prompts",
    ]
    missing = [k for k in must_explain_inline if k.lower() not in text.lower()]
    assert not missing, (
        "launch pack 必须就近解释这些核心 jargon，否则新同事看不懂："
        f"{missing}"
    )


def test_launch_pack_has_pre_trial_self_check_list() -> None:
    """launch pack 必须含"试用前 N 项自检"checklist，覆盖 10 个关键点。

    根因：用户明确要求 launch pack 提供 10 项自检 checklist；没有这条
    清单，新同事容易一上来接整个项目、不准备 yaml、把真实 key 粘进
    issue、误以为反馈就能启动 v3.0。
    """
    text = _read(LAUNCH_PACK)
    assert "试用前" in text and "自检" in text, (
        "launch pack 必须含 试用前自检 checklist 段（位于 §1 Quickstart 旁）。"
    )
    must_cover = [
        "一个小场景",
        "project.yaml",
        "tools.yaml",
        "evals.yaml",
        "report.md",
        "API key",  # no-leak 警告
        "live LLM judge",  # 默认 deterministic
        "v3.0",  # 反馈不等于启动 v3.0
    ]
    missing = [k for k in must_cover if k not in text]
    assert not missing, (
        f"launch pack 试用前自检 checklist 漏盖关键点：{missing}"
    )


def test_feedback_summary_has_maintainer_release_checklist() -> None:
    """feedback summary 必须含 maintainer release checklist，覆盖 5 个发布前自检维度。

    根因：用户要求 maintainer 发给同事试用前必须按清单逐项检查，否则
    会出现命令漂移、no-leak 失守、反馈数量被算错、v3.0 门槛被偷偷
    放宽等问题。
    """
    text = _read(FEEDBACK_SUMMARY)
    assert "Maintainer release checklist" in text or "release checklist" in text.lower(), (
        "feedback summary 必须含 'Maintainer release checklist' 段。"
    )
    # 必须覆盖 5 个发布前自检维度
    must_cover = [
        "README",  # 文档导航
        "drift",  # snippet/schema drift 测试
        "ruff",  # lint
        "pytest",  # 测试
        "no-leak",  # 安全
    ]
    missing = [k for k in must_cover if k not in text and k.lower() not in text.lower()]
    assert not missing, (
        f"Maintainer release checklist 漏盖关键发布前维度：{missing}"
    )


def test_feedback_summary_has_feedback_triage_workflow() -> None:
    """feedback summary 必须含"收到反馈后的分类"操作手册，钉死 v3.0 候选 3 项硬约束。

    根因：用户要求把"收到反馈→分类到 §A/§B/§C"写成可执行 maintainer
    操作手册；没有它，新 maintainer 容易把"看起来更厉害"的反馈也算
    成 v3.0 候选，从而绕过门槛。
    """
    text = _read(FEEDBACK_SUMMARY)
    assert "收到反馈后的分类" in text or "反馈后" in text and "分类" in text, (
        "feedback summary 必须含 收到反馈后的分类 段。"
    )
    # v3.0 候选 3 项硬约束必须显式列出
    must_state = [
        "deterministic",  # 反馈中必须说明 deterministic/offline 为什么不够
        "MCP",  # 必须明确说出需要的 v3.0 能力之一
        "具体业务",  # 必须明确说出具体业务场景，不是"看起来更厉害"
    ]
    missing = [k for k in must_state if k not in text]
    assert not missing, (
        f"反馈三类分流必须明确列出 v3.0 候选 3 项硬约束关键词，缺：{missing}"
    )
    # 必须含 no-leak 净化前置
    assert "no-leak" in text.lower() or "净化" in text, (
        "反馈分类前必须先做 no-leak 净化（删除 key / Authorization / "
        "完整请求体响应体），feedback summary 必须显式写出这一前置步骤。"
    )


def test_dogfooding_log_has_example_feedback_clearly_marked_not_real() -> None:
    """dogfooding log 必须含"示例反馈格式"段，但必须显式标 Example only。

    根因：用户要求展示一份合格反馈长什么样，但**严禁**伪造真实团队
    反馈。任何示例必须同时：
    - 标 'Example only — not real internal feedback'
    - 标 'Does not count toward the 3-feedback v3.0 gate'
    - 用 example-team / 占位日期等明显示例标记
    """
    text = _read(DOGFOODING_LOG)
    assert "示例反馈格式" in text or "Example only" in text, (
        "dogfooding log 必须含 示例反馈格式 (Example only) 段，"
        "用来给真实试用者演示一份合格反馈长什么样。"
    )
    # 必须同时含两条防伪声明
    assert "not real internal feedback" in text.lower(), (
        "示例反馈段必须显式标 'not real internal feedback'，防止被误读为"
        "外部团队真实反馈。"
    )
    assert "does not count toward" in text.lower() or "不计入" in text, (
        "示例反馈段必须显式声明**不计入** v3.0 触发门槛的 3 份反馈。"
    )
    # 占位团队名/日期
    assert "example-team" in text.lower() or "Demo User" in text or "EXAMPLE" in text, (
        "示例反馈必须使用 example-team / Demo User / EXAMPLE 等明显占位标记，"
        "禁止使用真实团队名。"
    )
