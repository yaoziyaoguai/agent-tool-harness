"""Feedback intake validator —— 内部试用反馈纪律 guard。

中文学习型说明
==============
本模块**不**联网、**不**调 LLM、**不**读 .env、**不**写文件。它给定
一条 feedback record（dict），按 [`docs/FEEDBACK_TRIAGE_WORKFLOW.md`]
§2 决策表的 9 输入字段 + 内部纪律一致性，输出一个
:class:`ValidationResult`。

**职责边界**
- 只做**确定性校验**（缺字段 / 字段越界 / 真实 secret 字面 / 纪律违反）；
- **不做**语义分析、**不做**自动修复、**不做**反馈追加、**不做**触发任何
  外部副作用。

**为什么是 v2.x feedback loop 的 guard**
当 maintainer 收到反馈手动追加到 ``INTERNAL_TRIAL_FEEDBACK_SUMMARY.md``
时，**最容易出错**的 5 件事被本 validator 钉死：

1. **synthetic feedback 被误算成真实反馈**——会把 v3.0 ≥3 门槛偷偷打开；
2. **maintainer rehearsal 被误算成真实反馈**——同上；
3. **security blocker 被分到普通 v2.x patch**——leak 没被立刻处置；
4. **v3.0 candidate 缺 offline gap explanation**——v3.0 启动条件被绕过；
5. **反馈正文混入真实 sk- / Bearer / 完整请求响应**——leak 入档案。

**为什么 validator 不能调用 LLM 或读取 secrets**
反馈本身可能含敏感数据（虽然 IM/template 已多次警告）。让 validator 把
反馈喂给真实 LLM = 把潜在 leak 主动外泄。validator 是**纪律边界**，
不是智能助手。

**MVP / mock / demo 边界**
- 16 必填字段 + 7 硬规则 + 真实-secret 字面扫描；
- **不**校验 reproduction artifact 路径真实存在（避免依赖文件系统）；
- **不**校验 next_action 文案质量（避免做语义分析）。

**未来扩展点**
- 接 CLI ``feedback-validate``（仅当反馈量 ≥10 份再考虑）；
- 加 yaml 文件读取入口；
- 加 reproduction artifact path 存在性校验；
- 接 ``ROADMAP.md`` 自动追加（**仍不**实现 v3.0 能力本身）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# 16 必填字段 —— 与 docs/INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md §11 + maintainer
# 在 INTERNAL_TRIAL_FEEDBACK_SUMMARY.md 追加时需要的元字段一一对应。
REQUIRED_FIELDS: tuple[str, ...] = (
    "feedback_id",
    # source_type ∈ maintainer_rehearsal / real_internal_teammate
    #              / user_idea_without_trial / synthetic
    "source_type",
    "real_internal_feedback",  # bool
    "maintainer_rehearsal",  # bool
    "trial_completed",  # bool
    "selected_tool",
    "bootstrap_result",  # pass / warning / fail
    "strict_reviewed_result",  # pass / warning / fail / not_run
    "run_result",  # pass / fail / not_run
    "report_artifacts_generated",  # bool
    "security_risk",  # bool
    "v2_patch_candidate",  # bool
    "v3_backlog_candidate",  # bool
    "offline_deterministic_gap_explanation",  # str | empty
    "final_triage_decision",  # in ALLOWED_TRIAGE_DECISIONS
    "next_action",
)

# §2 决策表的 5 桶 + invalid 占位（保护 maintainer 写错决策值）。
ALLOWED_TRIAGE_DECISIONS: tuple[str, ...] = (
    "v2.x-patch",
    "v3.0-backlog-candidate",
    "closed-as-design",
    "needs-more-evidence",
    "security-blocker",
)

# 不允许的 source_type → 把 synthetic 显式包含，避免有人把 synthetic
# 演练用例算成真实反馈。
_REAL_SOURCE_TYPES = ("real_internal_teammate",)
_NON_REAL_SOURCE_TYPES = (
    "maintainer_rehearsal",
    "user_idea_without_trial",
    "synthetic",
)
_ALL_SOURCE_TYPES = _REAL_SOURCE_TYPES + _NON_REAL_SOURCE_TYPES

# 真实 secret 字面扫描：sk- / sk_ / 长 Bearer / 真实托管 endpoint。
# 故意不含项目内 fixture 的 sentinel（"FAKE_KEY" / "THIS_MUST_NOT_LEAK"），
# 试用者反馈里**完全**不应该出现这类字面。
_FORBIDDEN_PATTERNS = (
    re.compile(r"\bsk-[A-Za-z0-9]{16,}"),
    re.compile(r"\bsk_[A-Za-z0-9]{16,}"),
    re.compile(r"Bearer [A-Za-z0-9._\-]{16,}"),
    re.compile(r"Authorization:\s*Bearer\s+[A-Za-z0-9._\-]{16,}"),
    re.compile(r"https://api\.(anthropic|openai)\.com"),
)


@dataclass
class ValidationResult:
    """结构化校验结果。

    字段说明：
    - ``ok``：是否通过全部 hard rule。``True`` 即可追加到反馈记录；
      ``False`` 时 maintainer 必须先修 errors 再追加。
    - ``errors``：硬错误列表（必须修）。
    - ``warnings``：软提示（建议修但不阻塞）。
    - ``counts_toward_real_feedback``：是否计入 3 份 v3.0 启动门槛。
      只有 ``source_type == real_internal_teammate`` 且
      ``maintainer_rehearsal == False`` 且 ``real_internal_feedback == True``
      且 ``trial_completed == True`` 才 ``True``。
    - ``suggested_triage``：根据规则推断的最佳分类（``security_risk`` 优先）。
      仅供 maintainer 参考，**不**自动写入反馈文件。
    """

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    counts_toward_real_feedback: bool = False
    suggested_triage: str | None = None


def _scan_for_secrets(record: dict[str, Any]) -> list[str]:
    """扫描反馈所有字符串字段中可能的真实 secret 字面。

    模拟边界：试用者把"我跑命令时遇到这个错误"的完整命令贴进反馈，
    其中 ``Authorization: Bearer ...`` 被一并粘进。validator 必须立刻
    拦下，否则 leak 会随反馈追加进 SUMMARY 永久存档。
    """
    findings: list[str] = []
    for k, v in record.items():
        if not isinstance(v, str):
            continue
        for pat in _FORBIDDEN_PATTERNS:
            m = pat.search(v)
            if m:
                findings.append(
                    f"field {k!r} 含疑似真实敏感字面（pattern={pat.pattern!r}）"
                )
                # 一个字段命中一次即可，避免重复噪音
                break
    return findings


def validate_feedback_dict(record: dict[str, Any]) -> ValidationResult:
    """对单条 feedback record 执行 16 字段 + 7 硬规则 + secret 扫描。

    7 硬规则（与 ``docs/FEEDBACK_TRIAGE_WORKFLOW.md`` §2 / §5 对齐）：

    1. ``maintainer_rehearsal == True`` 时 ``real_internal_feedback`` 必须 ``False``；
    2. ``source_type`` 必须在 :data:`_ALL_SOURCE_TYPES`；
    3. synthetic / maintainer_rehearsal / user_idea_without_trial 不计入真实反馈；
    4. ``v3_backlog_candidate == True`` 必须有
       ``offline_deterministic_gap_explanation``（非空字符串）；
    5. ``security_risk == True`` 时 ``final_triage_decision`` 必须是 ``security-blocker``；
    6. ``final_triage_decision`` 必须在 :data:`ALLOWED_TRIAGE_DECISIONS`；
    7. 所有字符串字段不得含真实 secret 字面（:func:`_scan_for_secrets`）。
    """
    errors: list[str] = []
    warnings: list[str] = []

    # ---- Rule: required fields present ---------------------------------
    for f in REQUIRED_FIELDS:
        if f not in record:
            errors.append(f"missing required field: {f!r}")

    # 字段全缺时直接返回，避免后续 KeyError 噪音
    if errors and all(f"missing required field: {f!r}" in errors for f in REQUIRED_FIELDS):
        return ValidationResult(ok=False, errors=errors, warnings=warnings)

    # ---- Rule 2: source_type allowlist ---------------------------------
    src = record.get("source_type")
    if src is not None and src not in _ALL_SOURCE_TYPES:
        errors.append(
            f"source_type {src!r} 不在 allowlist {_ALL_SOURCE_TYPES!r}"
        )

    # ---- Rule 1: maintainer rehearsal vs real_internal_feedback --------
    if record.get("maintainer_rehearsal") is True and record.get("real_internal_feedback") is True:
        errors.append(
            "maintainer_rehearsal=True 时 real_internal_feedback 必须 False"
            "（maintainer rehearsal 不计入真实反馈）"
        )

    # ---- Rule 3: synthetic / non-real → must not flag real_internal ----
    if src in _NON_REAL_SOURCE_TYPES and record.get("real_internal_feedback") is True:
        errors.append(
            f"source_type={src!r} 时 real_internal_feedback 必须 False"
            "（synthetic/maintainer rehearsal/user idea without trial 都不计入真实反馈）"
        )

    # ---- Rule 4: v3 candidate must explain offline gap -----------------
    if record.get("v3_backlog_candidate") is True:
        explanation = record.get("offline_deterministic_gap_explanation")
        if not isinstance(explanation, str) or not explanation.strip():
            errors.append(
                "v3_backlog_candidate=True 必须填 offline_deterministic_gap_explanation"
                "（说明 deterministic / offline / replay-first 为什么不够）"
            )

    # ---- Rule 5: security risk forces security-blocker ----------------
    if record.get("security_risk") is True:
        if record.get("final_triage_decision") != "security-blocker":
            errors.append(
                "security_risk=True 时 final_triage_decision 必须是 'security-blocker'"
                "（security 优先级 0，先停试用、净化、修复）"
            )

    # ---- Rule 6: final_triage_decision allowlist ----------------------
    decision = record.get("final_triage_decision")
    if decision is not None and decision not in ALLOWED_TRIAGE_DECISIONS:
        errors.append(
            f"final_triage_decision {decision!r} 不在 allowlist {ALLOWED_TRIAGE_DECISIONS!r}"
        )

    # ---- Rule 7: secret scan ------------------------------------------
    secret_findings = _scan_for_secrets(record)
    errors.extend(secret_findings)

    # ---- Soft warnings ------------------------------------------------
    if record.get("real_internal_feedback") is True and record.get("trial_completed") is False:
        warnings.append(
            "real_internal_feedback=True 但 trial_completed=False —— 反馈来源可信但"
            "试用未跑完，建议先归 needs-more-evidence 等试用者补跑完整 7 步"
        )

    # ---- counts_toward_real_feedback gating ---------------------------
    counts = (
        src == "real_internal_teammate"
        and record.get("maintainer_rehearsal") is False
        and record.get("real_internal_feedback") is True
        and record.get("trial_completed") is True
    )

    # ---- suggested_triage（仅参考，不强制覆盖 final_triage_decision）----
    suggested: str | None = None
    if record.get("security_risk") is True:
        suggested = "security-blocker"
    elif src in _NON_REAL_SOURCE_TYPES and record.get("v3_backlog_candidate") is True:
        # 非真实反馈即便提了 v3.0 能力，也只能 needs-more-evidence
        suggested = "needs-more-evidence"
    elif record.get("v3_backlog_candidate") is True and record.get("v2_patch_candidate") is False:
        suggested = "v3.0-backlog-candidate"
    elif record.get("v2_patch_candidate") is True:
        suggested = "v2.x-patch"
    elif src == "user_idea_without_trial":
        suggested = "needs-more-evidence"

    return ValidationResult(
        ok=not errors,
        errors=errors,
        warnings=warnings,
        counts_toward_real_feedback=counts,
        suggested_triage=suggested,
    )
