"""第二个 example 项目（``examples/knowledge_search``）的接入回归测试。

这一层负责什么、不负责什么（学习型说明）：
- **负责**：证明 ``agent_tool_harness`` 的 loader / auditor / runner / judge / report
  五条主链路在与 ``runtime_debug`` 完全不同的业务领域上**不需要任何核心改动**就能跑
  通；并把"框架核心硬编码 example 业务名"这一反模式钉成红线。
- **不负责**：测试 example 自身业务逻辑是否"正确"（KB 检索是 mock，没有真实业务）。

为什么单独写这一组测试：
- ROADMAP v0.1 blocking 1 = "在一个全新的 example 项目上完成同样的闭环"。仅靠跑一遍
  CLI smoke 不够，因为只要一处把 ``runtime_debug`` 工具名/字段写进核心包，初次跑还是
  能通过——但下一个项目就会撞墙。这里把"核心包绝不出现 KB 业务符号"做成 deterministic
  assertion，让未来任何"图省事写死本 example"的提交立刻 CI 红。

如何通过 artifacts 查问题：
- ``test_smoke_good_path`` 与 ``test_smoke_bad_path`` 跑完会留下 9 个标准 artifact 在
  ``runs/test_kb_*`` 下。失败时直接看 ``judge_results.json`` / ``diagnosis.json`` /
  ``report.md``，与文档里描述的排查路径一致——这同时也间接验证了 ``docs/ARTIFACTS.md``
  对真人用户依然可信。

哪些只是 MVP / mock / demo 边界：
- 这里的 smoke 仍然是 ``MockReplayAdapter`` 的 tautological replay；good=PASS / bad=FAIL
  并不能代表真实 Agent 能力，仅证明 harness 链路连通。``signal_quality`` 字段必须存在，
  并且必须是 ``tautological_replay``——任何把它静默升级成更高等级以掩盖 mock 性质的改动
  都会被 ``test_smoke_good_path_discloses_signal_quality`` 抓住。

未来扩展点（仅 ROADMAP，不在本测试实现）：
- 接入真实 OpenAI/Anthropic adapter 后，可以把 SIGNAL_QUALITY 断言扩成"adapter 对应
  的 signal_quality 等级"；
- 当 ROADMAP 添加第三个 example 时，把 ``CORE_FORBIDDEN_KB_SYMBOLS`` 抽成参数化 fixture。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIR = REPO_ROOT / "examples" / "knowledge_search"
CORE_PKG = REPO_ROOT / "agent_tool_harness"

# 这些是 knowledge_search example 独有的工具名 / namespace 片段。
# 一旦它们出现在 ``agent_tool_harness/`` 任何 .py 文件里，就意味着核心包被某个
# example 业务污染——这正是 v0.1 graduation audit 要严守的边界。
# （刻意只列业务专有词；不列像 ``article`` / ``search`` 这种通用词，避免误伤
# loader/auditor 里出现的通用术语。）
CORE_FORBIDDEN_KB_SYMBOLS = [
    "kb.search.search_articles",
    "kb.article.fetch_article",
    "kb.assistant.suggest_canned_response",
    "knowledge_search",
    "kb-sso-014",
]


def _run_cli(*args: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """以子进程运行 CLI，确保走的是用户视角的真实入口（而非测试内部 import）。

    用 subprocess 而不是 import + 直接调用，是为了：
    1. 真实经过 argparse / 错误处理路径——任何 CLI 选项漂移都会被立刻发现；
    2. 与 docs/ONBOARDING.md / README 中给真人用户的命令完全一致；
    3. 避免把测试本身耦合到核心 Python API（核心 API 仍属 MVP，可变）。
    """

    cmd = [sys.executable, "-m", "agent_tool_harness.cli", *args]
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def test_example_files_present() -> None:
    """第二 example 必须包含 project / tools / evals / demo_tools / README 五个最小文件。

    这是真人 onboarding 路径的最低要求：少任何一个文件，文档里给出的"复制这个目录就能
    跑"的承诺就不成立。
    """

    missing = [
        name
        for name in ("project.yaml", "tools.yaml", "evals.yaml", "demo_tools.py", "README.md")
        if not (EXAMPLE_DIR / name).exists()
    ]
    assert not missing, f"knowledge_search example 缺文件: {missing}"


def test_loader_can_read_second_example() -> None:
    """loader 必须能把第二 example 的 yaml 真实读成 ToolSpec / EvalSpec / ProjectSpec。

    如果 loader 抛 ConfigError / ToolRegistryError，说明 example 写得不符合契约——
    或者更严重：loader 之前隐式依赖了 runtime_debug 的某个字段。
    """

    from agent_tool_harness.config.loader import (
        load_evals,
        load_project,
        load_tools,
    )

    project = load_project(EXAMPLE_DIR / "project.yaml")
    tools = load_tools(EXAMPLE_DIR / "tools.yaml")
    evals = load_evals(EXAMPLE_DIR / "evals.yaml")

    assert project.name == "knowledge-search-demo"
    assert {tool.qualified_name for tool in tools} == {
        "kb.search.search_articles",
        "kb.article.fetch_article",
        "kb.assistant.suggest_canned_response",
    }
    assert len(evals) == 1
    assert evals[0].id == "kb_sso_session_loss_regression"


def test_audit_tools_smoke(tmp_path: Path) -> None:
    """audit-tools 必须能跑通且不产生 high-severity finding 信号污染。

    这里不要求满分——auditor 当前 MVP 是 structural 检查（已知会给某些工具 5.0），
    而是要求"能正常生成 audit_tools.json，且 summary.tool_count 与 yaml 中工具数相等"。
    一旦 auditor 因为 schema/字段差异在第二 example 上崩溃，就立刻暴露核心包对
    runtime_debug 字段的隐式假设。
    """

    out = tmp_path / "audit-tools"
    proc = _run_cli(
        "audit-tools",
        "--tools",
        str(EXAMPLE_DIR / "tools.yaml"),
        "--out",
        str(out),
        tmp_path=tmp_path,
    )
    assert proc.returncode == 0, f"audit-tools 失败:\nstdout={proc.stdout}\nstderr={proc.stderr}"
    payload = json.loads((out / "audit_tools.json").read_text(encoding="utf-8"))
    assert payload["summary"]["tool_count"] == 3
    # schema_version + run_metadata 是 v0.1 跨 artifact 共享 run_id 的承诺，必须始终存在。
    assert payload.get("schema_version")
    assert payload.get("run_metadata", {}).get("run_id")


def test_audit_evals_smoke(tmp_path: Path) -> None:
    """audit-evals 必须把唯一一条 eval 标记为 runnable=true 且无 high finding。

    eval 内部已经手写了 fixture / verifiable_outcome / judge.rules，因此 auditor
    若把它判 not_runnable，要么是 example 写错（应根因修复 yaml），要么是 auditor
    在第二 example 上行为不一致（应根因修复 auditor）——任何一种都不允许通过。
    """

    out = tmp_path / "audit-evals"
    proc = _run_cli(
        "audit-evals",
        "--evals",
        str(EXAMPLE_DIR / "evals.yaml"),
        "--out",
        str(out),
        tmp_path=tmp_path,
    )
    assert proc.returncode == 0, f"audit-evals 失败:\nstderr={proc.stderr}"
    payload = json.loads((out / "audit_evals.json").read_text(encoding="utf-8"))
    eval_results = payload["evals"]
    assert len(eval_results) == 1
    only = eval_results[0]
    assert only["runnable"] is True, only
    high_findings = [f for f in only["findings"] if f.get("severity") == "high"]
    assert not high_findings, f"第二 example eval 不应产生 high finding：{high_findings}"


def _expected_artifacts() -> set[str]:
    """与 ``EvalRunner.REQUIRED_ARTIFACTS`` 对齐的 9 个 artifact 名。

    这里不直接 import ``EvalRunner.REQUIRED_ARTIFACTS``，是为了让本测试同时充当
    "docs/ARTIFACTS.md 9 个文件清单 vs 代码现实"的交叉对账——如果未来代码加了第 10 个
    artifact，这个测试与文档都需要被同步更新。
    """

    return {
        "transcript.jsonl",
        "tool_calls.jsonl",
        "tool_responses.jsonl",
        "metrics.json",
        "audit_tools.json",
        "audit_evals.json",
        "judge_results.json",
        "diagnosis.json",
        "report.md",
    }


@pytest.mark.parametrize(
    ("mock_path", "expect_pass"),
    [
        ("good", True),
        ("bad", False),
    ],
)
def test_smoke_run_paths(tmp_path: Path, mock_path: str, expect_pass: bool) -> None:
    """good path 必 PASS / bad path 必 FAIL，且 9 个 artifact 全在。

    这是 v0.1 graduation 真正想验证的事：在新业务领域里，``MockReplayAdapter``
    + ``RuleJudge`` 的两条结构性保证仍然成立。如果 bad path 居然 PASS，要么是
    ``forbidden_first_tool`` 规则在第二 example 上失效（核心 bug），要么是
    ``MockReplayAdapter._bad_first_tool`` 选错了工具（adapter bug）——必须根因修复，
    不允许通过修测试绕过。
    """

    out = tmp_path / f"run-{mock_path}"
    proc = _run_cli(
        "run",
        "--project",
        str(EXAMPLE_DIR / "project.yaml"),
        "--tools",
        str(EXAMPLE_DIR / "tools.yaml"),
        "--evals",
        str(EXAMPLE_DIR / "evals.yaml"),
        "--out",
        str(out),
        "--mock-path",
        mock_path,
        tmp_path=tmp_path,
    )
    assert proc.returncode == 0, f"run --mock-path={mock_path} 失败:\n{proc.stderr}"

    artifacts = {p.name for p in out.iterdir() if p.is_file()}
    missing = _expected_artifacts() - artifacts
    assert not missing, f"缺 artifact: {missing}"

    metrics = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert metrics["signal_quality"] == "tautological_replay", metrics
    if expect_pass:
        assert metrics["passed"] == 1 and metrics["failed"] == 0, metrics
    else:
        assert metrics["passed"] == 0 and metrics["failed"] == 1, metrics


def test_core_package_does_not_hardcode_kb_example_symbols() -> None:
    """``agent_tool_harness/`` 任何 .py 文件都不允许出现第二 example 的业务专有符号。

    这是防"为了让第二 example 跑通就在核心里写死 kb.* 工具名" 这种反模式。
    历史上这种 demo-only 分支会让第三个 example 接入时再次失败，且不容易被代码 review
    抓到——所以放成 deterministic 测试。
    """

    offenders: list[str] = []
    for py in CORE_PKG.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for symbol in CORE_FORBIDDEN_KB_SYMBOLS:
            if symbol in text:
                offenders.append(f"{py.relative_to(REPO_ROOT)} 含 example 专有符号 '{symbol}'")
    assert not offenders, "\n".join(offenders)
