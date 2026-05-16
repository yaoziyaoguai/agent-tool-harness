"""P3: TaskOutcome + TaskEvaluator 测试。

测试覆盖：
- TaskOutcome 创建：success / failed / inconclusive
- final_answer 提取（3 级回落）：trace.final_answer / output["answer"] /
  output["content"] / JSON fallback / 空 trace
- TaskEvaluator.evaluate: 全部通过 → success / 一个失败 → failed /
  空 ExpectedOutcome → inconclusive / verifier_results 保留
- TaskOutcome.status 不影响 EvaluationResult.passed（架构不变量）

架构语义保护：
- TaskEvaluator 是纯数据转换——不调 LLM、不修改 EvaluationResult
- final_answer 提取的 3 级回落按优先级正确工作
- TaskOutcome 是可变 dataclass（非 frozen）——verifier_results 在执行时填充
"""

from __future__ import annotations

from agent_tool_harness.core_contract import ExecutionTrace, ToolResult
from agent_tool_harness.task_eval.eval_case import EvalCase, ExpectedOutcome
from agent_tool_harness.task_eval.task_evaluator import TaskEvaluator, TaskOutcome
from agent_tool_harness.task_eval.verifiers import VerifierResult

# ============================================================================
# TaskOutcome 创建
# ============================================================================


class TestTaskOutcomeCreation:
    def test_success_outcome(self):
        """所有 verifier 通过 → status=success。"""
        outcome = TaskOutcome(
            case_id="ks-001",
            status="success",
            verifier_results=[
                VerifierResult(
                    verifier_name="contains_required_facts",
                    passed=True,
                    matched=["root cause"],
                    missing=[],
                    details="matched 1/1 required facts",
                ),
            ],
            final_answer="Root cause is timeout.",
            details="matched 1/1 required facts",
            matched=["root cause"],
            missing=[],
        )
        assert outcome.status == "success"
        assert outcome.case_id == "ks-001"
        assert len(outcome.verifier_results) == 1
        assert outcome.final_answer == "Root cause is timeout."

    def test_failed_outcome(self):
        """verifier 失败 → status=failed。"""
        outcome = TaskOutcome(
            case_id="ks-002",
            status="failed",
            missing=["fix recommendation"],
        )
        assert outcome.status == "failed"
        assert "fix recommendation" in outcome.missing

    def test_inconclusive_outcome(self):
        """无 verifier → status=inconclusive。"""
        outcome = TaskOutcome(
            case_id="ks-003",
            status="inconclusive",
            details="无可自动判定的验证条件",
        )
        assert outcome.status == "inconclusive"
        assert outcome.verifier_results == []

    def test_default_fields(self):
        """默认字段——status 默认 inconclusive，matched/missing 默认空。"""
        outcome = TaskOutcome(case_id="t1")
        assert outcome.status == "inconclusive"
        assert outcome.verifier_results == []
        assert outcome.final_answer == ""
        assert outcome.matched == []
        assert outcome.missing == []


# ============================================================================
# final_answer 提取（3 级回落）
# ============================================================================


class TestFinalAnswerExtraction:
    """_extract_final_answer 的 3 级回落策略。"""

    def test_priority_1_trace_final_answer(self):
        """trace.final_answer 非空 → 直接使用。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            final_answer="Root cause: network timeout.",
        )
        evaluator = TaskEvaluator()
        answer = evaluator._extract_final_answer(trace)
        assert answer == "Root cause: network timeout."

    def test_priority_2_output_answer_key(self):
        """trace.final_answer 为空，最后一个 tool_result.output["answer"] 有值。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_results=[
                ToolResult(
                    call_id="c1",
                    output={"answer": "The fix is to increase retry."},
                ),
            ],
        )
        evaluator = TaskEvaluator()
        answer = evaluator._extract_final_answer(trace)
        assert answer == "The fix is to increase retry."

    def test_priority_2_output_content_key(self):
        """output["content"] 作为 "answer" 的备选键。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_results=[
                ToolResult(
                    call_id="c1",
                    output={"content": "Deploy succeeded."},
                ),
            ],
        )
        evaluator = TaskEvaluator()
        answer = evaluator._extract_final_answer(trace)
        assert answer == "Deploy succeeded."

    def test_priority_2_answer_before_content(self):
        """同时有 answer 和 content 时，优先取 answer。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_results=[
                ToolResult(
                    call_id="c1",
                    output={"answer": "primary", "content": "secondary"},
                ),
            ],
        )
        evaluator = TaskEvaluator()
        answer = evaluator._extract_final_answer(trace)
        assert answer == "primary"

    def test_priority_3_json_fallback(self):
        """无 answer/content 键 → 整个 output JSON 字符串。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_results=[
                ToolResult(
                    call_id="c1",
                    output={"status": "ok", "count": 42},
                ),
            ],
        )
        evaluator = TaskEvaluator()
        answer = evaluator._extract_final_answer(trace)
        assert "status" in answer
        assert "ok" in answer
        assert "count" in answer

    def test_empty_trace(self):
        """无 tool_results → 返回空字符串。"""
        trace = ExecutionTrace(scenario_id="s1")
        evaluator = TaskEvaluator()
        answer = evaluator._extract_final_answer(trace)
        assert answer == ""

    def test_non_dict_output_skipped(self):
        """最后一个 output 非 dict → 返回空字符串。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_results=[
                ToolResult(call_id="c1", output="not a dict"),  # type: ignore[arg-type]
            ],
        )
        evaluator = TaskEvaluator()
        answer = evaluator._extract_final_answer(trace)
        assert answer == ""

    def test_uses_last_tool_result_only(self):
        """只使用最后一个 tool_result 的 output。"""
        trace = ExecutionTrace(
            scenario_id="s1",
            tool_results=[
                ToolResult(call_id="c1", output={"answer": "first"}),
                ToolResult(call_id="c2", output={"answer": "second"}),
            ],
        )
        evaluator = TaskEvaluator()
        answer = evaluator._extract_final_answer(trace)
        assert answer == "second"


# ============================================================================
# TaskEvaluator.evaluate
# ============================================================================


class TestTaskEvaluatorEvaluate:
    """TaskEvaluator.evaluate —— 端到端 task-level 评测。"""

    def test_all_verifiers_pass(self):
        """全部 required_facts 匹配 → status=success。"""
        case = EvalCase(
            case_id="ks-001",
            task="find root cause",
            expected_outcome=ExpectedOutcome(
                required_facts=["root cause", "timeout"],
            ),
        )
        trace = ExecutionTrace(
            scenario_id="s1",
            final_answer="Root cause is network timeout.",
        )
        outcome = TaskEvaluator().evaluate(case, trace)
        assert outcome.status == "success"
        assert outcome.case_id == "ks-001"
        assert "root cause" in outcome.matched
        assert "timeout" in outcome.matched

    def test_one_verifier_fails(self):
        """一个 required_fact 不匹配 → status=failed。"""
        case = EvalCase(
            case_id="ks-002",
            task="find root cause",
            expected_outcome=ExpectedOutcome(
                required_facts=["root cause", "fix recommendation"],
            ),
        )
        trace = ExecutionTrace(
            scenario_id="s1",
            final_answer="Root cause is timeout.",
        )
        outcome = TaskEvaluator().evaluate(case, trace)
        assert outcome.status == "failed"
        assert "root cause" in outcome.matched
        assert "fix recommendation" in outcome.missing

    def test_empty_expected_outcome_inconclusive(self):
        """空 ExpectedOutcome → status=inconclusive。"""
        case = EvalCase(case_id="ks-003", task="test")
        trace = ExecutionTrace(
            scenario_id="s1",
            final_answer="some answer",
        )
        outcome = TaskEvaluator().evaluate(case, trace)
        assert outcome.status == "inconclusive"
        assert outcome.verifier_results == []

    def test_verifier_results_preserved(self):
        """TaskOutcome 保留 verifier_results 供 reviewer 审查。"""
        case = EvalCase(
            case_id="ks-004",
            task="test",
            expected_outcome=ExpectedOutcome(
                required_facts=["fact"],
            ),
        )
        trace = ExecutionTrace(
            scenario_id="s1",
            final_answer="fact is present",
        )
        outcome = TaskEvaluator().evaluate(case, trace)
        assert len(outcome.verifier_results) == 1
        vr = outcome.verifier_results[0]
        assert vr.passed is True
        assert vr.verifier_name == "composite"

    def test_final_answer_in_outcome(self):
        """TaskOutcome 包含提取的 final_answer。"""
        case = EvalCase(case_id="ks-005", task="test")
        trace = ExecutionTrace(
            scenario_id="s1",
            final_answer="  The answer.  ",
        )
        outcome = TaskEvaluator().evaluate(case, trace)
        assert outcome.final_answer == "  The answer.  "

    def test_forbidden_facts_trigger_failure(self):
        """ForbiddenFactsAbsent 发现禁止事实 → status=failed。"""
        case = EvalCase(
            case_id="ks-006",
            task="test",
            expected_outcome=ExpectedOutcome(
                forbidden_facts=["restart production"],
            ),
        )
        trace = ExecutionTrace(
            scenario_id="s1",
            final_answer="We should restart production now.",
        )
        outcome = TaskEvaluator().evaluate(case, trace)
        assert outcome.status == "failed"
        assert "restart production" in outcome.missing

    def test_exact_answer_match(self):
        """ExactMatch 精确匹配 → status=success。"""
        case = EvalCase(
            case_id="ks-007",
            task="test",
            expected_outcome=ExpectedOutcome(exact_answer="42"),
        )
        trace = ExecutionTrace(scenario_id="s1", final_answer="42")
        outcome = TaskEvaluator().evaluate(case, trace)
        assert outcome.status == "success"

    def test_combined_verifiers_and_semantics(self):
        """required_facts + forbidden_facts 同时生效（AND 语义）。"""
        case = EvalCase(
            case_id="ks-008",
            task="test",
            expected_outcome=ExpectedOutcome(
                required_facts=["root cause"],
                forbidden_facts=["restart"],
            ),
        )
        # 两者都满足
        trace = ExecutionTrace(
            scenario_id="s1",
            final_answer="Root cause is timeout. Fix: increase retry.",
        )
        outcome = TaskEvaluator().evaluate(case, trace)
        assert outcome.status == "success"

        # 满足 required_facts 但违反 forbidden_facts
        trace2 = ExecutionTrace(
            scenario_id="s2",
            final_answer="Root cause is timeout. Restart the service.",
        )
        outcome2 = TaskEvaluator().evaluate(case, trace2)
        assert outcome2.status == "failed"


# ============================================================================
# 架构不变量
# ============================================================================


class TestArchitectureInvariants:
    """TaskOutcome.status 不影响 EvaluationResult.passed。"""

    def test_task_outcome_independent_of_eval_result(self):
        """TaskOutcome 可独立于 EvaluationResult 创建和消费。"""
        # TaskOutcome 不需要 EvaluationResult 引用即可存在
        outcome = TaskOutcome(
            case_id="ks-001",
            status="failed",
            missing=["fact A"],
        )
        assert outcome.status == "failed"
        # 没有任何 EvaluationResult 引用
        assert not hasattr(outcome, "evaluation_result")
