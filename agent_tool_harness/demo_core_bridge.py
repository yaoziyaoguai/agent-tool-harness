"""Demo-to-Core 桥接层 —— 把旧 Demo runtime 对象映射到 Core Contract 对象。

架构边界
--------
- **负责**：把 ``AgentRunResult`` → ``ExecutionTrace``, ``JudgeResult`` →
  ``EvaluationResult`` 等旧→新映射。所有函数都是纯数据转换，无副作用、无 IO。
- **不负责**：不执行工具、不调用 Agent、不评判结果、不读/写磁盘、不生成报告。
- **为什么不改 MockReplayAdapter**：旧 adapter 仍在生产链路中稳定工作。桥接层让
  Core Contract 对象可以独立验证，不要求旧组件立刻适配新接口。
- **为什么桥接函数不生成 ReviewDecision**：ReviewDecision 必须由人工 Reviewer 显式创建。
  bridge 只负责机器产出（ExecutionTrace / Evidence / RuleFinding / EvaluationResult /
  ReportSummary），不越过 machine→human 治理边界。

与 Core Contract 的关系
-----------------------
- 输入：旧 Demo runtime 对象（AgentRunResult, JudgeResult, RuleCheckResult, dict）
- 输出：Core Contract 对象（ExecutionTrace, Evidence, RuleFinding, EvaluationResult,
  ReportSummary）
- 所有输出对象定义见 ``agent_tool_harness.core_contract``。

未来扩展点
----------
- 当 EvalRunner 迁移到消费 Core Contract 时，本模块的映射函数会被 runner 直接调用
- 当 MockReplayAdapter 实现 Agent2HarnessAdapter 时，部分映射逻辑可能内联到 adapter
"""

from __future__ import annotations

from typing import Any

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.core_contract import (
    EvaluationResult,
    Evidence,
    ExecutionTrace,
    ReportSummary,
    RuleFinding,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.judges.rule_judge import JudgeResult, RuleCheckResult
from agent_tool_harness.signal_quality import UNKNOWN

# ---------------------------------------------------------------------------
# AgentRunResult → ExecutionTrace
# ---------------------------------------------------------------------------


def agent_run_result_to_execution_trace(
    result: AgentRunResult,
    *,
    scenario_id: str | None = None,
) -> ExecutionTrace:
    """把旧 AgentRunResult 映射为 Core Contract ExecutionTrace。

    映射规则：
    - ``result.tool_calls`` (list[dict]) → ``list[ToolCall]``
    - ``result.tool_responses`` (list[dict]) → ``list[ToolResult]``
    - ``result.final_answer`` → ``ExecutionTrace.final_answer``
    - ``scenario_id`` 默认取 ``result.eval_id``，也可显式覆盖
    """
    tool_calls = [_dict_to_tool_call(c) for c in result.tool_calls]
    tool_results = [_dict_to_tool_result(r) for r in result.tool_responses]
    return ExecutionTrace(
        scenario_id=scenario_id or result.eval_id,
        tool_calls=tool_calls,
        tool_results=tool_results,
        final_answer=result.final_answer,
    )


def _dict_to_tool_call(call: dict[str, Any]) -> ToolCall:
    """把旧 tool_call dict 映射为 ToolCall。"""
    return ToolCall(
        tool_name=str(call.get("tool_name", "")),
        arguments=dict(call.get("arguments", {})),
        call_id=str(call.get("call_id", "")),
        timestamp=call.get("timestamp"),
    )


def _dict_to_tool_result(response: dict[str, Any]) -> ToolResult:
    """把旧 tool_response dict 映射为 ToolResult。

    旧格式的 response 嵌套在 ``response.response`` 中，包含 success/content/error。
    """
    payload = response.get("response", {})
    if not isinstance(payload, dict):
        payload = {}
    status = "success" if payload.get("success") else "error"
    return ToolResult(
        call_id=str(response.get("call_id", "")),
        status=status,
        output=dict(payload.get("content", {})),
        error=payload.get("error"),
    )


# ---------------------------------------------------------------------------
# ExecutionTrace → Evidence
# ---------------------------------------------------------------------------


def execution_trace_to_evidence(
    trace: ExecutionTrace,
    *,
    signal_quality: str = UNKNOWN,
    artifacts: dict[str, Any] | None = None,
) -> Evidence:
    """把 ExecutionTrace 打包为 Evidence。

    cost_usd / latency_ms 在当前 demo 模式下永远为 None——demo 没有真实数据。
    signal_quality 来自 adapter 的 SIGNAL_QUALITY 声明。
    """
    return Evidence(
        trace=trace,
        artifacts=artifacts or {},
        cost_usd=None,
        latency_ms=None,
        signal_quality=signal_quality,
    )


# ---------------------------------------------------------------------------
# RuleCheckResult → RuleFinding
# ---------------------------------------------------------------------------


def rule_check_to_rule_finding(
    check: RuleCheckResult,
    *,
    finding_id: str = "",
    severity: str = "",
) -> RuleFinding:
    """把单条 RuleCheckResult 映射为 RuleFinding。

    严重程度推导：
    - 显式传入的 severity 优先
    - 否则 rule_passed=True → "info"，rule_passed=False → "high"
    """
    rule_type = str(check.rule.get("type", "")) if isinstance(check.rule, dict) else ""
    return RuleFinding(
        finding_id=finding_id or f"rule-{rule_type or 'unknown'}",
        severity=severity or ("info" if check.passed else "high"),
        category="rule",
        message=check.message,
        evidence_ref=f"judge_results.json::eval_id={rule_type}",
        rule_type=rule_type,
        rule_passed=check.passed,
    )


# ---------------------------------------------------------------------------
# JudgeResult → EvaluationResult
# ---------------------------------------------------------------------------


def judge_result_to_evaluation_result(result: JudgeResult) -> EvaluationResult:
    """把旧 JudgeResult 映射为 EvaluationResult。

    每条 RuleCheckResult → RuleFinding，聚合为 EvaluationResult.findings。
    """
    findings = [
        rule_check_to_rule_finding(check, finding_id=f"{result.eval_id}-{i}")
        for i, check in enumerate(result.checks)
    ]
    passed = all(f.rule_passed for f in findings) if findings else False
    return EvaluationResult(
        scenario_id=result.eval_id,
        findings=list(findings),
        passed=passed,
        summary=_build_eval_summary(result.eval_id, passed, findings),
    )


def _build_eval_summary(
    eval_id: str, passed: bool, findings: list[RuleFinding]
) -> str:
    if not findings:
        return f"eval {eval_id}: 无规则检查结果，判定为不通过。"
    failed_rules = [f.rule_type for f in findings if not f.rule_passed]
    if failed_rules:
        return (
            f"eval {eval_id}: {len(failed_rules)}/{len(findings)} 条规则未通过 "
            f"({', '.join(failed_rules)})。"
        )
    return f"eval {eval_id}: 全部 {len(findings)} 条规则通过。"


# ---------------------------------------------------------------------------
# ExecutionTrace → AgentRunResult（反向映射，供 CoreEvaluation 使用）
# ---------------------------------------------------------------------------


def execution_trace_to_agent_run_result(trace: ExecutionTrace) -> AgentRunResult:
    """把 Core Contract ExecutionTrace 反向映射为旧 AgentRunResult。

    这是正向映射 ``agent_run_result_to_execution_trace`` 的逆操作。
    存在理由：CoreEvaluation 内部需要调用 RuleJudge.judge()，而 RuleJudge 的
    签名是 ``judge(case: EvalSpec, run: AgentRunResult) -> JudgeResult``。
    在 RuleJudge 适配 Core Contract 之前（后续轮次），本函数充当临时桥接。

    本轮不改 RuleJudge——这是刻意选择：RuleJudge 是稳定的 deterministic baseline，
    不应为了类型迁移引入风险。反向桥接是纯数据转换，风险可控。

    架构边界：
    - **负责**：ToolCall→dict, ToolResult→dict 的反向映射。
    - **不负责**：不调用 RuleJudge（那是 CoreEvaluation 的事）。
    """
    tool_calls: list[dict[str, Any]] = [
        {
            "call_id": c.call_id,
            "tool_name": c.tool_name,
            "arguments": c.arguments,
        }
        for c in trace.tool_calls
    ]
    tool_responses: list[dict[str, Any]] = []
    for r in trace.tool_results:
        response_dict: dict[str, Any] = {
            "call_id": r.call_id,
            "tool_name": "",
            "response": {
                "success": r.status == "success",
                "content": r.output,
            },
        }
        if r.error:
            response_dict["response"]["error"] = r.error
        tool_responses.append(response_dict)
    return AgentRunResult(
        eval_id=trace.scenario_id,
        final_answer=trace.final_answer,
        tool_calls=tool_calls,
        tool_responses=tool_responses,
    )


# ---------------------------------------------------------------------------
# metrics dict → ReportSummary
# ---------------------------------------------------------------------------


def build_report_summary(metrics: dict[str, Any]) -> ReportSummary:
    """从 EvalRunner._metrics() 输出的 dict 构造 ReportSummary。

    这是一个纯数据提取函数——不计算、不评判。字段缺失时使用默认值。
    """
    return ReportSummary(
        total_scenarios=int(metrics.get("total_evals", 0)),
        passed=int(metrics.get("passed", 0)),
        failed=int(metrics.get("failed", 0)),
        errors=int(metrics.get("error_evals", 0)),
        signal_quality=str(metrics.get("signal_quality", UNKNOWN)),
        generated_at=str(metrics.get("generated_at", "")),
    )
