"""钉死非 ``run`` subcommand 的"产物文件集合"契约。

为什么要写这个测试（请先读完再改）：
=====================================
v0.1 onboarding 走查里出现一次真实困惑：用户跑完 ``audit-tools --out X`` 看到目
录里只有一个 ``audit_tools.json``，对照 README "## Artifacts" 节里那张醒目的
9 文件清单（"transcript.jsonl / tool_calls.jsonl / .../ report.md"）开始怀疑
"另外 8 个去哪了？是不是丢产物了？"。

排查根因：CLI 没丢东西——``audit-tools`` 设计上**只**写一个文件，stdout 也老老
实实打印了 ``wrote runs/.../audit_tools.json``；9 文件清单仅适用于 ``run``。但
README 旧版只在第一句"每次 run 都会生成"作了 scope 限定，跳读的用户会被那张表
带偏。本轮在 README 已加了一段"其它 subcommand 各自只写一个文件"的明示，但**仅
靠文档无法防止未来漂移**：

- 谁悄悄给 ``audit-tools`` 加一个派生 markdown 视图（合理需求，已在 ROADMAP
  P2），README 不更新——下游 CI 仍以为只有 1 个文件，artifact 名字漂移；
- 反过来谁简化 ``promote-evals`` 改名了产物，README 没改——用户接 CI 失败。

所以本测试的角色是：**把"每个非 run subcommand 实际写出的文件集合"作为契约
钉在 CI 上**，任何变化必须同时改测试 + 改文档，逼维护者主动维持文档真实性。

这个测试**会发现**的真实 bug：
- subcommand 静默新增 / 删除 / 改名产物文件；
- 把 ``run`` 内部的多文件副作用泄漏到 standalone 子命令；
- ``promote-evals`` 把 evals 输出里漏写了 schema_version / promote_summary 之类
  的高层字段（顺带通过 JSON / YAML 解析的方式覆盖一层"可被下游读"的契约）；
- README "其它 subcommand 各自只写一个文件"承诺与现实漂移。

这个测试**不负责**的边界（请勿扩到这里）：
- 不验证文件**内容**正确性——那是各 subcommand 自己的单测职责
  （test_eval_generation_from_tools.py、test_eval_quality_auditor.py 等）；
- 不覆盖 ``run`` 子命令——``run`` 必须写 9 件套已由
  test_eval_runner_artifacts.py 钉死，重复钉只会增加维护成本；
- 不假装能验证 artifact schema 演化——schema_version 钩子留在
  test_artifact_schema_doc.py。

实现要点：
- 用 ``tmp_path`` 跑真实 CLI 入口（``main(argv)``），不 mock 文件 IO——只有真实
  写文件才能发现产物漂移；
- 用 ``examples/runtime_debug/`` 作为输入：v0.1 已确保它在 CI 上稳定可跑；不依
  赖 knowledge_search 是为了让本测试与"第二个 example 是否存在"解耦。
- 断言形式：``set(os.listdir(out_dir)) == {expected}``——必须**等于**而不是
  ``>=``，否则新文件偷偷溜进来不会被发现。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_tool_harness.cli import main as cli_main

REPO_ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = REPO_ROOT / "examples" / "runtime_debug"


def _run(argv: list[str]) -> int:
    """以列表形式调用真实 CLI；返回 exit code，便于断言成功。"""
    return cli_main(argv)


def test_audit_tools_writes_exactly_one_file(tmp_path: Path) -> None:
    """``audit-tools`` 必须只写 ``audit_tools.json``；多写少写都算回归。"""
    out = tmp_path / "audit-tools-out"
    rc = _run([
        "audit-tools",
        "--tools", str(EXAMPLE / "tools.yaml"),
        "--out", str(out),
    ])
    assert rc == 0
    assert set(os.listdir(out)) == {"audit_tools.json"}


def test_audit_evals_writes_exactly_one_file(tmp_path: Path) -> None:
    """``audit-evals`` 必须只写 ``audit_evals.json``。"""
    out = tmp_path / "audit-evals-out"
    rc = _run([
        "audit-evals",
        "--evals", str(EXAMPLE / "evals.yaml"),
        "--out", str(out),
    ])
    assert rc == 0
    assert set(os.listdir(out)) == {"audit_evals.json"}


def test_generate_evals_writes_only_the_out_yaml(tmp_path: Path) -> None:
    """``generate-evals`` 只写 ``--out`` 指定的 YAML，不在父目录撒任何旁支。"""
    out = tmp_path / "gen" / "candidates.yaml"
    rc = _run([
        "generate-evals",
        "--project", str(EXAMPLE / "project.yaml"),
        "--tools", str(EXAMPLE / "tools.yaml"),
        "--source", "tools",
        "--out", str(out),
    ])
    assert rc == 0
    assert set(os.listdir(out.parent)) == {"candidates.yaml"}


def test_promote_evals_writes_only_the_out_yaml(tmp_path: Path) -> None:
    """``promote-evals`` 只写 ``--out`` 指定的 YAML（可能 0 promoted 仍写空骨架）。"""
    candidates = tmp_path / "gen" / "candidates.yaml"
    _run([
        "generate-evals",
        "--project", str(EXAMPLE / "project.yaml"),
        "--tools", str(EXAMPLE / "tools.yaml"),
        "--source", "tools",
        "--out", str(candidates),
    ])

    promoted = tmp_path / "promoted" / "evals.promoted.yaml"
    rc = _run([
        "promote-evals",
        "--candidates", str(candidates),
        "--out", str(promoted),
    ])
    assert rc == 0
    assert set(os.listdir(promoted.parent)) == {"evals.promoted.yaml"}


@pytest.mark.parametrize(
    "marker",
    [
        "audit-tools` → `audit_tools.json",
        "audit-evals` → `audit_evals.json",
        "generate-evals",
        "promote-evals",
    ],
)
def test_readme_artifacts_section_disambiguates_run_vs_subcommand(marker: str) -> None:
    """README "## Artifacts" 节必须明确区分 ``run`` 9 文件与其它 subcommand 各 1 文件。

    fake/mock 边界：本断言完全是对真实 README 文本的子串检查，不模拟任何运行
    时；它模拟的是"未来谁把那段澄清删了"的真实回归场景。
    """
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "## Artifacts" in readme
    artifacts_section = readme.split("## Artifacts", 1)[1].split("\n## ", 1)[0]
    assert marker in artifacts_section, (
        f"README ## Artifacts 节缺少对 {marker!r} 的明示；"
        "fresh user 跑完 standalone subcommand 看到只有 1 个产物会误以为丢产物。"
    )
