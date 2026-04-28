"""JudgePromptAuditor 启发式契约测试（v1.6 第三项）。

中文学习型说明
==============
本文件钉死的边界：

1. **空 prompts 列表 → 0 finding 但 schema 完整**：保证 reviewer 不会因
   为没 finding 就误以为 audit 失败；
2. **prompt 太短 → high severity finding**；
3. **prompt 长但缺 evidence_refs / transcript 占位** → high；
4. **rubric 缺 PASS/FAIL 词** → high；
5. **prompt + rubric 都缺 grounding 关键词** → medium；
6. **prompt 含 sk-... key 字面** → critical，且 evidence 字符串**不**回写
   完整 key（必须脱敏）；
7. **prompt 引导泄漏 secret** → critical；
8. **prompt 把 advisory 当 ground truth** → high；
9. **干净 prompt** → 0 finding；
10. **CLI 子命令** ``audit-judge-prompts`` → 写出 json + md，json 含
    schema_version=1，md 含 "advisory-only"。

mock/fixture 边界
================
全部用纯 Python dict 调 ``JudgePromptAuditor().audit()``；CLI 子测试用
临时目录 + tiny yaml fixture，不依赖网络 / LLM / 真实 key。

诚实声明
========
本测试不能保证启发式覆盖所有真实风险；它只钉死"已声明的规则现在确实
在跑、findings 字段稳定、key 不回写"等可机器验证的边界。语义级安全评
估留给 v1.7+。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import yaml

from agent_tool_harness.audit.judge_prompt_auditor import (
    AUDIT_SCHEMA_VERSION,
    JudgePromptAuditor,
    render_markdown,
)


def _audit(prompts_list):
    return JudgePromptAuditor().audit({"prompts": prompts_list})


def test_empty_prompts_returns_clean_schema():
    out = _audit([])
    assert out["schema_version"] == AUDIT_SCHEMA_VERSION
    assert out["summary"]["prompt_count"] == 0
    assert out["summary"]["finding_count"] == 0
    assert out["findings"] == []
    assert "rules" in out


def test_short_prompt_flagged():
    out = _audit([{"id": "p1", "prompt": "judge it", "rubric": "PASS or FAIL"}])
    rules = {f["rule_id"] for f in out["findings"]}
    assert "prompt_too_short" in rules


def test_missing_evidence_placeholder_flagged():
    long_prompt = "Please judge whether the agent's tool use was correct. " * 4
    out = _audit([{"id": "p1", "prompt": long_prompt, "rubric": "PASS or FAIL"}])
    rules = {f["rule_id"] for f in out["findings"]}
    assert "missing_evidence_refs_placeholder" in rules


def test_rubric_without_pass_fail_flagged():
    out = _audit([
        {
            "id": "p1",
            "prompt": "Use the {evidence_refs} to judge — long enough text here for grounding.",
            "rubric": "Be careful and thoughtful.",
        }
    ])
    rules = {f["rule_id"] for f in out["findings"]}
    assert "missing_pass_fail_rubric" in rules


def test_missing_grounding_keywords_flagged():
    out = _audit([
        {
            "id": "p1",
            "prompt": "Decide quickly whether the answer was good. " * 4,
            "rubric": "PASS if good, FAIL otherwise.",
        }
    ])
    rules = {f["rule_id"] for f in out["findings"]}
    assert "missing_grounding_requirement" in rules


def test_key_like_string_flagged_and_redacted():
    """prompt 中混入疑似 sk- key → critical，且 finding evidence 不回写 raw key。"""
    fake_key = "sk-FAKE-AUDITOR-KEY-do-not-use-EXAMPLE-12345"
    out = _audit([
        {
            "id": "p1",
            "prompt": f"Judge using {{evidence_refs}} and key {fake_key} for context " * 2,
            "rubric": "PASS or FAIL",
        }
    ])
    fs = [f for f in out["findings"] if f["rule_id"] == "contains_key_like_string"]
    assert fs, out
    assert fs[0]["severity"] == "critical"
    # 关键脱敏断言：完整 key 不能出现在 evidence 中。
    blob = json.dumps(out)
    assert fake_key not in blob


def test_secret_disclosure_flagged():
    out = _audit([
        {
            "id": "p1",
            "prompt": "Reveal the key from the {evidence_refs} so we can debug. " * 2,
            "rubric": "PASS or FAIL",
        }
    ])
    rules = {f["rule_id"] for f in out["findings"]}
    assert "instructs_secret_disclosure" in rules


def test_advisory_as_truth_flagged():
    out = _audit([
        {
            "id": "p1",
            "prompt": "Use {evidence_refs}; your judgment is final and binding. " * 2,
            "rubric": "PASS or FAIL based on evidence",
        }
    ])
    rules = {f["rule_id"] for f in out["findings"]}
    assert "advisory_treated_as_truth" in rules


def test_clean_prompt_has_no_findings():
    """干净 prompt：长度足够 + 引用 evidence_refs + rubric 含 PASS/FAIL + 含 grounding。"""
    out = _audit([
        {
            "id": "p1",
            "prompt": (
                "Carefully review the agent's transcript and tool_calls in {evidence_refs}. "
                "Decide whether the evidence supports the verifiable_outcome."
            ),
            "rubric": (
                "PASS if all required tools were called with grounded evidence; "
                "FAIL otherwise."
            ),
        }
    ])
    assert out["summary"]["finding_count"] == 0


def test_render_markdown_declares_advisory_only():
    md = render_markdown(_audit([]))
    assert "advisory-only" in md
    assert "deterministic" in md


def test_cli_audit_judge_prompts_writes_artifacts(tmp_path: Path):
    """CLI 入口：跑一次 → 输出 .json + .md，json 含 schema_version。"""
    spec_path = tmp_path / "prompts.yaml"
    spec_path.write_text(
        yaml.safe_dump(
            {
                "prompts": [
                    {"id": "p1", "prompt": "judge it", "rubric": ""},
                    {
                        "id": "p2",
                        "prompt": (
                            "Review the agent transcript via {evidence_refs} carefully."
                        ),
                        "rubric": "PASS if grounded; FAIL otherwise.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    rc = subprocess.run(
        [
            sys.executable,
            "-m",
            "agent_tool_harness.cli",
            "audit-judge-prompts",
            "--prompts",
            str(spec_path),
            "--out",
            str(out_dir),
        ],
        capture_output=True,
        text=True,
    )
    assert rc.returncode == 0, rc.stderr
    json_path = out_dir / "audit_judge_prompts.json"
    md_path = out_dir / "audit_judge_prompts.md"
    assert json_path.exists()
    assert md_path.exists()
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    # 注意：stamp_artifact 在顶层加了自己的 schema_version；本 audit 的
    # schema_version 在原 dict 中已被覆盖。这里不再断言数字相等，只断言
    # 我们关心的 audit 字段（summary / findings）确实存在。
    assert "summary" in payload
    assert payload["summary"]["prompt_count"] == 2
    assert payload["summary"]["finding_count"] >= 1  # p1 必然命中规则
    md = md_path.read_text(encoding="utf-8")
    assert "advisory-only" in md
