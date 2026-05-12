"""TraceImportAdapter simple mapping mode 测试。

架构边界:
- 所有测试 zero-network, deterministic.
- 不读取 .env, 不调用外部 API.
- 不实现 JSONPath / deep nesting / filter / expression.
"""

from __future__ import annotations

import pytest

from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.core_contract import Evidence, ExecutionTrace
from agent_tool_harness.core_evaluation import CoreEvaluation
from agent_tool_harness.trace_import import (
    SimpleMappingConfig,
    TraceImportAdapter,
    TraceImportError,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_mapping(**overrides) -> SimpleMappingConfig:
    """构造标准 simple mapping 配置，字段名与 native 不同但结构一致。"""
    kwargs = dict(
        scenario_id_path="sid",
        tool_calls_path="calls",
        tool_results_path="results",
        final_answer_path="answer",
        messages_path="msgs",
        observations_path="obs",
        tool_call_id_field="cid",
        tool_call_name_field="name",
        tool_call_arguments_field="args",
        tool_call_timestamp_field="ts",
        tool_result_call_id_field="cid",
        tool_result_name_field="name",
        tool_result_status_field="st",
        tool_result_output_field="out",
        tool_result_error_field="err",
    )
    kwargs.update(overrides)
    return SimpleMappingConfig(**kwargs)


def _user_trace_dict(**overrides) -> dict:
    """构造用户自定义格式的 trace dict（字段名与 native 不同）。"""
    data = {
        "sid": "test-scenario",
        "calls": [
            {
                "cid": "c1",
                "name": "kb.search",
                "args": {"query": "test"},
            },
        ],
        "results": [
            {
                "cid": "c1",
                "name": "kb.search",
                "st": "success",
                "out": {"result": "ok"},
                "err": None,
            },
        ],
        "answer": "test answer",
        "msgs": [],
        "obs": [],
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# 成功路径
# ---------------------------------------------------------------------------


class TestSimpleMappingSuccess:
    """simple mapping 成功导入 → ExecutionTrace。"""

    def test_import_dict_returns_execution_trace(self):
        trace = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping()
        ).import_dict(_user_trace_dict())
        assert isinstance(trace, ExecutionTrace)

    def test_scenario_id_mapped(self):
        trace = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping()
        ).import_dict(_user_trace_dict())
        assert trace.scenario_id == "test-scenario"

    def test_tool_calls_mapped(self):
        trace = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping()
        ).import_dict(_user_trace_dict())
        assert len(trace.tool_calls) == 1
        assert trace.tool_calls[0].call_id == "c1"
        assert trace.tool_calls[0].tool_name == "kb.search"

    def test_arguments_mapped(self):
        trace = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping()
        ).import_dict(_user_trace_dict())
        assert trace.tool_calls[0].arguments == {"query": "test"}

    def test_tool_results_mapped(self):
        trace = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping()
        ).import_dict(_user_trace_dict())
        assert len(trace.tool_results) == 1
        assert trace.tool_results[0].call_id == "c1"
        assert trace.tool_results[0].tool_name == "kb.search"
        assert trace.tool_results[0].status == "success"

    def test_output_error_mapped(self):
        trace = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping()
        ).import_dict(_user_trace_dict())
        assert trace.tool_results[0].output == {"result": "ok"}
        assert trace.tool_results[0].error is None

    def test_status_ok_normalized(self):
        data = _user_trace_dict()
        data["results"][0]["st"] = "ok"
        trace = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping()
        ).import_dict(data)
        assert trace.tool_results[0].status == "success"

    def test_final_answer_mapped(self):
        trace = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping()
        ).import_dict(_user_trace_dict())
        assert trace.final_answer == "test answer"

    def test_messages_optional(self):
        data = _user_trace_dict()
        del data["msgs"]
        trace = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping(messages_path=None)
        ).import_dict(data)
        assert trace.messages == []

    def test_observations_optional(self):
        data = _user_trace_dict()
        del data["obs"]
        trace = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping(observations_path=None)
        ).import_dict(data)
        assert isinstance(trace, ExecutionTrace)

    def test_observations_stored_in_artifacts(self):
        data = _user_trace_dict()
        data["obs"] = [{"step": 1}]
        adapter = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping()
        )
        trace = adapter.import_dict(data)
        observations = getattr(trace, "_trace_import_observations", None)
        evidence = adapter.to_evidence(trace, observations=observations)
        assert evidence.artifacts.get("observations") == [{"step": 1}]

    def test_import_file(self, tmp_path):
        import json

        p = tmp_path / "trace.json"
        p.write_text(json.dumps(_user_trace_dict()), encoding="utf-8")
        trace = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping()
        ).import_file(p)
        assert trace.scenario_id == "test-scenario"

    def test_to_evidence(self):
        adapter = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping()
        )
        trace = adapter.import_dict(_user_trace_dict())
        evidence = adapter.to_evidence(trace)
        assert isinstance(evidence, Evidence)
        assert evidence.trace is trace

    def test_final_answer_optional(self):
        data = _user_trace_dict()
        del data["answer"]
        trace = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping(final_answer_path=None)
        ).import_dict(data)
        assert trace.final_answer == ""


# ---------------------------------------------------------------------------
# 错误路径
# ---------------------------------------------------------------------------


class TestSimpleMappingErrors:
    """simple mapping 错误处理。"""

    def test_missing_mapping_raises(self):
        with pytest.raises(TraceImportError, match="mapping is required"):
            TraceImportAdapter(mode="simple_mapping", mapping=None).import_dict(
                _user_trace_dict()
            )

    def test_mapping_target_not_found_scenario_id(self):
        data = _user_trace_dict()
        del data["sid"]
        with pytest.raises(TraceImportError, match="not found"):
            TraceImportAdapter(
                mode="simple_mapping", mapping=_make_mapping()
            ).import_dict(data)

    def test_mapping_target_not_found_tool_calls(self):
        data = _user_trace_dict()
        del data["calls"]
        with pytest.raises(TraceImportError, match="not found"):
            TraceImportAdapter(
                mode="simple_mapping", mapping=_make_mapping()
            ).import_dict(data)

    def test_tool_calls_path_not_list(self):
        data = _user_trace_dict()
        data["calls"] = "not a list"
        with pytest.raises(TraceImportError, match="must be a list"):
            TraceImportAdapter(
                mode="simple_mapping", mapping=_make_mapping()
            ).import_dict(data)

    def test_tool_results_path_not_list(self):
        data = _user_trace_dict()
        data["results"] = 42
        with pytest.raises(TraceImportError, match="must be a list"):
            TraceImportAdapter(
                mode="simple_mapping", mapping=_make_mapping()
            ).import_dict(data)

    def test_output_or_error_required(self):
        """P2 校验在 simple mapping 中同样生效。"""
        data = _user_trace_dict()
        data["results"][0]["out"] = {}
        data["results"][0]["err"] = None
        with pytest.raises(TraceImportError, match="needs output or error"):
            TraceImportAdapter(
                mode="simple_mapping", mapping=_make_mapping()
            ).import_dict(data)

    def test_tool_call_missing_mapped_call_id(self):
        data = _user_trace_dict()
        del data["calls"][0]["cid"]
        with pytest.raises(TraceImportError, match="missing call_id"):
            TraceImportAdapter(
                mode="simple_mapping", mapping=_make_mapping()
            ).import_dict(data)

    def test_tool_result_unknown_call_id(self):
        data = _user_trace_dict()
        data["results"][0]["cid"] = "unknown"
        with pytest.raises(TraceImportError, match="找不到对应项"):
            TraceImportAdapter(
                mode="simple_mapping", mapping=_make_mapping()
            ).import_dict(data)


# ---------------------------------------------------------------------------
# 不支持的路径格式
# ---------------------------------------------------------------------------


class TestUnsupportedPathRejection:
    """SimpleMappingConfig 拒绝不支持的路径格式。"""

    def test_dotted_path_rejected(self):
        with pytest.raises(TraceImportError, match="unsupported mapping path"):
            SimpleMappingConfig(
                scenario_id_path="data.scenario_id",
                tool_calls_path="calls",
                tool_results_path="results",
                tool_call_id_field="cid",
                tool_call_name_field="name",
                tool_result_call_id_field="cid",
                tool_result_name_field="name",
            )

    def test_dollar_path_rejected(self):
        with pytest.raises(TraceImportError, match="unsupported mapping path"):
            SimpleMappingConfig(
                scenario_id_path="$.scenario_id",
                tool_calls_path="calls",
                tool_results_path="results",
                tool_call_id_field="cid",
                tool_call_name_field="name",
                tool_result_call_id_field="cid",
                tool_result_name_field="name",
            )

    def test_bracket_star_path_rejected(self):
        with pytest.raises(TraceImportError, match="unsupported mapping path"):
            SimpleMappingConfig(
                scenario_id_path="items[*].scenario_id",
                tool_calls_path="calls",
                tool_results_path="results",
                tool_call_id_field="cid",
                tool_call_name_field="name",
                tool_result_call_id_field="cid",
                tool_result_name_field="name",
            )

    def test_field_path_dotted_rejected(self):
        with pytest.raises(TraceImportError, match="unsupported mapping path"):
            SimpleMappingConfig(
                scenario_id_path="sid",
                tool_calls_path="calls",
                tool_results_path="results",
                tool_call_id_field="data.cid",
                tool_call_name_field="name",
                tool_result_call_id_field="cid",
                tool_result_name_field="name",
            )


# ---------------------------------------------------------------------------
# 边界行为
# ---------------------------------------------------------------------------


class TestBoundaryBehavior:
    """不读 .env / 不调外部 API / 不生成 ReviewDecision / native 兼容。"""

    def test_native_mode_unaffected(self):
        """native mode 不传 mapping 时行为不变。"""
        from tests.test_trace_import_adapter import _valid_trace_dict

        trace = TraceImportAdapter().import_dict(_valid_trace_dict())
        assert trace.scenario_id == "test-scenario"

    def test_native_mode_explicit_still_works(self):
        from tests.test_trace_import_adapter import _valid_trace_dict

        trace = TraceImportAdapter(mode="native").import_dict(_valid_trace_dict())
        assert trace.scenario_id == "test-scenario"

    def test_no_env_read(self):
        import os

        saved = dict(os.environ)
        os.environ.clear()
        try:
            trace = TraceImportAdapter(
                mode="simple_mapping", mapping=_make_mapping()
            ).import_dict(_user_trace_dict())
            assert trace.scenario_id == "test-scenario"
        finally:
            os.environ.update(saved)

    def test_no_review_decision(self):
        import agent_tool_harness.trace_import as ti

        # SimpleMappingConfig 不应导入或构造 ReviewDecision
        assert "ReviewDecision" not in ti.SimpleMappingConfig.__dict__


# ---------------------------------------------------------------------------
# Core Flow 集成
# ---------------------------------------------------------------------------


class TestCoreFlowIntegration:
    """simple mapping 导入的 Evidence 可进入 CoreEvaluation。"""

    @staticmethod
    def _make_eval_spec(eval_id: str = "test-scenario") -> EvalSpec:
        return EvalSpec(
            id=eval_id,
            name="test",
            category="integration",
            split="test",
            realism_level="mock",
            complexity="low",
            source="test",
            user_prompt="trace import test",
            initial_context={},
            verifiable_outcome={},
            success_criteria=[],
            expected_tool_behavior={"required_tools": ["kb.search"]},
            judge={},
        )

    def test_core_evaluation_consumes_simple_mapped_evidence(self):
        adapter = TraceImportAdapter(
            mode="simple_mapping", mapping=_make_mapping()
        )
        trace = adapter.import_dict(_user_trace_dict())
        evidence = adapter.to_evidence(trace)
        result = CoreEvaluation().evaluate(evidence, self._make_eval_spec())
        assert result.scenario_id == "test-scenario"
        assert len(result.findings) > 0
