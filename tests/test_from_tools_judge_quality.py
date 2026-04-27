"""候选 eval judge / spec-completeness 质量治理测试。

为什么单独成文件：
- 这一组测试钉的是"``from_tools`` 候选阶段必须默认就降低 tautological / 自证风险"
  这一条根因边界。它与 ``test_anti_patch.py`` 的 anti-tautology review note 检查互补：
  那一组在审核者面前留提醒；本组在生成器/审计/promoter 三层都钉死，避免坏候选
  从任何缝隙偷溜进正式 evals.yaml。
- fake/mock 边界：本文件不调用真实 LLM、不接 transcript、不读真实工单；只用最小
  ToolSpec / EvalSpec 内存对象 + 真实 demo YAML 做断言。
- xfail 模拟约定：本文件**不引入新的 xfail**——所有断言都必须当前通过；如果未来
  把"语义级 LLM judge 才能检测"的能力加进来，可单独再起 xfail 文件，不与本文件混。

测试纪律（与 docs/TESTING.md 同步）：
- 不允许通过放宽断言追求绿；如果断言失败，必须修主体代码（生成器 / 审计 / promoter），
  不能为了让测试通过把生成器再写回 tautological 默认。
- 不允许把"工具被调用"当成评估成功——这是被本组测试反复钉住的根因。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.loader import load_project, load_tools
from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.eval_generation.candidate_writer import CandidateWriter
from agent_tool_harness.eval_generation.from_tools import FromToolsGenerator
from agent_tool_harness.eval_generation.promoter import CandidatePromoter

PROJECT_PATH = "examples/runtime_debug/project.yaml"
TOOLS_PATH = "examples/runtime_debug/tools.yaml"


# ---------------------------------------------------------------------------
# 内存 fixture：构造一个"契约完整"和"契约不完整"的最小 ToolSpec
# ---------------------------------------------------------------------------


def _complete_tool(**overrides: Any) -> ToolSpec:
    """构造契约齐全的 ToolSpec，用于"基线候选必须 runnable"的正向断言。

    所有关键字段都满足 ``_spec_completeness_gaps`` 的硬约束；任何修改都应同步
    更新 from_tools._CRITICAL_SPEC_GAPS 与本 fixture。
    """

    base: dict[str, Any] = {
        "name": "alpha",
        "namespace": "domain.x",
        "version": "0.1",
        "description": "Diagnostic tool for the alpha workflow.",
        "when_to_use": "Use when the user reports incident in workflow alpha.",
        "when_not_to_use": "Do not use for visual layout questions.",
        "input_schema": {
            "type": "object",
            "required": ["trace_id"],
            "properties": {
                "trace_id": {"type": "string"},
                "response_format": {"type": "string", "enum": ["concise", "detailed"]},
            },
        },
        "output_contract": {
            "required_fields": ["summary", "evidence", "next_action"],
            "raw_fields_allowed": False,
        },
        "token_policy": {
            "supports_pagination": True,
            "max_output_tokens": 1000,
            "actionable_errors": True,
        },
        "side_effects": {"destructive": False},
        "executor": {"type": "python", "path": "x.py", "function": "alpha"},
        "metadata": {
            "eval_generation": {
                "fixture": {"trace_id": "trace-001"},
                "expected_root_cause": "boundary",
                "evidence": ["ev-1"],
            },
        },
    }
    base.update(overrides)
    return ToolSpec(**base)


# ---------------------------------------------------------------------------
# 1) from_tools 默认 judge 必须含至少一条语义/防御性规则
# ---------------------------------------------------------------------------


def test_from_tools_default_judge_includes_semantic_rules():
    """模拟的真实 bug：旧默认 judge 只有 ``must_call_tool`` + ``must_use_evidence``，
    审核者不修就转正会得到 mock-replay 下结构性必过的 eval。这条断言钉住"默认就有
    语义/防御性规则"——若有人把默认改回去，立刻红。
    """

    candidates = FromToolsGenerator().generate(
        load_project(PROJECT_PATH), load_tools(TOOLS_PATH)
    )
    assert candidates, "需要至少一个候选才能验证默认 judge 规则"
    for cand in candidates:
        rule_types = [
            r.get("type") for r in cand["judge"]["rules"] if isinstance(r, dict)
        ]
        # 默认必须含 must_use_evidence；同时要求出现至少一条防御性/语义规则
        # （must_not_modify_before_evidence 永远加；expected_root_cause_contains
        # 在 hint 提供 expected_root_cause 时加）。
        assert "must_use_evidence" in rule_types, cand["id"]
        assert "must_not_modify_before_evidence" in rule_types, cand["id"]


def test_from_tools_default_judge_passes_tautology_audit():
    """对照测试：跑 EvalQualityAuditor，**默认候选不应**被报
    ``judge.tautological_must_call_tool``——否则说明默认判定退化回纯结构规则。

    注意：候选若 ``runnable=False``（缺 fixture），auditor 不会触发该 finding，
    但本测试针对的 candidate 1（runtime_input_boundary_candidate）默认 runnable=True，
    且 expected_tool_behavior.required_tools 非空——是触发 tautology 检测的最小条件。
    """

    candidates = FromToolsGenerator().generate(
        load_project(PROJECT_PATH), load_tools(TOOLS_PATH)
    )
    runnable_candidates = [c for c in candidates if c.get("runnable")]
    assert runnable_candidates, "需要至少一条 runnable 候选才能验证 tautology"
    for cand in runnable_candidates:
        case = EvalSpec(
            id=cand["id"],
            name=cand["name"],
            category=cand["category"],
            split=cand["split"],
            realism_level=cand["realism_level"],
            complexity=cand["complexity"],
            source=cand["source"],
            user_prompt=cand["user_prompt"],
            initial_context=cand["initial_context"],
            verifiable_outcome=cand["verifiable_outcome"],
            success_criteria=cand["success_criteria"],
            expected_tool_behavior=cand["expected_tool_behavior"],
            judge=cand["judge"],
        )
        result = EvalQualityAuditor().audit_eval(case)
        rule_ids = {f.rule_id for f in result.findings}
        assert "judge.tautological_must_call_tool" not in rule_ids, (
            cand["id"],
            rule_ids,
        )


# ---------------------------------------------------------------------------
# 2) success_criteria 反 tautology
# ---------------------------------------------------------------------------


def test_from_tools_success_criteria_includes_anti_tautology_text():
    """默认 success_criteria 必须显式说明"调用工具本身不算成功"，且要求结论引用
    evidence。这样审核者把 success_criteria 直接抄进正式 eval 时也带着反 tautology
    契约——而不是依赖审核者人脑记住。
    """

    candidates = FromToolsGenerator().generate(
        load_project(PROJECT_PATH), load_tools(TOOLS_PATH)
    )
    # demo 第二、三个候选不带 hint.success_criteria，会落到默认值；以此判定。
    defaulted = [
        c
        for c in candidates
        if c["success_criteria"] == FromToolsGenerator()._default_success_criteria()
    ]
    assert defaulted, "至少需要一条命中默认 success_criteria 才能验证文案"
    joined = "\n".join(defaulted[0]["success_criteria"])
    assert "evidence" in joined.lower() or "证据" in joined
    assert "调用" in joined or "tautolog" in joined.lower() or "成功标准" in joined


def test_eval_quality_auditor_flags_success_criteria_only_required_tools():
    """模拟的真实 bug：审核者把 success_criteria 写成
    ``["Required tools must be called", "Call required_tools in order"]``，看似有
    准则但全部只是 required_tools 的复述。RuleJudge 仍是 tautological，只是绕开了
    must_call_tool 检测。本断言钉住新 finding 能识别这种伪装。
    """

    case = EvalSpec(
        id="bad_criteria",
        name="bad",
        category="r",
        split="training",
        realism_level="synthetic_realistic",
        complexity="multi_step",
        source="incident",
        user_prompt="用户报告系统在 checkpoint 恢复后接受了过期输入，请定位根因。",
        initial_context={"trace_id": "t1"},
        verifiable_outcome={"expected_root_cause": "boundary"},
        # 全部条目只指向 required_tools 的复述，无证据/根因/行为语义
        success_criteria=[
            "All required_tools must be called.",
            "The required_tools should be invoked in the listed order.",
        ],
        expected_tool_behavior={"required_tools": ["alpha"]},
        judge={
            "rules": [
                {"type": "must_call_tool", "tool": "alpha"},
                {"type": "must_use_evidence"},
            ]
        },
    )
    result = EvalQualityAuditor().audit_eval(case)
    rule_ids = {f.rule_id for f in result.findings}
    assert "verifiability.success_criteria_only_required_tools" in rule_ids, rule_ids


def test_eval_quality_auditor_does_not_flag_normal_success_criteria():
    """对照测试：合理的 success_criteria（含证据/根因关键词）**不应**被误报。
    这是反补丁保险——避免新 finding 误伤所有正常 eval。
    """

    case = EvalSpec(
        id="ok_criteria",
        name="ok",
        category="r",
        split="training",
        realism_level="synthetic_realistic",
        complexity="multi_step",
        source="incident",
        user_prompt="用户报告系统在 checkpoint 恢复后接受了过期输入，请定位根因。",
        initial_context={"trace_id": "t1"},
        verifiable_outcome={"expected_root_cause": "boundary"},
        success_criteria=[
            "结论必须引用工具返回的 evidence。",
            "回答必须解释 root cause 并说明下一步行动。",
        ],
        expected_tool_behavior={"required_tools": ["alpha"]},
        judge={"rules": [{"type": "must_use_evidence"}]},
    )
    result = EvalQualityAuditor().audit_eval(case)
    rule_ids = {f.rule_id for f in result.findings}
    assert "verifiability.success_criteria_only_required_tools" not in rule_ids, rule_ids


# ---------------------------------------------------------------------------
# 3) 工具契约缺关键字段 → review_status=needs_review + runnable=false
# ---------------------------------------------------------------------------


def test_from_tools_marks_needs_review_when_tool_missing_when_to_use():
    """缺 ``when_to_use`` 是接入期最常见的"看似可用"陷阱：Agent 拿到工具但不知道何
    时该调用。本断言确保这种工具不会生成"看似 runnable"的候选。
    """

    tool = _complete_tool(when_to_use="")
    candidates = FromToolsGenerator().generate(
        project=load_project(PROJECT_PATH), tools=[tool]
    )
    assert len(candidates) == 1
    cand = candidates[0]
    assert cand["review_status"] == "needs_review"
    assert cand["runnable"] is False
    assert "missing_when_to_use" in cand["missing_context"]
    notes_text = " | ".join(cand["review_notes"])
    assert "needs_review" in notes_text or "tools.yaml" in notes_text


def test_from_tools_marks_needs_review_when_tool_missing_output_contract():
    """缺 ``output_contract`` 等同于"工具不告诉 Agent 我会返回什么"——
    must_use_evidence 直接没法工作。
    """

    tool = _complete_tool(output_contract={})
    candidates = FromToolsGenerator().generate(
        project=load_project(PROJECT_PATH), tools=[tool]
    )
    cand = candidates[0]
    assert cand["review_status"] == "needs_review"
    assert "missing_output_contract" in cand["missing_context"]


def test_from_tools_marks_needs_review_when_output_contract_missing_evidence():
    """``output_contract.required_fields`` 不含 ``evidence`` →
    must_use_evidence 永远拿不到证据。"""

    tool = _complete_tool(
        output_contract={"required_fields": ["summary", "next_action"]}
    )
    candidates = FromToolsGenerator().generate(
        project=load_project(PROJECT_PATH), tools=[tool]
    )
    cand = candidates[0]
    assert cand["review_status"] == "needs_review"
    assert "missing_evidence_in_output_contract" in cand["missing_context"]


def test_from_tools_marks_needs_review_when_input_schema_missing_response_format():
    """``input_schema.properties`` 不含 ``response_format`` → Agent 没有 token 控制
    开关，生成的 eval 没办法验证 token efficiency 维度。
    """

    tool = _complete_tool(
        input_schema={
            "type": "object",
            "required": ["trace_id"],
            "properties": {"trace_id": {"type": "string"}},
        },
    )
    candidates = FromToolsGenerator().generate(
        project=load_project(PROJECT_PATH), tools=[tool]
    )
    cand = candidates[0]
    assert cand["review_status"] == "needs_review"
    assert "missing_response_format" in cand["missing_context"]


def test_from_tools_keeps_candidate_status_when_spec_complete_but_hint_missing():
    """对照测试：契约齐全只是缺 hint（fixture / expected_root_cause）时，应保持
    ``review_status="candidate"`` + runnable=False，不要错误升级到 needs_review。
    审核者只需补 hint 即可继续转正流程。
    """

    tool = _complete_tool(metadata={})
    candidates = FromToolsGenerator().generate(
        project=load_project(PROJECT_PATH), tools=[tool]
    )
    cand = candidates[0]
    assert cand["review_status"] == "candidate"
    assert cand["runnable"] is False
    assert "fixture" in cand["missing_context"]
    assert "expected_root_cause" in cand["missing_context"]


# ---------------------------------------------------------------------------
# 4) promote-evals 跳过 needs_review / runnable=false 候选
# ---------------------------------------------------------------------------


def test_promote_skips_needs_review_candidate_from_generator(tmp_path):
    """端到端断言：从 generator 出来的 needs_review 候选必须被 promoter 跳过；
    且 reason 字符串必须包含 "review_status"，让审核者一眼看到下一步要做什么。
    这条钉死 promoter 的硬约束在生成器变化后仍然有效。
    """

    tool = _complete_tool(when_to_use="")
    candidates = FromToolsGenerator().generate(
        project=load_project(PROJECT_PATH), tools=[tool]
    )
    candidates_path = tmp_path / "eval_candidates.yaml"
    with candidates_path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(
            {"eval_candidates": candidates}, fh, allow_unicode=True, sort_keys=False
        )
    out_path = tmp_path / "promoted.yaml"
    result = CandidatePromoter().promote(candidates_path, out_path)

    assert result.promoted == []
    assert len(result.skipped) == 1
    reason = result.skipped[0]["reason"]
    assert "review_status" in reason
    assert "needs_review" in reason


# ---------------------------------------------------------------------------
# 5) anti-cheating prompt 兜底
# ---------------------------------------------------------------------------


def test_from_tools_scrubs_cheating_phrases_from_prompt():
    """模拟的真实 bug：hint 作者写 ``user_prompt: "请使用 alpha 工具排查这个故障"``，
    旧版本只去工具名得到 ``"请使用 相关诊断能力 工具排查这个故障"``——动词 + "工具"
    共现仍会被 EvalQualityAuditor 报 cheating_prompt。本断言钉住生成器的最终 scrub。
    """

    tool = _complete_tool(
        metadata={
            "eval_generation": {
                "user_prompt": "请使用 alpha 工具排查这个故障",
                "fixture": {"trace_id": "trace-001"},
                "expected_root_cause": "boundary",
            }
        }
    )
    candidates = FromToolsGenerator().generate(
        project=load_project(PROJECT_PATH), tools=[tool]
    )
    prompt = candidates[0]["user_prompt"]
    assert "请使用" not in prompt
    assert "alpha" not in prompt  # 工具名也已去除
    # 替换后不再同时出现"使用" + "工具"（避免动词+名词共现的作弊指向）
    assert not ("使用" in prompt and "工具" in prompt)


def test_candidate_writer_does_not_warn_cheating_for_scrubbed_prompts():
    """对照测试：经过 _scrub_cheating_signals 处理后的候选，CandidateWriter 不应
    再发 ``cheating_prompt_suspect`` warning——否则说明 scrub 没真起作用。
    """

    tool = _complete_tool(
        metadata={
            "eval_generation": {
                "user_prompt": "please use alpha to investigate the failure",
                "fixture": {"trace_id": "trace-001"},
                "expected_root_cause": "boundary",
            }
        }
    )
    candidates = FromToolsGenerator().generate(
        project=load_project(PROJECT_PATH), tools=[tool]
    )
    warnings = CandidateWriter().collect_warnings(candidates)
    assert not any("cheating_prompt_suspect" in w for w in warnings), warnings


# ---------------------------------------------------------------------------
# 6) 中文学习型注释/docstring 存在性检查
# ---------------------------------------------------------------------------


def test_from_tools_module_has_chinese_learning_docstrings():
    """治理硬约束：本轮新增/重写的关键函数必须有中文学习型 docstring。
    这是"凡是新增或修改代码必须写中文学习型注释/docstring"原则的回归保险——
    防止下次 refactor 把注释一并删掉退化为纯英文 API doc。
    """

    src = Path("agent_tool_harness/eval_generation/from_tools.py").read_text(
        encoding="utf-8"
    )
    # 关键新增函数 + 关键中文断言关键词
    assert "_spec_completeness_gaps" in src
    assert "_default_judge_rules" in src
    assert "_default_success_criteria" in src
    assert "_scrub_cheating_signals" in src
    # 中文学习型注释短语（任意命中即可，避免脆弱字符串匹配）
    chinese_hints = ("架构边界", "用户项目自定义入口", "如何通过 artifacts", "扩展点")
    hits = sum(1 for hint in chinese_hints if hint in src)
    assert hits >= 3, (
        f"from_tools.py 缺少中文学习型注释关键词，仅命中 {hits}/{len(chinese_hints)}"
    )


def test_eval_quality_auditor_new_finding_has_chinese_docstring():
    """治理硬约束（同上）：新增 finding 必须有中文 docstring 解释为什么这是真问题。"""

    src = Path("agent_tool_harness/audit/eval_quality_auditor.py").read_text(
        encoding="utf-8"
    )
    assert "_success_criteria_has_behavioral_signal" in src
    assert "success_criteria_only_required_tools" in src
    assert "deterministic 启发式" in src
