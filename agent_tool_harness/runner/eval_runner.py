from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

from agent_tool_harness.agents.agent_adapter_base import AgentAdapter, AgentRunResult
from agent_tool_harness.artifact_schema import make_run_metadata, stamp_artifact
from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor
from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.project_spec import ProjectSpec
from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.diagnose.trace_signal_analyzer import TraceSignalAnalyzer
from agent_tool_harness.diagnose.transcript_analyzer import TranscriptAnalyzer
from agent_tool_harness.judges.provider import (
    PROVIDER_SCHEMA_VERSION,
    JudgeProvider,
    MissingRecordingError,
    ProviderJudgeResult,
)
from agent_tool_harness.judges.rule_judge import JudgeResult, RuleCheckResult, RuleJudge
from agent_tool_harness.recorder.run_recorder import RunRecorder
from agent_tool_harness.reports.cost_tracker import build_llm_cost_artifact
from agent_tool_harness.reports.markdown_report import MarkdownReport
from agent_tool_harness.signal_quality import UNKNOWN, describe
from agent_tool_harness.tools.registry import ToolRegistry


class EvalRunner:
    """Agent tool-use eval 编排器。

    架构边界：
    - 负责编排 Audit -> Run -> Record -> Judge -> Diagnose -> Report。
    - 不把用户项目逻辑写死；项目差异来自 ProjectSpec/ToolSpec/EvalSpec 和 adapter/executor。
    - 不直接调用真实模型；adapter 决定 Agent 行为。

    为什么这样拆：
    runner 是证据链路的中枢，但每个判断点都由独立模块负责。这样失败时可以定位是工具设计、
    eval 质量、Agent 路径、judge 规则还是报告呈现的问题。

    协作契约：
    - auditor 先产出设计证据，即使某些 eval 不 runnable，也要进入 audit_evals.json。
    - adapter 只能通过 ToolRegistry 调工具，并通过 RunRecorder 留下 raw transcript。
    - judge/analyzer 只消费已经记录的运行事实，不反向影响 Agent 路径。
    - report 只是汇总视图，不能替代 JSONL artifacts 作为一手证据。

    失败保全：
    runner 是最后一道 artifact 兜底。adapter 抛异常、registry 初始化失败或 eval 被 audit 判为
    不可运行时，runner 仍会写 metrics/judge_results/diagnosis/report，并在 transcript.jsonl
    中留下 runner 事件，方便真实团队复盘“为什么没有走到工具调用”。
    """

    REQUIRED_ARTIFACTS = [
        "transcript.jsonl",
        "tool_calls.jsonl",
        "tool_responses.jsonl",
        "metrics.json",
        "audit_tools.json",
        "audit_evals.json",
        "judge_results.json",
        "diagnosis.json",
        "report.md",
        # v1.6 第二项：LLM 成本聚合 artifact。永远生成（即使没配 dry-run
        # provider 也写出空 totals），让 reviewer "找不到 artifact" vs
        # "找到 artifact 但 totals 全 0" 两种状态可区分。
        "llm_cost.json",
    ]

    def __init__(
        self,
        *,
        tool_auditor: ToolDesignAuditor | None = None,
        eval_auditor: EvalQualityAuditor | None = None,
        judge: RuleJudge | None = None,
        analyzer: TranscriptAnalyzer | None = None,
        trace_signal_analyzer: TraceSignalAnalyzer | None = None,
        report: MarkdownReport | None = None,
        dry_run_provider: JudgeProvider | None = None,
    ):
        self.tool_auditor = tool_auditor or ToolDesignAuditor()
        self.eval_auditor = eval_auditor or EvalQualityAuditor()
        self.judge = judge or RuleJudge()
        self.analyzer = analyzer or TranscriptAnalyzer()
        # trace_signal_analyzer 在每次 run 中需要按 ToolSpec 列表重建索引；这里
        # 允许调用方注入实例（测试可注入空实例），但实际 tools_by_name 索引在
        # ``run`` 中再装配——避免构造期就必须知道 tools。
        self._trace_signal_analyzer_override = trace_signal_analyzer
        self.report = report or MarkdownReport()
        # v1.1 第二轮：可选 dry-run JudgeProvider。**绝不**改变 deterministic
        # baseline——`self.judge` 始终是 ground truth；这里写入的结果只作为旁路
        # metadata 落到 ``judge_results.json::dry_run_provider``，让未来真实 LLM
        # judge 落地时只换 provider 实现，不影响现有契约。None 表示走纯 v1.0 路径。
        self.dry_run_provider = dry_run_provider

    def run(
        self,
        project: ProjectSpec,
        tools: list[ToolSpec],
        evals: list[EvalSpec],
        adapter: AgentAdapter,
        out_dir: str | Path,
    ) -> dict[str, Any]:
        """运行一批 eval 并尽量写完整 artifacts。

        这个方法不把“抛异常”当作停止记录的理由。真实 Agent 团队最需要的是失败现场，
        因此这里会把 adapter 异常、registry 初始化错误和 audit-runnable skip 都转成
        judge/diagnosis 结果，而不是让调用栈直接结束。
        """

        recorder = RunRecorder(out_dir)
        # 把 adapter 自报的信号质量提前抓出来，无论后续 audit/adapter 走哪条分支，metrics
        # 与 report 都能稳定地告诉用户“这次 run 的 PASS/FAIL 信号是什么级别”。
        signal_quality = str(getattr(adapter, "SIGNAL_QUALITY", UNKNOWN))
        # v0.2 第三轮：构造 trace-derived 信号分析器索引。这里同时按短名 / qualified
        # name 注册 ToolSpec，让 mock_replay_adapter（短名）和未来真实 adapter
        # （qualified name）都能命中契约 lookup。索引在每次 run 内只建一次，
        # 后面在每条 eval diagnosis 后调用 analyzer.analyze_eval。
        tools_by_name: dict[str, ToolSpec] = {}
        for tool in tools:
            tools_by_name[tool.name] = tool
            if tool.qualified_name and tool.qualified_name != tool.name:
                tools_by_name[tool.qualified_name] = tool
        trace_analyzer = self._trace_signal_analyzer_override or TraceSignalAnalyzer(
            tools_by_name
        )
        # 先审计契约，再运行 Agent。这样即使运行失败，也能区分是工具/eval 设计问题
        # 还是 Agent tool-use 路径问题。
        audit_tools = self.tool_auditor.audit(tools)
        audit_evals = self.eval_auditor.audit(evals)
        runnable_by_eval = self._runnable_by_eval(audit_evals)
        # 把 audit 结果索引成 analyzer 直接消费的形态：
        # - audit_eval_findings_by_id：{eval_id: [finding, ...]}，让 analyzer 能识别
        #   weak_eval_definition；
        # - audit_tool_findings_by_name：{tool_name: [finding, ...]}（同时按 namespace.name
        #   注册），让 analyzer 能识别 audit_signal_low。
        # 索引在这里集中做一次，避免 analyzer 反复 O(n*m) 扫整份 audit 输出。
        audit_eval_findings_by_id = {
            str(item.get("eval_id")): list(item.get("findings", []) or [])
            for item in audit_evals.get("evals", [])
        }
        audit_tool_findings_by_name: dict[str, list[dict[str, Any]]] = {}
        for item in audit_tools.get("tools", []):
            findings = list(item.get("findings", []) or [])
            short = str(item.get("tool_name", ""))
            qualified = str(item.get("qualified_name", ""))
            if short:
                audit_tool_findings_by_name.setdefault(short, []).extend(findings)
            if qualified and qualified != short:
                audit_tool_findings_by_name.setdefault(qualified, []).extend(findings)

        judge_results = []
        diagnoses = []
        run_results = []
        # v1.1 第二轮：dry_run_results 与 judge_results 一一对应（按 evals 顺序）；
        # 当未配置 provider 时为空列表，意味着 ``judge_results.json`` 不会出现
        # ``dry_run_provider`` 字段，与 v1.0 完全字节兼容。
        dry_run_results: list[dict[str, Any]] = []
        skipped = 0
        errors = 0
        try:
            registry = ToolRegistry(tools)
        except Exception as exc:  # noqa: BLE001 - registry 初始化失败也必须转成 artifacts。
            errors = len(evals)
            for case in evals:
                recorder.record_transcript(
                    case.id,
                    {
                        "role": "system",
                        "type": "runner_error",
                        "content": "ToolRegistry initialization failed before adapter run.",
                        "metadata": {
                            "error": str(exc),
                            "traceback": traceback.format_exc(limit=5),
                        },
                    },
                )
                run_result = AgentRunResult(case.id, "", [], [])
                judge_result = self._error_judge_result(
                    case.id,
                    "tool_registry_initialization_failed",
                    str(exc),
                )
                judge_results.append(judge_result.to_dict())
                _dry = self._invoke_dry_run_provider(case, run_result, judge_result.passed)
                if _dry is not None:
                    dry_run_results.append(_dry)
                diagnoses.append(
                    self._diagnose(
                        case,
                        run_result,
                        judge_result,
                        audit_eval_findings_by_id,
                        audit_tool_findings_by_name,
                        trace_analyzer,
                    )
                )
            return self._write_artifacts(
                project,
                evals,
                run_results,
                judge_results,
                diagnoses,
                audit_tools,
                audit_evals,
                recorder,
                skipped=0,
                errors=errors,
                signal_quality=signal_quality,
                dry_run_results=dry_run_results,
            )

        for case in evals:
            if not runnable_by_eval.get(case.id, case.runnable):
                skipped += 1
                # 不 runnable 的 eval 不进入执行阶段，但仍已在 audit_evals.json 中留下
                # 转正所需的 missing_context/finding 证据。这里额外写 runner_skip，让用户能
                # 在 transcript 中看到“为什么没有 tool call”。
                recorder.record_transcript(
                    case.id,
                    {
                        "role": "system",
                        "type": "runner_skip",
                        "content": (
                            "Eval skipped because EvalQualityAuditor marked it not runnable."
                        ),
                    },
                )
                run_result = AgentRunResult(case.id, "", [], [])
                judge_result = self._error_judge_result(
                    case.id,
                    "eval_not_runnable",
                    "EvalQualityAuditor marked this eval as not runnable.",
                )
                judge_results.append(judge_result.to_dict())
                _dry = self._invoke_dry_run_provider(case, run_result, judge_result.passed)
                if _dry is not None:
                    dry_run_results.append(_dry)
                diagnoses.append(
                    self._diagnose(
                        case,
                        run_result,
                        judge_result,
                        audit_eval_findings_by_id,
                        audit_tool_findings_by_name,
                        trace_analyzer,
                    )
                )
                continue
            try:
                recorder.record_transcript(
                    case.id,
                    {
                        "role": "system",
                        "type": "runner_start",
                        "content": "EvalRunner is starting adapter execution.",
                    },
                )
                run_result = adapter.run(case, registry, recorder)
            except Exception as exc:  # noqa: BLE001 - adapter 失败必须保留 partial transcript。
                errors += 1
                recorder.record_transcript(
                    case.id,
                    {
                        "role": "system",
                        "type": "runner_error",
                        "content": "Adapter execution failed; preserving partial run artifacts.",
                        "metadata": {
                            "error": str(exc),
                            "traceback": traceback.format_exc(limit=5),
                        },
                    },
                )
                run_result = self._partial_run_result(case, recorder)
                run_results.append(run_result)
                judge_result = self._error_judge_result(
                    case.id,
                    "adapter_execution_failed",
                    str(exc),
                )
                judge_results.append(judge_result.to_dict())
                _dry = self._invoke_dry_run_provider(case, run_result, judge_result.passed)
                if _dry is not None:
                    dry_run_results.append(_dry)
                diagnoses.append(
                    self._diagnose(
                        case,
                        run_result,
                        judge_result,
                        audit_eval_findings_by_id,
                        audit_tool_findings_by_name,
                        trace_analyzer,
                    )
                )
                continue
            run_results.append(run_result)
            judge_result = self.judge.judge(case, run_result)
            judge_results.append(judge_result.to_dict())
            _dry = self._invoke_dry_run_provider(case, run_result, judge_result.passed)
            if _dry is not None:
                dry_run_results.append(_dry)
            diagnoses.append(
                self._diagnose(
                    case,
                    run_result,
                    judge_result,
                    audit_eval_findings_by_id,
                    audit_tool_findings_by_name,
                    trace_analyzer,
                )
            )

        return self._write_artifacts(
            project,
            evals,
            run_results,
            judge_results,
            diagnoses,
            audit_tools,
            audit_evals,
            recorder,
            skipped=skipped,
            errors=errors,
            signal_quality=signal_quality,
            dry_run_results=dry_run_results,
        )

    def _write_artifacts(
        self,
        project: ProjectSpec,
        evals: list[EvalSpec],
        run_results: list[AgentRunResult],
        judge_results: list[dict[str, Any]],
        diagnoses: list[dict[str, Any]],
        audit_tools: dict[str, Any],
        audit_evals: dict[str, Any],
        recorder: RunRecorder,
        *,
        skipped: int,
        errors: int,
        signal_quality: str = UNKNOWN,
        dry_run_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """统一写最终 artifacts。

        所有成功、跳过和异常路径都走这里，避免某条异常路径漏写 report 或 JSON。这里写的是
        派生 artifacts；raw transcript/tool_calls/tool_responses 已经由 recorder 在运行中追加。

        ``signal_quality`` 来自 adapter 的自我披露，它会被同时写入 ``metrics.json`` 和
        ``report.md`` 的顶部 banner，让真实团队不会把 mock PASS 当成评估信号。
        """

        metrics = self._metrics(
            evals,
            run_results,
            judge_results,
            skipped=skipped,
            errors=errors,
            signal_quality=signal_quality,
            dry_run_results=dry_run_results,
        )
        judge_payload = {"results": judge_results}
        # v1.1 第二轮：仅在配置了 dry-run provider 且确实有结果时，才在
        # judge_results.json 顶层多加一个 ``dry_run_provider`` 数组——
        # 没配置时字段不存在，与 v1.0 完全字节兼容（schema "只增不删"承诺）。
        # 这里**绝不**用 dry-run 的 PASS/FAIL 覆盖 ``results[].passed``；
        # ``results`` 永远是 deterministic ground truth，``dry_run_provider``
        # 只是旁路 metadata 供 report.md / 用户复盘消费。
        if dry_run_results:
            judge_payload["dry_run_provider"] = {
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "results": dry_run_results,
            }
        diagnosis_payload = {"results": diagnoses}
        project_payload = {
            "name": project.name,
            "domain": project.domain,
            "description": project.description,
        }
        # P1：给所有派生 JSON artifact 打 schema_version + run_metadata 戳。
        # 设计选择：戳是**新增顶层 key**，不会包裹原有结构（详见 artifact_schema.py
        # 注释）；同一 run 内所有 artifact 共享同一份 run_metadata，下游可以靠
        # ``run_metadata.run_id`` 把 5 份 JSON 串起来复盘同一次 run。
        # raw JSONL（transcript / tool_calls / tool_responses）不打戳——它们是
        # 事件流，逐行独立；其字段约定由 docs/ARTIFACTS.md + 本 schema_version 共同
        # 表达。
        run_metadata = make_run_metadata(
            project_name=project.name,
            eval_count=len(evals),
            extra={"command": "run", "signal_quality": signal_quality},
        )
        recorder.write_json("metrics.json", stamp_artifact(metrics, run_metadata=run_metadata))
        recorder.write_json(
            "audit_tools.json", stamp_artifact(audit_tools, run_metadata=run_metadata)
        )
        recorder.write_json(
            "audit_evals.json", stamp_artifact(audit_evals, run_metadata=run_metadata)
        )
        recorder.write_json(
            "judge_results.json", stamp_artifact(judge_payload, run_metadata=run_metadata)
        )
        recorder.write_json(
            "diagnosis.json", stamp_artifact(diagnosis_payload, run_metadata=run_metadata)
        )
        # v1.6 第二项：聚合 dry_run_results 写 llm_cost.json。即使
        # dry_run_results 为 None 也生成空 totals，统一 reviewer 心智。
        llm_cost = build_llm_cost_artifact(dry_run_results)
        recorder.write_json(
            "llm_cost.json", stamp_artifact(llm_cost, run_metadata=run_metadata)
        )
        recorder.write_text(
            "report.md",
            self.report.render(
                project=project_payload,
                metrics=metrics,
                audit_tools=audit_tools,
                audit_evals=audit_evals,
                judge_results=judge_payload,
                diagnosis=diagnosis_payload,
                llm_cost=llm_cost,
            ),
        )
        return {
            "out_dir": str(recorder.out_dir),
            "metrics": metrics,
            "audit_tools": audit_tools,
            "audit_evals": audit_evals,
            "judge_results": judge_payload,
            "diagnosis": diagnosis_payload,
            "llm_cost": llm_cost,
            "artifacts": self.REQUIRED_ARTIFACTS,
            "run_metadata": run_metadata,
        }

    def _metrics(
        self,
        evals: list[EvalSpec],
        run_results: list[AgentRunResult],
        judge_results: list[dict[str, Any]],
        *,
        skipped: int = 0,
        errors: int = 0,
        signal_quality: str = UNKNOWN,
        dry_run_results: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """计算运行统计。

        `failed` 统计 judge 层面的未通过结果；`error_evals` 额外标出 runner/adapter 异常，
        这样报告能区分“模型路径错误”和“执行链路异常”。

        `signal_quality` / `signal_quality_note` 是与 Anthropic 文章方法论差距的显式标记：
        当前 adapter 是 MockReplayAdapter 时，它会被写为 ``tautological_replay``，提醒读者
        PASS 不能被解读为“工具对真实 Agent 好用”。这是 MVP 阶段的诚实披露，不是评分。

        v1.x 新增 ``judge_disagreement``：仅当配置了 dry-run JudgeProvider 时
        出现，统计 advisory provider 与 deterministic baseline 的分歧情况
        （total/agree/disagree/error/disagreement_rate）。**永远**不会改变
        ``passed/failed`` 计数——deterministic baseline 仍是 ground truth；
        分歧率只是诊断信号，让用户能定量看到"如果未来接真实 LLM judge，
        会和当前 deterministic 偏离多少"。
        """

        passed = sum(1 for result in judge_results if result.get("passed"))
        failed = len(judge_results) - passed
        tool_calls = sum(len(result.tool_calls) for result in run_results)
        metrics: dict[str, Any] = {
            "total_evals": len(evals),
            "runnable_evals": len(evals) - skipped,
            "executed_evals": len(run_results),
            "skipped_evals": skipped,
            "error_evals": errors,
            "passed": passed,
            "failed": failed,
            "total_tool_calls": tool_calls,
            "signal_quality": signal_quality,
            "signal_quality_note": describe(signal_quality),
        }
        if dry_run_results:
            # 只统计有 ``passed`` 字段的 entry——``error`` entry（缺 recording /
            # provider 异常）独立计数，避免把异常伪装成"分歧"或"一致"。
            agree = 0
            disagree = 0
            error = 0
            for entry in dry_run_results:
                if "error" in entry:
                    error += 1
                    continue
                # Composite 透传 deterministic 给 ProviderJudgeResult.passed，
                # 因此它的 ``agrees_with_deterministic`` 恒为 True；真实的
                # advisory vs deterministic 分歧记录在 ``entry.agreement``。
                # 这里优先读 ``agreement``（Composite 路径），缺失时回落到
                # ``agrees_with_deterministic``（直接挂 RecordedJudgeProvider
                # 的路径）——保证两种 provider 都能产生有意义的分歧率。
                # v1.3 多 advisory 模式下 ``agreement`` 可能为 ``None``
                # （平票或全 error），此时**不计入**任何 agree/disagree 桶，
                # 改记 ``error`` 桶——避免 ``bool(None) == False`` 被误算成
                # disagree（这是反吞异常假成功的关键路径）。
                if "agreement" in entry:
                    raw_agreement = entry["agreement"]
                    if raw_agreement is None:
                        error += 1
                        continue
                    is_agree = bool(raw_agreement)
                else:
                    is_agree = bool(entry.get("agrees_with_deterministic"))
                if is_agree:
                    agree += 1
                else:
                    disagree += 1
            decided = agree + disagree
            disagreement_rate = (disagree / decided) if decided else None
            metrics["judge_disagreement"] = {
                "schema_version": PROVIDER_SCHEMA_VERSION,
                "total": len(dry_run_results),
                "agree": agree,
                "disagree": disagree,
                "error": error,
                "disagreement_rate": disagreement_rate,
            }
        return metrics

    def _invoke_dry_run_provider(
        self,
        case: EvalSpec,
        run_result: AgentRunResult,
        deterministic_passed: bool,
    ) -> dict[str, Any] | None:
        """调用 dry-run JudgeProvider 并把结果序列化成 artifact 子条目。

        本方法负责什么
        --------------
        - 把 ``ProviderJudgeResult`` 转成可直接写入 ``judge_results.json::
          dry_run_provider`` 的 dict；
        - 显式记录 ``deterministic_passed``，让 artifact 读者一眼看出
          provider 是否与 deterministic baseline 一致——但 provider 的
          PASS/FAIL **绝不**会覆盖 ``results[].passed`` 字段；
        - 捕获 :class:`MissingRecordingError` 等可行动错误，写成结构化
          ``error`` 字段，**不**静默成 PASS（任何"recording 缺失就静默
          通过"都是吞异常假成功反模式）。

        本方法**不**负责什么
        --------------------
        - 不调用 deterministic RuleJudge；
        - 不修改 ``self.judge`` 的输出；
        - 不发起任何网络/外部 API 调用——这一点由 provider 实现自己保证，
          v1.1 第一轮契约测试已钉死所有现存 provider 都不开 socket。

        返回 ``None`` 表示未配置 dry-run provider；返回 dict 表示有结果
        （含成功 / 失败两种）。
        """

        provider = self.dry_run_provider
        if provider is None:
            return None
        entry: dict[str, Any] = {
            "eval_id": case.id,
            "provider": getattr(provider, "name", "unknown"),
            "mode": getattr(provider, "mode", "unknown"),
            "schema_version": PROVIDER_SCHEMA_VERSION,
            "deterministic_passed": deterministic_passed,
        }
        try:
            result: ProviderJudgeResult = provider.judge(case, run_result)
        except MissingRecordingError as exc:
            entry["error"] = {
                "type": "missing_recording",
                "message": str(exc),
            }
            return entry
        except Exception as exc:  # noqa: BLE001 - dry-run 不应阻塞 deterministic 主路径。
            entry["error"] = {
                "type": "provider_error",
                "message": str(exc),
                "traceback": traceback.format_exc(limit=5),
            }
            return entry
        # v1.x AnthropicCompatibleJudgeProvider：当 provider **返回**带
        # ``error_code`` 的结果（而不是抛异常）时，把它转成与"provider 抛异常"
        # 同构的结构化 ``entry.error`` 路径——避免：
        # 1) ``passed=False`` 被 metrics.judge_disagreement 误计为"分歧"；
        # 2) provider 已脱敏的 ``error_message`` 被 entry["passed"] 喧宾夺主。
        # 这一步**不**重新调用 provider，只读已落到 result.extra 的字段。
        error_code = result.extra.get("error_code") if hasattr(result, "extra") else None
        if error_code:
            entry["error"] = {
                "type": str(error_code),
                "message": str(result.extra.get("error_message", "")),
            }
            # ``model`` 在错误路径下也会落到 entry，便于排查"是哪个模型配置缺失"；
            # 但**不**包含 base_url / api_key——脱敏由 provider 保证。
            if result.extra.get("model") is not None:
                entry["model"] = result.extra["model"]
            return entry
        entry["passed"] = result.passed
        entry["agrees_with_deterministic"] = bool(result.passed) == bool(
            deterministic_passed
        )
        meta = result.metadata()
        for key in ("rationale", "confidence", "rubric"):
            value = meta.get(key)
            if value is not None:
                entry[key] = value
        # v1.x CompositeJudgeProvider：把 ``extra`` 中的 advisory_result /
        # deterministic_result / agreement 等结构化字段也写进 artifact，
        # 让 metrics.json::judge_disagreement 与 report.md 能直接消费——
        # 而不需要重新调用 provider 反推。这里只搬已知键，避免 provider 实现
        # 不小心把 raw API 响应等敏感字段（潜在 key/PII）泄漏到 artifact。
        # v1.3 多 advisory：新增 ``advisory_results`` (list)、``majority_passed``、
        # ``vote_distribution`` 三个聚合字段；与单 advisory 字段并存（CLI 通常
        # 二选一，不会同时出现）。
        for key in (
            "agreement",
            "advisory_result",
            "advisory_results",
            "majority_passed",
            "vote_distribution",
            "deterministic_result",
            "model",
            # v1.6 第一/二项：retry/backoff 治理证据 + token usage 透传，
            # 让 ``llm_cost.json`` 与 ``report.md`` 能直接消费而不需要反推。
            "attempts_summary",
            "retry_count",
            "usage",
        ):
            if key in result.extra:
                entry[key] = result.extra[key]
        return entry

    def _diagnose(
        self,
        case: EvalSpec,
        run_result: AgentRunResult,
        judge_result: JudgeResult,
        audit_eval_findings_by_id: dict[str, list[dict[str, Any]]],
        audit_tool_findings_by_name: dict[str, list[dict[str, Any]]],
        trace_analyzer: TraceSignalAnalyzer,
    ) -> dict[str, Any]:
        """聚合 TranscriptAnalyzer + TraceSignalAnalyzer 的复盘输出。

        架构边界：
        - **负责**：在每条 eval 复盘点合成两类证据——rule-derived findings
          （来自 TranscriptAnalyzer，消费 judge.checks）+ artifact-derived
          tool_use_signals（来自 TraceSignalAnalyzer，消费 raw payload 与
          ToolSpec.output_contract）。两类信号并存写入同一份 diagnosis 记录。
        - **不负责**：不重新执行工具、不修改 judge 结果、不调 LLM。

        为什么并存而不是合并：两层来源不同，证据语义不同。如果合并到一个
        ``findings`` 列表，下游消费者会失去"信号属于规则失败 / 还是 contract
        没满足"的区分。把 trace signals 放在新字段 ``tool_use_signals``，
        旧字段 ``findings`` 完全不变，向后兼容（artifact_schema 保持
        "只增不删"承诺）。

        失败保全：trace_analyzer.analyze_eval 抛异常时不应让 diagnosis 整体
        失败——这里捕获并塞入空列表 + 一条 info 信号，确保 diagnosis.json
        不会因一条规则的 bug 缺失整个 eval 的复盘视图。
        """

        diagnosis = self.analyzer.analyze(
            case,
            run_result,
            judge_result,
            audit_eval_findings=audit_eval_findings_by_id.get(case.id),
            audit_tool_findings=audit_tool_findings_by_name,
        )
        try:
            signals = trace_analyzer.analyze_eval(
                eval_id=case.id,
                user_prompt=case.user_prompt,
                tool_calls=run_result.tool_calls,
                tool_responses=run_result.tool_responses,
            )
        except Exception as exc:  # noqa: BLE001
            signals = [
                {
                    "signal_type": "signal_extraction_error",
                    "severity": "info",
                    "evidence_refs": [
                        f"diagnosis.json#eval_id={case.id} stage=trace_signal_analyzer",
                    ],
                    "related_tool": None,
                    "related_eval": case.id,
                    "why_it_matters": (
                        "TraceSignalAnalyzer 在本条 eval 上抛了异常；"
                        "其他归因仍可信，但这条信号缺失。"
                    ),
                    "suggested_fix": (
                        f"复盘 raw artifacts 后给 trace_signal_analyzer 提 issue；异常: {exc}"
                    ),
                }
            ]
        diagnosis["tool_use_signals"] = signals
        return diagnosis

    def _runnable_by_eval(self, audit_evals: dict[str, Any]) -> dict[str, bool]:
        """从 EvalQualityAuditor 输出中提取执行闸门。

        runner 不重新实现 eval 质量判断，而是消费 auditor 的结果。这样“是否 runnable”只有一个
        来源，避免 audit 判不可运行但 runner 仍执行的治理漏洞。
        """

        return {
            str(item.get("eval_id")): bool(item.get("runnable"))
            for item in audit_evals.get("evals", [])
        }

    def _error_judge_result(self, eval_id: str, rule_type: str, message: str) -> JudgeResult:
        """把 runner 级异常转成 JudgeResult。

        这不是把异常伪装成模型判断，而是为了让 judge_results.json 始终有结构化失败原因。
        """

        return JudgeResult(
            eval_id=eval_id,
            passed=False,
            checks=[
                RuleCheckResult(
                    rule={"type": rule_type},
                    passed=False,
                    message=message,
                )
            ],
        )

    def _partial_run_result(self, case: EvalSpec, recorder: RunRecorder) -> AgentRunResult:
        """从已落盘 JSONL 中恢复 adapter 抛错前的部分调用事实。

        adapter 可能已经写入若干 tool_call/tool_response 后才失败。这里读取 recorder 中同一 eval
        的部分证据，交给 judge/diagnosis 使用，避免异常路径把已发生的工具调用丢掉。
        """

        tool_calls = [
            call
            for call in recorder.read_jsonl("tool_calls.jsonl")
            if call.get("eval_id") == case.id
        ]
        tool_responses = [
            response
            for response in recorder.read_jsonl("tool_responses.jsonl")
            if response.get("eval_id") == case.id
        ]
        return AgentRunResult(
            eval_id=case.id,
            final_answer="",
            tool_calls=tool_calls,
            tool_responses=tool_responses,
        )
