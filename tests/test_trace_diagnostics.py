"""Trace diagnostics 测试。

覆盖:
- FieldCoverageReport: full coverage, partial coverage, extra source keys, all unmapped
- FieldTypeReport / TypeDiagnostic: all pass, type errors, list type errors
- TraceConfidence: native high/medium, simple_mapping medium/low
- DryRunResult: dry_run passes, dry_run catches errors, dry_run_native passes/fails
- 边界: empty data, empty lists, non-dict items, missing optional mapping
"""

from __future__ import annotations

import pytest

from agent_tool_harness.trace_diagnostics import (
    FieldCoverageReport,
    FieldTypeReport,
    TraceConfidence,
    TraceDiagnostics,
    TraceProvenance,
    TypeDiagnostic,
)
from agent_tool_harness.trace_import import SimpleMappingConfig

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _make_mapping(**overrides) -> SimpleMappingConfig:
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


def _native_trace_dict(**overrides) -> dict:
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


# ---------------------------------------------------------------------------
# FieldCoverageReport
# ---------------------------------------------------------------------------


class TestFieldCoverageFull:
    def test_all_required_fields_mapped(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        report = diag.check_field_coverage(data, mapping)

        assert report.coverage_ratio == 1.0
        assert report.mapped_required == 10
        assert report.unmapped_required == []
        # final_answer + messages + observations + tool_results[].error
        assert report.mapped_optional == 4
        # tool_calls[].timestamp: ts key 不在 call item 中
        assert report.unmapped_optional == ["tool_calls[].timestamp"]
        assert report.extra_source_keys == []

    def test_coverage_ratio_is_float(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        report = diag.check_field_coverage(data, mapping)
        assert isinstance(report.coverage_ratio, float)
        assert 0.0 <= report.coverage_ratio <= 1.0


class TestFieldCoveragePartial:
    def test_missing_scenario_id_source_key(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        del data["sid"]
        report = diag.check_field_coverage(data, mapping)

        assert "scenario_id" in report.unmapped_required
        assert report.coverage_ratio < 1.0

    def test_missing_tool_calls_source_key(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        del data["calls"]
        report = diag.check_field_coverage(data, mapping)

        assert "tool_calls" in report.unmapped_required
        # 列表内字段也无法映射
        assert any("tool_calls[]" in u for u in report.unmapped_required)

    def test_empty_tool_calls_list(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        data["calls"] = []
        report = diag.check_field_coverage(data, mapping)

        assert "tool_calls" in report.unmapped_required

    def test_extra_source_keys_reported(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        data["extra_field"] = "unused"
        data["another_extra"] = 42
        report = diag.check_field_coverage(data, mapping)

        assert "another_extra" in report.extra_source_keys
        assert "extra_field" in report.extra_source_keys
        assert len(report.warnings) >= 1

    def test_all_unmapped(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data: dict = {}
        report = diag.check_field_coverage(data, mapping)

        assert report.coverage_ratio == 0.0
        assert report.mapped_required == 0
        assert len(report.unmapped_required) == 10


class TestFieldCoverageOptional:
    def test_optional_fields_not_in_mapping_not_counted(self):
        """可选字段如果 mapping 未配置，不算 unmapped。"""
        diag = TraceDiagnostics()
        mapping = _make_mapping(
            final_answer_path=None,
            messages_path=None,
            observations_path=None,
        )
        data = _user_trace_dict()
        report = diag.check_field_coverage(data, mapping)

        # 可选字段未配 mapping 不应出现在 unmapped_optional
        # timestamp/error mapping 仍活跃（_make_mapping 默认），
        # 但 ts 不在 user_trace_dict item 中 → unmapped
        assert "final_answer" not in report.unmapped_optional
        assert "messages" not in report.unmapped_optional
        assert "observations" not in report.unmapped_optional
        # timestamp 的 mapping 仍活跃，item 中没有 ts → unmapped
        assert "tool_calls[].timestamp" in report.unmapped_optional

    def test_optional_field_present_but_mapping_missing(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping(final_answer_path=None)
        data = _user_trace_dict()
        report = diag.check_field_coverage(data, mapping)

        assert "final_answer" not in report.unmapped_optional


# ---------------------------------------------------------------------------
# FieldTypeReport / TypeDiagnostic
# ---------------------------------------------------------------------------


class TestFieldTypeAllPass:
    def test_all_types_correct(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        report = diag.check_field_types(data, mapping)

        assert report.all_passed is True
        assert report.error_count == 0
        for d in report.diagnostics:
            assert d.passed is True

    def test_diagnostics_non_empty(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        report = diag.check_field_types(data, mapping)

        assert len(report.diagnostics) > 0


class TestFieldTypeErrors:
    def test_scenario_id_wrong_type(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        data["sid"] = 12345  # 应为 str
        report = diag.check_field_types(data, mapping)

        assert report.all_passed is False
        assert report.error_count >= 1
        scenario_diag = [
            d for d in report.diagnostics if "scenario_id" in d.field_path
        ]
        assert len(scenario_diag) >= 1
        assert scenario_diag[0].passed is False
        assert scenario_diag[0].expected_type == "str"
        assert scenario_diag[0].actual_type == "int"

    def test_tool_calls_not_a_list(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        data["calls"] = "not a list"
        report = diag.check_field_types(data, mapping)

        assert report.error_count >= 1
        calls_diag = [
            d for d in report.diagnostics if d.field_path.startswith("calls")
        ]
        assert len(calls_diag) >= 1
        assert calls_diag[0].passed is False

    def test_tool_call_item_field_wrong_type(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        data["calls"][0]["cid"] = 999  # 应为 str
        report = diag.check_field_types(data, mapping)

        assert report.error_count >= 1
        cid_diag = [d for d in report.diagnostics if "call_id" in d.field_path]
        assert any(not d.passed for d in cid_diag)

    def test_arguments_not_dict(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        data["calls"][0]["args"] = ["not", "a", "dict"]
        report = diag.check_field_types(data, mapping)

        args_diag = [d for d in report.diagnostics if "arguments" in d.field_path]
        assert any(not d.passed for d in args_diag)


class TestFieldTypeReportProperties:
    def test_all_passed_true_when_no_errors(self):
        report = FieldTypeReport(
            diagnostics=[
                TypeDiagnostic(
                    field_path="x",
                    expected_type="str",
                    actual_type="str",
                    actual_value_repr="'x'",
                    passed=True,
                )
            ],
            all_passed=True,
            error_count=0,
        )
        assert report.all_passed is True
        assert report.error_count == 0

    def test_frozen(self):
        report = FieldTypeReport()
        with pytest.raises(AttributeError):
            report.all_passed = False  # type: ignore[misc]


# ---------------------------------------------------------------------------
# TraceConfidence
# ---------------------------------------------------------------------------


class TestTraceConfidence:
    def test_native_high_confidence(self):
        diag = TraceDiagnostics()
        coverage = FieldCoverageReport(
            total_required=10,
            mapped_required=10,
            unmapped_required=[],
            mapped_optional=3,
            unmapped_optional=[],
            extra_source_keys=[],
            coverage_ratio=1.0,
        )
        type_report = FieldTypeReport(all_passed=True, error_count=0)

        conf = diag.assess_confidence(
            provenance=TraceProvenance.NATIVE,
            coverage=coverage,
            type_report=type_report,
        )

        assert conf.level == "high"
        assert conf.provenance == TraceProvenance.NATIVE
        assert conf.warnings == []

    def test_native_with_type_errors_medium(self):
        diag = TraceDiagnostics()
        coverage = FieldCoverageReport(
            total_required=10,
            mapped_required=10,
            unmapped_required=[],
            mapped_optional=3,
            unmapped_optional=[],
            extra_source_keys=[],
            coverage_ratio=1.0,
        )
        type_report = FieldTypeReport(all_passed=False, error_count=2)

        conf = diag.assess_confidence(
            provenance=TraceProvenance.NATIVE,
            coverage=coverage,
            type_report=type_report,
        )

        assert conf.level == "medium"
        assert len(conf.warnings) >= 1

    def test_simple_mapping_full_coverage_medium(self):
        diag = TraceDiagnostics()
        coverage = FieldCoverageReport(
            total_required=10,
            mapped_required=10,
            unmapped_required=[],
            mapped_optional=3,
            unmapped_optional=[],
            extra_source_keys=[],
            coverage_ratio=1.0,
        )
        type_report = FieldTypeReport(all_passed=True, error_count=0)

        conf = diag.assess_confidence(
            provenance=TraceProvenance.SIMPLE_MAPPING,
            coverage=coverage,
            type_report=type_report,
        )

        assert conf.level == "medium"

    def test_simple_mapping_low_coverage_low(self):
        diag = TraceDiagnostics()
        coverage = FieldCoverageReport(
            total_required=10,
            mapped_required=5,
            unmapped_required=["scenario_id"],
            mapped_optional=0,
            unmapped_optional=[],
            extra_source_keys=[],
            coverage_ratio=0.5,
        )
        type_report = FieldTypeReport(all_passed=True, error_count=0)

        conf = diag.assess_confidence(
            provenance=TraceProvenance.SIMPLE_MAPPING,
            coverage=coverage,
            type_report=type_report,
        )

        assert conf.level == "low"
        assert any("覆盖率" in w for w in conf.warnings)

    def test_simple_mapping_type_errors_low(self):
        diag = TraceDiagnostics()
        coverage = FieldCoverageReport(
            total_required=10,
            mapped_required=10,
            unmapped_required=[],
            mapped_optional=3,
            unmapped_optional=[],
            extra_source_keys=[],
            coverage_ratio=1.0,
        )
        type_report = FieldTypeReport(all_passed=False, error_count=1)

        conf = diag.assess_confidence(
            provenance=TraceProvenance.SIMPLE_MAPPING,
            coverage=coverage,
            type_report=type_report,
        )

        assert conf.level == "low"

    def test_wrapper_bridge_always_low(self):
        diag = TraceDiagnostics()
        conf = diag.assess_confidence(
            provenance=TraceProvenance.WRAPPER_BRIDGE,
        )

        assert conf.level == "low"

    def test_confidence_is_frozen(self):
        conf = TraceConfidence(
            provenance=TraceProvenance.NATIVE,
            level="high",
            coverage_ratio=1.0,
            type_errors=0,
        )
        with pytest.raises(AttributeError):
            conf.level = "low"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# DryRunResult
# ---------------------------------------------------------------------------


class TestDryRunSimpleMapping:
    def test_passes_with_valid_data(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        result = diag.dry_run(data, mapping=mapping)

        assert result.passed is True
        assert result.mode == "simple_mapping"
        assert result.errors == []
        assert result.field_coverage.coverage_ratio == 1.0
        assert result.type_diagnostics.all_passed is True
        assert result.confidence.level == "medium"

    def test_catches_missing_mapping_target(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        del data["sid"]
        result = diag.dry_run(data, mapping=mapping)

        assert result.passed is False
        assert len(result.errors) >= 1
        assert any("sid" in e for e in result.errors)

    def test_catches_non_list_tool_calls(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        data["calls"] = "not a list"
        result = diag.dry_run(data, mapping=mapping)

        assert len(result.errors) >= 1

    def test_extra_source_keys_in_coverage(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        data["unused"] = "extra"
        result = diag.dry_run(data, mapping=mapping)

        assert "unused" in result.field_coverage.extra_source_keys

    def test_type_errors_affect_passed(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        data["sid"] = 123
        result = diag.dry_run(data, mapping=mapping)

        assert result.passed is False
        assert result.type_diagnostics.all_passed is False

    def test_result_is_frozen(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        result = diag.dry_run(data, mapping=mapping)
        with pytest.raises(AttributeError):
            result.passed = True  # type: ignore[misc]

    # ------------------------------------------------------------------
    # P2-1 修复验证: simple_mapping 语义不回归
    # ------------------------------------------------------------------

    def test_field_coverage_structure_preserved(self):
        """req 4: simple_mapping mode 仍保留 mapping field coverage。

        mapped_required / unmapped_required / mapped_optional /
        unmapped_optional / extra_source_keys 全部按 mapping 配置计算。
        """
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        result = diag.dry_run(data, mapping=mapping)

        fc = result.field_coverage
        assert fc.total_required == 10
        assert fc.mapped_required == 10
        assert fc.unmapped_required == []
        assert fc.mapped_optional >= 3  # final_answer + messages + observations
        # timestamp 的 mapping key "ts" 不在 item 中 → unmapped_optional
        assert "tool_calls[].timestamp" in fc.unmapped_optional

    def test_output_or_error_semantics_not_regressed(self):
        """req 5: simple_mapping output/error 字段映射不回归。

        output/error 字段在 simple_mapping 中被正确映射。mapping 层负责
        字段名映射和类型守卫；P2 output/error 非空校验在 _import_dict
        的 _parse_tool_results 中执行，dry_run 的 _apply_simple_mapping
        只做映射不执行下游校验。
        """
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        # 正常 output/error 字段映射 → dry_run 通过
        result = diag.dry_run(data, mapping=mapping)
        assert result.passed is True

        # 验证 output/error 字段已正确映射到 native schema
        # （通过 _apply_simple_mapping 模拟）
        from agent_tool_harness.trace_import import TraceImportAdapter

        mapped = TraceImportAdapter._apply_simple_mapping(data, mapping)
        assert mapped["tool_results"][0]["output"] == {"result": "ok"}
        assert mapped["tool_results"][0]["error"] is None

    def test_dry_run_success_behavior_not_regressed(self):
        """req 6: dry-run success 行为不回归。

        完整有效数据 → passed=True, medium confidence, 无 errors。
        """
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        result = diag.dry_run(data, mapping=mapping)

        assert result.passed is True
        assert result.mode == "simple_mapping"
        assert result.errors == []
        assert result.confidence.level == "medium"
        assert result.field_coverage.coverage_ratio == 1.0
        assert result.type_diagnostics.all_passed is True

    def test_dry_run_failure_behavior_not_regressed(self):
        """req 6: dry-run failure 行为不回归。

        空数据 → passed=False, low confidence, 有 errors。
        """
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data: dict = {}
        result = diag.dry_run(data, mapping=mapping)

        assert result.passed is False
        assert len(result.errors) >= 1
        assert result.field_coverage.coverage_ratio == 0.0
        assert result.confidence.level == "low"


class TestDryRunNative:
    def test_passes_with_valid_native_data(self):
        diag = TraceDiagnostics()
        data = _native_trace_dict()
        result = diag.dry_run_native(data)

        assert result.passed is True
        assert result.mode == "native"
        assert result.errors == []
        assert result.confidence.level == "high"

    def test_catches_missing_scenario_id(self):
        diag = TraceDiagnostics()
        data = _native_trace_dict()
        del data["scenario_id"]
        result = diag.dry_run_native(data)

        assert result.passed is False
        assert any("scenario_id" in e for e in result.errors)

    def test_catches_non_list_tool_calls(self):
        diag = TraceDiagnostics()
        data = _native_trace_dict()
        data["tool_calls"] = "not a list"
        result = diag.dry_run_native(data)

        assert any("tool_calls must be a list" in e for e in result.errors)

    def test_catches_empty_tool_calls(self):
        diag = TraceDiagnostics()
        data = _native_trace_dict()
        data["tool_calls"] = []
        result = diag.dry_run_native(data)

        assert any("tool_calls" in e for e in result.errors)

    def test_catches_missing_call_id(self):
        diag = TraceDiagnostics()
        data = _native_trace_dict()
        del data["tool_calls"][0]["call_id"]
        result = diag.dry_run_native(data)

        assert any("call_id" in e for e in result.errors)

    def test_catches_missing_output_and_error(self):
        diag = TraceDiagnostics()
        data = _native_trace_dict()
        data["tool_results"][0]["output"] = {}
        data["tool_results"][0]["error"] = None
        result = diag.dry_run_native(data)

        assert any("output or error" in e for e in result.errors)

    def test_catches_cross_ref_mismatch(self):
        diag = TraceDiagnostics()
        data = _native_trace_dict()
        data["tool_results"][0]["call_id"] = "nonexistent"
        result = diag.dry_run_native(data)

        assert any("找不到对应项" in e for e in result.errors)

    def test_native_with_wrong_types(self):
        diag = TraceDiagnostics()
        data = _native_trace_dict()
        data["tool_calls"][0]["arguments"] = "not dict"
        result = diag.dry_run_native(data)

        assert result.type_diagnostics.all_passed is False
        assert result.confidence.level == "medium"  # native + type errors

    # ------------------------------------------------------------------
    # P2-1 修复验证: native mode 不产生 simple_mapping-style 字段
    # ------------------------------------------------------------------

    def test_native_coverage_no_mapping_semantics(self):
        """req 1: native mode 不产生 simple_mapping-style unmapped mapping fields。

        native mode 没有 mapping config，coverage report 中的 mapped_optional /
        unmapped_optional / extra_source_keys 应始终为零/空。
        """
        diag = TraceDiagnostics()
        data = _native_trace_dict()
        result = diag.dry_run_native(data)

        fc = result.field_coverage
        assert fc.mapped_optional == 0
        assert fc.unmapped_optional == []
        assert fc.extra_source_keys == []

        # 即使数据有额外顶层 key，native mode 也不报告 extra
        data["custom_field"] = "anything"
        result2 = diag.dry_run_native(data)
        assert result2.field_coverage.extra_source_keys == []

    def test_native_optional_timestamp_missing_not_coverage_failure(self):
        """req 3: native mode optional timestamp 缺失不被当成 coverage failure。

        timestamp 是可选字段，不在 _NATIVE_REQUIRED_PATHS 中，
        缺失不应出现在 unmapped_required 中。
        """
        diag = TraceDiagnostics()
        data = _native_trace_dict()
        # 确保 tool_calls item 没有 timestamp
        assert "timestamp" not in data["tool_calls"][0]

        result = diag.dry_run_native(data)
        assert "timestamp" not in str(result.field_coverage.unmapped_required)
        assert result.passed is True
        assert result.field_coverage.coverage_ratio == 1.0

    def test_native_output_or_error_diagnostic_message(self):
        """req 2 补充: output/error 缺失时给出清晰 diagnostic message。

        区分 coverage 层（output key 存在即算 present）和 validation 层
        （output 非空 dict 或 error 非空 str 至少一个）。
        """
        diag = TraceDiagnostics()
        data = _native_trace_dict()
        data["tool_results"][0]["output"] = {}
        data["tool_results"][0]["error"] = None

        result = diag.dry_run_native(data)

        # coverage: output key 存在 → 不在 unmapped_required 中
        assert "tool_results[].output" not in result.field_coverage.unmapped_required
        # validation: output 为空 + error 为空 → 报错
        assert any("needs output or error" in e for e in result.errors)
        assert result.passed is False

    def test_native_missing_output_key_in_coverage(self):
        """output key 完全缺失时应出现在 coverage unmapped_required 中。"""
        diag = TraceDiagnostics()
        data = _native_trace_dict()
        del data["tool_results"][0]["output"]

        result = diag.dry_run_native(data)
        assert "tool_results[].output" in result.field_coverage.unmapped_required


class TestDryRunNativeNonDict:
    def test_non_dict_data(self):
        diag = TraceDiagnostics()
        result = diag.dry_run_native("not a dict")  # type: ignore[arg-type]

        assert result.passed is False
        assert len(result.errors) >= 1
        assert result.mode == "native"


# ---------------------------------------------------------------------------
# 边界情况
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_non_dict_items_in_tool_calls(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        data["calls"] = ["string instead of dict"]
        result = diag.dry_run(data, mapping=mapping)

        assert len(result.errors) >= 1

    def test_non_dict_items_in_tool_results(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        data["results"] = [123]
        result = diag.dry_run(data, mapping=mapping)

        assert len(result.errors) >= 1

    def test_mapping_without_optional_fields(self):
        """mapping 缺少可选字段配置不应报错。"""
        diag = TraceDiagnostics()
        mapping = _make_mapping(
            final_answer_path=None,
            messages_path=None,
            observations_path=None,
            tool_call_timestamp_field=None,
            tool_result_error_field=None,
        )
        data = _user_trace_dict()
        result = diag.dry_run(data, mapping=mapping)

        assert result.passed is True

    def test_type_diagnostic_value_truncation(self):
        """实际值过长时会被截断。"""
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        data["sid"] = "a" * 200
        report = diag.check_field_types(data, mapping)

        scenario_diag = [
            d for d in report.diagnostics if "scenario_id" in d.field_path
        ]
        assert len(scenario_diag) >= 1
        assert len(scenario_diag[0].actual_value_repr) <= 83  # 80 + "..."

    def test_empty_data_dict_dry_run(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data: dict = {}
        result = diag.dry_run(data, mapping=mapping)

        assert result.passed is False
        assert result.field_coverage.coverage_ratio == 0.0
        assert len(result.errors) >= 1

    def test_multiple_tool_calls_type_check(self):
        """类型检查只检查前 3 个 item。"""
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        # 添加多个 calls，只有前 3 个被检查
        for i in range(5):
            data["calls"].append(
                {"cid": f"c{i+2}", "name": f"tool.{i}", "args": {}}
            )
        report = diag.check_field_types(data, mapping)

        call_diags = [
            d
            for d in report.diagnostics
            if "tool_calls" in d.field_path and "call_id" in d.field_path
        ]
        assert len(call_diags) <= 3  # 只检查前 3 个 tool_calls item

    def test_coverage_report_frozen(self):
        report = FieldCoverageReport(
            total_required=10,
            mapped_required=10,
            unmapped_required=[],
            mapped_optional=0,
            unmapped_optional=[],
            extra_source_keys=[],
            coverage_ratio=1.0,
        )
        with pytest.raises(AttributeError):
            report.coverage_ratio = 0.5  # type: ignore[misc]

    def test_type_diagnostic_frozen(self):
        diag = TypeDiagnostic(
            field_path="x",
            expected_type="str",
            actual_type="int",
            actual_value_repr="1",
            passed=False,
        )
        with pytest.raises(AttributeError):
            diag.passed = True  # type: ignore[misc]

    def test_dry_run_result_frozen(self):
        diag = TraceDiagnostics()
        mapping = _make_mapping()
        data = _user_trace_dict()
        result = diag.dry_run(data, mapping=mapping)
        with pytest.raises(AttributeError):
            result.errors = ["new error"]  # type: ignore[misc]
