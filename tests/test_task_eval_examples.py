"""P5: 示例 EvalCase 加载与 TaskEvaluator 端到端测试。

测试覆盖：
- 3 个示例 YAML 文件的加载（deploy_root_cause, config_validation, error_diagnosis）
- 从 YAML 构造的 EvalCase 经 TaskEvaluator 产出的 TaskOutcome 状态正确
- 示例文件中的 required_facts / forbidden_facts / exact_answer / regex_patterns
  生效并通过 TaskEvaluator 验证

架构语义保护：
- 示例 YAML 不依赖任何外部服务、不包含真实密钥
- 所有验证为 deterministic——不调 LLM
"""

from __future__ import annotations

from pathlib import Path

from agent_tool_harness.core_contract import ExecutionTrace, ToolResult
from agent_tool_harness.task_eval.eval_case import load_eval_case_from_yaml
from agent_tool_harness.task_eval.task_evaluator import TaskEvaluator

EXAMPLES_DIR = Path(__file__).parent.parent / "agent_tool_harness" / "task_eval" / "examples"


def _resolve_example_path(filename: str) -> Path:
    """解析示例 YAML 路径——兼容从 tests/ 或 repo root 运行。"""
    p = EXAMPLES_DIR / filename
    if p.exists():
        return p
    # Fallback: 从 repo root 解析
    alt = Path("agent_tool_harness/task_eval/examples") / filename
    if alt.exists():
        return alt
    raise FileNotFoundError(f"找不到示例文件: {filename}")


# ============================================================================
# 加载
# ============================================================================


class TestLoadSampleEvalCases:
    def test_load_deploy_root_cause(self):
        """加载 deploy_root_cause.yaml → required_facts + forbidden_facts。"""
        path = _resolve_example_path("deploy_root_cause.yaml")
        case = load_eval_case_from_yaml(path)
        assert case.case_id == "deploy-root-cause-001"
        assert "root cause" in case.expected_outcome.required_facts
        assert "fix recommendation" in case.expected_outcome.required_facts
        assert "restart production without approval" in case.expected_outcome.forbidden_facts
        assert len(case.expected_outcome.regex_patterns) == 1
        assert case.difficulty == "medium"
        assert "deployment" in case.tags

    def test_load_config_validation(self):
        """加载 config_validation.yaml → required_facts + forbidden_facts + regex。"""
        path = _resolve_example_path("config_validation.yaml")
        case = load_eval_case_from_yaml(path)
        assert case.case_id == "config-validation-001"
        assert case.expected_outcome.exact_answer is None
        assert len(case.expected_outcome.regex_patterns) == 1
        assert "validation result" in case.expected_outcome.required_facts
        assert "error location" in case.expected_outcome.required_facts
        assert "config is probably fine" in case.expected_outcome.forbidden_facts

    def test_load_error_diagnosis(self):
        """加载 error_diagnosis.yaml → required_facts + forbidden_facts + json_fields。"""
        path = _resolve_example_path("error_diagnosis.yaml")
        case = load_eval_case_from_yaml(path)
        assert case.case_id == "error-diagnosis-001"
        assert case.expected_outcome.expected_json_fields == {"diagnosis": "OOM kill"}
        assert "OOM" in case.expected_outcome.required_facts
        assert "memory" in case.expected_outcome.required_facts
        assert "disk full" in case.expected_outcome.forbidden_facts
        assert case.difficulty == "hard"


# ============================================================================
# TaskEvaluator 端到端
# ============================================================================


class TestSampleEvalEndToEnd:
    """用示例 EvalCase 跑 TaskEvaluator.evaluate()——验证端到端 pipeline。"""

    def test_deploy_root_cause_success(self):
        """符合所有 required_facts + 无 forbidden_facts → success。"""
        path = _resolve_example_path("deploy_root_cause.yaml")
        case = load_eval_case_from_yaml(path)
        trace = ExecutionTrace(
            scenario_id="s1",
            final_answer=(
                "Root cause: connection timeout between deploy-service and "
                "database. Fix recommendation: increase connection timeout "
                "from 30s to 60s and add retry logic."
            ),
        )
        outcome = TaskEvaluator().evaluate(case, trace)
        assert outcome.status == "success"
        assert "root cause" in outcome.matched
        assert "fix recommendation" in outcome.matched

    def test_deploy_root_cause_fails_on_forbidden(self):
        """包含禁止事实 → failed。"""
        path = _resolve_example_path("deploy_root_cause.yaml")
        case = load_eval_case_from_yaml(path)
        trace = ExecutionTrace(
            scenario_id="s2",
            final_answer=(
                "Root cause is network timeout. Fix: restart production "
                "without approval and hope it works."
            ),
        )
        outcome = TaskEvaluator().evaluate(case, trace)
        assert outcome.status == "failed"

    def test_config_validation_success(self):
        """全部 required_facts + regex 满足 + 无 forbidden_facts → success。"""
        path = _resolve_example_path("config_validation.yaml")
        case = load_eval_case_from_yaml(path)
        trace = ExecutionTrace(
            scenario_id="s3",
            final_answer=(
                "validation result: config is invalid at line 42."
                " error location: line 42."
            ),
        )
        outcome = TaskEvaluator().evaluate(case, trace)
        assert outcome.status == "success"

    def test_config_validation_fails_on_forbidden(self):
        """包含 forbidden_facts → failed。"""
        path = _resolve_example_path("config_validation.yaml")
        case = load_eval_case_from_yaml(path)
        trace = ExecutionTrace(
            scenario_id="s4",
            final_answer="validation result: config is probably fine, error location: none",
        )
        outcome = TaskEvaluator().evaluate(case, trace)
        # forbidden_facts "config is probably fine" found → failed
        assert outcome.status == "failed"

    def test_error_diagnosis_with_json_field_match(self):
        """JsonFieldMatch 匹配 tool_output → success。"""
        path = _resolve_example_path("error_diagnosis.yaml")
        case = load_eval_case_from_yaml(path)
        trace = ExecutionTrace(
            scenario_id="s5",
            final_answer="Diagnosis: OOM kill due to memory leak in java process.",
            tool_results=[
                ToolResult(
                    call_id="c1",
                    output={"diagnosis": "OOM kill", "details": "java pid=12345"},
                ),
            ],
        )
        outcome = TaskEvaluator().evaluate(case, trace)
        assert outcome.status == "success"

    def test_error_diagnosis_fails_without_memory_mention(self):
        """required_facts 不满足 → failed。"""
        path = _resolve_example_path("error_diagnosis.yaml")
        case = load_eval_case_from_yaml(path)
        trace = ExecutionTrace(
            scenario_id="s6",
            final_answer="The server crashed. Check the logs.",
        )
        outcome = TaskEvaluator().evaluate(case, trace)
        assert outcome.status == "failed"
        assert "OOM" in outcome.missing
