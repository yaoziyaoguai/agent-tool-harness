"""Task-level Evaluation — v3.2 任务级评测。

架构边界
--------
- **负责**：定义 EvalCase、ExpectedOutcome、Verifier、TaskOutcome、TaskEvaluator，
  在 v3.1 的 trace-level inspection 之上提供 task-level verification。
- **不负责**：不运行 Agent、不调用 LLM（确定性 verifier 零网络依赖）、
  不修改 EvaluationResult / Finding 结构。
- **为什么独立于 core_evaluation**：TaskOutcome 在 EvaluationResult 之后独立计算，
  消费 ExecutionTrace 和 EvaluationResult，但不修改它们。
  TaskOutcome.status 不影响 EvaluationResult.passed——两者回答不同层级的问题。
"""

from agent_tool_harness.task_eval.eval_case import (
    EvalCase,
    ExpectedOutcome,
    load_eval_case_from_dict,
    load_eval_case_from_yaml,
)
from agent_tool_harness.task_eval.render import (
    render_task_outcome_markdown,
    render_task_outcome_text,
)
from agent_tool_harness.task_eval.task_evaluator import TaskEvaluator, TaskOutcome
from agent_tool_harness.task_eval.verifiers import (
    CompositeVerifier,
    ContainsRequiredFacts,
    ExactMatch,
    ForbiddenFactsAbsent,
    JsonFieldMatch,
    RegexMatch,
    VerifierResult,
    build_verifiers_from_outcome,
)

__all__ = [
    "CompositeVerifier",
    "ContainsRequiredFacts",
    "EvalCase",
    "ExactMatch",
    "ExpectedOutcome",
    "ForbiddenFactsAbsent",
    "JsonFieldMatch",
    "RegexMatch",
    "TaskEvaluator",
    "TaskOutcome",
    "VerifierResult",
    "build_verifiers_from_outcome",
    "load_eval_case_from_dict",
    "load_eval_case_from_yaml",
    "render_task_outcome_markdown",
    "render_task_outcome_text",
]
