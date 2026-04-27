from __future__ import annotations

import traceback
from pathlib import Path
from typing import Any

from agent_tool_harness.agents.agent_adapter_base import AgentAdapter, AgentRunResult
from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor
from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.project_spec import ProjectSpec
from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.diagnose.transcript_analyzer import TranscriptAnalyzer
from agent_tool_harness.judges.rule_judge import JudgeResult, RuleCheckResult, RuleJudge
from agent_tool_harness.recorder.run_recorder import RunRecorder
from agent_tool_harness.reports.markdown_report import MarkdownReport
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
        report: MarkdownReport | None = None,
    ):
        self.tool_auditor = tool_auditor or ToolDesignAuditor()
        self.eval_auditor = eval_auditor or EvalQualityAuditor()
        self.judge = judge or RuleJudge()
        self.analyzer = analyzer or TranscriptAnalyzer()
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
        # 先审计契约，再运行 Agent。这样即使运行失败，也能区分是工具/eval 设计问题
        # 还是 Agent tool-use 路径问题。
        audit_tools = self.tool_auditor.audit(tools)
        audit_evals = self.eval_auditor.audit(evals)
        runnable_by_eval = self._runnable_by_eval(audit_evals)

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
                diagnoses.append(self.analyzer.analyze(case, run_result, judge_result))
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
                diagnoses.append(self.analyzer.analyze(case, run_result, judge_result))
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
                diagnoses.append(self.analyzer.analyze(case, run_result, judge_result))
                continue
            run_results.append(run_result)
            judge_result = self.judge.judge(case, run_result)
            judge_results.append(judge_result.to_dict())
            diagnoses.append(self.analyzer.analyze(case, run_result, judge_result))

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
    ) -> dict[str, Any]:
        """统一写最终 artifacts。

        所有成功、跳过和异常路径都走这里，避免某条异常路径漏写 report 或 JSON。这里写的是
        派生 artifacts；raw transcript/tool_calls/tool_responses 已经由 recorder 在运行中追加。
        """

        metrics = self._metrics(evals, run_results, judge_results, skipped=skipped, errors=errors)
        judge_payload = {"results": judge_results}
        diagnosis_payload = {"results": diagnoses}
        project_payload = {
            "name": project.name,
            "domain": project.domain,
            "description": project.description,
        }
        recorder.write_json("metrics.json", metrics)
        recorder.write_json("audit_tools.json", audit_tools)
        recorder.write_json("audit_evals.json", audit_evals)
        recorder.write_json("judge_results.json", judge_payload)
        recorder.write_json("diagnosis.json", diagnosis_payload)
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
        }

    def _metrics(
        self,
        evals: list[EvalSpec],
        run_results: list[AgentRunResult],
        judge_results: list[dict[str, Any]],
        *,
        skipped: int = 0,
        errors: int = 0,
    ) -> dict[str, Any]:
        """计算运行统计。

        `failed` 统计 judge 层面的未通过结果；`error_evals` 额外标出 runner/adapter 异常，
        这样报告能区分“模型路径错误”和“执行链路异常”。
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
        }

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
