"""bootstrap-to-run sample pack E2E：scaffold → validate → reviewed → run。

为什么这是 v2.x bootstrap-to-run hardening 测试，不是 v3.0 executor 测试
----------------------------------------------------------------------
- v3.0 backlog 才考虑接 MCP / HTTP / Shell executor / 真实 LLM judge；
- 本测试链路全程：纯 Python 函数 + MockReplayAdapter（deterministic）+
  PythonToolExecutor（importlib but only loads safe pure functions in
  examples/bootstrap_to_run/sample_tools.py）+ RuleJudge（启发式，无 LLM）。
- 真实意义：钉死"reviewed config 能进 deterministic smoke run + 写出 10
  件套 artifact + 不联网 + 不读 .env"这一 v2.x 收口契约。

它能发现什么真实接入问题
------------------------
- 任何让 scaffold draft 直接被 run 误吞（ROADMAP 已禁止）；
- 任何 reviewer 没把 TODO 清完就把 runnable=true 的回归（被 strict-reviewed
  fail 拦下）；
- 任何 sample reviewed 配置 drift（tool name / executor path / required_tools
  对不上）；
- 任何 run 不再写 10 件套 artifact 的回归。

为什么 reviewed config 必须显式处理 TODO
----------------------------------------
EvalRunner + RuleJudge + PythonToolExecutor 的执行结果取决于 evals.yaml
里的 verifiable_outcome / judge.rules / required_tools 这些**业务字段**。
如果 reviewer 没把 TODO_xxx 替换成真实业务值就把 runnable 改 true，run
会拿 'TODO_expected_root_cause' 等占位字符串当真值跑，写出来的 PASS/FAIL
完全不可信。strict-reviewed 模式专门挡这类回归。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = REPO_ROOT / "examples" / "bootstrap_to_run"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent_tool_harness.cli", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_sample_pack_files_exist() -> None:
    """sample pack 4 个文件齐全（drift 钉死）。"""
    for fn in (
        "README.md",
        "sample_tools.py",
        "project.yaml",
        "tools.reviewed.yaml",
        "evals.reviewed.yaml",
    ):
        assert (SAMPLE_DIR / fn).is_file(), f"missing {fn}"


def test_validate_reviewed_strict_passes(tmp_path: Path) -> None:
    """reviewed 配置在 --strict-reviewed 模式下必须 status=pass，0 issue。

    这是 'reviewed 边界' 的核心契约：reviewer 主动移除 disclosure header +
    清空 TODO + runnable=true 之后，validate 应该给绿灯，否则下游 run 就
    没人敢跑。
    """
    r = _run_cli(
        "validate-generated",
        "--strict-reviewed",
        "--tools", str(SAMPLE_DIR / "tools.reviewed.yaml"),
        "--evals", str(SAMPLE_DIR / "evals.reviewed.yaml"),
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["status"] == "pass"
    assert payload["counts"]["runnable_evals_count"] == 1
    assert payload["counts"]["broken_tool_refs"] == 0
    assert payload["issues"] == []


def test_strict_reviewed_fails_on_unfilled_todo(tmp_path: Path) -> None:
    """**关键边界**：reviewer 漏清 TODO 但已经把 runnable 改 true（最危险情景）
    → strict-reviewed 必须 fail，draft 模式只 warning。"""
    bad_evals = tmp_path / "evals.reviewed.yaml"
    bad_text = (SAMPLE_DIR / "evals.reviewed.yaml").read_text(encoding="utf-8")
    # 注入残留 TODO（模拟 reviewer 漏清一个）。
    bad_text = bad_text.replace(
        "expected_root_cause: boundary_violation",
        "expected_root_cause: TODO_real_root_cause",
        1,
    )
    bad_evals.write_text(bad_text, encoding="utf-8")

    # draft 模式：runnable_eval_with_todo 是 fail（因为 runnable=true 还有 TODO）
    r_draft = _run_cli(
        "validate-generated",
        "--tools", str(SAMPLE_DIR / "tools.reviewed.yaml"),
        "--evals", str(bad_evals),
    )
    assert r_draft.returncode == 2
    assert "runnable_eval_with_todo" in r_draft.stdout

    # strict 模式：除了 runnable_eval_with_todo 还要触发 reviewed_config_has_todo
    r_strict = _run_cli(
        "validate-generated",
        "--strict-reviewed",
        "--tools", str(SAMPLE_DIR / "tools.reviewed.yaml"),
        "--evals", str(bad_evals),
    )
    assert r_strict.returncode == 2
    assert "reviewed_config_has_todo" in r_strict.stdout


def test_strict_reviewed_fails_when_no_runnable(tmp_path: Path) -> None:
    """reviewed 但没有 1 条 runnable=true → strict 必须 fail（否则 run 啥也没跑）。"""
    bad_evals = tmp_path / "evals.reviewed.yaml"
    bad_text = (SAMPLE_DIR / "evals.reviewed.yaml").read_text(encoding="utf-8")
    # 注意：reviewed.yaml 顶部注释里也写了 'runnable: true'，所以必须用更明确的
    # 缩进前缀定位真实数据行（避免改成注释行）。
    bad_text = bad_text.replace("    runnable: true", "    runnable: false", 1)
    bad_evals.write_text(bad_text, encoding="utf-8")

    r = _run_cli(
        "validate-generated",
        "--strict-reviewed",
        "--tools", str(SAMPLE_DIR / "tools.reviewed.yaml"),
        "--evals", str(bad_evals),
    )
    assert r.returncode == 2
    assert "reviewed_config_has_no_runnable_eval" in r.stdout


def test_run_with_reviewed_config_writes_10_artifacts(tmp_path: Path) -> None:
    """**端到端最小闭环**：用 reviewed config 跑一次 deterministic smoke run，
    必须写出 10 件套 artifact + 至少 1 条 eval passed。

    这是 v2.x bootstrap-to-run hardening 的最高级目标：把 'scaffold →
    validate → reviewed → run → report' 串成完整闭环，证明 reviewer 走完
    全流程后真的能跑出可靠 PASS/FAIL（在 MockReplayAdapter 边界内 ——
    PASS=adapter 复现了 expected_tool_behavior；不代表真实 Agent 能力，
    见 metrics.signal_quality 字段说明）。
    """
    out = tmp_path / "run_out"
    r = _run_cli(
        "run",
        "--project", str(SAMPLE_DIR / "project.yaml"),
        "--tools", str(SAMPLE_DIR / "tools.reviewed.yaml"),
        "--evals", str(SAMPLE_DIR / "evals.reviewed.yaml"),
        "--out", str(out),
        "--mock-path", "good",
    )
    assert r.returncode == 0, f"run failed: stderr={r.stderr}"
    expected_artifacts = {
        "transcript.jsonl",
        "tool_calls.jsonl",
        "tool_responses.jsonl",
        "metrics.json",
        "audit_tools.json",
        "audit_evals.json",
        "judge_results.json",
        "diagnosis.json",
        "llm_cost.json",
        "report.md",
    }
    actual = {f.name for f in out.iterdir() if f.is_file()}
    missing = expected_artifacts - actual
    assert not missing, f"missing artifacts: {missing}"

    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["passed"] >= 1
    assert metrics["error_evals"] == 0
    # signal_quality 必须明示 MVP 边界，不能伪装成真实 Agent 能力。
    assert "signal_quality" in metrics


def test_run_does_not_touch_network_or_env(tmp_path: Path) -> None:
    """安全契约：run sample pack 不应在 stdout/stderr 出现 .env / API key /
    Authorization / http(s):// 真实请求字符串。"""
    out = tmp_path / "run_out"
    r = _run_cli(
        "run",
        "--project", str(SAMPLE_DIR / "project.yaml"),
        "--tools", str(SAMPLE_DIR / "tools.reviewed.yaml"),
        "--evals", str(SAMPLE_DIR / "evals.reviewed.yaml"),
        "--out", str(out),
        "--mock-path", "good",
    )
    assert r.returncode == 0
    combined = r.stdout + r.stderr
    for forbidden in ("Authorization:", "Bearer sk-", ".env"):
        assert forbidden not in combined, f"sensitive token leaked: {forbidden!r}"


def test_readme_lists_5_step_chain() -> None:
    """README 里必须保留 5 步链路指引（防文档漂移）。"""
    text = (SAMPLE_DIR / "README.md").read_text(encoding="utf-8")
    for cmd in (
        "scaffold-tools",
        "scaffold-evals",
        "scaffold-fixtures",
        "validate-generated",
        "run",
    ):
        assert cmd in text, f"README missing step: {cmd}"


def test_sample_tools_module_imports_safely() -> None:
    """sample_tools.py 模块顶层必须**无副作用**——这是与 tests/fixtures/
    sample_tool_project/tools_unsafe.py 的核心区别（unsafe 故意 raise 作
    canary；本文件必须 production-imitation 安全）。"""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "_bootstrap_sample_tools_smoke", SAMPLE_DIR / "sample_tools.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # 这里如果 raise 测试就 fail
    assert callable(module.lookup_user_status)
    assert callable(module.inspect_user_session)


@pytest.mark.parametrize("scenario", ["good", "bad"])
def test_run_supports_both_mock_paths(tmp_path: Path, scenario: str) -> None:
    """good 和 bad 两条 mock path 都应该跑通（不是 PASS——bad 路径设计上 FAIL；
    而是 'CLI 不报错 + 写完 artifact'）。"""
    out = tmp_path / f"run_{scenario}"
    r = _run_cli(
        "run",
        "--project", str(SAMPLE_DIR / "project.yaml"),
        "--tools", str(SAMPLE_DIR / "tools.reviewed.yaml"),
        "--evals", str(SAMPLE_DIR / "evals.reviewed.yaml"),
        "--out", str(out),
        "--mock-path", scenario,
    )
    assert r.returncode == 0
    assert (out / "report.md").exists()
    assert (out / "metrics.json").exists()
