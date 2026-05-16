"""SuiteResult / SuiteMetrics / SuiteScorecard / CaseResult —— v3.3 聚合结果。

架构边界
--------
- **负责**：定义 suite-level 聚合数据结构（CaseResult, SuiteMetrics,
  SuiteScorecard, SuiteResult）和聚合函数。
- **不负责**：不加载 EvalCase 或 trace 文件（由 SuiteEvaluator 负责）、
  不做报告渲染、不修改任何 v3.1/v3.2 对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CaseResult:
    """单个 case 的评测结果摘要。

    不复制完整的 TaskOutcome / EvaluationResult——只存聚合需要的摘要字段。
    """

    case_id: str
    """EvalCase.case_id。"""

    trace_ref: str
    """trace 文件路径或标识。"""

    task_status: str
    """TaskOutcome.status: success | failed | inconclusive。"""

    deterministic_passed: bool
    """EvaluationResult.passed（trace-level deterministic 判定）。"""

    finding_count: int = 0
    """该 case 的 finding 总数。"""

    error_count: int = 0
    """该 case 的 error 级别 finding 数。"""

    warning_count: int = 0
    """该 case 的 warning 级别 finding 数。"""

    metrics_summary: dict[str, Any] = field(default_factory=dict)
    """从 ExecutionTrace 提取的关键指标摘要（tool_call_count 等）。"""


@dataclass(frozen=True)
class SuiteMetrics:
    """跨 case 聚合指标。

    所有字段为 0 或空 dict 的默认值——空 suite 也是合法的。
    """

    mean_tool_call_count: float = 0.0
    mean_tool_error_rate: float = 0.0
    mean_findings_per_case: float = 0.0
    total_findings: int = 0
    total_tool_calls: int = 0
    total_tool_errors: int = 0
    finding_count_by_category: dict[str, int] = field(default_factory=dict)
    finding_count_by_tool: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class SuiteScorecard:
    """suite 级别一页纸评分卡。"""

    suite_passed: bool
    """所有 case 的 deterministic_passed 都为 True 时为 True。"""

    task_success_rate: float
    """task_status == "success" 的 case 比例。"""

    deterministic_pass_rate: float
    """deterministic_passed == True 的 case 比例。"""

    top_failing_categories: list[str] = field(default_factory=list)
    """finding 最多的 category（降序，最多 5 个）。"""

    top_affected_tools: list[str] = field(default_factory=list)
    """finding 最多的 tool（降序，最多 5 个）。"""

    total_cases: int = 0
    passed_cases: int = 0
    failed_cases: int = 0


@dataclass(frozen=True)
class SuiteResult:
    """suite 级评测聚合结果。

    SuiteResult 是 suite report 的单一数据源。
    """

    suite_id: str
    """EvalSuite.suite_id。"""

    total_cases: int
    """suite 中 case 总数（去重）。"""

    task_success_count: int = 0
    task_failed_count: int = 0
    task_inconclusive_count: int = 0

    task_success_rate: float = 0.0
    deterministic_pass_rate: float = 0.0

    per_case_results: list[CaseResult] = field(default_factory=list)
    suite_metrics: SuiteMetrics = field(default_factory=SuiteMetrics)
    suite_scorecard: SuiteScorecard = field(
        default_factory=lambda: SuiteScorecard(
            suite_passed=False,
            task_success_rate=0.0,
            deterministic_pass_rate=0.0,
        )
    )


# ---------------------------------------------------------------------------
# 聚合函数
# ---------------------------------------------------------------------------


def aggregate_suite_results(
    suite_id: str,
    case_results: list[CaseResult],
) -> SuiteResult:
    """从 CaseResult 列表聚合出 SuiteResult。

    纯函数，不访问文件系统。
    空列表 → SuiteResult 全零（合法，表示 suite 无 case）。

    Args:
        suite_id: suite 标识。
        case_results: 单个 case 的评测结果摘要列表。

    Returns:
        聚合后的 SuiteResult。
    """
    total = len(case_results)

    if total == 0:
        return SuiteResult(
            suite_id=suite_id,
            total_cases=0,
            suite_scorecard=SuiteScorecard(
                suite_passed=True,  # 空 suite 视为通过
                task_success_rate=0.0,
                deterministic_pass_rate=0.0,
                total_cases=0,
            ),
        )

    # 计数
    success = sum(1 for r in case_results if r.task_status == "success")
    failed = sum(1 for r in case_results if r.task_status == "failed")
    inconclusive = sum(1 for r in case_results if r.task_status == "inconclusive")
    det_passed = sum(1 for r in case_results if r.deterministic_passed)

    # SuiteMetrics 聚合
    total_findings = sum(r.finding_count for r in case_results)
    total_tool_calls = sum(
        r.metrics_summary.get("tool_call_count", 0) for r in case_results
    )
    total_tool_errors = sum(
        r.metrics_summary.get("tool_error_count", 0) for r in case_results
    )
    tool_error_rate = (
        total_tool_errors / total_tool_calls if total_tool_calls > 0 else 0.0
    )

    mean_tool_call_count = total_tool_calls / total if total > 0 else 0.0
    mean_findings_per_case = total_findings / total if total > 0 else 0.0

    # SuiteScorecard
    suite_passed = all(r.deterministic_passed for r in case_results)
    task_success_rate = success / total if total > 0 else 0.0
    deterministic_pass_rate = det_passed / total if total > 0 else 0.0

    # top failing categories / tools —— 从 metrics_summary 聚合
    cat_counter: dict[str, int] = {}
    tool_counter: dict[str, int] = {}
    for r in case_results:
        for cat, count in r.metrics_summary.get("finding_count_by_category", {}).items():
            cat_counter[cat] = cat_counter.get(cat, 0) + count
        for tool, count in r.metrics_summary.get("finding_count_by_tool", {}).items():
            tool_counter[tool] = tool_counter.get(tool, 0) + count

    top_cats = sorted(cat_counter, key=lambda k: cat_counter[k], reverse=True)[:5]
    top_tools = sorted(tool_counter, key=lambda k: tool_counter[k], reverse=True)[:5]

    metrics = SuiteMetrics(
        mean_tool_call_count=mean_tool_call_count,
        mean_tool_error_rate=tool_error_rate,
        mean_findings_per_case=mean_findings_per_case,
        total_findings=total_findings,
        total_tool_calls=total_tool_calls,
        total_tool_errors=total_tool_errors,
        finding_count_by_category=dict(cat_counter),
        finding_count_by_tool=dict(tool_counter),
    )

    scorecard = SuiteScorecard(
        suite_passed=suite_passed,
        task_success_rate=task_success_rate,
        deterministic_pass_rate=deterministic_pass_rate,
        top_failing_categories=top_cats,
        top_affected_tools=top_tools,
        total_cases=total,
        passed_cases=det_passed,
        failed_cases=total - det_passed,
    )

    return SuiteResult(
        suite_id=suite_id,
        total_cases=total,
        task_success_count=success,
        task_failed_count=failed,
        task_inconclusive_count=inconclusive,
        task_success_rate=task_success_rate,
        deterministic_pass_rate=deterministic_pass_rate,
        per_case_results=list(case_results),
        suite_metrics=metrics,
        suite_scorecard=scorecard,
    )
