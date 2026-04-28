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

    analyze = subparsers.add_parser(
        "analyze-artifacts",
        help=(
            "对已有 run 目录做离线 trace-derived 信号复盘（deterministic 启发式，"
            "不调用 LLM、不重跑 Agent、不重跑工具）。"
        ),
    )
    analyze.add_argument(
        "--run",
        required=True,
        help="已有 run 目录（包含 tool_calls.jsonl / tool_responses.jsonl 等 9 个 artifact）",
    )
    analyze.add_argument(
        "--tools",
        required=True,
        help="tools.yaml —— 复盘需要 ToolSpec.output_contract / when_not_to_use 元数据",
    )
    analyze.add_argument(
        "--evals",
        required=False,
        help=(
            "evals.yaml（可选）—— 提供 user_prompt 才能触发 "
            "tool_selected_in_when_not_to_use_context 信号；不传时只覆盖 contract / "
            "重复调用类信号"
        ),
    )
    analyze.add_argument("--out", required=True)

    replay = subparsers.add_parser(
        "replay-run",
        help=(
            "用 TranscriptReplayAdapter 重放一份已有 run 目录，跑一次完整 EvalRunner 闭环 "
            "（不调 LLM / 不调 registry.execute；signal_quality=recorded_trajectory）。"
        ),
    )
    replay.add_argument(
        "--source-run",
        "--run",
        dest="source_run",
        required=True,
        help="已有 run 目录（必须包含 tool_calls.jsonl / tool_responses.jsonl 之一，"
             "建议同时含 transcript.jsonl 以重建 final_answer）。"
             "为统一 CLI 体验，本参数同时接受 --run 别名（与 analyze-artifacts 一致）。",
    )
    replay.add_argument("--project", required=True)
    replay.add_argument("--tools", required=True)
    replay.add_argument("--evals", required=True)
    replay.add_argument("--out", required=True)

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
        if args.command == "analyze-artifacts":
            return _analyze_artifacts(args.run, args.tools, args.evals, args.out)
        if args.command == "replay-run":
            return _replay_run(
                args.source_run,
                args.project,
                args.tools,
                args.evals,
                args.out,
            )
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


def _analyze_artifacts(
    run_dir: str,
    tools_path: str,
    evals_path: str | None,
    out: str,
) -> int:
    """对已有 run 目录做离线 trace-derived 信号复盘。

    架构边界：
    - **负责**：复用 :func:`agent_tool_harness.diagnose.trace_signal_analyzer.analyze_run_dir`
      读取 ``tool_calls.jsonl`` / ``tool_responses.jsonl``，按 eval_id 分组得到
      :class:`TraceSignalAnalyzer` 的 5 类 deterministic 信号，并把结果写到
      ``--out`` 目录下的 ``tool_use_signals.json`` + ``tool_use_signals.md``。
    - **不负责**：重新跑 Agent、重新调工具、调 LLM、写新的 judge 结论。本命令
      只是 replay 已有 raw artifact + 工具/eval 元数据，把 deterministic 信号
      派生出来；它**不是 LLM Judge**，**不是真实语义证明**。

    为什么要这条 CLI（而不是只读 ``diagnosis.json`` 里的 ``tool_use_signals``）：
    - ``diagnosis.json`` 是 ``run`` 命令在跑完时一次性写的；如果用户拿到一份
      历史 run（例如同事丢过来的 ``runs/`` 目录、或者 v0.2 第三轮之前生成的
      老 run），那份 ``diagnosis.json`` 里**根本没有**新的 ``tool_use_signals``
      字段。本命令让用户只用 ``--run`` + ``--tools`` 就能离线把信号补出来。
    - 让 trace 信号脱离 EvalRunner 独立存在，也方便 CI 把 "信号复盘" 做成
      和 "Agent 跑通" 完全独立的步骤——前者在 nightly 里跑、后者每条 PR 跑。

    错误处理（必须可行动，不允许吞异常假成功）：
    - ``--run`` 路径不存在 / 不是目录 → CLIError；
    - 该目录里两份 JSONL 都缺 → CLIError，并在 hint 里列出预期文件名；
    - ``--tools`` 加载失败 → 统一走 ConfigError 通道（``main`` 已处理）；
    - ``--evals`` 未传 → 写一条 stderr warning，提示
      ``tool_selected_in_when_not_to_use_context`` 信号会被跳过；
    - 复盘正常但 0 信号 → 仍输出 schema 完整的 JSON + Markdown，并打印
      "0 signals" 提示，避免被误以为 CLI 失败。

    输出契约：
    - ``tool_use_signals.json`` —— ``stamp_artifact`` 包过的 dict，含
      ``schema_version`` / ``run_metadata`` / 业务字段
      ``analyzed_run`` / ``signals_by_eval`` / ``signal_count``。
    - ``tool_use_signals.md`` —— 给人看的 Markdown，按 eval 分组列出信号，
      每条带 severity / signal_type / related_tool / why_it_matters /
      suggested_fix / evidence_refs。

    扩展点（写在这里，本轮**不**实现）：
    - 未来可以让本命令也并入 ``TranscriptAnalyzer`` 派生 finding，把
      "rule-derived" 和 "trace-derived" 都放进同一份 analysis 文件；
    - 也可以加 ``--diff PREV_RUN_DIR`` 做 run-to-run 信号变化对比。
    """

    from agent_tool_harness.diagnose.trace_signal_analyzer import analyze_run_dir

    run_path = Path(run_dir)
    if not run_path.exists() or not run_path.is_dir():
        raise CLIError(
            f"--run 指向的路径不存在或不是目录: {run_dir}\n"
            "hint: 请传入 `agent-tool-harness run` 写出的 run 目录"
            "（包含 tool_calls.jsonl / tool_responses.jsonl 等 9 个 artifact）。"
        )
    calls_path = run_path / "tool_calls.jsonl"
    responses_path = run_path / "tool_responses.jsonl"
    if not calls_path.exists() and not responses_path.exists():
        raise CLIError(
            f"--run 目录里既没有 tool_calls.jsonl 也没有 tool_responses.jsonl: {run_dir}\n"
            "hint: 该目录看起来不是一份 harness run。请先用 `agent-tool-harness run` "
            "生成 artifacts，再用本命令复盘。"
        )

    tools = load_tools(tools_path)
    _warn_if_empty(tools, "tools", tools_path)

    user_prompts_by_eval: dict[str, str] = {}
    if evals_path:
        evals = load_evals(evals_path)
        for spec in evals:
            user_prompts_by_eval[spec.id] = spec.user_prompt or ""
    else:
        print(
            "warning: --evals 未传；tool_selected_in_when_not_to_use_context 信号"
            "（依赖 user_prompt 词袋命中）将被跳过。如需该信号请补 --evals。",
            file=sys.stderr,
        )

    signals_by_eval = analyze_run_dir(
        run_path,
        tools=tools,
        user_prompts_by_eval=user_prompts_by_eval,
    )
    signal_count = sum(len(v) for v in signals_by_eval.values())

    out_dir = Path(out)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "analyzed_run": str(run_path),
        "signals_by_eval": signals_by_eval,
        "signal_count": signal_count,
        "analysis_kind": "trace_derived_deterministic_heuristic",
        "analysis_kind_note": (
            "本结果由 deterministic 启发式从已有 raw artifact 复盘而来，"
            "不是 LLM Judge，不是语义级证明；同义词改写的诱饵仍可能漏。"
        ),
    }
    stamped = stamp_artifact(
        payload,
        run_metadata=make_run_metadata(extra={"command": "analyze-artifacts"}),
    )
    json_path = out_dir / "tool_use_signals.json"
    _write_json(json_path, stamped)

    md_path = out_dir / "tool_use_signals.md"
    md_path.write_text(
        _render_trace_signals_markdown(run_path, signals_by_eval, signal_count),
        encoding="utf-8",
    )

    print(f"wrote {json_path}")
    print(f"wrote {md_path}")
    eval_count = len([k for k, v in signals_by_eval.items() if v])
    print(f"signals: {signal_count} across {eval_count} eval(s)")
    return 0


def _replay_run(
    source_run: str,
    project_path: str,
    tools_path: str,
    evals_path: str,
    out: str,
) -> int:
    """用 TranscriptReplayAdapter 把一份历史 run 跑成完整的新 EvalRunner 闭环。

    架构边界：
    - **负责**：装配 TranscriptReplayAdapter + EvalRunner，让用户能用一条命令
      把任意历史 run 重新跑通 audit / judge / diagnose / report，得到一份新
      的 9-artifact 目录，但 Agent 行为严格来自源 run（recorded_trajectory）。
    - **不负责**：调用真实模型；调用真实工具（adapter 不调 registry.execute）；
      校验源 run 的字段级 schema（只在 adapter 构造时校验关键文件存在）。

    错误处理：
    - 源目录不存在 / 缺关键 JSONL → ``TranscriptReplaySourceError``，由 ``main``
      已有的 ``except FileNotFoundError`` 通道打印可行动 hint；
    - tools/evals/project 加载失败 → 沿用 ConfigError 通道。

    输出契约：
    - ``--out`` 目录写完整 9 个 artifact（与 ``run`` 命令对齐）；
    - ``metrics.json``/``report.md`` 顶部 ``signal_quality = recorded_trajectory``，
      明确告诉读者"这次的 PASS/FAIL 是 trajectory 复刻，不是当前 Agent 决策"；
    - stdout 打一行 JSON 摘要 ``{out_dir, metrics, source_run}``，便于 CI grep。
    """

    from agent_tool_harness.agents.transcript_replay_adapter import (
        TranscriptReplayAdapter,
    )

    tools = load_tools(tools_path)
    evals = load_evals(evals_path)
    _warn_if_empty(tools, "tools", tools_path)
    _warn_if_empty(evals, "evals", evals_path)

    adapter = TranscriptReplayAdapter(source_run)
    result = EvalRunner().run(
        load_project(project_path),
        tools,
        evals,
        adapter,
        out,
    )
    print(
        json.dumps(
            {
                "out_dir": result["out_dir"],
                "metrics": result["metrics"],
                "source_run": str(adapter.source_run_dir),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _render_trace_signals_markdown(
    run_dir: Path,
    signals_by_eval: dict[str, list[dict]],
    signal_count: int,
) -> str:
    """把 trace-derived signals 渲染成给人看的 Markdown。

    设计边界：
    - 只渲染信号本身，不重复 ``report.md`` 的其他段（avoid duplication）；
    - 显式声明 deterministic / 非 LLM Judge 的方法论披露，避免下游误读；
    - 没有信号时也输出完整骨架 + 一句"0 signals"，让 reviewer 一眼能确认
      "分析跑过了，只是真没信号"，而不是误以为命令失败。
    """

    lines: list[str] = []
    lines.append("# Trace-derived tool-use signals")
    lines.append("")
    lines.append(f"- analyzed run: `{run_dir}`")
    lines.append(f"- signal count: **{signal_count}**")
    lines.append(
        "- analysis kind: `trace_derived_deterministic_heuristic` "
        "(NOT an LLM Judge, NOT semantic proof)"
    )
    lines.append("")
    if signal_count == 0:
        lines.append(
            "_No deterministic trace-derived signals fired. 这并不证明工具响应一定健康——"
            "deterministic 启发式有边界（详见 `docs/ARCHITECTURE.md` Diagnose 段）。_"
        )
        lines.append("")
        return "\n".join(lines)

    for eval_id in sorted(signals_by_eval):
        signals = signals_by_eval[eval_id]
        if not signals:
            continue
        lines.append(f"## eval: `{eval_id}`")
        lines.append("")
        for sig in signals:
            related = sig.get("related_tool")
            related_part = f" (tool: `{related}`)" if related else ""
            lines.append(
                f"- [{sig.get('severity', '?')}] **{sig.get('signal_type', '?')}**"
                f"{related_part}"
            )
            why = sig.get("why_it_matters")
            if why:
                lines.append(f"  - why: {why}")
            fix = sig.get("suggested_fix")
            if fix:
                lines.append(f"  - suggested fix: {fix}")
            refs = sig.get("evidence_refs") or []
            if refs:
                lines.append(f"  - evidence: {', '.join(refs)}")
        lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
