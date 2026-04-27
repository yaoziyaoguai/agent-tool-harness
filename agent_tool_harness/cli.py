from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor
from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.config.loader import ConfigError, load_evals, load_project, load_tools
from agent_tool_harness.eval_generation.candidate_writer import CandidateWriter
from agent_tool_harness.eval_generation.generator import EvalGenerator
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
    _write_json(out_dir / "audit_tools.json", result)
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
    path = CandidateWriter().write(candidates, out)
    print(f"wrote {path}")
    return 0


def _audit_evals(evals_path: str, out: str) -> int:
    evals = load_evals(evals_path)
    _warn_if_empty(evals, "evals", evals_path)
    result = EvalQualityAuditor().audit(evals)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "audit_evals.json", result)
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


if __name__ == "__main__":
    raise SystemExit(main())
