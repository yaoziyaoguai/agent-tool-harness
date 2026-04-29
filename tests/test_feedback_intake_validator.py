"""Tests pinning the feedback intake validator —— v2.x feedback loop guard。

中文学习型说明
==============
本测试**不**调真实 LLM、**不**联网、**不**读 .env、**不**读真实反馈
文件。它只对 ``agent_tool_harness.feedback.validator.validate_feedback_dict``
做行为级契约校验，确保 7 条硬规则**不可逆**：

1. valid real internal feedback 必须 pass + counts_toward_real_feedback=True；
2. maintainer_rehearsal=True 时 real_internal_feedback=True 必须 fail；
3. synthetic feedback 不能计入真实反馈（counts=False）；
4. v3_backlog_candidate 缺 offline gap explanation 必须 fail；
5. security_risk=True 必须强制 final_triage_decision = security-blocker；
6. final_triage_decision 不在 allowlist 必须 fail；
7. 反馈含 ``sk-`` / ``Bearer`` / ``Authorization`` / 真实 endpoint 必须 fail；
8. 缺必填字段必须 fail；
9. validator 不读 .env / 不联网 / 不调 LLM（通过 import-time 检查）。

为什么 feedback validator 是 v2.x feedback loop 的 guard
-----------------------------------------------------
maintainer 收到反馈手动追加到 ``INTERNAL_TRIAL_FEEDBACK_SUMMARY.md``
时，最容易把"看起来很重要"的反馈错算成真实反馈、错升级到 v3.0、
错把 leak 写进存档。validator 把这 5 类常见错误**机械化拦截**，让
v3.0 ≥3 门槛、security 优先级、no-leak 边界都不依赖人脑记忆。

为什么 synthetic feedback 不能计入真实反馈
------------------------------------
synthetic 是演练用例，**不**来自真实业务场景；如果允许 synthetic 凑
3 份门槛，v3.0 启动条件就变成"维护者写得出 3 段假反馈"。

为什么 v3.0 需要真实反馈 gate
-------------------------
单份反馈可能是个人偏好；3 份指向同一类根因才是工程信号。低于 3 份
启动 v3.0 = 把猜测当需求。

为什么 security blocker 优先级最高
----------------------------
任何把 security blocker 包装成"我们需要更安全的托管层 → 启动 v3.0"
的论证都是绕过 v2.x patch 边界——v2.x 必须先把当前 leak 修干净。
validator 用 Rule 5 强制 ``security-blocker`` 决策，避免被吞成普通
patch。

为什么 validator 不能调用 LLM 或读取 secrets
---------------------------------------
反馈本身可能含敏感数据。validator 是**纪律边界**，不是智能助手。
"""

from __future__ import annotations

from agent_tool_harness.feedback import (
    ALLOWED_TRIAGE_DECISIONS,
    REQUIRED_FIELDS,
    validate_feedback_dict,
)


def _good_real_feedback() -> dict:
    """构造一份"完全合法的真实试用反馈"基线，便于其它 case 改 1-2 字段。"""
    return {
        "feedback_id": "fb-2024-001",
        "source_type": "real_internal_teammate",
        "real_internal_feedback": True,
        "maintainer_rehearsal": False,
        "trial_completed": True,
        "selected_tool": "json_diff",
        "bootstrap_result": "pass",
        "strict_reviewed_result": "pass",
        "run_result": "pass",
        "report_artifacts_generated": True,
        "security_risk": False,
        "v2_patch_candidate": True,
        "v3_backlog_candidate": False,
        "offline_deterministic_gap_explanation": "",
        "final_triage_decision": "v2.x-patch",
        "next_action": "improve REVIEW_CHECKLIST wording",
    }


# -------------------------------------------------------------- Rule 1
def test_valid_real_internal_feedback_passes_and_counts():
    """合法真实反馈：ok=True + counts=True + 推荐 v2.x-patch。"""
    r = validate_feedback_dict(_good_real_feedback())
    assert r.ok, r.errors
    assert r.counts_toward_real_feedback is True
    assert r.suggested_triage == "v2.x-patch"


# -------------------------------------------------------------- Rule 2
def test_maintainer_rehearsal_cannot_claim_real_feedback():
    """模拟边界：维护者把自己 dry-run 标 real_internal_feedback=True
    试图凑 v3.0 ≥3 门槛——必须立刻 fail。
    """
    rec = _good_real_feedback()
    rec["maintainer_rehearsal"] = True
    rec["source_type"] = "maintainer_rehearsal"
    r = validate_feedback_dict(rec)
    assert r.ok is False
    assert any("maintainer_rehearsal" in e for e in r.errors)
    assert r.counts_toward_real_feedback is False


# -------------------------------------------------------------- Rule 3
def test_synthetic_feedback_does_not_count_toward_real():
    """synthetic 演练用例：即便其它字段都对，也不计入真实反馈。"""
    rec = _good_real_feedback()
    rec["source_type"] = "synthetic"
    rec["real_internal_feedback"] = False
    r = validate_feedback_dict(rec)
    assert r.ok, r.errors
    assert r.counts_toward_real_feedback is False


def test_synthetic_with_real_internal_feedback_true_fails():
    """模拟边界：synthetic case 标 real_internal_feedback=True 试图蒙混。"""
    rec = _good_real_feedback()
    rec["source_type"] = "synthetic"
    rec["real_internal_feedback"] = True
    r = validate_feedback_dict(rec)
    assert r.ok is False
    assert any(
        "synthetic" in e or "non-real" in e.lower() or "都不计入真实反馈" in e
        for e in r.errors
    )


# -------------------------------------------------------------- Rule 4
def test_v3_candidate_missing_offline_gap_explanation_fails():
    """v3.0 candidate 必须解释 deterministic / offline 为什么不够。

    模拟边界：试用者写"我希望接 OpenAI"但没说 deterministic 哪里不够，
    被错升级到 v3.0 backlog 凑门槛。
    """
    rec = _good_real_feedback()
    rec["v3_backlog_candidate"] = True
    rec["v2_patch_candidate"] = False
    rec["offline_deterministic_gap_explanation"] = "   "  # 只有空白
    rec["final_triage_decision"] = "v3.0-backlog-candidate"
    r = validate_feedback_dict(rec)
    assert r.ok is False
    assert any("offline_deterministic_gap_explanation" in e for e in r.errors)


def test_v3_candidate_with_offline_gap_explanation_passes():
    """补上 offline gap explanation 后通过，suggested_triage 推到 v3.0 backlog。"""
    rec = _good_real_feedback()
    rec["v3_backlog_candidate"] = True
    rec["v2_patch_candidate"] = False
    rec["offline_deterministic_gap_explanation"] = (
        "我们的工具响应是 streaming，replay-first fixture 无法覆盖部分发包路径"
    )
    rec["final_triage_decision"] = "v3.0-backlog-candidate"
    r = validate_feedback_dict(rec)
    assert r.ok, r.errors
    assert r.suggested_triage == "v3.0-backlog-candidate"


# -------------------------------------------------------------- Rule 5
def test_security_risk_forces_security_blocker_decision():
    """security_risk=True 不能被分到 v2.x-patch / 其它桶。

    模拟边界：maintainer 收到含 leak 的反馈，懒得走 6 步 security-blocker
    流程，直接标成 v2.x-patch 想"顺手修一下"——leak 没被立刻处置。
    """
    rec = _good_real_feedback()
    rec["security_risk"] = True
    rec["final_triage_decision"] = "v2.x-patch"  # 错误分类
    r = validate_feedback_dict(rec)
    assert r.ok is False
    assert any("security-blocker" in e for e in r.errors)
    # suggested 必须强行推到 security-blocker
    assert r.suggested_triage == "security-blocker"


def test_security_risk_with_correct_decision_passes():
    rec = _good_real_feedback()
    rec["security_risk"] = True
    rec["final_triage_decision"] = "security-blocker"
    r = validate_feedback_dict(rec)
    assert r.ok, r.errors


# -------------------------------------------------------------- Rule 6
def test_invalid_final_triage_decision_fails():
    """final_triage_decision 不在 5 桶 allowlist 必须 fail。"""
    rec = _good_real_feedback()
    rec["final_triage_decision"] = "interesting-but-skip"
    r = validate_feedback_dict(rec)
    assert r.ok is False
    assert any("final_triage_decision" in e for e in r.errors)


def test_allowed_triage_decisions_match_workflow_doc_buckets():
    """allowlist 必须严格 = workflow §2 决策表 5 桶。"""
    assert ALLOWED_TRIAGE_DECISIONS == (
        "v2.x-patch",
        "v3.0-backlog-candidate",
        "closed-as-design",
        "needs-more-evidence",
        "security-blocker",
    )


# -------------------------------------------------------------- Rule 7
def test_feedback_with_sk_secret_pattern_fails():
    """模拟边界：试用者粘了 OpenAI / Anthropic 风格 sk- key。"""
    rec = _good_real_feedback()
    rec["next_action"] = "see error: sk-prjABCDEFGHIJKLMNOP1234567890XYZ"
    r = validate_feedback_dict(rec)
    assert r.ok is False
    assert any("敏感字面" in e or "sensitive" in e.lower() for e in r.errors)


def test_feedback_with_bearer_token_fails():
    rec = _good_real_feedback()
    rec["next_action"] = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9XYZ"
    r = validate_feedback_dict(rec)
    assert r.ok is False


def test_feedback_with_real_endpoint_url_fails():
    rec = _good_real_feedback()
    rec["next_action"] = "tried https://api.openai.com/v1/chat/completions"
    r = validate_feedback_dict(rec)
    assert r.ok is False


def test_safe_sanitized_error_summary_passes():
    """脱敏后的 error 描述（无 sk- / Bearer / 真实 endpoint）必须通过。"""
    rec = _good_real_feedback()
    rec["next_action"] = (
        "validate-generated --strict-reviewed 返回 exit_code=2，stderr 提示"
        "broken reference at evals.yaml line 18"
    )
    r = validate_feedback_dict(rec)
    assert r.ok, r.errors


# -------------------------------------------------------------- Rule 8
def test_missing_required_fields_fails():
    """完全缺字段必须 fail，且不抛 KeyError。"""
    r = validate_feedback_dict({})
    assert r.ok is False
    assert len(r.errors) >= len(REQUIRED_FIELDS)


def test_partial_fields_fails_with_named_missing():
    rec = _good_real_feedback()
    del rec["security_risk"]
    del rec["final_triage_decision"]
    r = validate_feedback_dict(rec)
    assert r.ok is False
    assert any("security_risk" in e for e in r.errors)
    assert any("final_triage_decision" in e for e in r.errors)


# -------------------------------------------------------------- Rule 9: validator hygiene
def test_validator_module_does_not_import_network_or_llm():
    """validator 不能 import requests/httpx/openai/anthropic/dotenv 等。

    模拟边界：未来有人"顺手"加 LLM 协助 triage——立刻被本测试拦下。
    """
    import agent_tool_harness.feedback.validator as v

    src = open(v.__file__, encoding="utf-8").read()
    forbidden_imports = (
        "import requests",
        "import httpx",
        "import openai",
        "import anthropic",
        "import dotenv",
        "from dotenv",
        "urllib.request",
        "http.client",
        "socket",
    )
    for imp in forbidden_imports:
        assert imp not in src, f"validator 不应 import {imp!r}"


def test_validator_does_not_read_env_vars_for_decisions():
    """validator 决策不能依赖任何环境变量。"""
    import agent_tool_harness.feedback.validator as v

    src = open(v.__file__, encoding="utf-8").read()
    assert "os.environ" not in src
    assert "os.getenv" not in src


# -------------------------------------------------------------- aux: warnings
def test_real_feedback_but_trial_not_completed_warns_not_errors():
    """real=True 但 trial_completed=False 是 warning（建议补跑），不是 error。"""
    rec = _good_real_feedback()
    rec["trial_completed"] = False
    r = validate_feedback_dict(rec)
    # Rule 1-7 都没违反 → ok=True；warning 应提示
    assert r.ok, r.errors
    assert any("trial_completed=False" in w for w in r.warnings)
    # 但不应计入真实反馈门槛
    assert r.counts_toward_real_feedback is False


def test_user_idea_without_trial_suggested_needs_more_evidence():
    """user_idea_without_trial → 推荐 needs-more-evidence。"""
    rec = _good_real_feedback()
    rec["source_type"] = "user_idea_without_trial"
    rec["real_internal_feedback"] = False
    rec["trial_completed"] = False
    rec["v2_patch_candidate"] = False
    rec["v3_backlog_candidate"] = False
    rec["final_triage_decision"] = "needs-more-evidence"
    r = validate_feedback_dict(rec)
    assert r.ok, r.errors
    assert r.suggested_triage == "needs-more-evidence"
    assert r.counts_toward_real_feedback is False
