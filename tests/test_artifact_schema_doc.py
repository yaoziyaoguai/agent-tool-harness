"""验证 docs/ARTIFACTS.md 文档存在并覆盖全部 9 个 artifact 名称。

为什么需要这条治理性测试：
- 框架对外承诺“每次 run 都生成 9 个 artifact”，但只有运行时断言不够；
  使用者第一时间会去找一篇文档对齐字段。如果未来有人删字段或漏写文档，
  本测试会失败。
- 同时检查 README 与 ARCHITECTURE 引用 docs/ARTIFACTS.md，避免文档变成孤岛。

不在范围内：
- 不验证 ARTIFACTS.md 字段一一对应代码（那需要 schema 自动生成，属未来 P1+）。
- 不验证 ARTIFACTS.md 内 markdown 排版。
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
    "report.md",
]


def test_artifact_schema_doc_exists_and_lists_all_nine_artifacts():
    """ARTIFACTS.md 必须存在并显式提到全部 9 个 artifact。"""

    doc = Path("docs/ARTIFACTS.md")
    assert doc.exists(), "docs/ARTIFACTS.md 必须存在；它是用户接入的字段契约入口"
    text = doc.read_text(encoding="utf-8")
    for name in EXPECTED_ARTIFACTS:
        assert name in text, f"ARTIFACTS.md 缺少对 {name} 的描述"
    # 关键边界声明：必须明确告诉读者派生视图不能替代 raw artifacts。
    assert "raw artifacts" in text or "raw" in text
    assert "signal_quality" in text


def test_readme_and_architecture_link_artifact_doc():
    """README 与 ARCHITECTURE 必须引用 ARTIFACTS.md，避免它成为孤岛文档。"""

    readme = Path("README.md").read_text(encoding="utf-8")
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    assert "docs/ARTIFACTS.md" in readme or "ARTIFACTS.md" in readme
    assert "ARTIFACTS.md" in architecture
