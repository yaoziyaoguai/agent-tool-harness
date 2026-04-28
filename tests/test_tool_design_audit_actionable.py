"""ToolDesignAuditor v0.2 第二轮：actionable structured findings 测试。

为什么单独成文件：
- 这一组测试钉的是"finding 输出格式契约"——下游消费者（report.md / 远程 dashboard /
  CI bot）依赖 ``principle`` / ``principle_title`` / ``why_it_matters`` /
  ``suggestion`` / ``severity`` 等字段做归类与展示，任何一个字段悄悄消失或改名都
  应该被立刻发现。
- 与 ``test_tool_design_audit_semantic.py``（钉判定逻辑）和
  ``test_tool_design_audit_decoy.py``（钉端到端诱饵识别）分工互补。

fake/mock 边界：本文件只用最小 ToolSpec 内存对象 + 端到端 audit_tools.json /
report.md 输出，不调用任何真实工具。

测试纪律：finding 必须 deterministic 启发式；signal_quality 必须永远写
``deterministic_heuristic``——不允许偷偷升级为 production-grade 暗示用户已具备
LLM 语义判定能力。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agent_tool_harness.audit.tool_design_auditor import (
    _PRINCIPLE_TITLES,
    ToolDesignAuditor,
)
from agent_tool_harness.config.tool_spec import ToolSpec


def _spec(**overrides: Any) -> ToolSpec:
    """字段齐全的最小 ToolSpec 工厂——只针对一个变量做反例。"""

    base: dict[str, Any] = {
        "name": "alpha_resource_action",
        "namespace": "alpha.resource",
        "version": "0.1",
        "description": (
            "Look up a customer billing invoice by its invoice id and return summary "
            "plus the billing contact information for downstream reconciliation."
        ),
        "when_to_use": "Use when the user asks about an invoice status or billing contact.",
        "when_not_to_use": "Do not use for shipping address questions.",
        "input_schema": {
            "type": "object",
            "required": ["invoice_id"],
            "properties": {
                "invoice_id": {"type": "string"},
                "response_format": {"type": "string", "enum": ["concise", "detailed"]},
            },
        },
        "output_contract": {
            "required_fields": ["summary", "evidence", "next_action", "technical_id"],
            "raw_fields_allowed": False,
        },
        "token_policy": {
            "supports_pagination": True,
            "supports_filtering": True,
            "supports_range_selection": True,
            "max_output_tokens": 800,
            "default_limit": 10,
            "truncation_guidance": "Narrow by invoice_id.",
            "actionable_errors": True,
        },
        "side_effects": {"destructive": False, "open_world_access": False},
        "executor": {"type": "python", "module": "demo", "function": "alpha"},
    }
    base.update(overrides)
    return ToolSpec(**base)


# ---------------------------------------------------------------------------
# 1) finding 字段契约
# ---------------------------------------------------------------------------


def test_finding_dict_carries_principle_and_principle_title_for_all_rule_ids():
    """每条 finding 输出必须含 ``principle`` + ``principle_title``。

    模拟真实 bug：下游 dashboard 想按 Anthropic 5 类原则分组展示，但 v0.1 finding
    只有 ``rule_id`` 字符串需要解析。本测试钉住"自描述"契约——只要 finding 出来，
    一定有 principle 字段。
    """

    tool = _spec(
        description=(
            "Quickly returns a likely root cause guess from a runtime trace_id without "
            "inspecting the underlying event chain. A single-step shortcut for incident "
            "questions."
        ),
        input_schema={
            "type": "object",
            "required": ["x"],
            "properties": {"x": {"type": "string"}},
        },
    )
    result = ToolDesignAuditor().audit([tool])
    findings = result["tools"][0]["findings"]
    assert findings, "at least one finding expected"
    for f in findings:
        # principle 必须能从 _PRINCIPLE_TITLES 找到对应标题
        assert f["principle"] in _PRINCIPLE_TITLES, f
        assert f["principle_title"] == _PRINCIPLE_TITLES[f["principle"]], f


def test_finding_principle_matches_rule_id_prefix():
    """``principle`` 必须等于 rule_id 的"."左半段——契约不变。"""

    tool = _spec(when_to_use="Use it.", when_not_to_use="Do not use it for layout.")
    result = ToolDesignAuditor().audit([tool])
    for f in result["tools"][0]["findings"]:
        assert f["principle"] == f["rule_id"].split(".")[0]


def test_high_severity_findings_have_why_it_matters_and_suggestion():
    """v0.2 第二轮 high-severity 关键 finding 必须同时携带 why_it_matters +
    suggestion，让用户能直接行动。

    若未来新增 high-severity 规则忘了写 why_it_matters，本测试不会拦下来——这
    是有意设计：规则数量在增长，硬性要求每条都写会变成形式主义。本测试只钉住
    本轮承诺过的三条核心新规则（shallow_wrapper / semantic_overlap /
    usage_boundary_duplicated），其它规则的 why_it_matters 是可选字段。
    """

    primary = _spec(
        name="primary_invoice_lookup",
        namespace="primary.invoice",
        description=(
            "Trace runtime incident chain through ordered event ids and boundary "
            "transitions and checkpoint state. Use when users ask root cause questions."
        ),
        when_to_use=(
            "Use first for runtime, checkpoint, or boundary incidents where users want "
            "root cause and trace_id is available."
        ),
    )
    decoy = _spec(
        name="primary_invoice_quick",
        namespace="primary.quick",
        description=(
            "Trace runtime incident chain through ordered event ids and boundary "
            "transitions and checkpoint state without inspecting underlying records. "
            "A single-step shortcut for any runtime incident root cause question."
        ),
        when_to_use=(
            "Use first for runtime, checkpoint, or boundary incidents where users want "
            "root cause and trace_id is available; you do not need to call other tools."
        ),
        when_not_to_use=(
            "Use first for runtime, checkpoint, or boundary incidents where users want "
            "root cause and trace_id is available; you do not need to call other tools."
        ),
    )
    result = ToolDesignAuditor().audit([primary, decoy])
    decoy_findings = next(t for t in result["tools"] if t["tool_name"] == decoy.name)
    by_rule = {f["rule_id"]: f for f in decoy_findings["findings"]}
    for must_have in (
        "right_tools.shallow_wrapper",
        "right_tools.semantic_overlap",
        "prompt_spec.usage_boundary_duplicated",
    ):
        assert must_have in by_rule, (must_have, by_rule)
        f = by_rule[must_have]
        assert f["severity"] == "high"
        assert f["why_it_matters"], (
            f"high-severity rule {must_have} 必须写 why_it_matters，否则下游消费者"
            "无法解释'为什么必须改'"
        )
        assert f["suggestion"], must_have


# ---------------------------------------------------------------------------
# 2) audit_tools.json schema_version + run_metadata + signal_quality
# ---------------------------------------------------------------------------


@pytest.fixture()
def audit_runtime_artifact(tmp_path: Path) -> dict[str, Any]:
    """运行 CLI audit-tools 后读 audit_tools.json，验证 stamp + payload。"""

    from agent_tool_harness.cli import main

    out = tmp_path / "audit-runtime"
    rc = main([
        "audit-tools",
        "--tools",
        "examples/runtime_debug/tools.yaml",
        "--out",
        str(out),
    ])
    assert rc == 0
    return json.loads((out / "audit_tools.json").read_text(encoding="utf-8"))


def test_audit_tools_artifact_carries_schema_version_and_run_metadata(
    audit_runtime_artifact: dict[str, Any]
) -> None:
    """audit_tools.json 必须始终带 schema_version + run_metadata。

    模拟真实 bug：v0.2 改了 finding 字段后，run pipeline 把这个文件传给远程
    dashboard，但 dashboard 不知道 schema 变了。schema_version 字段是版本协商
    的最小契约——本测试钉住它不能消失。
    """

    assert audit_runtime_artifact["schema_version"]
    assert audit_runtime_artifact["run_metadata"]["run_id"]
    assert audit_runtime_artifact["run_metadata"]["generated_at"]


def test_audit_tools_artifact_signal_quality_must_be_deterministic_heuristic(
    audit_runtime_artifact: dict[str, Any]
) -> None:
    """signal_quality 必须永远写 ``deterministic_heuristic``。

    模拟真实 bug：未来某次"快速 patch"把 signal_quality 改成 production_grade
    或 semantic_audit 暗示用户当前 audit 已是 LLM 级证明——这是治理事故。本
    断言钉死边界：只允许通过引入真实 transcript / LLM judge 才升级；纯启发式
    增强不许动这个字段。
    """

    summary = audit_runtime_artifact["summary"]
    assert summary["signal_quality"] == "deterministic_heuristic"
    assert summary["signal_quality_note"]


# ---------------------------------------------------------------------------
# 3) report.md actionable rendering
# ---------------------------------------------------------------------------


def test_report_md_renders_signal_quality_warnings_and_principle_for_high_findings(
    tmp_path: Path,
) -> None:
    """跑一次 run 让 report.md 生成；断言 Tool Design Audit 节包含：
    1) signal_quality + note；
    2) high-severity finding 渲染 principle_title + why_it_matters + suggested_fix。

    这是端到端契约测试——只要 ToolDesignAuditor 输出的字段被任何一处下游悄悄
    丢弃，本测试都会立刻失败。
    """

    from agent_tool_harness.cli import main

    out = tmp_path / "good-run"
    rc = main([
        "run",
        "--project",
        "examples/runtime_debug/project.yaml",
        "--tools",
        "examples/runtime_debug/tools.yaml",
        "--evals",
        "examples/runtime_debug/evals.yaml",
        "--out",
        str(out),
        "--mock-path",
        "good",
    ])
    assert rc == 0
    report = (out / "report.md").read_text(encoding="utf-8")
    assert "### Tool Design Audit signal quality" in report
    assert "deterministic_heuristic" in report
    # runtime_debug 工具集合是反向保护用例——不应触发 high-severity finding。
    # 但 signal quality 段必须仍然渲染——这是无论是否有 finding 都必须出现的边界声明。


def test_report_md_renders_high_severity_decoy_findings_with_principle_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """构造一个含诱饵的 tools.yaml，跑 audit-tools 后断言 audit_tools.json
    finding 含 principle_title——再用 MarkdownReport 直接渲染验证 report 字符串。

    fake/mock 边界：这里直接调用 MarkdownReport.render，不跑 run pipeline，
    避免把 mock adapter 的 PASS/FAIL 信号引入本测试——本测试只关心 audit
    输出怎么被渲染。
    """

    from agent_tool_harness.reports.markdown_report import MarkdownReport

    primary = _spec(
        name="primary_invoice_lookup",
        namespace="primary.invoice",
        description=(
            "Trace runtime incident chain through ordered event ids and boundary "
            "transitions and checkpoint state. Use when users ask root cause questions."
        ),
        when_to_use=(
            "Use first for runtime, checkpoint, or boundary incidents where users want "
            "root cause and trace_id is available."
        ),
    )
    decoy = _spec(
        name="primary_invoice_quick",
        namespace="primary.quick",
        description=(
            "Trace runtime incident chain through ordered event ids and boundary "
            "transitions and checkpoint state without inspecting underlying records. "
            "A single-step shortcut for any runtime incident root cause question."
        ),
        when_to_use=(
            "Use first for runtime, checkpoint, or boundary incidents where users want "
            "root cause and trace_id is available; you do not need to call other tools."
        ),
        when_not_to_use=(
            "Use first for runtime, checkpoint, or boundary incidents where users want "
            "root cause and trace_id is available; you do not need to call other tools."
        ),
    )
    audit_tools = ToolDesignAuditor().audit([primary, decoy])
    report = MarkdownReport().render(
        project={"name": "decoy-fixture"},
        audit_tools=audit_tools,
        audit_evals={"summary": {"eval_count": 0, "average_score": 0}, "evals": []},
        metrics={
            "total_evals": 0,
            "passed": 0,
            "failed": 0,
            "skipped_evals": 0,
            "error_evals": 0,
            "total_tool_calls": 0,
            "signal_quality": "tautological_replay",
            "signal_quality_note": "n/a",
        },
        judge_results={"results": []},
        diagnosis={"results": []},
    )
    assert "### Tool Design Audit signal quality" in report
    assert "### Tool Design Audit warnings" in report
    assert "semantic_risk_detected" in report
    assert "### Tool Design Audit high-severity findings" in report
    # principle 标题（取 right_tools 这一段）必须出现
    assert "Choosing the right tools" in report
    # why_it_matters 与 suggested_fix 必须落到 report——这是 actionable 契约。
    assert "why_it_matters:" in report
    assert "suggested_fix:" in report
