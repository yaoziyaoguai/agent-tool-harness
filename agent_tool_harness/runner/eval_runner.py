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
from agent_tool_harness.judges.rule_judge import JudgeResult, RuleCheckResult, RuleJudge
from agent_tool_harness.recorder.run_recorder import RunRecorder
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
        )
        judge_payload = {"results": judge_results}
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
        recorder.write_text(
            "report.md",
            self.report.render(
                project=project_payload,
                metrics=metrics,
                audit_tools=audit_tools,
                audit_evals=audit_evals,
                judge_results=judge_payload,
                diagnosis=diagnosis_payload,
            ),
        )
        return {
            "out_dir": str(recorder.out_dir),
            "metrics": metrics,
            "audit_tools": audit_tools,
            "audit_evals": audit_evals,
            "judge_results": judge_payload,
            "diagnosis": diagnosis_payload,
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
    ) -> dict[str, Any]:
        """计算运行统计。

        `failed` 统计 judge 层面的未通过结果；`error_evals` 额外标出 runner/adapter 异常，
        这样报告能区分“模型路径错误”和“执行链路异常”。

        `signal_quality` / `signal_quality_note` 是与 Anthropic 文章方法论差距的显式标记：
        当前 adapter 是 MockReplayAdapter 时，它会被写为 ``tautological_replay``，提醒读者
        PASS 不能被解读为“工具对真实 Agent 好用”。这是 MVP 阶段的诚实披露，不是评分。
        """

        passed = sum(1 for result in judge_results if result.get("passed"))
        failed = len(judge_results) - passed
        tool_calls = sum(len(result.tool_calls) for result in run_results)
        return {
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
