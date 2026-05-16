"""TaskOutcome + TaskEvaluator —— v3.2 任务级评测聚合。

架构边界
--------
- **负责**：从 ExecutionTrace 提取 final answer、运行 verifier 列表、
  聚合 VerifierResult 列表为 TaskOutcome。
- **不负责**：不修改 EvaluationResult、不调 LLM、不定义 verifier 逻辑
  （那是 verifiers.py 的事）、不定义 EvalCase（那是 eval_case.py 的事）。
- **为什么 TaskOutcome.status 不影响 EvaluationResult.passed**：
  trace-level 评测（ToolUseInspector + RuleJudge）回答"Agent 是否按规则使用工具"；
  task-level 评测（TaskOutcome）回答"Agent 是否完成用户任务"。
  两者是不同层级的问题，不应互相影响。
- **为什么 final_answer 提取用 3 级回落**：
  trace.final_answer 是 v3.1 就有的结构化字段（优先级最高）；
  如果为空，从最后一个 tool_result.output 中查找 answer/content 键；
  再找不到就取整个 output 的 JSON 字符串表示。保证在现有数据上也能工作。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from agent_tool_harness.core_contract import ExecutionTrace
from agent_tool_harness.task_eval.eval_case import EvalCase, ExpectedOutcome
from agent_tool_harness.task_eval.verifiers import (
    CompositeVerifier,
    VerifierResult,
    build_verifiers_from_outcome,
)


@dataclass
class TaskOutcome:
    """单次 task-level 评测的聚合结果。

    设计原则：
    - status 三态：success（所有 verifier 通过）、failed（任一 verifier 失败）、
      inconclusive（无 verifier，无法自动判定）。
    - matched/missing 聚合所有 verifier 的结果，方便报告展示。
    - verifier_results 保留每个子 verifier 的独立结果，reviewer 可逐项审查。
    """

    case_id: str
    """对应的 EvalCase.case_id。"""

    status: str = "inconclusive"
    """success | failed | inconclusive。"""

    verifier_results: list[VerifierResult] = field(default_factory=list)
    """所有子 verifier 的独立执行结果。"""

    final_answer: str = ""
    """从 ExecutionTrace 提取的最终答案文本。"""

    details: str = ""
    """人类可读的判定摘要。"""

    matched: list[str] = field(default_factory=list)
    """聚合的所有 matched 事实/字段/pattern。"""

    missing: list[str] = field(default_factory=list)
    """聚合的所有 missing 事实/字段/pattern。"""


class TaskEvaluator:
    """Task-level 评测器——消费 EvalCase + ExecutionTrace，产出 TaskOutcome。

    架构边界：
    - **负责**：提取 final answer、运行 verifier、聚合结果。
    - **不负责**：不修改 EvaluationResult、不调 LLM。
    - 用法：
        outcome = TaskEvaluator().evaluate(eval_case, execution_trace)
    """

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    def evaluate(
        self,
        eval_case: EvalCase,
        trace: ExecutionTrace,
    ) -> TaskOutcome:
        """对一次 Agent 执行做 task-level 评测。

        Args:
            eval_case: 评测用例定义（含 ExpectedOutcome）。
            trace: Agent 执行轨迹（含 final_answer 和 tool_results）。

        Returns:
            TaskOutcome: 聚合后的任务评测结果。
        """
        final_answer = self._extract_final_answer(trace)
        verifier = self._build_verifier(eval_case.expected_outcome)

        if verifier is None:
            return TaskOutcome(
                case_id=eval_case.case_id,
                status="inconclusive",
                verifier_results=[],
                final_answer=final_answer,
                details="无可自动判定的验证条件（ExpectedOutcome 为空）",
            )

        result = verifier.verify(
            final_answer,
            self._extract_tool_outputs(trace),
        )

        status = self._determine_status([result])
        return TaskOutcome(
            case_id=eval_case.case_id,
            status=status,
            verifier_results=[result],
            final_answer=final_answer,
            details=result.details,
            matched=list(result.matched),
            missing=list(result.missing),
        )

    # ------------------------------------------------------------------
    # Final answer 提取（3 级回落）
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_final_answer(trace: ExecutionTrace) -> str:
        """从 ExecutionTrace 提取最终答案，按优先级回落。

        Priority 1: trace.final_answer（结构化字段，v3.1 已有）。
        Priority 2: 最后一个 tool_result.output 的 "answer" 或 "content" 键。
        Priority 3: 最后一个 tool_result.output 的 JSON 字符串表示。
        """
        # Priority 1
        if trace.final_answer.strip():
            return trace.final_answer

        # Priority 2 & 3: 从最后一个 tool_result 取
        if not trace.tool_results:
            return ""

        last_output = trace.tool_results[-1].output
        if not isinstance(last_output, dict) or not last_output:
            return ""

        # Priority 2
        for key in ("answer", "content"):
            val = last_output.get(key)
            if isinstance(val, str) and val.strip():
                return val

        # Priority 3
        return json.dumps(last_output, ensure_ascii=False)

    @staticmethod
    def _extract_tool_outputs(trace: ExecutionTrace) -> list[dict[str, Any]]:
        """从 ExecutionTrace 提取所有 tool_result.output 列表。"""
        return [r.output for r in trace.tool_results]

    # ------------------------------------------------------------------
    # Verifier 构建
    # ------------------------------------------------------------------

    @staticmethod
    def _build_verifier(expected_outcome: ExpectedOutcome):
        """从 ExpectedOutcome 构造 CompositeVerifier。

        返回 None 表示无自动验证条件（→ inconclusive）。
        使用 CompositeVerifier(mode="all") 包裹所有子 verifier——
        ExpectedOutcome 的 AND 语义：所有条件都必须满足。
        """
        sub_verifiers = build_verifiers_from_outcome(expected_outcome)
        if not sub_verifiers:
            return None
        return CompositeVerifier(sub_verifiers, mode="all")

    # ------------------------------------------------------------------
    # 状态判定
    # ------------------------------------------------------------------

    @staticmethod
    def _determine_status(results: list[VerifierResult]) -> str:
        """从 VerifierResult 列表判定 TaskOutcome.status。

        - 所有 passed=True → success
        - 任一 passed=False → failed
        - 空列表 → inconclusive（调用方应在更上层处理，此处兜底）
        """
        if not results:
            return "inconclusive"
        if all(r.passed for r in results):
            return "success"
        return "failed"
