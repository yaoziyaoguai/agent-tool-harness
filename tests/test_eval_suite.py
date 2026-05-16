"""v3.3 P1: EvalSuite manifest 加载测试。"""

from __future__ import annotations

import tempfile
from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from agent_tool_harness.suite_eval.eval_suite import (
    EvalCaseRef,
    EvalSuite,
    TraceInputRef,
    _dict_to_eval_suite,
    load_eval_suite,
)

# ---------------------------------------------------------------------------
# EvalCaseRef / TraceInputRef
# ---------------------------------------------------------------------------


def test_eval_case_ref_creation():
    ref = EvalCaseRef(case_path="cases/ks-001.yaml", case_id="ks-001")
    assert ref.case_path == "cases/ks-001.yaml"
    assert ref.case_id == "ks-001"


def test_trace_input_ref_creation():
    ref = TraceInputRef(trace_path="traces/trace_001.json", case_id="ks-001")
    assert ref.trace_path == "traces/trace_001.json"
    assert ref.case_id == "ks-001"


def test_eval_case_ref_frozen():
    ref = EvalCaseRef(case_path="cases/ks-001.yaml", case_id="ks-001")
    with pytest.raises(FrozenInstanceError):
        ref.case_path = "other.yaml"  # type: ignore[misc]


def test_trace_input_ref_frozen():
    ref = TraceInputRef(trace_path="traces/trace_001.json", case_id="ks-001")
    with pytest.raises(FrozenInstanceError):
        ref.trace_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# EvalSuite 最小字段
# ---------------------------------------------------------------------------


def test_eval_suite_minimal():
    suite = EvalSuite(suite_id="suite-1", name="Test Suite")
    assert suite.suite_id == "suite-1"
    assert suite.name == "Test Suite"
    assert suite.cases == []
    assert suite.trace_inputs == []
    assert suite.description == ""
    assert suite.tags == []
    assert suite.metadata == {}


def test_eval_suite_full():
    cases = [EvalCaseRef(case_path="c.yaml", case_id="c1")]
    traces = [TraceInputRef(trace_path="t.json", case_id="c1")]
    suite = EvalSuite(
        suite_id="suite-1",
        name="Full Suite",
        cases=cases,
        trace_inputs=traces,
        description="a test suite",
        tags=["smoke", "regression"],
        metadata={"agent_version": "2.3.0"},
    )
    assert len(suite.cases) == 1
    assert len(suite.trace_inputs) == 1
    assert suite.description == "a test suite"
    assert suite.tags == ["smoke", "regression"]
    assert suite.metadata == {"agent_version": "2.3.0"}


def test_eval_suite_frozen():
    suite = EvalSuite(suite_id="s", name="n")
    with pytest.raises(FrozenInstanceError):
        suite.suite_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# dict 加载（校验路径）
# ---------------------------------------------------------------------------


def test_dict_load_minimal():
    suite = _dict_to_eval_suite({"suite_id": "s1", "name": "Minimal Suite"})
    assert suite.suite_id == "s1"
    assert suite.name == "Minimal Suite"
    assert suite.cases == []
    assert suite.trace_inputs == []


def test_dict_load_missing_suite_id():
    with pytest.raises(ValueError, match="suite_id"):
        _dict_to_eval_suite({"name": "No ID"})


def test_dict_load_empty_suite_id():
    with pytest.raises(ValueError, match="suite_id"):
        _dict_to_eval_suite({"suite_id": "", "name": "Empty ID"})


def test_dict_load_missing_name():
    with pytest.raises(ValueError, match="name"):
        _dict_to_eval_suite({"suite_id": "s1"})


def test_dict_load_with_cases():
    data = {
        "suite_id": "s1",
        "name": "Suite with cases",
        "cases": [
            {"case_path": "cases/a.yaml", "case_id": "a"},
            {"case_path": "cases/b.yaml", "case_id": "b"},
        ],
    }
    suite = _dict_to_eval_suite(data)
    assert len(suite.cases) == 2
    assert suite.cases[0].case_id == "a"
    assert suite.cases[1].case_path == "cases/b.yaml"


def test_dict_load_with_trace_inputs():
    data = {
        "suite_id": "s1",
        "name": "Suite with traces",
        "trace_inputs": [
            {"trace_path": "traces/t1.json", "case_id": "a"},
        ],
    }
    suite = _dict_to_eval_suite(data)
    assert len(suite.trace_inputs) == 1
    assert suite.trace_inputs[0].trace_path == "traces/t1.json"


def test_dict_load_with_optional_fields():
    data = {
        "suite_id": "s1",
        "name": "Full Suite",
        "description": "desc",
        "tags": ["smoke", "regression"],
        "metadata": {"harness_version": "3.3.0"},
    }
    suite = _dict_to_eval_suite(data)
    assert suite.description == "desc"
    assert suite.tags == ["smoke", "regression"]
    assert suite.metadata == {"harness_version": "3.3.0"}


def test_dict_load_duplicate_case_ids():
    data = {
        "suite_id": "s1",
        "name": "Dup IDs",
        "cases": [
            {"case_path": "a.yaml", "case_id": "dup"},
            {"case_path": "b.yaml", "case_id": "dup"},
        ],
    }
    with pytest.raises(ValueError, match="重复"):
        _dict_to_eval_suite(data)


def test_dict_load_invalid_cases_type():
    data = {"suite_id": "s1", "name": "Bad", "cases": "not_a_list"}
    with pytest.raises(ValueError, match="cases"):
        _dict_to_eval_suite(data)


def test_dict_load_case_missing_case_path():
    data = {
        "suite_id": "s1",
        "name": "Bad case",
        "cases": [{"case_id": "a"}],
    }
    with pytest.raises(ValueError, match="case_path"):
        _dict_to_eval_suite(data)


def test_dict_load_case_missing_case_id():
    data = {
        "suite_id": "s1",
        "name": "Bad case",
        "cases": [{"case_path": "a.yaml"}],
    }
    with pytest.raises(ValueError, match="case_id"):
        _dict_to_eval_suite(data)


def test_dict_load_invalid_tags():
    data = {"suite_id": "s1", "name": "Bad tags", "tags": [1, 2, 3]}
    with pytest.raises(ValueError, match="tags"):
        _dict_to_eval_suite(data)


def test_dict_load_invalid_metadata():
    data = {"suite_id": "s1", "name": "Bad meta", "metadata": {1: "val"}}
    with pytest.raises(ValueError, match="metadata"):
        _dict_to_eval_suite(data)


# ---------------------------------------------------------------------------
# YAML 文件加载
# ---------------------------------------------------------------------------


def test_yaml_load_minimal():
    yaml_content = """suite_id: "suite-minimal"
name: "Minimal Suite via YAML"
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        suite = load_eval_suite(tmp_path)
        assert suite.suite_id == "suite-minimal"
        assert suite.name == "Minimal Suite via YAML"
    finally:
        Path(tmp_path).unlink()


def test_yaml_load_full():
    yaml_content = """suite_id: "ks-suite-001"
name: "Knowledge Search Eval Suite"
description: "验证知识搜索工具"
cases:
  - case_path: "cases/ks-001.yaml"
    case_id: "ks-001"
  - case_path: "cases/ks-002.yaml"
    case_id: "ks-002"
trace_inputs:
  - trace_path: "traces/trace_001.json"
    case_id: "ks-001"
tags:
  - "knowledge_search"
  - "regression"
metadata:
  agent_version: "2.3.0"
  harness_version: "3.3.0"
"""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        suite = load_eval_suite(tmp_path)
        assert suite.suite_id == "ks-suite-001"
        assert suite.name == "Knowledge Search Eval Suite"
        assert suite.description == "验证知识搜索工具"
        assert len(suite.cases) == 2
        assert suite.cases[0].case_id == "ks-001"
        assert suite.cases[1].case_path == "cases/ks-002.yaml"
        assert len(suite.trace_inputs) == 1
        assert suite.trace_inputs[0].trace_path == "traces/trace_001.json"
        assert suite.tags == ["knowledge_search", "regression"]
        assert suite.metadata == {
            "agent_version": "2.3.0",
            "harness_version": "3.3.0",
        }
    finally:
        Path(tmp_path).unlink()


def test_yaml_load_file_not_found():
    with pytest.raises(FileNotFoundError):
        load_eval_suite("/nonexistent/path.yaml")


def test_yaml_load_not_a_dict():
    yaml_content = "- item1\n- item2\n"
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False, encoding="utf-8"
    ) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        with pytest.raises(ValueError, match="mapping"):
            load_eval_suite(tmp_path)
    finally:
        Path(tmp_path).unlink()
