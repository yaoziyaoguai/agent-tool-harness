"""P1B 接入体验三件套治理测试：
1. candidate promote 流程；
2. generate-evals warnings；
3. artifact schema_version + run_metadata。

为什么单独成文件：
- 这些测试钉的是"接入体验合同"——审核者拿到候选要看到 review_notes、CI 拿到
  artifact 要看到 schema_version、promoter 拒绝覆盖正式 evals.yaml 这类**用户
  对外可见的承诺**。
- 与 ``test_p0_governance_hardening.py`` 互补：那是"判定根因"层；本文件是"接入
  契约"层。两者都不允许被弱化。
- fake/mock 边界：本文件不引入真实 LLM、真实 transcript、真实 issue tracker；
  只通过最小 YAML fixture 验证机械搬运 / warning 计算 / 戳是否真写到磁盘。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.artifact_schema import ARTIFACT_SCHEMA_VERSION
from agent_tool_harness.cli import main as cli_main
from agent_tool_harness.config.loader import load_evals, load_project, load_tools
from agent_tool_harness.eval_generation.candidate_writer import CandidateWriter
from agent_tool_harness.eval_generation.promoter import CandidatePromoter
from agent_tool_harness.runner.eval_runner import EvalRunner

# ---------------------------------------------------------------------------
# 共用 fixture：构造一份"完整可 promote"的候选 dict
# ---------------------------------------------------------------------------


def _accepted_candidate(cid: str = "case_accepted") -> dict:
    """构造一条满足 promoter 全部硬约束的候选。

    用于反向用例：故意一个字段一个字段往下减，看 promoter 是否真的把它跳掉；
    避免误把"reject 全部" 当作 "promoter 工作正常"。
    """

    return {
        "id": cid,
        "name": "Accepted candidate",
        "category": "demo",
        "split": "regression",
        "realism_level": "regression",
        "complexity": "multi_step",
        "source": "generated_from_tools",
        "user_prompt": "A real user reports an issue and asks the agent to diagnose.",
        "initial_context": {"trace_id": "trace-001"},
        "verifiable_outcome": {
            "expected_root_cause": "input_boundary",
            "evidence": ["ev-17"],
        },
        "success_criteria": ["Cite evidence."],
        "expected_tool_behavior": {"required_tools": ["alpha"]},
        "judge": {"rules": [{"type": "must_use_evidence"}]},
        "runnable": True,
        "missing_context": [],
        "review_status": "accepted",
        "review_notes": ["已人工核对真实用户场景。"],
    }


def _write_candidates(tmp_path: Path, candidates: list[dict]) -> Path:
    path = tmp_path / "eval_candidates.yaml"
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump({"eval_candidates": candidates}, fh, allow_unicode=True, sort_keys=False)
    return path


# ---------------------------------------------------------------------------
# 1) candidate promote 流程
# ---------------------------------------------------------------------------


def test_promote_passes_accepted_runnable_candidate(tmp_path):
    """accepted + runnable + 字段齐全 → 必须被 promote。

    并验证审核痕迹（review_status / review_notes / source）随 eval 一起搬运，不丢。
    """

    candidates_path = _write_candidates(tmp_path, [_accepted_candidate()])
    out_path = tmp_path / "promoted.yaml"
    result = CandidatePromoter().promote(candidates_path, out_path)

    assert len(result.promoted) == 1
    assert result.skipped == []
    promoted = result.promoted[0]
    assert promoted["review_status"] == "accepted"
    assert promoted["review_notes"]
    assert promoted["source"] == "generated_from_tools"


def test_promote_skips_needs_review(tmp_path):
    """review_status != accepted 必须被跳过，并给出可行动 reason。"""

    cand = _accepted_candidate("case_needs_review")
    cand["review_status"] = "needs_review"
    candidates_path = _write_candidates(tmp_path, [cand])
    out_path = tmp_path / "promoted.yaml"

    result = CandidatePromoter().promote(candidates_path, out_path)

    assert result.promoted == []
    assert len(result.skipped) == 1
    assert "review_status" in result.skipped[0]["reason"]


def test_promote_skips_rejected(tmp_path):
    """review_status=rejected 也必须被跳过。"""

    cand = _accepted_candidate("case_rejected")
    cand["review_status"] = "rejected"
    candidates_path = _write_candidates(tmp_path, [cand])
    out_path = tmp_path / "promoted.yaml"

    result = CandidatePromoter().promote(candidates_path, out_path)

    assert result.promoted == []
    assert result.skipped[0]["id"] == "case_rejected"


def test_promote_skips_runnable_false(tmp_path):
    """runnable=False 即使 accepted 也必须跳过（避免把不可运行的 eval 推进正式 suite）。"""

    cand = _accepted_candidate("case_unrunnable")
    cand["runnable"] = False
    candidates_path = _write_candidates(tmp_path, [cand])
    out_path = tmp_path / "promoted.yaml"

    result = CandidatePromoter().promote(candidates_path, out_path)

    assert result.promoted == []
    assert "runnable" in result.skipped[0]["reason"]


def test_promote_skips_missing_initial_context_or_outcome(tmp_path):
    """缺 initial_context / verifiable_outcome / expected_root_cause / judge.rules
    任何一项都必须被跳过，并解释下一步要补什么。
    """

    bad_specimens = []
    a = _accepted_candidate("case_no_init")
    a["initial_context"] = {}
    bad_specimens.append((a, "initial_context"))
    b = _accepted_candidate("case_no_outcome")
    b["verifiable_outcome"] = {}
    bad_specimens.append((b, "verifiable_outcome"))
    c = _accepted_candidate("case_no_root_cause")
    c["verifiable_outcome"] = {"expected_root_cause": ""}
    bad_specimens.append((c, "expected_root_cause"))
    d = _accepted_candidate("case_no_rules")
    d["judge"] = {"rules": []}
    bad_specimens.append((d, "judge.rules"))

    for cand, expected_keyword in bad_specimens:
        candidates_path = _write_candidates(tmp_path, [cand])
        out_path = tmp_path / f"promoted_{cand['id']}.yaml"
        result = CandidatePromoter().promote(candidates_path, out_path)
        assert result.promoted == [], cand["id"]
        assert expected_keyword in result.skipped[0]["reason"], cand["id"]


def test_promote_refuses_to_overwrite_existing_file_without_force(tmp_path):
    """默认禁止覆盖：保护用户手写正式 evals.yaml。

    这是 promoter 最重要的安全承诺；任何"为了方便"加默认 force 的改动都必须让
    本测试红灯。
    """

    candidates_path = _write_candidates(tmp_path, [_accepted_candidate()])
    out_path = tmp_path / "evals.yaml"
    out_path.write_text(
        "evals:\n  - id: hand_authored\n    user_prompt: real user task\n",
        encoding="utf-8",
    )
    original = out_path.read_text(encoding="utf-8")

    with pytest.raises(FileExistsError):
        CandidatePromoter().promote(candidates_path, out_path)

    # 未加 --force 的失败必须不动原文件。
    assert out_path.read_text(encoding="utf-8") == original


def test_promote_with_force_overwrites_when_explicit(tmp_path):
    """显式 force 才允许覆盖，避免 promoter 永远不能跑第二次。"""

    candidates_path = _write_candidates(tmp_path, [_accepted_candidate()])
    out_path = tmp_path / "evals.yaml"
    out_path.write_text("evals: []\n", encoding="utf-8")
    result = CandidatePromoter().promote(candidates_path, out_path, force=True)
    assert len(result.promoted) == 1
    data = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert data["evals"][0]["id"] == "case_accepted"


def test_promoted_file_is_loadable_by_load_evals_and_audit_friendly(tmp_path):
    """promoted 文件必须能被 load_evals 直接读，且 EvalQualityAuditor runnable=True。

    这是 promote → audit-evals → run 闭环最关键的一条："promoter 不能产生
    loader 不认的格式"，否则审核闭环就断了。
    """

    candidates_path = _write_candidates(tmp_path, [_accepted_candidate()])
    out_path = tmp_path / "promoted.yaml"
    CandidatePromoter().promote(candidates_path, out_path)

    evals = load_evals(out_path)
    assert len(evals) == 1
    assert evals[0].id == "case_accepted"

    from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor

    audit = EvalQualityAuditor().audit(evals)
    # promoted 候选的 audit.runnable 必须为 True；如果框架未来收紧 audit 标准
    # 让本测试红灯，请同时检查 _accepted_candidate 是否也要补字段——而**不是**
    # 在 promoter 里塞默认值绕过审计。
    assert audit["evals"][0]["runnable"] is True


# ---------------------------------------------------------------------------
# 2) generate-evals warnings
# ---------------------------------------------------------------------------


def test_writer_warns_on_empty_candidates(tmp_path):
    """空候选 → warnings 必须显式提示 empty_input，文件可写但内容为空 list。"""

    out = tmp_path / "out.yaml"
    CandidateWriter().write([], out)
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["eval_candidates"] == []
    assert any("empty_input" in w for w in data["warnings"])


def test_writer_warns_on_all_unrunnable(tmp_path):
    """全部 runnable=false → 必须出现 all_unrunnable warning。"""

    cands = [
        {
            "id": "a",
            "runnable": False,
            "review_notes": ["补 fixture"],
            "missing_context": ["fixture"],
        },
        {
            "id": "b",
            "runnable": False,
            "review_notes": ["补 fixture"],
            "missing_context": ["fixture"],
        },
    ]
    out = tmp_path / "out.yaml"
    CandidateWriter().write(cands, out)
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert any("all_unrunnable" in w for w in data["warnings"])


def test_writer_warns_on_missing_review_notes_and_high_missing_context(tmp_path):
    cands = [
        {"id": "x", "runnable": True, "missing_context": ["fixture", "expected_root_cause"]},
        {"id": "y", "runnable": True, "review_notes": []},
    ]
    out = tmp_path / "out.yaml"
    CandidateWriter().write(cands, out)
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    text = " | ".join(data["warnings"])
    assert "missing_review_notes" in text
    assert "high_missing_context" in text


def test_writer_warns_on_cheating_prompts(tmp_path):
    """cheating prompt 必须被 warning 标记（与 EvalQualityAuditor 启发式呼应）。"""

    cands = [
        {
            "id": "cheat",
            "runnable": True,
            "review_notes": ["x"],
            "user_prompt": "Please call the runtime trace tool to find the root cause.",
        }
    ]
    out = tmp_path / "out.yaml"
    CandidateWriter().write(cands, out)
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert any("cheating_prompt_suspect" in w for w in data["warnings"])


def test_writer_does_not_invent_warnings_for_clean_candidates(tmp_path):
    """合理候选不应触发任何 warning（避免新检查误伤正常生成器输出）。"""

    cand = _accepted_candidate("case_clean")
    cand["missing_context"] = []
    out = tmp_path / "out.yaml"
    CandidateWriter().write([cand], out)
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["warnings"] == []


# ---------------------------------------------------------------------------
# 3) artifact schema_version + run_metadata
# ---------------------------------------------------------------------------


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_run_artifacts_carry_schema_version_and_run_metadata(tmp_path):
    """run 的 5 个 JSON artifact 必须都带 schema_version 与一致的 run_metadata.run_id。

    一致性是设计上的关键：下游可以靠 run_id 把 metrics/judge/diagnosis 等串起来
    复盘同一次 run；如果各 artifact 各自独立生成 run_id，下游就要做交叉匹配。
    """

    EvalRunner().run(
        load_project("examples/runtime_debug/project.yaml"),
        load_tools("examples/runtime_debug/tools.yaml"),
        load_evals("examples/runtime_debug/evals.yaml"),
        MockReplayAdapter("good"),
        tmp_path,
    )
    files = [
        "metrics.json",
        "audit_tools.json",
        "audit_evals.json",
        "judge_results.json",
        "diagnosis.json",
    ]
    run_ids = set()
    for fname in files:
        data = _read_json(tmp_path / fname)
        assert data["schema_version"] == ARTIFACT_SCHEMA_VERSION, fname
        assert "run_metadata" in data, fname
        assert data["run_metadata"]["run_id"], fname
        run_ids.add(data["run_metadata"]["run_id"])
    assert len(run_ids) == 1, f"all artifacts in one run must share run_id, got {run_ids}"


def test_failure_run_artifacts_also_carry_schema_version(tmp_path):
    """adapter 抛错路径写出的 artifact 也必须带 schema_version。

    失败现场最需要稳定解析契约——如果 CI 只在失败时 grep schema_version，结果发现
    "正常 run 有，失败 run 没有"，下游会处理混乱。本测试钉住这个等价边界。
    """

    class _Boom:
        SIGNAL_QUALITY = "tautological_replay"

        def run(self, case, registry, recorder):  # noqa: ANN001
            raise RuntimeError("boom")

    EvalRunner().run(
        load_project("examples/runtime_debug/project.yaml"),
        load_tools("examples/runtime_debug/tools.yaml"),
        load_evals("examples/runtime_debug/evals.yaml"),
        _Boom(),
        tmp_path,
    )
    metrics = _read_json(tmp_path / "metrics.json")
    judge = _read_json(tmp_path / "judge_results.json")
    assert metrics["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert judge["schema_version"] == ARTIFACT_SCHEMA_VERSION
    # 即使 adapter 失败，run_metadata 仍要写齐 project_name / eval_count。
    assert metrics["run_metadata"]["project_name"]
    assert metrics["run_metadata"]["eval_count"] >= 1


def test_audit_cli_artifacts_carry_schema_version(tmp_path, monkeypatch):
    """独立 audit-tools / audit-evals 命令产出的 JSON 也要带 schema_version。

    这是为了让"不在 run 流程里"的 audit 输出与 run 内嵌的 audit 输出 schema
    一致；下游 CI 不需要分两个解析分支。
    """

    out_tools = tmp_path / "tools_dir"
    out_evals = tmp_path / "evals_dir"
    rc1 = cli_main(
        [
            "audit-tools",
            "--tools",
            "examples/runtime_debug/tools.yaml",
            "--out",
            str(out_tools),
        ]
    )
    rc2 = cli_main(
        [
            "audit-evals",
            "--evals",
            "examples/runtime_debug/evals.yaml",
            "--out",
            str(out_evals),
        ]
    )
    assert rc1 == 0 and rc2 == 0
    audit_tools = _read_json(out_tools / "audit_tools.json")
    audit_evals = _read_json(out_evals / "audit_evals.json")
    assert audit_tools["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert audit_evals["schema_version"] == ARTIFACT_SCHEMA_VERSION
    # 命令名透传到 extra，便于审计哪条命令产出。
    assert audit_tools["run_metadata"]["extra"]["command"] == "audit-tools"
    assert audit_evals["run_metadata"]["extra"]["command"] == "audit-evals"


def test_promoter_output_carries_schema_version(tmp_path):
    """promoter 输出的 evals.yaml 顶层也带 schema_version + promote_summary。

    审核者拿到 promoted 文件后能立刻看到"哪些被搬运、哪些被跳"的人类可读摘要，
    不需要回去看 stderr。
    """

    candidates_path = _write_candidates(
        tmp_path,
        [_accepted_candidate("a"), {**_accepted_candidate("b"), "review_status": "needs_review"}],
    )
    out_path = tmp_path / "promoted.yaml"
    CandidatePromoter().promote(candidates_path, out_path)
    data = yaml.safe_load(out_path.read_text(encoding="utf-8"))
    assert data["schema_version"] == ARTIFACT_SCHEMA_VERSION
    assert data["promote_summary"]["promoted_ids"] == ["a"]
    assert data["promote_summary"]["skipped"][0]["id"] == "b"


# ---------------------------------------------------------------------------
# CLI 端到端：promote-evals 命令本身的退出码与行为
# ---------------------------------------------------------------------------


def test_cli_promote_evals_returns_0_with_summary(tmp_path, capsys):
    candidates_path = _write_candidates(tmp_path, [_accepted_candidate()])
    out_path = tmp_path / "promoted.yaml"
    rc = cli_main(
        [
            "promote-evals",
            "--candidates",
            str(candidates_path),
            "--out",
            str(out_path),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 0
    summary = json.loads(captured.out.strip().splitlines()[-1])
    assert summary["promoted_count"] == 1
    assert summary["skipped_count"] == 0


def test_cli_promote_evals_refuses_overwrite_without_force(tmp_path, capsys):
    candidates_path = _write_candidates(tmp_path, [_accepted_candidate()])
    out_path = tmp_path / "evals.yaml"
    out_path.write_text("evals: []\n", encoding="utf-8")
    rc = cli_main(
        [
            "promote-evals",
            "--candidates",
            str(candidates_path),
            "--out",
            str(out_path),
        ]
    )
    captured = capsys.readouterr()
    assert rc == 2
    assert "refused to overwrite" in captured.err
    assert "--force" in captured.err
