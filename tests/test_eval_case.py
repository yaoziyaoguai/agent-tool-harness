"""P1: EvalCase / ExpectedOutcome schema 测试。

测试覆盖：
- EvalCase 最小字段创建 → case_id, task 有值
- EvalCase 含 ExpectedOutcome → expected_outcome 非 None
- ExpectedOutcome 空（无 verifier） → 所有 list 为空，exact_answer/notes 为 None
- ExpectedOutcome 含 required_facts → list 正确存储
- YAML 加载 EvalCase（最小）→ 所有字段正确解析
- YAML 加载 EvalCase（含 ExpectedOutcome）→ required_facts/forbidden_facts 正确
- YAML 加载 EvalCase（含 regex_patterns）→ regex 列表正确
- VerifierResult 创建 → 字段正确
- EvalCase 缺少必填字段 → ValueError
- EvalCase optional trace_ref → 可 None
- EvalCase difficulty 校验 → 非法值 raise ValueError
- EvalCase 完整字段创建 → tags/difficulty/metadata correct

架构语义保护：
- frozen=True 保证 EvalCase/ExpectedOutcome/VerifierResult 不可变——这对
  确定性评测至关重要：同一个 case 传入不同 TaskEvaluator 不会意外修改
- EvalCase 不包含任何 IO 依赖（YAML 加载在模块级函数中，不污染 dataclass）
- ExpectedOutcome 完全独立于 trace 格式——不依赖 ExecutionTrace 的具体结构
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent_tool_harness.task_eval.eval_case import (
    EvalCase,
    ExpectedOutcome,
    load_eval_case_from_dict,
    load_eval_case_from_yaml,
)
from agent_tool_harness.task_eval.verifiers import VerifierResult

# ============================================================================
# EvalCase 创建
# ============================================================================


class TestEvalCaseMinimalCreation:
    """EvalCase 最小字段创建——case_id 和 task 是最小必填集。"""

    def test_minimal_creation(self):
        """只有 case_id 和 task，其他字段使用默认值。"""
        case = EvalCase(case_id="test-001", task="测试任务")
        assert case.case_id == "test-001"
        assert case.task == "测试任务"
        assert case.input == {}
        assert case.trace_ref is None
        assert case.tags == []
        assert case.difficulty == "medium"
        assert case.metadata == {}

    def test_expected_outcome_default_is_empty(self):
        """不传 expected_outcome 时默认空 ExpectedOutcome——无自动验证条件。"""
        case = EvalCase(case_id="t1", task="test")
        outcome = case.expected_outcome
        assert outcome.required_facts == []
        assert outcome.forbidden_facts == []
        assert outcome.expected_json_fields == {}
        assert outcome.exact_answer is None
        assert outcome.regex_patterns == []
        assert outcome.human_notes is None


class TestEvalCaseFullCreation:
    """EvalCase 完整字段创建——tags / difficulty / metadata / trace_ref。"""

    def test_full_fields(self):
        case = EvalCase(
            case_id="ks-001",
            task="找到部署失败原因",
            input={"context": "deploy failed at 14:30"},
            expected_outcome=ExpectedOutcome(
                required_facts=["root cause", "fix recommendation"],
                forbidden_facts=["restart production"],
            ),
            trace_ref="scenario-dep-001",
            tags=["deployment", "production"],
            difficulty="hard",
            metadata={"owner": "alice", "created": "2026-05-16"},
        )
        assert case.case_id == "ks-001"
        assert case.task == "找到部署失败原因"
        assert case.input["context"] == "deploy failed at 14:30"
        assert case.trace_ref == "scenario-dep-001"
        assert "deployment" in case.tags
        assert case.difficulty == "hard"
        assert case.metadata["owner"] == "alice"

    def test_expected_outcome_with_required_facts(self):
        """ExpectedOutcome 正确存储 required_facts 列表。"""
        case = EvalCase(
            case_id="t1",
            task="test",
            expected_outcome=ExpectedOutcome(
                required_facts=["fact A", "fact B"],
            ),
        )
        assert case.expected_outcome.required_facts == ["fact A", "fact B"]
        # 其他字段保持默认
        assert case.expected_outcome.forbidden_facts == []
        assert case.expected_outcome.exact_answer is None

    def test_expected_outcome_all_fields(self):
        """ExpectedOutcome 全部字段正确存储。"""
        outcome = ExpectedOutcome(
            required_facts=["f1"],
            forbidden_facts=["bad"],
            expected_json_fields={"status": "ok"},
            exact_answer="42",
            regex_patterns=[r"\d+", r"error:.*"],
            human_notes="需要人工确认",
        )
        assert outcome.required_facts == ["f1"]
        assert outcome.forbidden_facts == ["bad"]
        assert outcome.expected_json_fields == {"status": "ok"}
        assert outcome.exact_answer == "42"
        assert outcome.regex_patterns == [r"\d+", r"error:.*"]
        assert outcome.human_notes == "需要人工确认"


# ============================================================================
# EvalCase 校验
# ============================================================================


class TestEvalCaseValidation:
    """EvalCase 输入校验——必填字段非空、difficulty 合法值。"""

    def test_missing_case_id_raises(self):
        """case_id 为空字符串应 raise ValueError。"""
        with pytest.raises(ValueError, match="case_id"):
            EvalCase(case_id="", task="test")

    def test_missing_task_raises(self):
        """task 为空字符串应 raise ValueError。"""
        with pytest.raises(ValueError, match="task"):
            EvalCase(case_id="t1", task="")

    def test_invalid_difficulty_raises(self):
        """difficulty 不是 easy/medium/hard 应 raise ValueError。"""
        with pytest.raises(ValueError, match="difficulty"):
            EvalCase(case_id="t1", task="test", difficulty="impossible")


# ============================================================================
# YAML 加载
# ============================================================================


class TestLoadEvalCaseFromDict:
    """load_eval_case_from_dict —— dict 到 EvalCase 的反序列化。"""

    def test_minimal_dict(self):
        """最小 dict —— 只有 case_id 和 task。"""
        data = {"case_id": "min-001", "task": "最小测试"}
        case = load_eval_case_from_dict(data)
        assert case.case_id == "min-001"
        assert case.task == "最小测试"
        assert case.expected_outcome.required_facts == []

    def test_dict_with_expected_outcome(self):
        """dict 含 expected_outcome —— required_facts / forbidden_facts 正确解析。"""
        data = {
            "case_id": "ks-001",
            "task": "找到部署失败原因",
            "expected_outcome": {
                "required_facts": ["root cause"],
                "forbidden_facts": ["restart"],
            },
        }
        case = load_eval_case_from_dict(data)
        assert case.expected_outcome.required_facts == ["root cause"]
        assert case.expected_outcome.forbidden_facts == ["restart"]

    def test_dict_with_regex_patterns(self):
        """expected_outcome 含 regex_patterns。"""
        data = {
            "case_id": "re-001",
            "task": "regex test",
            "expected_outcome": {
                "regex_patterns": [r"error: .+", r"\d+%"],
            },
        }
        case = load_eval_case_from_dict(data)
        assert case.expected_outcome.regex_patterns == [r"error: .+", r"\d+%"]

    def test_dict_with_exact_answer(self):
        """expected_outcome 含 exact_answer。"""
        data = {
            "case_id": "ex-001",
            "task": "exact test",
            "expected_outcome": {"exact_answer": "42"},
        }
        case = load_eval_case_from_dict(data)
        assert case.expected_outcome.exact_answer == "42"

    def test_dict_with_tags_and_metadata(self):
        """tags 和 metadata 正确解析。"""
        data = {
            "case_id": "tm-001",
            "task": "tags test",
            "tags": ["production", "critical"],
            "difficulty": "hard",
            "metadata": {"owner": "bob"},
        }
        case = load_eval_case_from_dict(data)
        assert case.tags == ["production", "critical"]
        assert case.difficulty == "hard"
        assert case.metadata == {"owner": "bob"}


class TestLoadEvalCaseFromYaml:
    """load_eval_case_from_yaml —— 从 YAML 文件加载 EvalCase。"""

    def test_load_minimal_yaml(self):
        """最小 YAML 文件正确加载。"""
        yaml_content = """case_id: yaml-min-001
task: YAML 最小测试
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(yaml_content)
            tmp_path = f.name

        try:
            case = load_eval_case_from_yaml(tmp_path)
            assert case.case_id == "yaml-min-001"
            assert case.task == "YAML 最小测试"
            assert case.expected_outcome.required_facts == []
        finally:
            Path(tmp_path).unlink()

    def test_load_full_yaml(self):
        """完整 YAML 含 expected_outcome / tags / difficulty。"""
        yaml_content = """case_id: ks-001
task: 找到部署失败原因并给出修复建议
input:
  context: 生产环境 deploy-service 在 2026-05-15 14:30 部署失败
expected_outcome:
  required_facts:
    - root cause
    - fix recommendation
  forbidden_facts:
    - restart production without approval
  regex_patterns:
    - 'error: .+ at .+'
difficulty: medium
tags:
  - deployment
  - production
metadata:
  owner: alice
"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, encoding="utf-8"
        ) as f:
            f.write(yaml_content)
            tmp_path = f.name

        try:
            case = load_eval_case_from_yaml(tmp_path)
            assert case.case_id == "ks-001"
            assert "root cause" in case.expected_outcome.required_facts
            assert "fix recommendation" in case.expected_outcome.required_facts
            assert "restart production without approval" in case.expected_outcome.forbidden_facts
            assert r"error: .+ at .+" in case.expected_outcome.regex_patterns
            assert case.difficulty == "medium"
            assert "deployment" in case.tags
            assert case.metadata["owner"] == "alice"
        finally:
            Path(tmp_path).unlink()

    def test_yaml_file_not_found(self):
        """不存在的 YAML 文件应 raise FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            load_eval_case_from_yaml("/nonexistent/path/eval.yaml")


# ============================================================================
# VerifierResult
# ============================================================================


class TestVerifierResult:
    """VerifierResult — 单次 verifier 执行的确定性结果。"""

    def test_passed_result(self):
        """通过的 verifier 结果——matched 有值、missing 为空。"""
        result = VerifierResult(
            verifier_name="contains_required_facts",
            passed=True,
            matched=["fact A", "fact B"],
            missing=[],
            details="matched 2/2 required facts",
        )
        assert result.passed is True
        assert result.matched == ["fact A", "fact B"]
        assert result.missing == []

    def test_failed_result(self):
        """失败的 verifier 结果——matched 部分、missing 有值。"""
        result = VerifierResult(
            verifier_name="contains_required_facts",
            passed=False,
            matched=["fact A"],
            missing=["fact B"],
            details="matched 1/2 required facts",
        )
        assert result.passed is False
        assert result.matched == ["fact A"]
        assert result.missing == ["fact B"]
        assert "1/2" in result.details

    def test_default_fields(self):
        """VerifierResult 的 matched/missing 默认空列表。"""
        result = VerifierResult(verifier_name="test", passed=True)
        assert result.matched == []
        assert result.missing == []
        assert result.details == ""
