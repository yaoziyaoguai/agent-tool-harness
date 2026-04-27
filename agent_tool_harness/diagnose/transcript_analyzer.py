from __future__ import annotations

from typing import Any

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.judges.rule_judge import JudgeResult


class TranscriptAnalyzer:
    """从 transcript/tool calls 派生诊断。

    架构边界：
    - 负责解释失败路径，例如第一步工具选择错误、缺少关键 evidence、没有调用关键工具。
    - 不重新执行工具，也不替代 RuleJudge。
    - 诊断结果写入 diagnosis.json，并进入报告供人复盘。

    扩展点：
    - 后续可加入更细的调用图、latency/token 分析和 transcript 片段定位。
    """

    def analyze(self, case: EvalSpec, run: AgentRunResult, judge: JudgeResult) -> dict[str, Any]:
        tool_names = [call["tool_name"] for call in run.tool_calls]
        required = list(case.expected_tool_behavior.get("required_tools", []))
        issues: list[dict[str, str]] = []

        if required and tool_names:
            first_required = required[0]
            if tool_names[0] != first_required:
                issues.append(
                    {
                        "type": "wrong_first_tool",
                        "message": (
                            f"第一步工具选择错误：期望优先查看 {first_required}，"
                            f"实际先调用 {tool_names[0]}。"
                        ),
                    }
                )
        missing = [tool for tool in required if tool not in tool_names]
        for tool in missing:
            issues.append(
                {
                    "type": "missing_required_tool",
                    "message": f"没有调用关键工具 {tool}，缺少对应证据链。",
                }
            )
        if not self._has_evidence(run):
            issues.append(
                {
                    "type": "missing_evidence",
                    "message": "最终结论没有引用工具 evidence，无法证明判断来自真实工具返回。",
                }
            )
        failed_rules = [
            check.message for check in judge.checks if not check.passed
        ]
        return {
            "eval_id": case.id,
            "passed": judge.passed,
            "first_tool": tool_names[0] if tool_names else None,
            "tool_sequence": tool_names,
            "missing_required_tools": missing,
            "issues": issues,
            "failed_rules": failed_rules,
            "summary": self._summary(judge.passed, issues),
        }

    def _has_evidence(self, run: AgentRunResult) -> bool:
        return "evidence" in run.final_answer.lower() and any(
            response.get("response", {}).get("content", {}).get("evidence")
            for response in run.tool_responses
        )

    def _summary(self, passed: bool, issues: list[dict[str, str]]) -> str:
        if passed:
            return "Agent 使用关键工具并基于 evidence 给出了可验证结论。"
        if not issues:
            return "Judge 判失败，但 transcript 诊断没有发现额外结构性问题。"
        return "；".join(issue["message"] for issue in issues)
