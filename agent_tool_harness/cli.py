from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.artifact_schema import make_run_metadata, stamp_artifact
from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor
from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.config.loader import ConfigError, load_evals, load_project, load_tools
from agent_tool_harness.eval_generation.candidate_writer import CandidateWriter
from agent_tool_harness.eval_generation.generator import EvalGenerator
from agent_tool_harness.eval_generation.promoter import CandidatePromoter
from agent_tool_harness.runner.eval_runner import EvalRunner
from agent_tool_harness.tools.registry import ToolRegistryError


class CLIError(SystemExit):
    """CLI 友好错误。

    架构边界：
    - 只承担“把 loader/registry 抛出的内部错误转成给真实用户看的可行动消息”的职责。
    - 不重新做配置校验，也不重写 ConfigError 的语义；它只是改变错误显示方式。

    退出码统一使用 2，与 argparse 的 usage error 对齐，方便 shell 脚本判断。
    """

    def __init__(self, message: str):
        super().__init__(2)
        self.message = message


def _build_parser() -> argparse.ArgumentParser:
    """构造 CLI argparse 解析器。

    架构边界：
    - **负责**：把所有 subcommand + 必填/可选参数集中声明在一处，作为"CLI 接口
      的唯一事实来源"。`main()` 调它来解析 argv；测试也调它来验证 README /
      docs/ONBOARDING.md 里的 ``python -m agent_tool_harness.cli ...`` 片段
      和真实 CLI 完全一致。
    - **不负责**：执行任何业务（loader / runner / writer 都由 ``main`` 路由），
      也不做参数语义校验（例如 ``--source tests`` 必须配 ``--tests``）——
      这类组合校验由 ``main`` 在拿到 args 后用 ``CLIError`` 显式报错，避免和
      argparse 内部行为耦合。

    为什么单独抽出来：
    - v0.1 收口期间真人 onboarding 走查发现 ``docs/ONBOARDING.md §3`` 给出的
      ``generate-evals`` 命令缺 ``--project`` / ``--source``，新用户第 3 步直接
      被 argparse 拒收。根因是仓库没有任何测试把"文档命令"和"真实 parser"对齐，
      只能靠人工同步。把 parser 抽出后，``tests/test_doc_cli_snippets.py`` 可以
      静态扫描所有 markdown bash block，对每条命令调一次 ``parse_args``——drift
      会立刻被测试钉住，不再漏到真实用户面前。

    扩展点：新增 subcommand / 新参数请只在本函数内追加，并同步更新 README +
    docs/ONBOARDING.md 的命令片段；test_doc_cli_snippets 会兜底验证一致性。
    """

    parser = argparse.ArgumentParser(prog="agent-tool-harness")
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit_tools = subparsers.add_parser("audit-tools")
    audit_tools.add_argument("--tools", required=True)
    audit_tools.add_argument("--out", required=True)

    generate = subparsers.add_parser("generate-evals")
    generate.add_argument("--project", required=True)
    generate.add_argument("--tools", required=True)
    generate.add_argument("--source", choices=["tools", "tests"], required=True)
    generate.add_argument("--tests")
    generate.add_argument("--out", required=True)

    audit_evals = subparsers.add_parser("audit-evals")
    audit_evals.add_argument("--evals", required=True)
    audit_evals.add_argument("--out", required=True)

    run = subparsers.add_parser("run")
    run.add_argument("--project", required=True)
    run.add_argument("--tools", required=True)
    run.add_argument("--evals", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--mock-path", choices=["good", "bad"], default="good")

    promote = subparsers.add_parser(
        "promote-evals",
        help=(
            "把 review 通过的候选（review_status=accepted 且 runnable=true）"
            "搬运成正式 evals.yaml 片段；默认禁止覆盖已有文件，需 --force。"
        ),
    )
    promote.add_argument("--candidates", required=True)
    promote.add_argument("--out", required=True)
    promote.add_argument(
        "--force",
        action="store_true",
        help="允许覆盖已存在的输出文件（默认禁止，避免冲掉手写正式 evals.yaml）",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。

    CLI 只负责参数解析和模块编排，不把任何 demo 项目逻辑写进命令实现。

    错误处理边界：
    - 用户配置错误（坏路径、坏 YAML、duplicate eval id 等）会被 ConfigError 捕获并以
      可行动信息打印到 stderr，退出码 2。这是“真实用户最常见的接入失败面”——
      框架不应该把 Python traceback 直接抛给他们。
    - tools/evals 为空时，CLI 会在 stderr 写一条警告，但不强制 hard fail；这给真实团队
      在 audit 阶段查看“空配置如何被报告呈现”的余地。run 命令仍允许继续，但报告会显示
      0 eval / 0 工具，方便诊断。
    - --source tests 必须搭配 --tests，否则给出明确提示而非 argparse 的内部异常。
    """

    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "audit-tools":
            return _audit_tools(args.tools, args.out)
        if args.command == "generate-evals":
            return _generate_evals(args.project, args.tools, args.source, args.tests, args.out)
        if args.command == "audit-evals":
            return _audit_evals(args.evals, args.out)
        if args.command == "run":
            return _run(args.project, args.tools, args.evals, args.out, args.mock_path)
        if args.command == "promote-evals":
            return _promote_evals(args.candidates, args.out, force=args.force)
    except ConfigError as exc:
        # ConfigError 表示用户配置存在“框架无法理解”的结构问题。这里只显示消息，
        # 避免把内部 traceback 推给真实团队；他们应该得到一条直接告诉他们改哪个字段
        # 的提示。详细字段位置已经包含在 ConfigError 消息里。
        print(f"error: configuration invalid — {exc}", file=sys.stderr)
        print(
            "hint: 检查 YAML 路径、root 类型（mapping 或 list）、字段类型；"
            "tools/evals 列表项必须是 mapping；eval.id 必须唯一。",
            file=sys.stderr,
        )
        return 2
    except FileNotFoundError as exc:
        print(f"error: file not found — {exc}", file=sys.stderr)
        print(
            "hint: 确认相对路径是从当前工作目录解析；project.yaml 中的 executor.path "
            "相对 tools.yaml 所在目录。",
            file=sys.stderr,
        )
        return 2
    except ToolRegistryError as exc:
        # ToolRegistryError 通常意味着用户写了重复的 qualified tool name，或者用了短名
        # 但同名工具在多个 namespace 下存在。这是 run 命令最容易踩的注册期失败，
        # 把它转成 CLI 友好错误，避免用户看到内部 traceback。
        print(f"error: tool registry — {exc}", file=sys.stderr)
        print(
            "hint: 确保 tools.yaml 中每个 namespace.name 唯一；"
            "使用短名调用前请先消除歧义。",
            file=sys.stderr,
        )
        return 2
    except FileExistsError as exc:
        # promote-evals 拒绝覆盖时走这里。把它和 ConfigError 区分开，方便 CI 脚本根据
        # 退出原因决定是否加 --force。
        print(f"error: refused to overwrite — {exc}", file=sys.stderr)
        print(
            "hint: 如果你确定要覆盖（例如 --out 指向 runs/ 临时目录而非手写正式 "
            "evals.yaml），请加 --force 重跑。",
            file=sys.stderr,
        )
        return 2
    except CLIError as exc:
        print(f"error: {exc.message}", file=sys.stderr)
        return 2
    raise AssertionError(args.command)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def _warn_if_empty(items: list, label: str, source_path: str) -> None:
    """对“合法但为空”的配置发出软警告。

    为什么不 hard fail：真实团队偶尔会先 commit 一个占位 tools.yaml/evals.yaml 来跑
    audit，希望看到“空状态在报告里长什么样”。框架在这种情况下应继续，但必须明确
    告诉用户“你跑出来的 0 是因为这里没有内容”，避免误以为 audit 真的过了。
    """

    if not items:
        print(
            f"warning: {label} loaded from {source_path} is empty; "
            f"audit/report will reflect a zero-{label} run.",
            file=sys.stderr,
        )


def _audit_tools(tools_path: str, out: str) -> int:
    tools = load_tools(tools_path)
    _warn_if_empty(tools, "tools", tools_path)
    result = ToolDesignAuditor().audit(tools)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 给独立 audit-tools artifact 也打 schema_version 戳，让"不在 run 里跑"的 audit
    # 输出与 run 内部产出一致；下游 CI 解析逻辑可统一处理。
    stamped = stamp_artifact(
        result,
        run_metadata=make_run_metadata(extra={"command": "audit-tools"}),
    )
    _write_json(out_dir / "audit_tools.json", stamped)
    print(f"wrote {out_dir / 'audit_tools.json'}")
    return 0


def _generate_evals(
    project_path: str,
    tools_path: str,
    source: str,
    tests_path: str | None,
    out: str,
) -> int:
    generator = EvalGenerator()
    if source == "tools":
        candidates = generator.from_tools(load_project(project_path), load_tools(tools_path))
    else:
        if not tests_path:
            # 显式拒绝 `--source tests` 缺 `--tests` 的组合；这是真实团队最容易踩的坑。
            # 用 CLIError 而不是 SystemExit 字符串，是为了让 main() 的 except 走统一格式。
            raise CLIError(
                "--source tests requires --tests <path>; "
                "示例：--source tests --tests tests/"
            )
        candidates = generator.from_tests(tests_path)
    writer = CandidateWriter()
    path = writer.write(candidates, out)
    # warnings 是质量提示，**不**影响退出码（CLI 仍 0）。把它打到 stderr 是为了
    # 让 CI/审核者立刻看到；同时它也已经被写入 YAML 顶层 ``warnings`` 字段，跟随
    # 候选文件进 review/PR diff，形成审核闭环。详见 CandidateWriter docstring。
    warnings = writer.collect_warnings(candidates)
    for warning in warnings:
        print(f"warning: {warning}", file=sys.stderr)
    print(f"wrote {path}")
    return 0


def _audit_evals(evals_path: str, out: str) -> int:
    evals = load_evals(evals_path)
    _warn_if_empty(evals, "evals", evals_path)
    result = EvalQualityAuditor().audit(evals)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamped = stamp_artifact(
        result,
        run_metadata=make_run_metadata(
            eval_count=len(evals),
            extra={"command": "audit-evals"},
        ),
    )
    _write_json(out_dir / "audit_evals.json", stamped)
    print(f"wrote {out_dir / 'audit_evals.json'}")
    return 0


def _run(project_path: str, tools_path: str, evals_path: str, out: str, mock_path: str) -> int:
    tools = load_tools(tools_path)
    evals = load_evals(evals_path)
    _warn_if_empty(tools, "tools", tools_path)
    _warn_if_empty(evals, "evals", evals_path)
    result = EvalRunner().run(
        load_project(project_path),
        tools,
        evals,
        MockReplayAdapter(mock_path),
        out,
    )
    print(
        json.dumps(
            {"out_dir": result["out_dir"], "metrics": result["metrics"]},
            ensure_ascii=False,
        )
    )
    return 0


def _promote_evals(candidates_path: str, out: str, *, force: bool) -> int:
    """把 review 通过的候选搬运到正式 evals.yaml 片段。

    退出码：
    - 0：正常（即使 promoted 为空、即使有 skipped 项；这是为了让"候选还差什么"
      不被误解为 CLI 失败，审核者仍能从 stdout/JSON 看到 skip 原因）；
    - 2：拒绝覆盖（FileExistsError）/ FileNotFoundError / ConfigError 等。

    输出：stdout 写一行 JSON 摘要 ``{out, promoted, skipped, summary}``，便于 CI
    grep；文件本身已包含 ``promote_summary``，这里只是镜像，方便不读文件就能看到。
    """

    promoter = CandidatePromoter()
    promote_result = promoter.promote(candidates_path, out, force=force)
    summary = {
        "out": str(promote_result.out_path),
        "promoted_count": len(promote_result.promoted),
        "skipped_count": len(promote_result.skipped),
        "promoted_ids": [str(item.get("id")) for item in promote_result.promoted],
        "skipped": promote_result.skipped,
    }
    if promote_result.skipped:
        # 把"哪些候选被跳"在 stderr 显式列一遍，让审核者立即看到下一步要补什么；
        # 不靠他们去打开 YAML 翻 promote_summary。
        for item in promote_result.skipped:
            print(
                f"skip: candidate {item['id']} — {item['reason']}",
                file=sys.stderr,
            )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
