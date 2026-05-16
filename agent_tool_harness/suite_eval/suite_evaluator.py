"""SuiteEvaluator —— v3.3 suite 级评测编排。

架构边界
--------
- **负责**：加载 EvalSuite manifest 引用的 case/trace 文件，
  逐个 case 调用 TaskEvaluator，聚合为 SuiteResult。
- **不负责**：不做报告渲染、不修改 v3.1/v3.2 对象、不定义聚合逻辑
  （那是 suite_result.py 的事）。
"""

from __future__ import annotations

from collections.abc import Callable

from agent_tool_harness.core_contract import ExecutionTrace
from agent_tool_harness.suite_eval.eval_suite import EvalSuite, TraceInputRef
from agent_tool_harness.suite_eval.suite_result import (
    CaseResult,
    SuiteResult,
    aggregate_suite_results,
)
from agent_tool_harness.task_eval.task_evaluator import TaskEvaluator

# trace_loader 签名：接收 trace_path，返回 ExecutionTrace
TraceLoader = Callable[[str], ExecutionTrace]


class SuiteEvaluator:
    """suite 级评测编排器。

    逐个 case 评测：加载 EvalCase + ExecutionTrace → TaskEvaluator → TaskOutcome
    → CaseResult → aggregate_suite_results() → SuiteResult。

    用法::

        evaluator = SuiteEvaluator()
        result = evaluator.evaluate(suite, task_evaluator, trace_loader)
    """

    def evaluate(
        self,
        suite: EvalSuite,
        task_evaluator: TaskEvaluator,
        trace_loader: TraceLoader,
    ) -> SuiteResult:
        """运行 suite 中的所有 eval case，聚合返回 SuiteResult。

        Args:
            suite: EvalSuite manifest。
            task_evaluator: TaskEvaluator 实例。
            trace_loader: 接收 trace_path → ExecutionTrace 的可调用对象。

        Returns:
            聚合后的 SuiteResult。
        """
        case_results: list[CaseResult] = []
        case_map = {c.case_id: c for c in suite.cases}

        for trace_ref in suite.trace_inputs:
            case_ref = case_map.get(trace_ref.case_id)
            if case_ref is None:
                # trace 引用了 suite 中没有的 case_id——跳过
                continue

            case_result = self._evaluate_one(
                case_path=case_ref.case_path,
                trace_ref=trace_ref,
                task_evaluator=task_evaluator,
                trace_loader=trace_loader,
            )
            case_results.append(case_result)

        return aggregate_suite_results(suite.suite_id, case_results)

    # ------------------------------------------------------------------
    # 单个 case + trace 评测
    # ------------------------------------------------------------------

    @staticmethod
    def _evaluate_one(
        case_path: str,
        trace_ref: TraceInputRef,
        task_evaluator: TaskEvaluator,
        trace_loader: TraceLoader,
    ) -> CaseResult:
        """加载一个 EvalCase + ExecutionTrace，评测并返回 CaseResult。"""
        from agent_tool_harness.task_eval.eval_case import load_eval_case_from_yaml

        eval_case = load_eval_case_from_yaml(case_path)
        trace = trace_loader(trace_ref.trace_path)

        # 运行 task-level 评测
        outcome = task_evaluator.evaluate(eval_case, trace)

        # 从 trace 提取指标摘要
        tool_call_count = len(trace.tool_calls)
        tool_error_count = sum(
            1 for r in trace.tool_results if r.status == "error"
        )

        # finding 统计——从 outcome.verifier_results 聚合
        error_count = 0
        warning_count = 0
        for vr in outcome.verifier_results:
            if not vr.passed:
                error_count += 1

        finding_count = error_count + warning_count
        # 从 trace 层面获取 deterministic_passed——如果 trace
        # 有 evaluation_result 则使用，否则默认为 task 级别 passed
        deterministic_passed = getattr(trace, "_evaluation_passed", None)
        if deterministic_passed is None:
            deterministic_passed = outcome.status == "success"

        return CaseResult(
            case_id=trace_ref.case_id,
            trace_ref=trace_ref.trace_path,
            task_status=outcome.status,
            deterministic_passed=bool(deterministic_passed),
            finding_count=finding_count,
            error_count=error_count,
            warning_count=warning_count,
            metrics_summary={
                "tool_call_count": tool_call_count,
                "tool_error_count": tool_error_count,
                "tool_result_count": len(trace.tool_results),
                "final_answer_length": len(outcome.final_answer),
                "finding_count_by_tool": _count_findings_by_tool(trace),
                "finding_count_by_category": {},
            },
        )


def _count_findings_by_tool(trace: ExecutionTrace) -> dict[str, int]:
    """统计每个 tool 的错误调用次数。"""
    counts: dict[str, int] = {}
    for tc in trace.tool_calls:
        tool_name = tc.tool_name or "unknown"
        counts[tool_name] = counts.get(tool_name, 0) + 1
    return counts
