"""TraceImportAdapter 测试 —— native schema mode。

架构边界:
- 所有测试 zero-network, deterministic.
- 不读取 .env, 不调用外部 API.
- 不依赖 demo adapter 或 real provider.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.core_contract import Evidence, ExecutionTrace
from agent_tool_harness.core_evaluation import CoreEvaluation
from agent_tool_harness.fake_judge import FakeJudgeProvider
from agent_tool_harness.trace_import import (
    TraceImportAdapter,
    TraceImportError,
    import_trace_as_evidence,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _valid_trace_dict(**overrides) -> dict:
    """构造合法的 native trace dict，允许按需覆盖字段。"""
    data = {
        "scenario_id": "test-scenario",
        "tool_calls": [
            {
                "call_id": "c1",
                "tool_name": "kb.search",
                "arguments": {"query": "test"},
            },
        ],
        "tool_results": [
            {
                "call_id": "c1",
                "tool_name": "kb.search",
                "status": "success",
                "output": {"result": "ok"},
                "error": None,
            },
        ],
        "final_answer": "test answer",
        "messages": [],
        "observations": [],
    }
    data.update(overrides)
    return data


def _valid_trace_json() -> str:
    return json.dumps(_valid_trace_dict())


# ---------------------------------------------------------------------------
# 成功路径
# ---------------------------------------------------------------------------


class TestImportDictSuccess:
    """import_dict 成功路径。"""

    def test_import_dict_returns_execution_trace(self):
        trace = TraceImportAdapter().import_dict(_valid_trace_dict())
        assert isinstance(trace, ExecutionTrace)

    def test_scenario_id_preserved(self):
        trace = TraceImportAdapter().import_dict(_valid_trace_dict())
        assert trace.scenario_id == "test-scenario"

    def test_tool_calls_count_preserved(self):
        trace = TraceImportAdapter().import_dict(_valid_trace_dict())
        assert len(trace.tool_calls) == 1

    def test_tool_call_fields_preserved(self):
        trace = TraceImportAdapter().import_dict(_valid_trace_dict())
        tc = trace.tool_calls[0]
        assert tc.call_id == "c1"
        assert tc.tool_name == "kb.search"
        assert tc.arguments == {"query": "test"}

    def test_tool_call_timestamp_preserved_when_provided(self):
        data = _valid_trace_dict()
        data["tool_calls"][0]["timestamp"] = "2025-01-15T10:30:00Z"
        trace = TraceImportAdapter().import_dict(data)
        assert trace.tool_calls[0].timestamp == "2025-01-15T10:30:00Z"

    def test_tool_call_timestamp_none_when_missing(self):
        trace = TraceImportAdapter().import_dict(_valid_trace_dict())
        assert trace.tool_calls[0].timestamp is None

    def test_tool_results_fields_preserved(self):
        trace = TraceImportAdapter().import_dict(_valid_trace_dict())
        tr = trace.tool_results[0]
        assert tr.call_id == "c1"
        assert tr.tool_name == "kb.search"
        assert tr.status == "success"
        assert tr.output == {"result": "ok"}
        assert tr.error is None

    def test_tool_result_status_ok_normalized_to_success(self):
        data = _valid_trace_dict()
        data["tool_results"][0]["status"] = "ok"
        trace = TraceImportAdapter().import_dict(data)
        assert trace.tool_results[0].status == "success"

    def test_tool_result_status_defaults_to_success(self):
        data = _valid_trace_dict()
        del data["tool_results"][0]["status"]
        trace = TraceImportAdapter().import_dict(data)
        assert trace.tool_results[0].status == "success"

    def test_tool_result_error_preserved(self):
        data = _valid_trace_dict()
        data["tool_results"][0]["status"] = "error"
        data["tool_results"][0]["error"] = "timeout"
        data["tool_results"][0]["output"] = {}
        trace = TraceImportAdapter().import_dict(data)
        assert trace.tool_results[0].status == "error"
        assert trace.tool_results[0].error == "timeout"

    def test_final_answer_preserved(self):
        trace = TraceImportAdapter().import_dict(_valid_trace_dict())
        assert trace.final_answer == "test answer"

    def test_final_answer_defaults_empty(self):
        data = _valid_trace_dict()
        del data["final_answer"]
        trace = TraceImportAdapter().import_dict(data)
        assert trace.final_answer == ""

    def test_messages_defaults_empty(self):
        data = _valid_trace_dict()
        del data["messages"]
        trace = TraceImportAdapter().import_dict(data)
        assert trace.messages == []

    def test_messages_preserved(self):
        data = _valid_trace_dict()
        data["messages"] = [{"role": "user", "content": "hello"}]
        trace = TraceImportAdapter().import_dict(data)
        assert trace.messages == [{"role": "user", "content": "hello"}]

    def test_arguments_defaults_empty(self):
        data = _valid_trace_dict()
        del data["tool_calls"][0]["arguments"]
        trace = TraceImportAdapter().import_dict(data)
        assert trace.tool_calls[0].arguments == {}

    def test_output_defaults_empty_when_error_present(self):
        """缺失 output 但有 error 时，output 默认 {}。"""
        data = _valid_trace_dict()
        del data["tool_results"][0]["output"]
        data["tool_results"][0]["error"] = "timeout"
        trace = TraceImportAdapter().import_dict(data)
        assert trace.tool_results[0].output == {}

    def test_multiple_tool_calls_and_results(self):
        data = _valid_trace_dict()
        data["tool_calls"] = [
            {"call_id": "c1", "tool_name": "kb.search", "arguments": {"q": "a"}},
            {"call_id": "c2", "tool_name": "kb.read", "arguments": {"id": 1}},
        ]
        data["tool_results"] = [
            {"call_id": "c1", "tool_name": "kb.search", "output": {"r": 1}},
            {"call_id": "c2", "tool_name": "kb.read", "output": {"r": 2}},
        ]
        trace = TraceImportAdapter().import_dict(data)
        assert len(trace.tool_calls) == 2
        assert len(trace.tool_results) == 2
        assert trace.tool_calls[0].call_id == "c1"
        assert trace.tool_calls[1].call_id == "c2"


class TestImportFileSuccess:
    """import_file 成功路径。"""

    def test_import_file_from_temp(self, tmp_path):
        p = tmp_path / "trace.json"
        p.write_text(_valid_trace_json(), encoding="utf-8")
        trace = TraceImportAdapter().import_file(p)
        assert trace.scenario_id == "test-scenario"
        assert len(trace.tool_calls) == 1

    def test_import_file_not_found(self, tmp_path):
        p = tmp_path / "nonexistent.json"
        with pytest.raises(TraceImportError, match="无法读取文件"):
            TraceImportAdapter().import_file(p)


class TestImportExampleFile:
    """examples/trace_import/native_trace.json 可以被导入。"""

    def test_import_example_native_trace(self):
        repo_root = Path(__file__).resolve().parent.parent
        example_path = repo_root / "examples" / "trace_import" / "native_trace.json"
        trace = TraceImportAdapter().import_file(example_path)
        assert trace.scenario_id == "knowledge_search_regression"
        assert len(trace.tool_calls) == 2
        assert len(trace.tool_results) == 2
        assert trace.tool_calls[0].tool_name == "kb.search.search_articles"
        assert trace.tool_calls[1].tool_name == "kb.search.get_article"
        assert "SSO session storage layer" in trace.final_answer

    def test_example_to_evidence(self):
        repo_root = Path(__file__).resolve().parent.parent
        example_path = repo_root / "examples" / "trace_import" / "native_trace.json"
        evidence = import_trace_as_evidence(example_path)
        assert isinstance(evidence, Evidence)
        assert evidence.trace.scenario_id == "knowledge_search_regression"
        assert evidence.signal_quality is not None


# ---------------------------------------------------------------------------
# to_evidence
# ---------------------------------------------------------------------------


class TestToEvidence:
    """TraceImportAdapter.to_evidence 和 import_trace_as_evidence。"""

    def test_to_evidence_returns_evidence(self):
        adapter = TraceImportAdapter()
        trace = adapter.import_dict(_valid_trace_dict())
        evidence = adapter.to_evidence(trace)
        assert isinstance(evidence, Evidence)

    def test_evidence_trace_is_imported_trace(self):
        adapter = TraceImportAdapter()
        trace = adapter.import_dict(_valid_trace_dict())
        evidence = adapter.to_evidence(trace)
        assert evidence.trace is trace

    def test_to_evidence_stores_observations_in_artifacts(self):
        adapter = TraceImportAdapter()
        data = _valid_trace_dict()
        data["observations"] = [{"step": 1, "thought": "searching"}]
        trace = adapter.import_dict(data)
        observations = getattr(trace, "_trace_import_observations", None)
        evidence = adapter.to_evidence(trace, observations=observations)
        assert "observations" in evidence.artifacts
        assert evidence.artifacts["observations"] == [{"step": 1, "thought": "searching"}]

    def test_to_evidence_no_observations(self):
        adapter = TraceImportAdapter()
        data = _valid_trace_dict()
        data["observations"] = []
        trace = adapter.import_dict(data)
        evidence = adapter.to_evidence(trace)
        assert "observations" not in evidence.artifacts

    def test_import_trace_as_evidence_convenience(self, tmp_path):
        p = tmp_path / "trace.json"
        p.write_text(_valid_trace_json(), encoding="utf-8")
        evidence = import_trace_as_evidence(p)
        assert isinstance(evidence, Evidence)
        assert evidence.trace.scenario_id == "test-scenario"


# ---------------------------------------------------------------------------
# 校验失败路径
# ---------------------------------------------------------------------------


class TestValidationErrors:
    """字段校验失败 → TraceImportError。"""

    def test_missing_scenario_id(self):
        data = _valid_trace_dict()
        del data["scenario_id"]
        with pytest.raises(TraceImportError, match="missing scenario_id"):
            TraceImportAdapter().import_dict(data)

    def test_empty_scenario_id(self):
        data = _valid_trace_dict()
        data["scenario_id"] = ""
        with pytest.raises(TraceImportError, match="missing scenario_id"):
            TraceImportAdapter().import_dict(data)

    def test_whitespace_scenario_id(self):
        data = _valid_trace_dict()
        data["scenario_id"] = "   "
        with pytest.raises(TraceImportError, match="missing scenario_id"):
            TraceImportAdapter().import_dict(data)

    def test_tool_calls_not_list(self):
        data = _valid_trace_dict()
        data["tool_calls"] = "not a list"
        with pytest.raises(TraceImportError, match="tool_calls must be a list"):
            TraceImportAdapter().import_dict(data)

    def test_tool_calls_none(self):
        data = _valid_trace_dict()
        data["tool_calls"] = None
        with pytest.raises(TraceImportError, match="tool_calls must be a list"):
            TraceImportAdapter().import_dict(data)

    def test_tool_calls_empty(self):
        data = _valid_trace_dict()
        data["tool_calls"] = []
        with pytest.raises(TraceImportError, match="tool_calls 不能为空"):
            TraceImportAdapter().import_dict(data)

    def test_tool_results_not_list(self):
        data = _valid_trace_dict()
        data["tool_results"] = 42
        with pytest.raises(TraceImportError, match="tool_results must be a list"):
            TraceImportAdapter().import_dict(data)

    def test_tool_results_empty(self):
        data = _valid_trace_dict()
        data["tool_results"] = []
        with pytest.raises(TraceImportError, match="tool_results 不能为空"):
            TraceImportAdapter().import_dict(data)

    def test_tool_call_missing_call_id(self):
        data = _valid_trace_dict()
        del data["tool_calls"][0]["call_id"]
        with pytest.raises(TraceImportError, match="missing call_id"):
            TraceImportAdapter().import_dict(data)

    def test_tool_call_empty_call_id(self):
        data = _valid_trace_dict()
        data["tool_calls"][0]["call_id"] = ""
        with pytest.raises(TraceImportError, match="missing call_id"):
            TraceImportAdapter().import_dict(data)

    def test_tool_call_missing_tool_name(self):
        data = _valid_trace_dict()
        del data["tool_calls"][0]["tool_name"]
        with pytest.raises(TraceImportError, match="missing tool_name"):
            TraceImportAdapter().import_dict(data)

    def test_tool_call_empty_tool_name(self):
        data = _valid_trace_dict()
        data["tool_calls"][0]["tool_name"] = ""
        with pytest.raises(TraceImportError, match="missing tool_name"):
            TraceImportAdapter().import_dict(data)

    def test_tool_result_missing_call_id(self):
        data = _valid_trace_dict()
        del data["tool_results"][0]["call_id"]
        with pytest.raises(TraceImportError, match="missing call_id"):
            TraceImportAdapter().import_dict(data)

    def test_tool_result_missing_tool_name(self):
        data = _valid_trace_dict()
        del data["tool_results"][0]["tool_name"]
        with pytest.raises(TraceImportError, match="missing tool_name"):
            TraceImportAdapter().import_dict(data)

    # ------------------------------------------------------------------
    # P2: output 或 error 至少一个非空
    # ------------------------------------------------------------------

    def test_output_empty_and_error_none_is_error(self):
        data = _valid_trace_dict()
        data["tool_results"][0]["output"] = {}
        data["tool_results"][0]["error"] = None
        with pytest.raises(TraceImportError, match="needs output or error"):
            TraceImportAdapter().import_dict(data)

    def test_output_missing_and_error_missing_is_error(self):
        data = _valid_trace_dict()
        del data["tool_results"][0]["output"]
        # error 本来就不在 _valid_trace_dict 的 tool_results 中有值，但设 None 显式
        data["tool_results"][0]["error"] = None
        with pytest.raises(TraceImportError, match="needs output or error"):
            TraceImportAdapter().import_dict(data)

    def test_output_empty_dict_and_error_empty_string_is_error(self):
        data = _valid_trace_dict()
        data["tool_results"][0]["output"] = {}
        data["tool_results"][0]["error"] = ""
        with pytest.raises(TraceImportError, match="needs output or error"):
            TraceImportAdapter().import_dict(data)

    def test_error_nonempty_output_missing_is_allowed(self):
        data = _valid_trace_dict()
        del data["tool_results"][0]["output"]
        data["tool_results"][0]["error"] = "timeout"
        trace = TraceImportAdapter().import_dict(data)
        assert trace.tool_results[0].error == "timeout"
        assert trace.tool_results[0].output == {}

    def test_output_nonempty_error_missing_is_allowed(self):
        data = _valid_trace_dict()
        data["tool_results"][0]["output"] = {"key": "val"}
        data["tool_results"][0]["error"] = None
        trace = TraceImportAdapter().import_dict(data)
        assert trace.tool_results[0].output == {"key": "val"}
        assert trace.tool_results[0].error is None

    def test_tool_result_unknown_call_id(self):
        data = _valid_trace_dict()
        data["tool_results"][0]["call_id"] = "unknown-call-id"
        with pytest.raises(TraceImportError, match="找不到对应项"):
            TraceImportAdapter().import_dict(data)

    def test_malformed_json(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json{{{", encoding="utf-8")
        with pytest.raises(TraceImportError, match="invalid JSON"):
            TraceImportAdapter().import_file(p)

    def test_json_not_a_dict(self, tmp_path):
        p = tmp_path / "arr.json"
        p.write_text('[1, 2, 3]', encoding="utf-8")
        with pytest.raises(TraceImportError, match="must be a JSON object"):
            TraceImportAdapter().import_file(p)

    def test_tool_call_not_a_dict(self):
        data = _valid_trace_dict()
        data["tool_calls"] = [[1, 2, 3]]
        with pytest.raises(TraceImportError, match="must be a JSON object"):
            TraceImportAdapter().import_dict(data)

    def test_tool_result_not_a_dict(self):
        data = _valid_trace_dict()
        data["tool_results"] = ["string"]
        with pytest.raises(TraceImportError, match="must be a JSON object"):
            TraceImportAdapter().import_dict(data)


# ---------------------------------------------------------------------------
# 边界行为
# ---------------------------------------------------------------------------


class TestBoundaryBehavior:
    """不读 .env / 不调外部 API / 不生成 ReviewDecision。"""

    def test_no_env_read(self, monkeypatch):
        """验证 import_dict 不读取环境变量。"""
        monkeypatch.setattr(os, "environ", {})
        # 即使没有环境变量也能正常工作
        trace = TraceImportAdapter().import_dict(_valid_trace_dict())
        assert trace.scenario_id == "test-scenario"

    def test_no_review_decision_import(self):
        """验证 TraceImportAdapter 不 import ReviewDecision。"""
        # 模块不应导入 ReviewDecision，也不能构造它
        import agent_tool_harness.trace_import as ti

        source = (Path(ti.__file__)).read_text() if ti.__file__ else ""
        # 允许 docstring 中提到 ReviewDecision（说明为什么不能生成），
        # 但不能有实际的 import 语句引入它
        assert "from agent_tool_harness.core_contract import" not in source or \
            "ReviewDecision" not in ti.__dict__

    def test_field_path_in_error(self):
        """验证错误信息包含 field_path。"""
        data = _valid_trace_dict()
        del data["scenario_id"]
        with pytest.raises(TraceImportError) as exc_info:
            TraceImportAdapter().import_dict(data)
        assert exc_info.value.field_path == "scenario_id"

    def test_trace_import_error_is_exception(self):
        assert issubclass(TraceImportError, Exception)


# ---------------------------------------------------------------------------
# Core Flow 集成
# ---------------------------------------------------------------------------


class TestCoreFlowIntegration:
    """导入后的 Evidence 可以进入 CoreEvaluation。"""

    @staticmethod
    def _make_eval_spec(
        eval_id: str = "test-scenario",
        required_tools: list[str] | None = None,
    ) -> EvalSpec:
        """构造与 native trace 匹配的 EvalSpec。"""
        return EvalSpec(
            id=eval_id,
            name="test scenario",
            category="integration",
            split="test",
            realism_level="mock",
            complexity="low",
            source="test",
            user_prompt="trace import test",
            initial_context={},
            verifiable_outcome={},
            success_criteria=[],
            expected_tool_behavior={
                "required_tools": required_tools or ["kb.search"],
            },
            judge={},
        )

    def test_core_evaluation_consumes_imported_evidence(self):
        adapter = TraceImportAdapter()
        trace = adapter.import_dict(_valid_trace_dict())
        evidence = adapter.to_evidence(trace)
        result = CoreEvaluation().evaluate(evidence, self._make_eval_spec())
        assert result.scenario_id == "test-scenario"
        assert len(result.findings) > 0

    def test_core_evaluation_with_fake_judge_provider(self):
        """配合 FakeJudgeProvider，不调用真实 LLM。"""
        adapter = TraceImportAdapter()
        trace = adapter.import_dict(_valid_trace_dict())
        evidence = adapter.to_evidence(trace)
        fake = FakeJudgeProvider()
        evaluator = CoreEvaluation(judge_provider=fake)
        result = evaluator.evaluate(evidence, self._make_eval_spec())
        # RuleFinding + JudgeFinding 都在
        assert len(result.findings) >= 1
        judge_findings = [f for f in result.findings if f.category == "judge"]
        assert len(judge_findings) >= 1

    def test_example_trace_core_evaluation(self):
        """示例 native trace 可以被 CoreEvaluation 评估。"""
        repo_root = Path(__file__).resolve().parent.parent
        example_path = repo_root / "examples" / "trace_import" / "native_trace.json"
        evidence = import_trace_as_evidence(example_path)
        eval_spec = self._make_eval_spec(
            eval_id="knowledge_search_regression",
            required_tools=["kb.search.search_articles"],
        )
        result = CoreEvaluation().evaluate(evidence, eval_spec)
        assert result.scenario_id == "knowledge_search_regression"
        assert len(result.findings) > 0
