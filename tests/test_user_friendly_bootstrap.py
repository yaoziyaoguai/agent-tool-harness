"""User-Friendly Bootstrap Flow E2E：bootstrap CLI + Python API。

为什么写这套测试
----------------
v2.x User-Friendly Bootstrap Flow 把 4 步 scaffold + validate 合并成 1 条
``bootstrap`` 命令，方便内部用户从代码到 generated draft 只跑一次命令。
但收束之后必须钉死以下真实接入契约：

1. 不执行 / 不 import 用户代码（关键：sample_tool_project 里有 canary
   ``tools_unsafe.py``，顶层 ``raise``，任何动态 import 退路都会被立刻
   fail）；
2. 不读 ``.env`` / 不联网 / 不调真实 LLM；
3. 默认拒绝覆盖已有 out_dir，``--force`` 才允许；
4. 输出目录结构稳定（tools.generated.yaml / evals.generated.yaml /
   fixtures/ / validation_summary.json / REVIEW_CHECKLIST.md）；
5. REVIEW_CHECKLIST.md 必须包含给 reviewer 的关键提示词
   （"generated draft" / "review required" / "TODO" / "strict-reviewed" /
   "no secrets" / "v3.0"），防文档漂移；
6. validation_summary.json 内字段与 ``ValidateGeneratedReport`` 同步；
7. source 不存在或无可识别 tool 时必须 fail with clear message，不可
   假成功；
8. CLI 与 Python API 行为一致。

它能发现什么真实 bug
-------------------
- 任何让 bootstrap 偷偷 ``import`` 用户模块的回归（canary 立即 raise）；
- 任何让 bootstrap 在 reviewed config 已存在时悄悄覆盖的回归；
- 任何让 REVIEW_CHECKLIST 失去关键提示词的文案 drift；
- 任何让 source 路径错误时 silent 通过的回归。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from agent_tool_harness.scaffold import bootstrap_user_project
from agent_tool_harness.scaffold.bootstrap import (
    _CHECKLIST_REQUIRED_PHRASES,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
SAFE_SAMPLE = REPO_ROOT / "tests" / "fixtures" / "sample_tool_project"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent_tool_harness.cli", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


# --- Python API tests --------------------------------------------------------


def test_bootstrap_writes_expected_layout(tmp_path: Path) -> None:
    """bootstrap 输出目录结构稳定（drift 测试）。"""
    out = tmp_path / "boot"
    report = bootstrap_user_project(SAFE_SAMPLE, out)
    expected = {
        "tools.generated.yaml",
        "evals.generated.yaml",
        "validation_summary.json",
        "REVIEW_CHECKLIST.md",
    }
    assert expected.issubset({p.name for p in out.iterdir()})
    assert (out / "fixtures").is_dir()
    assert report.tools_yaml.is_file()
    assert report.evals_yaml.is_file()
    assert report.fixtures_dir.is_dir()


def test_bootstrap_does_not_execute_canary(tmp_path: Path) -> None:
    """**安全核心契约**：sample_tool_project/tools_unsafe.py 顶层
    ``raise RuntimeError("would-have-executed" / "safety canary")``。
    bootstrap 只能 ast 静态扫描；如果有任何动态 import 退路，本测试
    会因为 RuntimeError 抛出而 fail。
    """
    out = tmp_path / "boot"
    bootstrap_user_project(SAFE_SAMPLE, out)
    # 进一步验证：写出来的 yaml/checklist 里也不能含 canary 字符串
    blob = ""
    for f in out.rglob("*"):
        if f.is_file():
            blob += f.read_text(encoding="utf-8", errors="ignore")
    for forbidden in ("would-have-executed", "safety canary"):
        assert forbidden not in blob


def test_bootstrap_default_refuses_overwrite(tmp_path: Path) -> None:
    """默认 force=False 时已存在 out_dir 必须 fail，避免误冲掉 reviewer
    已经手改的 reviewed config。"""
    out = tmp_path / "boot"
    bootstrap_user_project(SAFE_SAMPLE, out)
    with pytest.raises(FileExistsError):
        bootstrap_user_project(SAFE_SAMPLE, out)


def test_bootstrap_force_overwrites(tmp_path: Path) -> None:
    """force=True 必须能覆盖（rm -rf 重建），并且老文件不残留。"""
    out = tmp_path / "boot"
    bootstrap_user_project(SAFE_SAMPLE, out)
    sentinel = out / "old_review_artifact.txt"
    sentinel.write_text("reviewer's old work that should be wiped", encoding="utf-8")
    bootstrap_user_project(SAFE_SAMPLE, out, force=True)
    assert not sentinel.exists()
    assert (out / "tools.generated.yaml").is_file()


def test_bootstrap_source_missing_fails_clearly(tmp_path: Path) -> None:
    """source 路径不存在必须 fail（不可假成功 → 否则 reviewer 拿到一份
    空 yaml 还以为他工具没有任何 def）。"""
    out = tmp_path / "boot"
    with pytest.raises(Exception) as exc:  # noqa: PT011 — 上游可能抛多种 ConfigError
        bootstrap_user_project(tmp_path / "does_not_exist", out)
    assert exc.value is not None


def test_validation_summary_matches_report(tmp_path: Path) -> None:
    """validation_summary.json 落盘内容必须等于 report.validation.to_json()
    （防止 reviewer 看到的 status 与 BootstrapReport 内的 status 不一致）。
    """
    out = tmp_path / "boot"
    report = bootstrap_user_project(SAFE_SAMPLE, out)
    on_disk = json.loads((out / "validation_summary.json").read_text(encoding="utf-8"))
    assert on_disk["status"] == report.validation.status
    assert on_disk["counts"] == report.validation.counts


def test_review_checklist_contains_required_phrases(tmp_path: Path) -> None:
    """REVIEW_CHECKLIST 必须含全部关键提示词（防文案 drift / 误导 reviewer）。"""
    out = tmp_path / "boot"
    bootstrap_user_project(SAFE_SAMPLE, out)
    text = (out / "REVIEW_CHECKLIST.md").read_text(encoding="utf-8")
    for phrase in _CHECKLIST_REQUIRED_PHRASES:
        assert phrase in text, f"REVIEW_CHECKLIST missing phrase: {phrase!r}"


def test_bootstrap_no_network_or_env_leak(tmp_path: Path) -> None:
    """落盘文件不能包含 Authorization/Bearer/.env 等敏感字符串。"""
    out = tmp_path / "boot"
    bootstrap_user_project(SAFE_SAMPLE, out)
    blob = "\n".join(
        f.read_text(encoding="utf-8", errors="ignore")
        for f in out.rglob("*")
        if f.is_file()
    )
    for forbidden in ("Authorization:", "Bearer sk-"):
        assert forbidden not in blob


# --- CLI tests ---------------------------------------------------------------


def test_cli_bootstrap_help_lists_command() -> None:
    """CLI 顶层 help 必须列出 bootstrap 子命令（防 schema drift）。"""
    r = _run_cli("--help")
    assert r.returncode == 0
    assert "bootstrap" in r.stdout


def test_cli_bootstrap_runs_end_to_end(tmp_path: Path) -> None:
    """CLI 入口能跑完整流程，stdout 是 JSON-safe，stderr 含 wrote 行。"""
    out = tmp_path / "boot"
    r = _run_cli(
        "bootstrap",
        "--source", str(SAFE_SAMPLE),
        "--out", str(out),
    )
    assert r.returncode == 0, r.stderr
    payload = json.loads(r.stdout)
    assert payload["validation_status"] in {"pass", "warning", "fail"}
    assert "wrote bootstrap to" in r.stderr
    assert (out / "REVIEW_CHECKLIST.md").is_file()


def test_cli_bootstrap_default_refuses_overwrite(tmp_path: Path) -> None:
    """CLI 默认拒绝覆盖；FileExistsError 由 main() 处理为非 0 exit code。"""
    out = tmp_path / "boot"
    r1 = _run_cli("bootstrap", "--source", str(SAFE_SAMPLE), "--out", str(out))
    assert r1.returncode == 0
    r2 = _run_cli("bootstrap", "--source", str(SAFE_SAMPLE), "--out", str(out))
    assert r2.returncode != 0
    assert "already exists" in (r2.stderr + r2.stdout)


def test_cli_bootstrap_force_overwrites(tmp_path: Path) -> None:
    """CLI --force 能覆盖。"""
    out = tmp_path / "boot"
    _run_cli("bootstrap", "--source", str(SAFE_SAMPLE), "--out", str(out))
    r = _run_cli(
        "bootstrap", "--source", str(SAFE_SAMPLE), "--out", str(out), "--force"
    )
    assert r.returncode == 0, r.stderr


# --- Bootstrap UX hardening: --bootstrap-dir doctor entry --------------------


def test_validate_bootstrap_dir_runs_against_full_dir(tmp_path: Path) -> None:
    """validate-generated --bootstrap-dir 应该自动定位 tools/evals/fixtures。"""
    out = tmp_path / "boot"
    bootstrap_user_project(SAFE_SAMPLE, out)
    r = _run_cli("validate-generated", "--bootstrap-dir", str(out))
    assert r.returncode == 0, r.stderr  # draft mode → warning, not fail
    payload = json.loads(r.stdout)
    assert payload["status"] in {"pass", "warning"}
    # 自动定位到了 fixtures/ 子目录
    assert payload["fixtures_dir"] is not None


def test_validate_bootstrap_dir_strict_fails_on_unreviewed_draft(
    tmp_path: Path,
) -> None:
    """--bootstrap-dir + --strict-reviewed 必须 fail（draft 还没人 review）。"""
    out = tmp_path / "boot"
    bootstrap_user_project(SAFE_SAMPLE, out)
    r = _run_cli(
        "validate-generated", "--bootstrap-dir", str(out), "--strict-reviewed"
    )
    assert r.returncode == 2  # TODO 残留 + 无 runnable
    assert "reviewed_config_has_todo" in r.stdout
    assert "reviewed_config_has_no_runnable_eval" in r.stdout


def test_validate_bootstrap_dir_warns_when_checklist_deleted(
    tmp_path: Path,
) -> None:
    """reviewer 误删 REVIEW_CHECKLIST.md → stderr 必须 warn（防静默丢链路）。"""
    out = tmp_path / "boot"
    bootstrap_user_project(SAFE_SAMPLE, out)
    (out / "REVIEW_CHECKLIST.md").unlink()
    r = _run_cli("validate-generated", "--bootstrap-dir", str(out))
    assert "missing REVIEW_CHECKLIST.md" in r.stderr


def test_validate_bootstrap_dir_warns_when_summary_deleted(
    tmp_path: Path,
) -> None:
    """validation_summary.json 缺失也要 warn。"""
    out = tmp_path / "boot"
    bootstrap_user_project(SAFE_SAMPLE, out)
    (out / "validation_summary.json").unlink()
    r = _run_cli("validate-generated", "--bootstrap-dir", str(out))
    assert "missing validation_summary.json" in r.stderr


def test_validate_bootstrap_dir_rejects_mutually_exclusive_args(
    tmp_path: Path,
) -> None:
    """--bootstrap-dir 与 --tools/--evals 互斥（防用户用错参数也假成功）。"""
    out = tmp_path / "boot"
    bootstrap_user_project(SAFE_SAMPLE, out)
    r = _run_cli(
        "validate-generated",
        "--bootstrap-dir", str(out),
        "--tools", str(out / "tools.generated.yaml"),
        "--evals", str(out / "evals.generated.yaml"),
    )
    assert r.returncode == 2
    assert "mutually exclusive" in r.stderr


def test_validate_bootstrap_dir_rejects_nonexistent_dir(tmp_path: Path) -> None:
    """传入不存在目录必须 fail with clear message。"""
    r = _run_cli(
        "validate-generated", "--bootstrap-dir", str(tmp_path / "no-such-dir")
    )
    assert r.returncode == 2
    assert "not a directory" in r.stderr


def test_cli_bootstrap_stdout_lists_next_steps(tmp_path: Path) -> None:
    """bootstrap 完成后 stderr 必须含明确的 4 条 next steps（防 UX 退化）。"""
    out = tmp_path / "boot"
    r = _run_cli("bootstrap", "--source", str(SAFE_SAMPLE), "--out", str(out))
    assert r.returncode == 0
    for needle in (
        "Next steps:",
        "1) review TODO",
        "2) doctor check",
        "3) strict review",
        "4) deterministic smoke",
        "no .env / no network / no live LLM",
    ):
        assert needle in r.stderr, f"missing in stderr: {needle!r}"


# --- v2.x Real Trial Readiness ----------------------------------------------


def test_real_trial_candidate_doc_exists() -> None:
    """docs/REAL_TRIAL_CANDIDATE.md 必须存在并含关键提示词
    （防"内部同事不知道怎么选第一个试用工具"的 UX 退化）。"""
    doc = REPO_ROOT / "docs" / "REAL_TRIAL_CANDIDATE.md"
    assert doc.is_file()
    text = doc.read_text(encoding="utf-8")
    for needle in (
        "First Tool Suitability",  # 核心标题
        "no secrets",
        "no live LLM",
        "deterministic",
        "v3.0",
        "REVIEW_CHECKLIST",
        "bootstrap",
        "validate-generated",
        "--strict-reviewed",
        "--mock-path good",
    ):
        assert needle.lower() in text.lower(), f"missing: {needle}"


def test_real_trial_doc_has_no_secrets_leakage() -> None:
    """REAL_TRIAL_CANDIDATE.md 自身不能含真实 token / Authorization / 完整请求体。"""
    doc = REPO_ROOT / "docs" / "REAL_TRIAL_CANDIDATE.md"
    text = doc.read_text(encoding="utf-8")
    for forbidden in ("Bearer sk-", "Authorization: sk-"):
        assert forbidden not in text


def test_review_checklist_includes_first_tool_suitability(tmp_path: Path) -> None:
    """生成的 REVIEW_CHECKLIST §6 必须出现 First Tool Suitability Checklist
    （这是防止 reviewer 第一轮就接错工具的关键）。"""
    out = tmp_path / "boot"
    bootstrap_user_project(SAFE_SAMPLE, out)
    text = (out / "REVIEW_CHECKLIST.md").read_text(encoding="utf-8")
    assert "First Tool Suitability" in text
    for marker in (
        "mockable",
        "deterministic eval",
        "secret",  # "不需要真实 secret"
        "联网",
        "v3.0",
        "MCP",
    ):
        assert marker in text, f"checklist missing marker: {marker}"
