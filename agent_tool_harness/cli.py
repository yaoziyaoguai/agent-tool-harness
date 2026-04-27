from __future__ import annotations

import argparse
import json
from pathlib import Path

from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor
from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.config.loader import load_evals, load_project, load_tools
from agent_tool_harness.eval_generation.candidate_writer import CandidateWriter
from agent_tool_harness.eval_generation.generator import EvalGenerator
from agent_tool_harness.runner.eval_runner import EvalRunner


def main(argv: list[str] | None = None) -> int:
    """CLI 入口。

    CLI 只负责参数解析和模块编排，不把任何 demo 项目逻辑写进命令实现。
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
    if args.command == "audit-tools":
        return _audit_tools(args.tools, args.out)
    if args.command == "generate-evals":
        return _generate_evals(args.project, args.tools, args.source, args.tests, args.out)
    if args.command == "audit-evals":
        return _audit_evals(args.evals, args.out)
    if args.command == "run":
        return _run(args.project, args.tools, args.evals, args.out, args.mock_path)
    raise AssertionError(args.command)


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def _audit_tools(tools_path: str, out: str) -> int:
    tools = load_tools(tools_path)
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
            raise SystemExit("--tests is required when --source tests")
        candidates = generator.from_tests(tests_path)
    path = CandidateWriter().write(candidates, out)
    print(f"wrote {path}")
    return 0


def _audit_evals(evals_path: str, out: str) -> int:
    evals = load_evals(evals_path)
    result = EvalQualityAuditor().audit(evals)
    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_json(out_dir / "audit_evals.json", result)
    print(f"wrote {out_dir / 'audit_evals.json'}")
    return 0


def _run(project_path: str, tools_path: str, evals_path: str, out: str, mock_path: str) -> int:
    result = EvalRunner().run(
        load_project(project_path),
        load_tools(tools_path),
        load_evals(evals_path),
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
