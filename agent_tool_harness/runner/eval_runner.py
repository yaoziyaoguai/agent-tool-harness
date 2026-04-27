from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_tool_harness.agents.agent_adapter_base import AgentAdapter
from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor
from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.project_spec import ProjectSpec
from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.diagnose.transcript_analyzer import TranscriptAnalyzer
from agent_tool_harness.judges.rule_judge import RuleJudge
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
        recorder = RunRecorder(out_dir)
        registry = ToolRegistry(tools)
        audit_tools = self.tool_auditor.audit(tools)
        audit_evals = self.eval_auditor.audit(evals)

        judge_results = []
        diagnoses = []
        run_results = []
        for case in evals:
            if not case.runnable:
                continue
            run_result = adapter.run(case, registry, recorder)
            run_results.append(run_result)
            judge_result = self.judge.judge(case, run_result)
            judge_results.append(judge_result.to_dict())
            diagnoses.append(self.analyzer.analyze(case, run_result, judge_result))

        metrics = self._metrics(evals, run_results, judge_results)
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
            "out_dir": str(Path(out_dir)),
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
        run_results: list[Any],
        judge_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        passed = sum(1 for result in judge_results if result.get("passed"))
        failed = len(judge_results) - passed
        tool_calls = sum(len(result.tool_calls) for result in run_results)
        return {
            "total_evals": len(evals),
            "runnable_evals": sum(1 for case in evals if case.runnable),
            "executed_evals": len(run_results),
            "passed": passed,
            "failed": failed,
            "total_tool_calls": tool_calls,
        }
