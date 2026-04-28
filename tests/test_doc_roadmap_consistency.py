"""文档 ↔ 仓库事实一致性回归测试。

为什么需要这一类测试（学习型说明）：
- 在 v0.1 graduation audit 中我们发现，ROADMAP / ARCHITECTURE / TESTING 在被多次
  重写后会留下"指向不存在的章节"或"指向已改名/未合入文件"的死链。
  对一个新接入的真人用户来说，文档里写"详见某处"但点进去什么都没有，是非常致命
  的体验：他会怀疑整个 harness 是否仍然可信。
- harness 的核心承诺之一是 "PASS/FAIL 之外，先去看 artifacts / docs 找根因"——
  如果 docs 自己就指向空洞，这个承诺就破了。
- 因此把 docs ↔ 仓库现实之间的最小一致性钉成 deterministic 测试，让未来任何重写
  ROADMAP / 引入新 milestone / 改动 xfail 文件名时，都必须同步更新文档，否则 CI 红。

这一层负责什么、不负责什么：
- **负责**：检查极少量、强 invariant 的事实（例如"docs 中提到的 xfail 测试函数
  必须在仓库里真实存在"），不做风格 / 字数 / 排版判断。
- **不负责**：检查 docs 内容是否"写得好"、是否覆盖了所有功能——那是人工 review
  的职责。这里只防"指向空洞"。

如何通过 artifacts 查问题：
- 该测试不写运行时 artifact，它只读 docs/*.md 与 tests/*.py。失败时直接报告
  "docs 里写了 X，仓库里没有"，是文档 bug 而非运行时 bug。

未来扩展点（仅 ROADMAP 想法，不在本测试实现）：
- 可以扩成"docs 里出现的所有 ``tests/...py::...`` 引用都必须 importable"；
- 可以扩成"docs 里出现的所有 ``runs/...`` 路径都必须能被 CLI 命令真实生成"。
但当前 MVP 保持极小：只覆盖最容易腐烂、且对真人 onboarding 影响最大的两条。
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    REPO_ROOT / "docs" / "ROADMAP.md",
    REPO_ROOT / "docs" / "ARCHITECTURE.md",
    REPO_ROOT / "docs" / "TESTING.md",
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "ONBOARDING.md",
    REPO_ROOT / "docs" / "ARTIFACTS.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_docs_have_no_stale_stage_numbering() -> None:
    """ROADMAP 现在以 v0.1 / v0.2 / v0.3 / v1.0 切分阶段，旧版 ``第N阶段`` 引用
    会指向不存在的章节，对真人用户是死链。

    任一文档里出现"第八阶段 / 第七阶段 / 第六阶段"等历史 stage 编号即视为腐烂引用。
    （"第二阶段"在 ARCHITECTURE 顶层用作"本轮做了什么"的回顾性陈述，不是章节链接，
    所以白名单它，但禁止再新增其他 stage 编号链接。）
    """
    forbidden = ["第三阶段", "第四阶段", "第五阶段", "第六阶段", "第七阶段", "第八阶段", "第九阶段"]
    offenders: list[str] = []
    for doc in DOCS:
        if not doc.exists():
            continue
        text = _read(doc)
        for token in forbidden:
            if token in text:
                offenders.append(f"{doc.relative_to(REPO_ROOT)} 含腐烂阶段引用 '{token}'")
    assert not offenders, "\n".join(offenders)


def test_roadmap_xfail_section_points_to_real_test() -> None:
    """ROADMAP §xfail 里写到的测试文件 + 函数名必须在 ``tests/`` 真实存在，否则真人
    用户去仓库查"这个 xfail 是哪条？转正条件是啥？"会找不到。

    这里用启发式做最小校验：扫描 ROADMAP 中所有 ``tests/...py`` 路径以及
    ``::test_xxx`` 函数引用，对照仓库实际 ``tests/`` 文件 + AST 函数定义。
    """
    roadmap = _read(REPO_ROOT / "docs" / "ROADMAP.md")
    # 仅取 §xfail 测试 一节的内容（避免把 candidate A 分支段落也卷进来）
    section_marker = "## xfail 测试"
    assert section_marker in roadmap, "ROADMAP 应有 '## xfail 测试' 章节"
    section = roadmap.split(section_marker, 1)[1]
    # 截到下一个 ``## `` 标题
    next_h2 = section.find("\n## ")
    if next_h2 != -1:
        section = section[:next_h2]

    import re

    # tests/xxx_xfail.py::test_yyy 形式的所有引用
    refs = re.findall(r"tests/([\w./]+\.py)::(\w+)", section)
    assert refs, "ROADMAP §xfail 至少要列一条具体的 tests/xxx::test_yyy 引用"

    missing: list[str] = []
    for rel, fn in refs:
        path = REPO_ROOT / "tests" / rel
        if not path.exists():
            missing.append(f"docs/ROADMAP.md §xfail 引用 tests/{rel} 不存在")
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        defined = {
            node.name
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        if fn not in defined:
            missing.append(
                f"docs/ROADMAP.md §xfail 引用 tests/{rel}::{fn} 在该文件中未定义"
            )
    assert not missing, "\n".join(missing)
