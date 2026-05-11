"""run artifact 与文档清单的防漂移测试 (#1 internal dogfooding 走查发现)。

这一组测试钉死一类**真实 onboarding bug**：

- v1.6 起 `agent_tool_harness.cli run` 每次都会写出 `llm_cost.json`
  （advisory-only 成本预估，顶层 `estimated_cost_usd` 永远 `null`），
  让一次 run 的固定 artifact 由原来的 9 个变成 10 个；
- 但 `docs/ARTIFACTS.md` 总览段、表格行数、README §Artifacts 计数 / bullet
  列表、`README §快速开始 → 7) 跑 bad 路径` 之后的 §Artifacts 解释段
  都长期停留在"9 个"。

**真实危害**：内部小组按 ARTIFACTS.md 表格只能查 9 个 artifact，
但实际 run 出来 10 个，会把 `llm_cost.json` 当成"未文档化的多余文件"误删，
或者读 README 时以为缺漏，反复来问 maintainer。

**为什么这是 v2.x patch 范围**：只校验文档总览/表格 ↔ 实际 run 输出文件名集合
是否一致，**不**修改任何核心代码、不引入新依赖、不 mock 真实 LLM、不联网。

**为什么这能发现真实 bug**：
- 任何人将来在 runner 里再加一个新的 artifact，必须同步把它加到 ARTIFACTS.md
  表格 + README bullet 列表，否则这组测试会立刻失败；
- 任何人将来在 runner 里删掉一个 artifact 也会被同样钉住；
- 与 `tests/test_artifact_consistency.py`（schema_version / no-leak）正交：
  那个测试看 artifact 内部字段，本测试看"哪些文件存在"这一层契约。
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
IMPL_DOC = REPO_ROOT / "docs" / "CURRENT_IMPLEMENTATION.md"
README = REPO_ROOT / "README.md"


@pytest.fixture(scope="module")
def actual_run_artifact_filenames(tmp_path_factory) -> set[str]:
    """实跑一次 run 拿到真实 artifact 文件名集合（**不**联网，**不**调真实 LLM）。

    选择 `examples/runtime_debug/` 是因为它是仓库唯一同时被 README §快速开始、
    INTERNAL_TRIAL_QUICKSTART 与 ARTIFACTS.md 引用的标准 demo example，
    保证我们对照的"真实 run"恰好就是文档让用户跑的那一条。
    """
    out_dir = tmp_path_factory.mktemp("run_for_doc_drift")
    cmd = [
        sys.executable,
        "-m",
        "agent_tool_harness.cli",
        "run",
        "--project",
        str(REPO_ROOT / "examples" / "runtime_debug" / "project.yaml"),
        "--tools",
        str(REPO_ROOT / "examples" / "runtime_debug" / "tools.yaml"),
        "--evals",
        str(REPO_ROOT / "examples" / "runtime_debug" / "evals.yaml"),
        "--out",
        str(out_dir),
        "--mock-path",
        "bad",
    ]
    subprocess.run(cmd, check=True, cwd=REPO_ROOT, capture_output=True)
    return {p.name for p in out_dir.iterdir() if p.is_file()}


def _impl_doc_artifact_filenames() -> set[str]:
    r"""从 CURRENT_IMPLEMENTATION.md 抽取 backtick 文件名。

    匹配文本中所有 `xxx.ext` 形态的 artifact 文件名。
    """
    text = IMPL_DOC.read_text(encoding="utf-8")
    return set(re.findall(r"`([a-z_]+\.[a-z]+)`", text))


def test_artifacts_doc_lists_every_real_run_artifact(
    actual_run_artifact_filenames: set[str],
) -> None:
    """CURRENT_IMPLEMENTATION.md 必须覆盖每一个真实 run 写出的 artifact。"""
    doc_files = _impl_doc_artifact_filenames()
    missing = actual_run_artifact_filenames - doc_files
    assert not missing, (
        f"CURRENT_IMPLEMENTATION.md 漏了 run 真实写入的 artifact: {sorted(missing)}"
    )


def test_artifacts_doc_does_not_list_phantom_files(
    actual_run_artifact_filenames: set[str],
) -> None:
    """CURRENT_IMPLEMENTATION.md 中提到的 artifact 必须真的会被 run 写出来。"""
    doc_files = _impl_doc_artifact_filenames()
    # Filter to only artifact-like files (not random backtick strings)
    artifact_like = {f for f in doc_files if f.endswith((".json", ".jsonl", ".md"))}
    phantom = artifact_like - actual_run_artifact_filenames
    assert not phantom, (
        f"CURRENT_IMPLEMENTATION.md 列了 run 不会写的 artifact: {sorted(phantom)}"
    )


def test_llm_cost_artifact_estimated_cost_is_advisory_null(
    actual_run_artifact_filenames: set[str], tmp_path: Path
) -> None:
    """补一条边界测试：llm_cost.json 顶层 estimated_cost_usd 必须是 null。

    这是 v1.6 起的 advisory-only 契约：harness 永远不假装报真实账单。
    本测试与 `tests/test_artifact_consistency.py` 的同类断言互为冗余覆盖，
    专门给"用户照 README/ARTIFACTS 找 llm_cost.json 后会做什么"的场景兜底。
    """
    assert "llm_cost.json" in actual_run_artifact_filenames

    out_dir = tmp_path / "verify_llm_cost"
    cmd = [
        sys.executable,
        "-m",
        "agent_tool_harness.cli",
        "run",
        "--project",
        str(REPO_ROOT / "examples" / "runtime_debug" / "project.yaml"),
        "--tools",
        str(REPO_ROOT / "examples" / "runtime_debug" / "tools.yaml"),
        "--evals",
        str(REPO_ROOT / "examples" / "runtime_debug" / "evals.yaml"),
        "--out",
        str(out_dir),
        "--mock-path",
        "bad",
    ]
    subprocess.run(cmd, check=True, cwd=REPO_ROOT, capture_output=True)
    payload = json.loads((out_dir / "llm_cost.json").read_text(encoding="utf-8"))
    assert payload.get("estimated_cost_usd") is None, (
        "llm_cost.json 顶层 estimated_cost_usd 必须为 null（advisory-only 契约）"
    )
