"""Trace import diagnostics —— mapping 字段覆盖率 / 类型诊断 / 可信度 / dry-run。

架构边界
--------
- **负责**: 分析用户 trace 数据和 mapping 配置，产出结构化诊断报告。dry-run
  模拟 mapping 过程但不产生 ExecutionTrace。
- **不负责**: 不修改 trace、不产生 ExecutionTrace、不调用外部 API、不读 .env、
  不用 LLM 解析。
- **为什么独立于 TraceImportAdapter**: TraceImportAdapter 负责"导入或报错"——
  它是门禁。TraceDiagnostics 负责"分析并报告"——它是诊断工具。用户在 import
  之前用 dry-run 了解 mapping 质量，在 import 之后用 diagnostics 了解 trace
  可信度。两者职责不同，不应混在同一个类里。
- **所有检查 deterministic, zero-network, 不抛异常（dry-run 内部 catch）**。

与 TraceImportAdapter 的关系
----------------------------
- ``dry_run()`` 内部调用 ``TraceImportAdapter._apply_simple_mapping()`` 模拟映射
- ``dry_run_native()`` 独立校验 native schema 字段
- 所有诊断函数返回报告 dataclass，不抛异常
"""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Any

from agent_tool_harness.trace_import import (
    SimpleMappingConfig,
    TraceImportAdapter,
    TraceImportError,
)

# ---------------------------------------------------------------------------
# native schema required / optional field 定义
# ---------------------------------------------------------------------------

# native mode 必要顶层字段
_NATIVE_REQUIRED_TOP_FIELDS = ("scenario_id", "tool_calls", "tool_results")

# native mode 可选顶层字段
_NATIVE_OPTIONAL_TOP_FIELDS = ("final_answer", "messages", "observations")

# tool_call item 必要字段
_TOOL_CALL_REQUIRED_FIELDS = ("call_id", "tool_name", "arguments")

# tool_call item 可选字段
_TOOL_CALL_OPTIONAL_FIELDS = ("timestamp",)

# tool_result item 必要字段
_TOOL_RESULT_REQUIRED_FIELDS = ("call_id", "tool_name", "status", "output")

# tool_result item 可选字段
_TOOL_RESULT_OPTIONAL_FIELDS = ("error",)

# 所有 native required field path（用于 coverage 计算）
_NATIVE_REQUIRED_PATHS = [
    "scenario_id",
    "tool_calls",
    "tool_calls[].call_id",
    "tool_calls[].tool_name",
    "tool_calls[].arguments",
    "tool_results",
    "tool_results[].call_id",
    "tool_results[].tool_name",
    "tool_results[].status",
    "tool_results[].output",
]

# field path → expected Python type（用于 type diagnostics）
_FIELD_TYPE_EXPECTATIONS: dict[str, type | tuple] = {
    "scenario_id": str,
    "tool_calls": list,
    "tool_calls[].call_id": str,
    "tool_calls[].tool_name": str,
    "tool_calls[].arguments": dict,
    "tool_calls[].timestamp": str,
    "tool_results": list,
    "tool_results[].call_id": str,
    "tool_results[].tool_name": str,
    "tool_results[].status": str,
    "tool_results[].output": dict,
    "tool_results[].error": str,
    "final_answer": str,
    "messages": list,
    "observations": list,
}

# ---------------------------------------------------------------------------
# TraceProvenance
# ---------------------------------------------------------------------------


class TraceProvenance(enum.Enum):
    """trace 来源——决定 baseline 可信度等级。

    - NATIVE: 用户直接提供符合 ExecutionTrace schema 的 JSON，不经映射。
    - SIMPLE_MAPPING: 通过 SimpleMappingConfig 映射导入。
    - WRAPPER_BRIDGE: 从 demo adapter wrapper 桥接（deprecated path, 最低可信度）。
    """

    NATIVE = "native"
    SIMPLE_MAPPING = "simple_mapping"
    WRAPPER_BRIDGE = "wrapper_bridge"


# ---------------------------------------------------------------------------
# FieldCoverageReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FieldCoverageReport:
    """mapping 字段覆盖率诊断结果。

    报告哪些 native 必要字段被 mapping 覆盖，哪些 source key 未被 mapping 引用。
    """

    total_required: int
    """native schema 必要字段总数"""
    mapped_required: int
    """成功映射的必要字段数"""
    unmapped_required: list[str]
    """未被 mapping 覆盖的必要字段 native path 列表"""
    mapped_optional: int
    """成功映射的可选字段数"""
    unmapped_optional: list[str]
    """未被 mapping 覆盖的可选字段 native path 列表"""
    extra_source_keys: list[str]
    """source data 顶层 key 中未被 mapping 引用的 key 列表"""
    coverage_ratio: float
    """mapped_required / total_required，范围 [0.0, 1.0]"""
    warnings: list[str] = field(default_factory=list)
    """human-readable 警告"""


# ---------------------------------------------------------------------------
# TypeDiagnostic / FieldTypeReport
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TypeDiagnostic:
    """单个字段的类型诊断结果。"""

    field_path: str
    """native field path，如 'tool_calls[0].call_id'"""
    expected_type: str
    """期望的 Python type 名，如 'str'"""
    actual_type: str
    """实际的 Python type 名，如 'int'"""
    actual_value_repr: str
    """实际值的 repr，截断至 80 字符"""
    passed: bool
    """类型是否匹配"""


@dataclass(frozen=True)
class FieldTypeReport:
    """字段类型诊断汇总。"""

    diagnostics: list[TypeDiagnostic] = field(default_factory=list)
    """所有字段的类型诊断结果"""
    all_passed: bool = True
    """所有类型检查是否通过"""
    error_count: int = 0
    """类型不匹配的字段数"""


# ---------------------------------------------------------------------------
# TraceConfidence
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TraceConfidence:
    """trace 可信度评估。

    provenance 决定 baseline，coverage 和 type errors 做调整。
    """

    provenance: TraceProvenance
    """trace 来源"""
    level: str
    """可信度等级: 'high' | 'medium' | 'low'"""
    coverage_ratio: float
    """字段覆盖率"""
    type_errors: int
    """类型错误数"""
    warnings: list[str] = field(default_factory=list)
    """可信度相关的警告"""


# ---------------------------------------------------------------------------
# DryRunResult
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DryRunResult:
    """mapping dry-run 完整诊断结果。

    聚合字段覆盖率、类型诊断、可信度评估。errors 中包含会阻止 import 的问题。
    """

    passed: bool
    """所有校验是否通过（无 errors 且 type_diagnostics 全通过）"""
    mode: str
    """'native' | 'simple_mapping'"""
    field_coverage: FieldCoverageReport
    """字段覆盖率报告"""
    type_diagnostics: FieldTypeReport
    """字段类型诊断报告"""
    confidence: TraceConfidence
    """trace 可信度评估"""
    errors: list[str] = field(default_factory=list)
    """会阻止 import 的错误消息列表"""
    warnings: list[str] = field(default_factory=list)
    """不阻止 import 但值得注意的问题"""


# ---------------------------------------------------------------------------
# TraceDiagnostics
# ---------------------------------------------------------------------------


class TraceDiagnostics:
    """trace import 诊断工具。

    架构边界:
    - **负责**: 分析 trace 数据和 mapping 配置，产出结构化诊断报告。
    - **不负责**: 不修改 trace、不产生 ExecutionTrace、不抛异常（内部 catch）。
    - 所有方法 deterministic、zero-network。

    使用方式::

        diag = TraceDiagnostics()
        result = diag.dry_run(data, mapping=mapping_config)
        print(result.field_coverage.coverage_ratio)
        print(result.confidence.level)
    """

    # ------------------------------------------------------------------
    # dry_run (simple_mapping mode)
    # ------------------------------------------------------------------

    def dry_run(
        self, data: dict[str, Any], *, mapping: SimpleMappingConfig
    ) -> DryRunResult:
        """对 simple_mapping 模式执行 dry-run——不产生 ExecutionTrace。

        内部流程:
        1. 检查 field coverage
        2. 检查 field types
        3. 尝试实际 mapping（捕获 TraceImportError）
        4. 评估 confidence
        5. 聚合为 DryRunResult

        Returns:
            DryRunResult——即使 mapping 有错误也返回完整诊断，不抛异常。
        """
        errors: list[str] = []
        warnings: list[str] = []

        # 1. 字段覆盖率
        coverage = self.check_field_coverage(data, mapping)

        # 2. 字段类型诊断
        type_report = self.check_field_types(data, mapping)

        # 3. 尝试实际 mapping（捕获会阻止 import 的错误）
        try:
            TraceImportAdapter._apply_simple_mapping(data, mapping)
        except TraceImportError as exc:
            errors.append(str(exc))

        # 4. confidence
        confidence = self.assess_confidence(
            provenance=TraceProvenance.SIMPLE_MAPPING,
            coverage=coverage,
            type_report=type_report,
        )

        # 5. 汇总 warnings
        all_warnings = list(warnings) + coverage.warnings + confidence.warnings

        passed = len(errors) == 0 and type_report.all_passed

        return DryRunResult(
            passed=passed,
            mode="simple_mapping",
            field_coverage=coverage,
            type_diagnostics=type_report,
            confidence=confidence,
            errors=errors,
            warnings=all_warnings,
        )

    # ------------------------------------------------------------------
    # dry_run_native (native mode)
    # ------------------------------------------------------------------

    def dry_run_native(self, data: dict[str, Any]) -> DryRunResult:
        """对 native 模式执行 dry-run——不产生 ExecutionTrace。

        校验 native schema 必要字段和类型，但不创建 ExecutionTrace 对象。
        """
        errors: list[str] = []
        warnings: list[str] = []

        if not isinstance(data, dict):
            return DryRunResult(
                passed=False,
                mode="native",
                field_coverage=FieldCoverageReport(
                    total_required=len(_NATIVE_REQUIRED_PATHS),
                    mapped_required=0,
                    unmapped_required=list(_NATIVE_REQUIRED_PATHS),
                    mapped_optional=0,
                    unmapped_optional=[],
                    extra_source_keys=[],
                    coverage_ratio=0.0,
                    warnings=["trace data must be a JSON object"],
                ),
                type_diagnostics=FieldTypeReport(),
                confidence=TraceConfidence(
                    provenance=TraceProvenance.NATIVE,
                    level="low",
                    coverage_ratio=0.0,
                    type_errors=0,
                ),
                errors=["trace data must be a JSON object"],
            )

        # 1. 必要字段存在性检查（native mode 无 mapping config）
        coverage = self._check_native_coverage(data)

        # 2. 类型诊断
        type_report = self._check_native_types(data)

        # 3. 尝试校验（不创建对象，只做关键校验）
        native_errors = self._validate_native_schema(data)
        errors.extend(native_errors)

        # 4. confidence
        confidence = self.assess_confidence(
            provenance=TraceProvenance.NATIVE,
            coverage=coverage,
            type_report=type_report,
        )

        all_warnings = list(warnings) + coverage.warnings + confidence.warnings
        passed = len(errors) == 0 and type_report.all_passed

        return DryRunResult(
            passed=passed,
            mode="native",
            field_coverage=coverage,
            type_diagnostics=type_report,
            confidence=confidence,
            errors=errors,
            warnings=all_warnings,
        )

    # ------------------------------------------------------------------
    # check_field_coverage
    # ------------------------------------------------------------------

    def check_field_coverage(
        self, data: dict[str, Any], mapping: SimpleMappingConfig
    ) -> FieldCoverageReport:
        """检查 simple_mapping 配置对 source data 的字段覆盖率。

        对每个 native required field，检查 mapping 指向的 source key 是否存在。
        同时报告 source data 顶层 key 中未被 mapping 引用的 key。
        """
        warnings: list[str] = []

        # 构建 mapping 引用的所有 source key
        referenced_keys = self._collect_mapping_source_keys(mapping)
        source_keys = set(data.keys())
        extra = sorted(source_keys - referenced_keys)

        if extra:
            warnings.append(
                f"source data 中有 {len(extra)} 个未被 mapping 引用的顶层 key: "
                f"{', '.join(extra)}"
            )

        # 检查每个 native required path 对应的 source key 是否存在
        unmapped: list[str] = []
        mapped_count = 0

        for native_path in _NATIVE_REQUIRED_PATHS:
            source_key = self._native_path_to_source_key(native_path, mapping)
            if source_key is None:
                unmapped.append(native_path)
                continue
            # 顶层字段: 检查 key 是否存在于 source data
            if "[]" not in native_path:
                if source_key in data:
                    val = data[source_key]
                    if native_path == "scenario_id":
                        if isinstance(val, str) and val.strip():
                            mapped_count += 1
                        else:
                            unmapped.append(native_path)
                    elif native_path in ("tool_calls", "tool_results"):
                        if isinstance(val, list) and len(val) > 0:
                            mapped_count += 1
                        else:
                            unmapped.append(native_path)
                else:
                    unmapped.append(native_path)
            else:
                # 列表内字段: 检查 list 中第一个 item 是否有对应 key
                list_path = (
                    mapping.tool_calls_path
                    if "tool_calls" in native_path
                    else mapping.tool_results_path
                )
                source_list = data.get(list_path)
                if isinstance(source_list, list) and len(source_list) > 0:
                    first_item = source_list[0]
                    if isinstance(first_item, dict) and source_key in first_item:
                        mapped_count += 1
                    else:
                        unmapped.append(native_path)
                else:
                    unmapped.append(native_path)

        # 可选字段覆盖率
        unmapped_opt: list[str] = []
        mapped_opt = 0
        optional_paths = [
            "tool_calls[].timestamp",
            "tool_results[].error",
            "final_answer",
            "messages",
            "observations",
        ]
        for opt_path in optional_paths:
            source_key = self._native_path_to_source_key(opt_path, mapping)
            if source_key is None:
                continue  # 可选字段未配 mapping 不算 unmapped
            if "[]" not in opt_path:
                # 顶层可选字段
                if source_key in data:
                    mapped_opt += 1
                else:
                    unmapped_opt.append(opt_path)
            else:
                # 列表内可选字段: 检查第一个 item
                list_path = (
                    mapping.tool_calls_path
                    if "tool_calls" in opt_path
                    else mapping.tool_results_path
                )
                source_list = data.get(list_path)
                if isinstance(source_list, list) and len(source_list) > 0:
                    first_item = source_list[0]
                    if isinstance(first_item, dict) and source_key in first_item:
                        mapped_opt += 1
                    else:
                        unmapped_opt.append(opt_path)
                else:
                    unmapped_opt.append(opt_path)

        total = len(_NATIVE_REQUIRED_PATHS)
        ratio = mapped_count / total if total > 0 else 0.0

        return FieldCoverageReport(
            total_required=total,
            mapped_required=mapped_count,
            unmapped_required=unmapped,
            mapped_optional=mapped_opt,
            unmapped_optional=unmapped_opt,
            extra_source_keys=extra,
            coverage_ratio=ratio,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # check_field_types
    # ------------------------------------------------------------------

    def check_field_types(
        self, data: dict[str, Any], mapping: SimpleMappingConfig
    ) -> FieldTypeReport:
        """检查 simple_mapping 映射后各字段的类型是否符合 native schema 预期。"""
        diagnostics: list[TypeDiagnostic] = []
        error_count = 0

        # 顶层字段类型检查
        top_checks = [
            ("scenario_id", mapping.scenario_id_path),
            ("tool_calls", mapping.tool_calls_path),
            ("tool_results", mapping.tool_results_path),
        ]
        for native_path, source_key in top_checks:
            if source_key in data:
                diag = self._check_single_type(
                    data[source_key], native_path, source_key
                )
                diagnostics.append(diag)
                if not diag.passed:
                    error_count += 1

        # 可选顶层字段
        opt_top = [
            ("final_answer", mapping.final_answer_path),
            ("messages", mapping.messages_path),
            ("observations", mapping.observations_path),
        ]
        for native_path, source_key in opt_top:
            if source_key and source_key in data:
                diag = self._check_single_type(
                    data[source_key], native_path, source_key
                )
                diagnostics.append(diag)
                if not diag.passed:
                    error_count += 1

        # tool_calls list item 字段（检查前 3 个）
        calls_list = data.get(mapping.tool_calls_path)
        if isinstance(calls_list, list):
            for i, item in enumerate(calls_list[:3]):
                if not isinstance(item, dict):
                    continue
                item_checks = [
                    (f"tool_calls[{i}].call_id", mapping.tool_call_id_field),
                    (f"tool_calls[{i}].tool_name", mapping.tool_call_name_field),
                ]
                for native_path, field_key in item_checks:
                    if field_key in item:
                        diag = self._check_single_type(
                            item[field_key], native_path, field_key
                        )
                        diagnostics.append(diag)
                        if not diag.passed:
                            error_count += 1
                # arguments
                args_key = mapping.tool_call_arguments_field
                if args_key and args_key in item:
                    diag = self._check_single_type(
                        item[args_key],
                        f"tool_calls[{i}].arguments",
                        args_key,
                    )
                    diagnostics.append(diag)
                    if not diag.passed:
                        error_count += 1
                # timestamp (optional)
                ts_key = mapping.tool_call_timestamp_field
                if ts_key and ts_key in item and item[ts_key] is not None:
                    diag = self._check_single_type(
                        item[ts_key],
                        f"tool_calls[{i}].timestamp",
                        ts_key,
                    )
                    diagnostics.append(diag)
                    if not diag.passed:
                        error_count += 1

        # tool_results list item 字段（检查前 3 个）
        results_list = data.get(mapping.tool_results_path)
        if isinstance(results_list, list):
            for i, item in enumerate(results_list[:3]):
                if not isinstance(item, dict):
                    continue
                item_checks = [
                    (f"tool_results[{i}].call_id", mapping.tool_result_call_id_field),
                    (
                        f"tool_results[{i}].tool_name",
                        mapping.tool_result_name_field,
                    ),
                ]
                for native_path, field_key in item_checks:
                    if field_key in item:
                        diag = self._check_single_type(
                            item[field_key], native_path, field_key
                        )
                        diagnostics.append(diag)
                        if not diag.passed:
                            error_count += 1
                # status
                status_key = mapping.tool_result_status_field
                if status_key and status_key in item:
                    diag = self._check_single_type(
                        item[status_key],
                        f"tool_results[{i}].status",
                        status_key,
                    )
                    diagnostics.append(diag)
                    if not diag.passed:
                        error_count += 1
                # output
                output_key = mapping.tool_result_output_field
                if output_key and output_key in item:
                    diag = self._check_single_type(
                        item[output_key],
                        f"tool_results[{i}].output",
                        output_key,
                    )
                    diagnostics.append(diag)
                    if not diag.passed:
                        error_count += 1
                # error (optional)
                err_key = mapping.tool_result_error_field
                if err_key and err_key in item and item[err_key] is not None:
                    diag = self._check_single_type(
                        item[err_key],
                        f"tool_results[{i}].error",
                        err_key,
                    )
                    diagnostics.append(diag)
                    if not diag.passed:
                        error_count += 1

        all_passed = error_count == 0
        return FieldTypeReport(
            diagnostics=diagnostics,
            all_passed=all_passed,
            error_count=error_count,
        )

    # ------------------------------------------------------------------
    # assess_confidence
    # ------------------------------------------------------------------

    def assess_confidence(
        self,
        *,
        provenance: TraceProvenance,
        coverage: FieldCoverageReport | None = None,
        type_report: FieldTypeReport | None = None,
    ) -> TraceConfidence:
        """评估 trace 可信度。

        规则:
        - NATIVE → baseline high, type errors > 0 → medium
        - SIMPLE_MAPPING + coverage >= 0.9 + type errors == 0 → medium
        - SIMPLE_MAPPING + coverage < 0.9 or type errors > 0 → low
        - WRAPPER_BRIDGE → always low
        """
        warnings: list[str] = []
        type_errors = type_report.error_count if type_report else 0
        cov_ratio = coverage.coverage_ratio if coverage else 0.0

        if provenance == TraceProvenance.NATIVE:
            if type_errors == 0:
                level = "high"
            else:
                level = "medium"
                warnings.append(
                    f"native schema 但有 {type_errors} 个类型错误，"
                    f"可信度降为 medium"
                )
        elif provenance == TraceProvenance.SIMPLE_MAPPING:
            if cov_ratio >= 0.9 and type_errors == 0:
                level = "medium"
            else:
                level = "low"
                if cov_ratio < 0.9:
                    warnings.append(
                        f"字段覆盖率 {cov_ratio:.0%} 低于 90%，可信度为 low"
                    )
                if type_errors > 0:
                    warnings.append(
                        f"{type_errors} 个字段类型错误，可信度为 low"
                    )
        else:  # WRAPPER_BRIDGE
            level = "low"
            warnings.append("wrapper_bridge 路径已弃用，可信度固定为 low")

        return TraceConfidence(
            provenance=provenance,
            level=level,
            coverage_ratio=cov_ratio,
            type_errors=type_errors,
            warnings=warnings,
        )

    # ------------------------------------------------------------------
    # 内部 helper
    # ------------------------------------------------------------------

    @staticmethod
    def _native_path_to_source_key(
        native_path: str, mapping: SimpleMappingConfig
    ) -> str | None:
        """将 native field path 映射到 source key。

        Returns None 表示该 native path 在 mapping config 中没有对应项。
        """
        path_to_source: dict[str, str | None] = {
            "scenario_id": mapping.scenario_id_path,
            "tool_calls": mapping.tool_calls_path,
            "tool_results": mapping.tool_results_path,
            "final_answer": mapping.final_answer_path,
            "messages": mapping.messages_path,
            "observations": mapping.observations_path,
            "tool_calls[].call_id": mapping.tool_call_id_field,
            "tool_calls[].tool_name": mapping.tool_call_name_field,
            "tool_calls[].arguments": mapping.tool_call_arguments_field,
            "tool_calls[].timestamp": mapping.tool_call_timestamp_field,
            "tool_results[].call_id": mapping.tool_result_call_id_field,
            "tool_results[].tool_name": mapping.tool_result_name_field,
            "tool_results[].status": mapping.tool_result_status_field,
            "tool_results[].output": mapping.tool_result_output_field,
            "tool_results[].error": mapping.tool_result_error_field,
        }
        return path_to_source.get(native_path)

    @staticmethod
    def _collect_mapping_source_keys(mapping: SimpleMappingConfig) -> set[str]:
        """收集 mapping config 中引用的所有 source key。"""
        keys: set[str] = set()
        for attr in (
            "scenario_id_path",
            "tool_calls_path",
            "tool_results_path",
            "final_answer_path",
            "messages_path",
            "observations_path",
        ):
            val = getattr(mapping, attr, None)
            if isinstance(val, str):
                keys.add(val)
        return keys

    @staticmethod
    def _check_single_type(
        value: Any, native_path: str, source_key: str
    ) -> TypeDiagnostic:
        """检查单个值的类型是否匹配 native schema 预期。"""
        # normalize list item paths: tool_calls[0].call_id → tool_calls[].call_id
        lookup_path = re.sub(r"\[\d+\]", "[]", native_path)
        expected = _FIELD_TYPE_EXPECTATIONS.get(lookup_path)
        if expected is None:
            return TypeDiagnostic(
                field_path=f"{source_key} → {native_path}",
                expected_type="any",
                actual_type=type(value).__name__,
                actual_value_repr=_truncate_repr(value),
                passed=True,
            )

        # 对于 list 和 dict，允许子类型
        actual_type = type(value)
        if expected is str:
            passed = isinstance(value, str)
        elif expected is dict:
            passed = isinstance(value, dict)
        elif expected is list:
            passed = isinstance(value, list)
        else:
            passed = isinstance(value, expected)

        return TypeDiagnostic(
            field_path=f"{source_key} → {native_path}",
            expected_type=expected.__name__,
            actual_type=actual_type.__name__,
            actual_value_repr=_truncate_repr(value),
            passed=passed,
        )

    @staticmethod
    def _check_native_coverage(data: dict[str, Any]) -> FieldCoverageReport:
        """native mode 必要字段存在性检查。

        native mode 没有 mapping config——这里的 "coverage" 指 native schema
        required fields 是否在 data 中存在，而非 mapping 覆盖率。
        FieldCoverageReport.mapped_required 在此上下文中意为 "present required fields"。

        不做:
        - 不检查可选字段（native mode 无可选字段 mapping 概念）
        - 不检查 output/error 至少一个（那是 schema validation 的职责，
          由 _validate_native_schema 负责）
        """
        warnings: list[str] = []

        # 必要顶层字段存在性
        missing: list[str] = []
        present_count = 0
        for f in _NATIVE_REQUIRED_TOP_FIELDS:
            if f in data:
                val = data[f]
                if f == "scenario_id":
                    if isinstance(val, str) and val.strip():
                        present_count += 1
                    else:
                        missing.append(f)
                elif f in ("tool_calls", "tool_results"):
                    if isinstance(val, list) and len(val) > 0:
                        present_count += 1
                    else:
                        missing.append(f)
            else:
                missing.append(f)

        # 列表内必要字段存在性（检查第一个 item）
        for list_field in ("tool_calls", "tool_results"):
            items = data.get(list_field)
            if isinstance(items, list) and len(items) > 0:
                first = items[0]
                if isinstance(first, dict):
                    req_fields = (
                        _TOOL_CALL_REQUIRED_FIELDS
                        if list_field == "tool_calls"
                        else _TOOL_RESULT_REQUIRED_FIELDS
                    )
                    for sub_f in req_fields:
                        path = f"{list_field}[].{sub_f}"
                        if sub_f in first:
                            present_count += 1
                        else:
                            missing.append(path)

        total = len(_NATIVE_REQUIRED_PATHS)
        ratio = present_count / total if total > 0 else 0.0

        return FieldCoverageReport(
            total_required=total,
            mapped_required=present_count,
            unmapped_required=missing,
            mapped_optional=0,
            unmapped_optional=[],
            extra_source_keys=[],  # native mode: 所有顶层 key 都合法
            coverage_ratio=ratio,
            warnings=warnings,
        )

    @staticmethod
    def _check_native_types(data: dict[str, Any]) -> FieldTypeReport:
        """native mode 字段类型诊断。"""
        diagnostics: list[TypeDiagnostic] = []
        error_count = 0

        # 顶层字段
        for f in _NATIVE_REQUIRED_TOP_FIELDS + _NATIVE_OPTIONAL_TOP_FIELDS:
            if f in data:
                diag = TraceDiagnostics._check_single_type(data[f], f, f)
                diagnostics.append(diag)
                if not diag.passed:
                    error_count += 1

        # tool_calls items（前 3 个）
        for list_field in ("tool_calls", "tool_results"):
            items = data.get(list_field)
            if isinstance(items, list):
                for i, item in enumerate(items[:3]):
                    if not isinstance(item, dict):
                        continue
                    fields_to_check = (
                        _TOOL_CALL_REQUIRED_FIELDS + _TOOL_CALL_OPTIONAL_FIELDS
                        if list_field == "tool_calls"
                        else _TOOL_RESULT_REQUIRED_FIELDS + _TOOL_RESULT_OPTIONAL_FIELDS
                    )
                    for sub_f in fields_to_check:
                        if sub_f in item and item[sub_f] is not None:
                            path = f"{list_field}[{i}].{sub_f}"
                            diag = TraceDiagnostics._check_single_type(
                                item[sub_f], path, path
                            )
                            diagnostics.append(diag)
                            if not diag.passed:
                                error_count += 1

        return FieldTypeReport(
            diagnostics=diagnostics,
            all_passed=error_count == 0,
            error_count=error_count,
        )

    @staticmethod
    def _validate_native_schema(data: dict[str, Any]) -> list[str]:
        """native schema 关键校验——返回会阻止 import 的错误列表。

        这是 dry-run diagnostics 的 lightweight native schema check。
        **正式 import 仍以 TraceImportAdapter._import_dict 为准**——
        这里不能替代正式 import。如果 TraceImportAdapter 的 schema 规则扩展，
        需要同步更新此处或抽取 shared validator。

        与 TraceImportAdapter._import_dict 的校验对齐：
        - scenario_id 非空字符串
        - tool_calls / tool_results 为 list 且非空
        - 每个 item 有 call_id / tool_name
        - output 或 error 至少一个非空
        - call_id 交叉引用
        """
        errors: list[str] = []

        # scenario_id
        sid = data.get("scenario_id")
        if not isinstance(sid, str) or not sid.strip():
            errors.append("missing scenario_id")

        # tool_calls
        calls = data.get("tool_calls")
        if not isinstance(calls, list):
            errors.append("tool_calls must be a list")
        elif len(calls) == 0:
            errors.append("tool_calls 不能为空")
        else:
            for i, item in enumerate(calls):
                if not isinstance(item, dict):
                    errors.append(f"tool_calls[{i}] must be a JSON object")
                    continue
                cid = item.get("call_id")
                if not isinstance(cid, str) or not cid.strip():
                    errors.append(f"tool_calls[{i}] missing call_id")
                tname = item.get("tool_name")
                if not isinstance(tname, str) or not tname.strip():
                    errors.append(f"tool_calls[{i}] missing tool_name")

        # tool_results
        results = data.get("tool_results")
        if not isinstance(results, list):
            errors.append("tool_results must be a list")
        elif len(results) == 0:
            errors.append("tool_results 不能为空")
        else:
            for i, item in enumerate(results):
                if not isinstance(item, dict):
                    errors.append(f"tool_results[{i}] must be a JSON object")
                    continue
                cid = item.get("call_id")
                if not isinstance(cid, str) or not cid.strip():
                    errors.append(f"tool_results[{i}] missing call_id")
                tname = item.get("tool_name")
                if not isinstance(tname, str) or not tname.strip():
                    errors.append(f"tool_results[{i}] missing tool_name")
                # output or error at least one non-empty
                out = item.get("output")
                err = item.get("error")
                has_output = isinstance(out, dict) and len(out) > 0
                has_error = isinstance(err, str) and err.strip()
                if not has_output and not has_error:
                    errors.append(f"tool_results[{i}] needs output or error")

        # cross-ref: result call_ids must exist in calls
        if isinstance(calls, list) and isinstance(results, list):
            call_ids = {
                c["call_id"]
                for c in calls
                if isinstance(c, dict) and isinstance(c.get("call_id"), str)
            }
            for _i, r in enumerate(results):
                if isinstance(r, dict):
                    rcid = r.get("call_id")
                    if isinstance(rcid, str) and rcid not in call_ids:
                        errors.append(
                            f"tool_result.call_id={rcid!r} 在 tool_calls 中找不到对应项"
                        )

        return errors


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _truncate_repr(value: Any, max_len: int = 80) -> str:
    """截断 repr 到 max_len 字符。"""
    s = repr(value)
    if len(s) > max_len:
        s = s[: max_len - 3] + "..."
    return s
