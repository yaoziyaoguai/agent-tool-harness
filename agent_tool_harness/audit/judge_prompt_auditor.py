"""Judge prompt / rubric 启发式安全审计 — v1.6 第三项。

中文学习型说明
==============
本模块负责什么
--------------
- 在 user 把"将要发给 LLM Judge"的 prompt 文本 + rubric 文本提交给真
  实模型**之前**，做一轮 deterministic 启发式扫描，提示常见安全 / 治理
  风险（如太短、缺 evidence_refs 占位符、缺 pass/fail 评分标准、缺
  grounding 要求、含 key 字面、引导泄漏 secret、把 advisory 当成最终
  ground truth 之类反模式）；
- 输出 JSON + Markdown 双 artifact，让 reviewer 在合入新 judge prompt 之
  前能 PR-diff 这份 audit；
- 严格 deterministic：所有规则都是字符串 / 正则匹配，**不**调任何 LLM、
  **不**联网、**不**需要 secret。

本模块**不**负责什么
--------------------
- **不**做语义级评估（"这条 prompt 是否能让模型给出对的判断"属于真实
  LLM judge 评估，不属于 v1.6 范围）；
- **不**自动改写 prompt，只产出 finding；
- **不**保证"通过 audit 就一定安全"——本模块只是治理 baseline；
- 不引入 ``regex`` / ``yaml`` 之外的依赖（stdlib only）。

artifact 排查路径
-----------------
- ``runs/<dir>/audit_judge_prompts.json``：findings 列表（含 severity /
  rule_id / evidence 字符串片段）；
- ``runs/<dir>/audit_judge_prompts.md``：human-readable 渲染。

用户接入点
----------
- CLI: ``python -m agent_tool_harness.cli audit-judge-prompts \
        --prompts <path> --out <out_dir>``。
  输入 ``<path>`` 是一个 yaml / json 文件，顶层结构：
  ``{"prompts": [{"id": "...", "prompt": "...", "rubric": "..."}]}``；
- 也可以通过 ``JudgePromptAuditor().audit(spec_dict)`` 在 Python 内嵌
  调用。

未来扩展点
----------
- 接入真实 LLM judge 后做"prompt 实际效果回归测试"（属于 v1.7+）；
- 引入 prompt schema validator 把 "evidence_refs" 强制要求字段化；
- 与 transcript_analyzer 联动：发现 prompt 在历史 run 中导致幻觉时打高
  severity。
"""

from __future__ import annotations

import re
from typing import Any

AUDIT_SCHEMA_VERSION = 1


# 规则元数据集中维护，方便 reviewer 快速理解每条 finding 的来源。
_RULES = {
    "prompt_too_short": {
        "severity": "high",
        "description": "prompt 文本过短（<80 字符），LLM 缺乏 grounding 容易幻觉",
    },
    "missing_evidence_refs_placeholder": {
        "severity": "high",
        "description": (
            "prompt 未引用 evidence_refs / transcript / artifact 占位符，"
            "无法 ground 在真实证据"
        ),
    },
    "missing_pass_fail_rubric": {
        "severity": "high",
        "description": (
            "rubric 缺失 PASS/FAIL/通过/失败 之类显式判定词，"
            "LLM 难以输出 deterministic 结论"
        ),
    },
    "missing_grounding_requirement": {
        "severity": "medium",
        "description": "prompt 未要求模型基于 evidence/事实/transcript 判断，可能编造理由",
    },
    "contains_key_like_string": {
        "severity": "critical",
        "description": "prompt/rubric 出现疑似 API key 字面（sk- / Bearer / 长 hex），严禁入仓",
    },
    "instructs_secret_disclosure": {
        "severity": "critical",
        "description": "prompt 中存在引导模型披露 key/secret/credential/token 的措辞",
    },
    "advisory_treated_as_truth": {
        "severity": "high",
        "description": (
            "prompt 暗示模型输出就是最终结果"
            "（'你的判断就是最终结果' / 'final ground truth'），"
            "违反 advisory-only 边界"
        ),
    },
}


# 关键正则 / 关键字常量，集中维护。
_KEY_LIKE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-]{20,}"),
    re.compile(r"\b[A-Fa-f0-9]{32,}\b"),  # 长 hex（多见于 token）
]
_SECRET_DISCLOSURE_KEYWORDS = (
    "reveal the key",
    "reveal your key",
    "print the api key",
    "leak the secret",
    "show me the credential",
    "披露 key",
    "泄漏 key",
    "输出密钥",
)
_ADVISORY_AS_TRUTH_KEYWORDS = (
    "your judgment is final",
    "your output is the final ground truth",
    "你的判断就是最终结果",
    "你的输出就是最终事实",
)
_GROUNDING_KEYWORDS = (
    "evidence",
    "transcript",
    "artifact",
    "tool_calls",
    "tool_responses",
    "证据",
    "凭证",
    "执行轨迹",
)
_PASS_FAIL_KEYWORDS = ("pass", "fail", "通过", "失败", "passed", "true", "false")
_EVIDENCE_PLACEHOLDERS = (
    "{evidence_refs}",
    "{transcript}",
    "{tool_calls}",
    "{tool_responses}",
    "evidence_refs",
)


def _evidence_snippet(text: str, marker: str, span: int = 24) -> str:
    """从 text 中截取 marker 附近的脱敏 snippet（不回写 raw key）。

    硬约束：snippet **绝不**返回 raw key 字面——找到 key 时只返回 marker
    名 + 长度 + 前缀 4 字符 + ``…[redacted]…``，避免 audit artifact 自身泄漏。
    """
    if marker == "<key-like>":
        return "<key-like value redacted; only first 4 chars retained for triage>"
    idx = text.lower().find(marker.lower())
    if idx < 0:
        return ""
    start = max(0, idx - span)
    end = min(len(text), idx + len(marker) + span)
    return text[start:end].replace("\n", " ")


def _check_one_prompt(item: dict[str, Any]) -> list[dict[str, Any]]:
    """对单条 prompt spec 跑全量启发式规则。"""
    findings: list[dict[str, Any]] = []
    pid = str(item.get("id", "?"))
    prompt = str(item.get("prompt", "") or "")
    rubric = str(item.get("rubric", "") or "")
    combined = prompt + "\n" + rubric

    def _add(rule_id: str, evidence: str = "") -> None:
        meta = _RULES[rule_id]
        findings.append(
            {
                "prompt_id": pid,
                "rule_id": rule_id,
                "severity": meta["severity"],
                "description": meta["description"],
                "evidence": evidence,
            }
        )

    if len(prompt.strip()) < 80:
        _add("prompt_too_short", f"len={len(prompt.strip())}")

    has_placeholder = any(p in combined for p in _EVIDENCE_PLACEHOLDERS)
    if not has_placeholder:
        _add("missing_evidence_refs_placeholder")

    rubric_lower = rubric.lower()
    if rubric and not any(k in rubric_lower for k in _PASS_FAIL_KEYWORDS):
        _add("missing_pass_fail_rubric")
    if not rubric:
        _add("missing_pass_fail_rubric", evidence="rubric is empty")

    combined_lower = combined.lower()
    if not any(k.lower() in combined_lower for k in _GROUNDING_KEYWORDS):
        _add("missing_grounding_requirement")

    for pat in _KEY_LIKE_PATTERNS:
        m = pat.search(combined)
        if m:
            raw = m.group(0)
            redacted = raw[:4] + "…[redacted len=" + str(len(raw)) + "]"
            _add("contains_key_like_string", evidence=redacted)
            break

    for kw in _SECRET_DISCLOSURE_KEYWORDS:
        if kw.lower() in combined_lower:
            _add("instructs_secret_disclosure", evidence=_evidence_snippet(combined, kw))
            break

    for kw in _ADVISORY_AS_TRUTH_KEYWORDS:
        if kw.lower() in combined_lower:
            _add("advisory_treated_as_truth", evidence=_evidence_snippet(combined, kw))
            break

    return findings


class JudgePromptAuditor:
    """对一组 judge prompt / rubric 跑启发式安全 audit。

    用法
    ----
    >>> auditor = JudgePromptAuditor()
    >>> result = auditor.audit({"prompts": [{"id": "p1", "prompt": "...", "rubric": "..."}]})
    >>> result["summary"]["finding_count"]

    输出 schema
    -----------
    顶层::

        {
          "schema_version": 1,
          "summary": {"prompt_count": N, "finding_count": M,
                      "by_severity": {"critical": ..., "high": ..., "medium": ...}},
          "findings": [ {prompt_id, rule_id, severity, description, evidence} ],
          "rules": { rule_id: {severity, description} },
        }
    """

    def audit(self, spec: dict[str, Any]) -> dict[str, Any]:
        prompts = spec.get("prompts") if isinstance(spec, dict) else None
        if not isinstance(prompts, list):
            raise ValueError(
                "audit-judge-prompts: input spec must be a mapping with key 'prompts' (list)"
            )
        all_findings: list[dict[str, Any]] = []
        for item in prompts:
            if not isinstance(item, dict):
                raise ValueError(
                    "audit-judge-prompts: each prompt entry must be a mapping with id/prompt/rubric"
                )
            all_findings.extend(_check_one_prompt(item))
        by_sev = {"critical": 0, "high": 0, "medium": 0}
        for f in all_findings:
            sev = f["severity"]
            by_sev[sev] = by_sev.get(sev, 0) + 1
        return {
            "schema_version": AUDIT_SCHEMA_VERSION,
            "summary": {
                "prompt_count": len(prompts),
                "finding_count": len(all_findings),
                "by_severity": by_sev,
            },
            "findings": all_findings,
            "rules": _RULES,
        }


def render_markdown(audit_result: dict[str, Any]) -> str:
    """把 audit 结果渲染成 reviewer 可读的 Markdown。

    渲染契约：明确声明 deterministic / advisory-only；按 severity 分组列
    finding；不输出原始 key 字面（snippet 已脱敏）。
    """

    summary = audit_result.get("summary", {})
    by_sev = summary.get("by_severity", {})
    lines = [
        "# Judge Prompt Audit (deterministic, advisory-only)",
        "",
        "> 本 audit 仅基于启发式规则，**不**等价于真实 LLM judge 安全验证；",
        "> 通过 audit 不代表 prompt 在生产中一定安全。详见 docs/ARTIFACTS.md。",
        "",
        f"- Prompts audited: {summary.get('prompt_count', 0)}",
        f"- Findings: {summary.get('finding_count', 0)}",
        f"  - critical: {by_sev.get('critical', 0)}",
        f"  - high: {by_sev.get('high', 0)}",
        f"  - medium: {by_sev.get('medium', 0)}",
        "",
        "## Findings",
        "",
    ]
    findings = audit_result.get("findings", [])
    if not findings:
        lines.append("- (none)")
        return "\n".join(lines) + "\n"
    for f in findings:
        lines.append(
            f"- [{f.get('severity', '?').upper()}] {f.get('prompt_id')} :: "
            f"`{f.get('rule_id')}` — {f.get('description')}"
        )
        if f.get("evidence"):
            lines.append(f"    evidence: {f['evidence']}")
    return "\n".join(lines) + "\n"
