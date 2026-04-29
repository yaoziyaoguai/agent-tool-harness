"""docs ↔ CLI 漂移防回归测试（v1.7 第一项）。

中文学习型说明
==============
本文件钉死的边界
----------------
1. **README + TRY_IT + ONBOARDING + TRY_IT_v1_7** 中出现的所有
   ``python -m agent_tool_harness.cli <subcommand>`` 片段，subcommand 必须
   是当前 argparse 真正注册的子命令；
2. v1.6 新增的 ``audit-judge-prompts`` 子命令必须在 README + ARTIFACTS +
   TRY_IT_v1_7 中至少被引用一次（防"加了 CLI 但忘了文档"漂移）；
3. 关键 artifact 文件名（``llm_cost.json`` / ``audit_judge_prompts.json``）
   必须在 ``EvalRunner.REQUIRED_ARTIFACTS`` 或 ``ARTIFACTS.md`` 中声明，
   且文档必须显式声明 advisory-only / 不是真实账单（防"产物加了但文档
   宣传成真实账单"漂移）。

本文件**不**负责什么
--------------------
- 不验证 snippet 命令的 ``--flag`` 是否仍合法（CLI flag 演进时频繁误报）；
  这一层留给 v1.7+ 更细粒度 schema-driven snippet 检查。
- 不渲染文档；纯 grep + argparse 自省。

防回归价值
----------
真实可能的 bug：
- 给 CLI 加了新子命令但忘了在 README/TRY_IT 写文档；
- 删了 CLI 子命令但 README 还在引用，用户复制粘贴会失败；
- 把 advisory-only 字样从 ARTIFACTS.md 删掉，把 cost 当真实账单宣传；
- 把 ``llm_cost.json`` 从 REQUIRED_ARTIFACTS 移除但 README 还说会产出。
"""

from __future__ import annotations

import re
from pathlib import Path

from agent_tool_harness.cli import _build_parser as build_parser
from agent_tool_harness.runner.eval_runner import EvalRunner

REPO_ROOT = Path(__file__).resolve().parent.parent

DOCS_TO_SCAN = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "TRY_IT.md",
    REPO_ROOT / "docs" / "TRY_IT_v1_7.md",
    REPO_ROOT / "docs" / "ONBOARDING.md",
    REPO_ROOT / "docs" / "INTERNAL_TRIAL.md",
    REPO_ROOT / "docs" / "INTERNAL_TRIAL_QUICKSTART.md",
    REPO_ROOT / "docs" / "INTERNAL_TRIAL_LAUNCH_PACK.md",
]

CLI_SNIPPET_RE = re.compile(
    r"python\s+-m\s+agent_tool_harness\.cli\s+([a-z][a-z0-9-]*)"
)


def _registered_subcommands() -> set[str]:
    """通过 argparse 自省拿到当前真实注册的子命令集合。

    设计取舍：直接 reach into ``parser._subparsers`` 拿 choices。这是
    argparse 内部 API，但对 v1.x 稳定；一旦 argparse 升级破坏它，本测
    试会立即失败——这正是我们想要的"早警告"信号。
    """
    parser = build_parser()
    for action in parser._actions:
        if hasattr(action, "choices") and isinstance(action.choices, dict):
            return set(action.choices.keys())
    raise AssertionError("could not introspect argparse subcommands")


def test_docs_only_reference_real_subcommands():
    real = _registered_subcommands()
    missing: list[tuple[str, str]] = []
    for doc in DOCS_TO_SCAN:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        for m in CLI_SNIPPET_RE.finditer(text):
            sub = m.group(1)
            if sub not in real:
                missing.append((doc.name, sub))
    assert not missing, (
        "docs reference subcommands that argparse no longer registers: "
        f"{missing}\n  registered: {sorted(real)}"
    )


def test_v16_subcommand_referenced_in_key_docs():
    """v1.6 的 audit-judge-prompts 必须在 README + ARTIFACTS + TRY_IT_v1_7 至少出现一次。

    防"代码加了 CLI 但用户找不到入口"漂移。
    """
    keyword = "audit-judge-prompts"
    must_mention = [
        REPO_ROOT / "README.md",
        REPO_ROOT / "docs" / "ARTIFACTS.md",
        REPO_ROOT / "docs" / "TRY_IT_v1_7.md",
    ]
    missing = [str(p.relative_to(REPO_ROOT)) for p in must_mention
               if keyword not in p.read_text(encoding="utf-8")]
    assert not missing, (
        f"{keyword} not mentioned in: {missing}; "
        "v1.6 新 CLI 必须有用户可见的接入点文档。"
    )


def test_llm_cost_artifact_is_required_and_documented():
    """llm_cost.json 必须在 REQUIRED_ARTIFACTS 中且 ARTIFACTS.md 显式声明 advisory-only。"""
    assert "llm_cost.json" in EvalRunner.REQUIRED_ARTIFACTS
    artifacts_doc = (REPO_ROOT / "docs" / "ARTIFACTS.md").read_text(encoding="utf-8")
    assert "llm_cost.json" in artifacts_doc
    # 防"把 advisory-only / 不是真实账单 删掉伪装真实计费"漂移：
    # ARTIFACTS.md 必须保留 advisory-only 措辞，且必须保留"不是真实账单"
    # 中文断言（保留两处文案断言，删任何一处都立即失败）。
    assert "advisory-only" in artifacts_doc, (
        "ARTIFACTS.md 必须保留 'advisory-only' 措辞，禁止把 cost 当真实账单宣传"
    )
    assert "不是真实账单" in artifacts_doc, (
        "ARTIFACTS.md 必须保留 '不是真实账单' 中文断言"
    )


def test_audit_judge_prompts_doc_declares_advisory_only():
    """audit_judge_prompts.json 在 ARTIFACTS.md 必须保留 '不代表 prompt 在生产中安全' 边界。"""
    artifacts_doc = (REPO_ROOT / "docs" / "ARTIFACTS.md").read_text(encoding="utf-8")
    assert "audit_judge_prompts.json" in artifacts_doc
    assert "启发式" in artifacts_doc
    # 必须明确声明"通过 audit 不代表安全"——防止用户把 audit 通过当终判。
    assert "通过 audit 不代表" in artifacts_doc
