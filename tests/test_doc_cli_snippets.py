"""校验 README / docs/CLI_USAGE.md 的 CLI 命令片段与真实 argparse 一致。

把"文档里宣告的 CLI 接口"和"真实 argparse 接受的参数"绑在一起，防止
doc-vs-CLI drift 导致新用户照抄命令失败。

实现要点：
- 复用 ``agent_tool_harness.cli._build_parser``
- 只扫 ``README.md`` + ``docs/CLI_USAGE.md``（外部接入路径必读文档）
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from agent_tool_harness.cli import _build_parser

# 仓库根目录：本文件位于 ``tests/``，根目录即上一层。
REPO_ROOT = Path(__file__).resolve().parent.parent

# 接入路径必读文档；新增文档时如希望同样校验，请追加在这里并保持按"用户接入
# 顺序"排列，便于失败信息直观对应到接入步骤。
DOC_PATHS = [
    REPO_ROOT / "README.md",
    REPO_ROOT / "docs" / "CLI_USAGE.md",
]

# 我们关心的 CLI 调用前缀。``python -m agent_tool_harness.cli`` 是文档统一的
# 入口；命令行别名（如 ``agent-tool-harness``）属于安装后的可执行入口，受
# entry_point 影响，不在本测试范围内。
CLI_PREFIX = "python -m agent_tool_harness.cli"


def _extract_cli_invocations(markdown: str) -> list[list[str]]:
    """从 markdown 内容里抽取所有 CLI 调用的 argv 列表。

    实现细节：
    - 只扫 markdown 三反引号 + bash 语言标签的 fenced 代码块（开头是 ```bash``，
      结尾是 ``` ` ` ` ```）——这是文档里"用户应该照抄运行"的部分；行内代码
      / 普通段落不算。
    - 行尾反斜杠续行先合并成一行，再按 ``shlex.split`` 解析参数；这样和真实
      shell 复制粘贴的行为一致。
    - 注释行（``#`` 开头）跳过；这是 README 里常见的"# 1) 审计工具契约"等说明。
    """

    invocations: list[list[str]] = []
    for block in re.findall(r"```bash\n(.*?)```", markdown, flags=re.DOTALL):
        # 把以反斜杠结尾的续行折成一行，保留原始空白结构语义。
        joined = re.sub(r"\\\s*\n\s*", " ", block)
        for raw_line in joined.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.startswith(CLI_PREFIX):
                continue
            tail = line[len(CLI_PREFIX):].strip()
            if not tail:
                # 仅 ``python -m agent_tool_harness.cli`` 自身没有 subcommand；
                # 文档里不应该出现，这里宽松跳过而不是误报。
                continue
            invocations.append(shlex.split(tail))
    return invocations


def test_doc_cli_snippets_match_argparse():
    """所有接入文档里的 CLI 命令必须能被真实 argparse 解析。

    断言失败时直接列出出问题的文档路径 + argv + argparse 的 exit code，让
    维护者一眼定位是哪份文档的哪条命令漏了参数；不要把失败信息缩到只剩
    布尔，否则失去发现真实 drift 的能力。
    """

    parser = _build_parser()
    failures: list[tuple[str, list[str], int | str | None]] = []
    total_invocations = 0

    for path in DOC_PATHS:
        text = path.read_text(encoding="utf-8")
        invocations = _extract_cli_invocations(text)
        total_invocations += len(invocations)
        for argv in invocations:
            try:
                parser.parse_args(argv)
            except SystemExit as exc:  # argparse 用 SystemExit 表达拒收
                failures.append((str(path.relative_to(REPO_ROOT)), argv, exc.code))

    # 防御性断言：如果文档完全不含 CLI 命令片段，说明本测试的抽取规则失效
    # （例如有人把 ```bash 改成 ```sh）；与其静默通过，不如硬失败提醒维护者。
    assert total_invocations > 0, (
        "未在接入文档中抽到任何 CLI 命令片段；请检查 _extract_cli_invocations "
        "是否还能识别当前 markdown 代码块格式（例如 ```bash 的语言标签是否被改名）。"
    )

    assert not failures, (
        "接入文档里的 CLI 片段与真实 argparse 不一致（10 分钟接入路径会在这些命令上断掉）：\n"
        + "\n".join(
            f"  - {path}: argv={argv!r} exit_code={code}"
            for path, argv, code in failures
        )
    )


@pytest.mark.parametrize(
    "argv",
    [
        # 这条 argv 故意缺 ``--project`` / ``--source``——也就是 v0.1 收口期间
        # ONBOARDING §3 真实踩到的 bug。列在这里是为了**双向锁定**：未来如果
        # 有人改弱了 ``_build_parser`` 的 required 约束（例如把 ``--project``
        # 改成 optional 让坏文档也能跑），本断言会立刻失败，提醒"放宽约束 =
        # 默许文档继续误导用户"。
        ["generate-evals", "--tools", "x.yaml", "--out", "y.yaml"],
    ],
)
def test_required_args_are_actually_required(argv):
    """验证关键 subcommand 的必填参数确实是必填。

    这是上面 doc-vs-CLI 测试的"对偶"——仅靠文档对齐还不够，必须保证 parser
    真的会在缺参时拒收，否则文档对齐了但 parser 被悄悄放宽，drift 又出现。
    fake/mock 说明：本用例不模拟任何外部依赖，直接对真实 ``_build_parser``
    施加缺参 argv，模拟"新用户漏拷一行"的真实失败场景。
    """

    parser = _build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(argv)


def test_readme_quickstart_audits_the_just_promoted_file():
    """README 代码块中如有 promote-evals → audit-evals，路径必须连贯。"""

    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")

    promoted_paths: list[str] = []
    audited_paths: list[str] = []
    for block in re.findall(r"```bash\n(.*?)```", readme, flags=re.DOTALL):
        joined = re.sub(r"\\\s*\n\s*", " ", block)
        for raw_line in joined.splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "promote-evals" in line and "--out" in line:
                argv = shlex.split(line)
                if "--out" in argv:
                    promoted_paths.append(argv[argv.index("--out") + 1])
            if "audit-evals" in line and "--evals" in line:
                argv = shlex.split(line)
                if "--evals" in argv:
                    audited_paths.append(argv[argv.index("--evals") + 1])

    if not promoted_paths:
        pytest.skip("README 当前未演示 promote-evals；流程一致性约束不适用。")

    missing = [p for p in promoted_paths if p not in audited_paths]
    assert not missing, (
        "README 中 promote-evals 输出未被任何 audit-evals 验证：\n"
        + "\n".join(f"  - promoted but never audited: {p}" for p in missing)
        + f"\n  audited paths: {audited_paths!r}"
    )
