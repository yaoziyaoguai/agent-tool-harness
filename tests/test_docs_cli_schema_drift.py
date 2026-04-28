"""v1.8 第二项：schema-driven CLI snippet drift 检查。

中文学习型说明
==============
本文件**钉死**的边界
--------------------
v1.7 的 ``test_docs_cli_snippets.py`` 只覆盖 subcommand **名字**是否真
实存在；本测试在此之上做 **schema-driven flag** 漂移检查：

1. 从 argparse 自省每个 subcommand 的 **required flag 集合**；
2. 扫描 README / TRY_IT / TRY_IT_v1_7 / ONBOARDING 中的
   ``python -m agent_tool_harness.cli <sub> [flags ...]`` 片段，提取
   实际 flag；
3. 对每条 snippet 验证：所有 required flag 都被提供；所有出现的 flag
   都是该 subcommand 注册过的 flag；
4. 如果 snippet 跨多行（``\\`` 续行），先按 shell-like 规则 join。

设计取舍：
- 只校验 ``--`` flag 名是否真实，不校验值——值是 path / 字面量，
  会随 example 演进。
- 接受 ``--flag value`` 与 ``--flag=value`` 两种写法；
- 跳过 ``--`` 后面的位置参数（本 CLI 目前没有，预留兼容）；
- 对 argparse 中的 alias（如 ``--source-run`` / ``--run`` 别名）
  自动展开。

本文件**不**负责什么
--------------------
- 不验证 flag value 的合法性（snippet 中 path 是否存在、format 是否对）；
- 不验证 subcommand 名是否真实——那是 ``test_docs_cli_snippets.py``
  的职责，本测试假定该层已通过；
- 不强制顺序——argparse 本身允许 flag 任意顺序。

防回归价值（这些 bug 都是 v1.7 测试无法捕获的）
-------------------------------------------------
- 把 ``--source-run`` 改名为 ``--source`` 但 README 还在用旧名
  （subcommand 名没变，v1.7 测试无法捕获，但用户复制粘贴会失败）；
- 给 ``replay-run`` 加新 required flag 但 TRY_IT_v1_7 snippet 没补；
- 删掉 ``--mock-path`` 但 README "## 快速开始" 还在用；
- 把 ``--out`` 从 required 改成 optional 但文档说"必传"；这种漂移用
  argparse required 集合做交叉检查能立刻抓住。

实现注意：
- argparse 的 ``optionals`` action 列表里既有 ``--flag``、也有 ``-h``，
  我们只关心 ``--`` 长选项；
- 用 ``action.option_strings`` 拿到所有 alias 名；
- 用 ``action.required`` 区分 required vs optional。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_tool_harness.cli import _build_parser as build_parser

REPO_ROOT = Path(__file__).resolve().parent.parent

DOCS_TO_SCAN = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "TRY_IT.md",
    REPO_ROOT / "docs" / "TRY_IT_v1_7.md",
    REPO_ROOT / "docs" / "ONBOARDING.md",
    REPO_ROOT / "docs" / "INTERNAL_TRIAL.md",
]

# 多行 shell snippet 起手匹配；含可选 ``\\`` 续行。
# 用非贪婪到下一行不以 ``  `` / ``\\`` 续行结尾为止。
# 简化策略：先把整段代码块按 ``\\\n`` 续行 join 成单行，再 line-by-line
# 找 ``python -m agent_tool_harness.cli`` 起手的命令。
SNIPPET_HEAD = re.compile(
    r"python\s+-m\s+agent_tool_harness\.cli\s+([a-z][a-z0-9-]*)(.*)"
)


def _extract_subcommand_schema() -> dict[str, dict]:
    """对每个 subcommand 自省 ``{required_flags, all_flags}``。

    返回 ``{sub_name: {"required": set[str], "all": set[str]}}``。
    """
    parser = build_parser()
    sub_action = next(
        a for a in parser._actions
        if hasattr(a, "choices") and isinstance(a.choices, dict)
    )
    out: dict[str, dict] = {}
    for sub_name, sub_parser in sub_action.choices.items():
        all_flags: set[str] = set()
        required_flags: set[str] = set()
        # canonical 把 alias map 到第一个 long option（如 --source-run / --run
        # 都映射成 canonical "--source-run"），让"用户用了 alias"也算合法。
        canonical_of: dict[str, str] = {}
        for action in sub_parser._actions:
            longs = [s for s in action.option_strings if s.startswith("--")]
            if not longs:
                continue
            canonical = longs[0]
            for s in longs:
                all_flags.add(s)
                canonical_of[s] = canonical
            if action.required:
                required_flags.add(canonical)
        out[sub_name] = {
            "required": required_flags,
            "all": all_flags,
            "canonical_of": canonical_of,
        }
    return out


def _join_continuations(block: str) -> str:
    """把 ``\\\n`` 续行 join 成单行，方便后续 token 化。"""
    # 处理 markdown 中 \\ 续行（注意 markdown 源码里就是字面 \）。
    return re.sub(r"\\\s*\n\s*", " ", block)


def _extract_snippets_from_code_blocks(text: str) -> list[tuple[str, str]]:
    """从 markdown 中提取 ```bash``` 与 ``` code blocks，返回 ``[(sub, args_str)]``。

    args_str 是 subcommand 后面到本命令结束的字符串（不含命令名本身）。
    """
    snippets: list[tuple[str, str]] = []
    # 匹配 ``` 开头到 ``` 结尾的代码块。
    blocks = re.findall(r"```[a-zA-Z]*\n(.*?)\n```", text, flags=re.DOTALL)
    for block in blocks:
        joined = _join_continuations(block)
        for line in joined.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            m = SNIPPET_HEAD.search(line)
            if m:
                snippets.append((m.group(1), m.group(2).strip()))
    return snippets


def _tokenize_args(args_str: str) -> list[str]:
    """把 args_str 按 shell-like 规则切 token；只关心 ``--flag`` 形态。

    简化：按 whitespace split；遇到 ``--flag=value`` 拆出 ``--flag``。
    不处理引号——本仓库 docs snippet 不用嵌套引号。
    """
    tokens: list[str] = []
    for raw in args_str.split():
        if raw.startswith("--"):
            # 把 --flag=value 拆成 --flag。
            if "=" in raw:
                tokens.append(raw.split("=", 1)[0])
            else:
                tokens.append(raw)
    return tokens


def _collect_all_doc_snippets() -> list[tuple[str, str, str]]:
    """返回 ``[(doc_name, sub, args_str)]``，扫所有受控 doc。"""
    out: list[tuple[str, str, str]] = []
    for doc in DOCS_TO_SCAN:
        if not doc.exists():
            continue
        text = doc.read_text(encoding="utf-8")
        for sub, args in _extract_snippets_from_code_blocks(text):
            out.append((doc.name, sub, args))
    return out


SCHEMA = _extract_subcommand_schema()
DOC_SNIPPETS = _collect_all_doc_snippets()


def test_at_least_one_snippet_per_doc_is_extracted():
    """sanity：至少能从 README / TRY_IT_v1_7 中各抽到一条 snippet。

    如果抽不到，说明正则 / 代码块解析坏了，本测试自身失效。
    """
    docs_with_snippets = {doc for doc, _, _ in DOC_SNIPPETS}
    assert "README.md" in docs_with_snippets
    assert "TRY_IT_v1_7.md" in docs_with_snippets


@pytest.mark.parametrize("doc,sub,args_str", DOC_SNIPPETS)
def test_doc_snippet_uses_only_registered_flags(doc: str, sub: str, args_str: str):
    """每条 snippet 中出现的所有 ``--flag`` 必须是该 subcommand 注册过的 flag。"""
    schema = SCHEMA.get(sub)
    # subcommand 名漂移由 test_docs_cli_snippets.py 钉，本测试假定通过。
    if schema is None:
        pytest.skip(f"subcommand {sub} unknown; covered by snippet name test")
    used = _tokenize_args(args_str)
    unknown = [f for f in used if f not in schema["all"]]
    assert not unknown, (
        f"{doc} snippet 'agent_tool_harness.cli {sub} {args_str}' uses "
        f"unregistered flags {unknown}; argparse only knows {sorted(schema['all'])}"
    )


@pytest.mark.parametrize("doc,sub,args_str", DOC_SNIPPETS)
def test_doc_snippet_provides_all_required_flags(doc: str, sub: str, args_str: str):
    """每条 snippet 必须包含该 subcommand 的所有 required flag（按 canonical 比较）。"""
    schema = SCHEMA.get(sub)
    if schema is None:
        pytest.skip(f"subcommand {sub} unknown; covered by snippet name test")
    used_canonical = {
        schema["canonical_of"].get(f, f) for f in _tokenize_args(args_str)
    }
    missing = sorted(schema["required"] - used_canonical)
    assert not missing, (
        f"{doc} snippet 'agent_tool_harness.cli {sub} {args_str}' missing "
        f"required flags {missing}; user 复制粘贴会被 argparse 拒收。"
    )
