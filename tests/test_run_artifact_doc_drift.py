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
ARTIFACTS_DOC = REPO_ROOT / "docs" / "ARTIFACTS.md"
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


def _artifact_table_filenames() -> set[str]:
    r"""从 ARTIFACTS.md 总览 Markdown 表格里抽出第一列 backtick 文件名。

    只读总览段（## 总览 之后到下一个 H2 之前）。表格行匹配
    `| \`xxx.json\` | ... |` 这种格式。
    """
    text = ARTIFACTS_DOC.read_text(encoding="utf-8")
    overview_match = re.search(
        r"^## 总览\n(.*?)^## ", text, re.MULTILINE | re.DOTALL
    )
    assert overview_match, "ARTIFACTS.md 必须包含 '## 总览' 段"
    overview = overview_match.group(1)
    return set(re.findall(r"^\|\s*`([a-z_]+\.[a-z]+)`\s*\|", overview, re.MULTILINE))


def _readme_artifact_bullets() -> set[str]:
    r"""从 README §Artifacts bullet list 抽出 `xxx.yyy` 文件名。

    只截取 `## Artifacts` 到下一个 H2 之间的段，按 `- \`name.ext\`` 行抽。
    """
    text = README.read_text(encoding="utf-8")
    section = re.search(r"^## Artifacts\n(.*?)^## ", text, re.MULTILINE | re.DOTALL)
    assert section, "README 必须包含 '## Artifacts' 段"
    body = section.group(1)
    return set(re.findall(r"^-\s*`([a-z_]+\.[a-z]+)`", body, re.MULTILINE))


def test_artifacts_doc_table_lists_every_real_run_artifact(
    actual_run_artifact_filenames: set[str],
) -> None:
    """ARTIFACTS.md 总览表格必须覆盖每一个真实 run 写出的文件。

    这是 P0：用户拿 ARTIFACTS.md 当 schema reference 时，表格里没列的文件
    会被当作"未文档化"或多余。v1.6 起的 `llm_cost.json` 必须在表格里。
    """
    table = _artifact_table_filenames()
    missing = actual_run_artifact_filenames - table
    assert not missing, (
        f"ARTIFACTS.md 总览表格漏了 run 真实写入的 artifact: {sorted(missing)}; "
        f"表格当前: {sorted(table)}; "
        f"实际 run 输出: {sorted(actual_run_artifact_filenames)}"
    )


def test_artifacts_doc_table_does_not_list_phantom_files(
    actual_run_artifact_filenames: set[str],
) -> None:
    """ARTIFACTS.md 表格里出现的文件必须真的会被 run 写出来。

    防止文档"先于实现"或"实现已删但文档没删"的反向漂移。
    """
    table = _artifact_table_filenames()
    phantom = table - actual_run_artifact_filenames
    assert not phantom, (
        f"ARTIFACTS.md 表格列了 run 不会写的 artifact: {sorted(phantom)}"
    )


def test_artifacts_doc_total_count_is_consistent_with_table(
    actual_run_artifact_filenames: set[str],
) -> None:
    """ARTIFACTS.md 总览段叙述的 artifact 总数必须与表格 / 真实 run 一致。

    这是本轮 dogfooding 走查发现的根因：表格已经修了 10 行，但介绍段仍写
    "九个 artifact" 是常见漏洞；这条测试钉死介绍段的"N 个"叙述。
    """
    text = ARTIFACTS_DOC.read_text(encoding="utf-8")
    actual_n = len(actual_run_artifact_filenames)
    chinese_digits = "零一二三四五六七八九十"
    expected_cn = chinese_digits[actual_n] if actual_n < len(chinese_digits) else ""
    assert (
        f"{actual_n} 个 artifact" in text
        or f"{expected_cn}个 artifact" in text
        or f"下列{expected_cn}个文件" in text
    ), (
        f"ARTIFACTS.md 总览段必须叙述实际 artifact 数量 ({actual_n})，"
        "但当前文本未找到任何匹配；可能仍写着旧的 9 个 / 九个"
    )
    forbidden_substrings = ["九个 artifact", "下列九个文件"]
    if actual_n != 9:
        for s in forbidden_substrings:
            assert s not in text, (
                f"ARTIFACTS.md 仍包含过时叙述 {s!r}；run 实际产出 {actual_n} 个"
            )


def test_readme_artifacts_bullet_list_matches_real_run(
    actual_run_artifact_filenames: set[str],
) -> None:
    """README §Artifacts bullet 列表必须与真实 run 输出严格相等。

    用户从 README 复制 artifact 列表去对照 `runs/<dir>/` 时，缺一漏一就会
    引发"是不是没装好 / 是不是 run 失败"的误判。
    """
    bullets = _readme_artifact_bullets()
    assert bullets == actual_run_artifact_filenames, (
        f"README §Artifacts bullet 与真实 run 输出不一致;\n"
        f"  bullet list: {sorted(bullets)}\n"
        f"  real run   : {sorted(actual_run_artifact_filenames)}\n"
        f"  漏 (在 run 但 README 没列): {sorted(actual_run_artifact_filenames - bullets)}\n"
        f"  多 (README 写了但 run 不产出): {sorted(bullets - actual_run_artifact_filenames)}"
    )


def test_readme_artifacts_count_phrase_matches_real_run(
    actual_run_artifact_filenames: set[str],
) -> None:
    """README §Artifacts 段叙述的"N 个产物"必须与真实 run 数量一致。

    这一条专门钉死本轮发现的 README §Artifacts "9 个产物" / "9 件套" 漂移；
    `analyze-artifacts` / `replay-run` 段中的 "N 个 artifact" 也一并校验。
    """
    text = README.read_text(encoding="utf-8")
    n = len(actual_run_artifact_filenames)
    if n != 9:
        forbidden = [
            "9 个产物",
            "9 件套",
            "9 个文件",
            "与 `run` 命令一样的 9 个 artifact",
        ]
        for s in forbidden:
            assert s not in text, (
                f"README 仍包含过时叙述 {s!r}；run 实际产出 {n} 个"
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
