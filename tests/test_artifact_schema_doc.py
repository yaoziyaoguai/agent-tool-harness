"""验证 CURRENT_IMPLEMENTATION.md 覆盖全部 10 个 artifact 名称。

为什么需要这条治理性测试：
- 框架对外承诺"每次 run 都生成 10 个 artifact"，但只有运行时断言不够；
  使用者第一时间会去找一篇文档对齐字段。如果未来有人删字段或漏写文档，
  本测试会失败。
- 同时检查 README 引用 docs/CURRENT_IMPLEMENTATION.md，避免文档变成孤岛。
"""

from pathlib import Path

EXPECTED_ARTIFACTS = [
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
]


def test_artifact_doc_exists_and_lists_all_artifacts():
    """CURRENT_IMPLEMENTATION.md 必须存在并显式提到全部 10 个 artifact。"""

    doc = Path("docs/CURRENT_IMPLEMENTATION.md")
    assert doc.exists(), "docs/CURRENT_IMPLEMENTATION.md 必须存在"
    text = doc.read_text(encoding="utf-8")
    for name in EXPECTED_ARTIFACTS:
        assert name in text, f"CURRENT_IMPLEMENTATION.md 缺少对 {name} 的描述"
    assert "advisory-only" in text
    assert "signal_quality" in text.lower()


def test_readme_links_implementation_doc():
    """README 必须引用 CURRENT_IMPLEMENTATION.md，避免它成为孤岛文档。"""

    readme = Path("README.md").read_text(encoding="utf-8")
    assert "CURRENT_IMPLEMENTATION.md" in readme
