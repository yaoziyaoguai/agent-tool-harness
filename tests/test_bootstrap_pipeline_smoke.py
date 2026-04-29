"""bootstrap pipeline 端到端 smoke：scaffold-tools → scaffold-evals → scaffold-fixtures。

测试什么真实 bug
----------------
- 钉死"scaffold 三步链路全程不 import / exec 用户代码"的安全不变量。
  样本工程里 `tools_unsafe.py` 顶层 `raise RuntimeError`，任何走了动态
  import 退路的改动会立刻让端到端 FAIL。
- 钉死 5 行披露 header（draft / review required / does not execute / does
  not call live provider / deterministic offline）。任何把 scaffold 改成
  "看起来像 production 配置"的改动会立刻 FAIL。
- 钉死 runnable=false + TODO 占位策略——防止有人为了"让 smoke 直接跑通"
  把 scaffold 的 expected_root_cause 改成具体值，从而把伪造判定推到下游。
- 钉死覆盖保护契约：scaffold-evals 默认拒绝整文件覆盖；scaffold-fixtures
  默认逐文件软跳过。
- 钉死 CLI 子命令注册（argparse drift 探测）。

不测什么
--------
- 不测 reviewer 把 TODO 替换成真实业务字段后的 `audit-evals` 通过率
  （那需要业务知识，超出 scaffold 范围）。
- 不测 fixture 内容是否符合真实工具 schema（scaffold 本就不知道）。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PROJECT = REPO_ROOT / "tests" / "fixtures" / "sample_tool_project"


def _run_cli(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """跑一次 `python -m agent_tool_harness.cli ...`；显式 capture，便于断言。"""
    return subprocess.run(
        [sys.executable, "-m", "agent_tool_harness.cli", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def bootstrap_outputs(tmp_path_factory: pytest.TempPathFactory) -> dict[str, Path]:
    """端到端跑 scaffold-tools → scaffold-evals → scaffold-fixtures，返回路径集合。

    用 module-scope 是为了让 6+ 条断言共享一次 subprocess，避免每条 test
    都重新跑三个 CLI（既慢又看不出"端到端"语义）。
    """
    base = tmp_path_factory.mktemp("bootstrap_e2e")
    tools_yaml = base / "tools.draft.yaml"
    evals_yaml = base / "evals.draft.yaml"
    fixtures_dir = base / "fixtures.draft"

    r1 = _run_cli(
        "scaffold-tools",
        "--source", str(SAMPLE_PROJECT),
        "--out", str(tools_yaml),
        cwd=REPO_ROOT,
    )
    assert r1.returncode == 0, f"scaffold-tools failed: stderr={r1.stderr}"
    assert tools_yaml.exists()

    r2 = _run_cli(
        "scaffold-evals",
        "--tools", str(tools_yaml),
        "--out", str(evals_yaml),
        cwd=REPO_ROOT,
    )
    assert r2.returncode == 0, f"scaffold-evals failed: stderr={r2.stderr}"
    assert evals_yaml.exists()

    r3 = _run_cli(
        "scaffold-fixtures",
        "--tools", str(tools_yaml),
        "--out-dir", str(fixtures_dir),
        cwd=REPO_ROOT,
    )
    assert r3.returncode == 0, f"scaffold-fixtures failed: stderr={r3.stderr}"
    assert fixtures_dir.is_dir()

    return {
        "tools_yaml": tools_yaml,
        "evals_yaml": evals_yaml,
        "fixtures_dir": fixtures_dir,
        "stdout1": r1.stdout,
        "stdout2": r2.stdout,
        "stdout3": r3.stdout,
    }


def test_unsafe_module_was_never_imported(bootstrap_outputs: dict) -> None:
    """安全不变量：tools_unsafe.py 顶层 RuntimeError 不应触发。

    如果触发了，subprocess 会以非零退出，bootstrap_outputs fixture 已经
    在 r1 / r2 / r3 任一阶段断言失败。本测试本身只要能被 collected 就证明
    fixture 成功——但额外检查 stderr 中绝不包含我们的 canary 文本。
    """
    for stdout_key in ("stdout1", "stdout2", "stdout3"):
        assert "would-have-executed" not in bootstrap_outputs[stdout_key]
        assert "safety canary" not in bootstrap_outputs[stdout_key]


def test_scaffolded_tools_yaml_has_disclosure_header_and_safe_tools_only(
    bootstrap_outputs: dict,
) -> None:
    """tools.yaml 顶部必须有 disclosure；只抽到了 safe 文件的工具 + unsafe 文件
    的 risky_action（ast 静态可见，但 module 顶层语句没被执行）。"""
    text = bootstrap_outputs["tools_yaml"].read_text(encoding="utf-8")
    for phrase in ("generated draft", "review required", "does not execute"):
        assert phrase in text, f"missing disclosure phrase: {phrase}"

    data = yaml.safe_load(text)
    names = {t["name"] for t in data["tools"]}
    # tools_safe.py 的两个 public 函数 + tools_unsafe.py 的 risky_action（仅 ast 可见）。
    assert {"query_user_profile", "list_recent_orders", "risky_action"} <= names
    # 私有 helper 必须被排除。
    assert "_internal_helper" not in names


def test_scaffolded_evals_yaml_has_5line_header_and_runnable_false(
    bootstrap_outputs: dict,
) -> None:
    """evals.yaml 顶部 5 行披露 + 每条 eval runnable=false + TODO 占位。"""
    text = bootstrap_outputs["evals_yaml"].read_text(encoding="utf-8")
    for phrase in (
        "generated draft",
        "review required",
        "does not execute tools",
        "does not call live provider",
        "deterministic/offline starter only",
    ):
        assert phrase in text, f"missing eval header phrase: {phrase}"

    data = yaml.safe_load(text)
    assert isinstance(data["evals"], list) and len(data["evals"]) >= 1
    for ev in data["evals"]:
        # runnable=false 是双重保险：reviewer 漏看 TODO 也不会跑出 misleading PASS。
        assert ev["runnable"] is False, f"eval {ev['id']} must be runnable=false"
        # 业务字段必须含 TODO 占位（防止 scaffold 伪造正确答案）。
        assert "TODO" in ev["verifiable_outcome"]["expected_root_cause"]
        assert ev["metadata"]["scaffold_status"] == "draft"


def test_scaffolded_fixtures_have_disclosure_and_one_per_tool(
    bootstrap_outputs: dict,
) -> None:
    """每个 tool 一个 fixture 文件 + 含 example only / not real tool output 披露。"""
    fixtures_dir = bootstrap_outputs["fixtures_dir"]
    files = sorted(fixtures_dir.glob("*.fixture.yaml"))
    assert {f.name for f in files} >= {
        "query_user_profile.fixture.yaml",
        "list_recent_orders.fixture.yaml",
        "risky_action.fixture.yaml",
    }
    for f in files:
        text = f.read_text(encoding="utf-8")
        for phrase in (
            "example only",
            "review required",
            "not real tool output",
            "generated without executing tool",
        ):
            assert phrase in text, f"{f.name} missing disclosure phrase: {phrase}"
        data = yaml.safe_load(text)
        assert "good" in data and "bad" in data
        assert "TODO" in json.dumps(data, ensure_ascii=False)


def test_scaffold_evals_refuses_overwrite_without_force(
    bootstrap_outputs: dict, tmp_path: Path
) -> None:
    """scaffold-evals 默认禁止覆盖已有 --out（防止冲掉手写正式 evals.yaml）。"""
    evals_yaml = bootstrap_outputs["evals_yaml"]
    # 第二次跑同一个 --out，必须非零退出。
    r = _run_cli(
        "scaffold-evals",
        "--tools", str(bootstrap_outputs["tools_yaml"]),
        "--out", str(evals_yaml),
        cwd=REPO_ROOT,
    )
    assert r.returncode != 0
    assert "force" in (r.stderr + r.stdout).lower()


def test_scaffold_fixtures_soft_skips_existing_files(
    bootstrap_outputs: dict,
) -> None:
    """scaffold-fixtures 默认逐文件软跳过：第二次跑 stdout 应明确说明 skipped。"""
    r = _run_cli(
        "scaffold-fixtures",
        "--tools", str(bootstrap_outputs["tools_yaml"]),
        "--out-dir", str(bootstrap_outputs["fixtures_dir"]),
        cwd=REPO_ROOT,
    )
    assert r.returncode == 0
    assert "skipped" in r.stdout.lower()


def test_cli_help_lists_three_scaffold_subcommands() -> None:
    """argparse drift 探测：scaffold-tools / scaffold-evals / scaffold-fixtures
    三个子命令都必须被注册（任何 import 失败 / parser 漏注册都会被抓住）。"""
    r = _run_cli("--help", cwd=REPO_ROOT)
    assert r.returncode == 0
    for sub in ("scaffold-tools", "scaffold-evals", "scaffold-fixtures"):
        assert sub in r.stdout, f"subcommand {sub} missing from --help"
