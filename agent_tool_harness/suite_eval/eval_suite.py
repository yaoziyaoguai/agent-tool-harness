"""EvalSuite manifest —— v3.3 suite-level 评测入口。

架构边界
--------
- **负责**：定义 EvalSuite / EvalCaseRef / TraceInputRef 数据结构、
  从 YAML/dict 加载并校验。
- **不负责**：不做 aggregation、不做 report、不加载实际 EvalCase 或 trace 文件。
  这些由 SuiteEvaluator（P2）负责。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import yaml


@dataclass(frozen=True)
class EvalCaseRef:
    """suite manifest 中对一个 EvalCase YAML 文件的引用。"""

    case_path: str
    """相对于 suite manifest YAML 所在目录的 EvalCase 文件路径。"""

    case_id: str
    """对应 EvalCase.case_id，用于在 suite 内匹配 trace_inputs。"""


@dataclass(frozen=True)
class TraceInputRef:
    """suite manifest 中对一条 trace JSON 文件的引用。"""

    trace_path: str
    """相对于 suite manifest YAML 所在目录的 trace 文件路径。"""

    case_id: str
    """关联的 EvalCase.case_id，一条 case 可以对应多条 trace。"""


@dataclass(frozen=True)
class EvalSuite:
    """一次 suite 级评测的 manifest。

    EvalSuite 是纯引用文件——它不内嵌 EvalCase 或 trace 数据，
    而是通过 EvalCaseRef / TraceInputRef 指向外部文件。
    SuiteEvaluator 在 evaluate() 时按需加载这些文件。

    设计原则：
    - YAML manifest 与 project.yaml / tools.yaml / evals.yaml 风格一致
    - cases 和 trace_inputs 分离，支持一对多（一个 case 对应多条 trace）
    - metadata 自由扩展，不限制 key
    """

    suite_id: str
    """suite 唯一标识。"""

    name: str
    """人类可读的 suite 名称。"""

    cases: list[EvalCaseRef] = field(default_factory=list)
    """suite 包含的 EvalCase 引用列表。"""

    trace_inputs: list[TraceInputRef] = field(default_factory=list)
    """suite 包含的 trace 引用列表。"""

    description: str = ""
    """suite 的可选描述。"""

    tags: list[str] = field(default_factory=list)
    """suite 的可选标签。"""

    metadata: dict[str, str] = field(default_factory=dict)
    """自由扩展元数据（agent_version, harness_version 等）。"""


# ---------------------------------------------------------------------------
# 从 YAML 加载
# ---------------------------------------------------------------------------


def load_eval_suite(yaml_path: str) -> EvalSuite:
    """从 YAML manifest 文件加载 EvalSuite。

    YAML 格式示例::

        suite_id: "ks-suite-001"
        name: "Knowledge Search Eval Suite"
        description: "验证知识搜索工具在不同难度 case 上的表现"
        cases:
          - case_path: "cases/ks-001.yaml"
            case_id: "ks-001"
        trace_inputs:
          - trace_path: "traces/trace_001.json"
            case_id: "ks-001"
        tags: ["knowledge_search", "regression"]
        metadata:
          agent_version: "2.3.0"

    Args:
        yaml_path: YAML manifest 文件路径。

    Returns:
        EvalSuite 实例。

    Raises:
        FileNotFoundError: 文件不存在。
        ValueError: 缺少必填字段或格式错误。
        yaml.YAMLError: YAML 解析错误。
    """
    with open(yaml_path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError(f"EvalSuite YAML 必须是 mapping，收到: {type(data).__name__}")

    return _dict_to_eval_suite(data)


# ---------------------------------------------------------------------------
# 从 dict 加载（供测试和内部调用使用）
# ---------------------------------------------------------------------------


def _dict_to_eval_suite(data: dict) -> EvalSuite:
    """从 dict 构造 EvalSuite，含完整校验。"""
    suite_id = data.get("suite_id")
    if not suite_id or not isinstance(suite_id, str):
        raise ValueError("EvalSuite 缺少必填字段 suite_id（非空字符串）")

    name = data.get("name")
    if not name or not isinstance(name, str):
        raise ValueError("EvalSuite 缺少必填字段 name（非空字符串）")

    # cases
    cases_raw = data.get("cases", [])
    if not isinstance(cases_raw, list):
        raise ValueError("cases 必须是 list")
    cases = _parse_case_refs(cases_raw)

    # trace_inputs
    traces_raw = data.get("trace_inputs", [])
    if not isinstance(traces_raw, list):
        raise ValueError("trace_inputs 必须是 list")
    trace_inputs = _parse_trace_refs(traces_raw)

    # 可选字段
    description = data.get("description", "")
    if not isinstance(description, str):
        raise ValueError("description 必须是字符串")

    tags = data.get("tags", [])
    if not isinstance(tags, list):
        raise ValueError("tags 必须是 list")
    for t in tags:
        if not isinstance(t, str):
            raise ValueError(f"tags 中每个元素必须是字符串，收到: {type(t).__name__}")

    metadata = data.get("metadata", {})
    if not isinstance(metadata, dict):
        raise ValueError("metadata 必须是 dict")
    for k, v in metadata.items():
        if not isinstance(k, str) or not isinstance(v, str):
            raise ValueError("metadata 的所有 key/value 必须是字符串")

    return EvalSuite(
        suite_id=suite_id,
        name=name,
        cases=cases,
        trace_inputs=trace_inputs,
        description=description,
        tags=tags,
        metadata=metadata,
    )


def _parse_case_refs(raw: list) -> list[EvalCaseRef]:
    """解析 cases 列表中的每个 entry 为 EvalCaseRef。"""
    refs: list[EvalCaseRef] = []
    seen_ids: set[str] = set()
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"cases[{i}] 必须是 mapping，收到: {type(entry).__name__}")
        case_path = entry.get("case_path", "")
        if not case_path or not isinstance(case_path, str):
            raise ValueError(f"cases[{i}].case_path 缺失或非字符串")
        case_id = entry.get("case_id", "")
        if not case_id or not isinstance(case_id, str):
            raise ValueError(f"cases[{i}].case_id 缺失或非字符串")
        if case_id in seen_ids:
            raise ValueError(f"cases 中 case_id 重复: {case_id}")
        seen_ids.add(case_id)
        refs.append(EvalCaseRef(case_path=case_path, case_id=case_id))
    return refs


def _parse_trace_refs(raw: list) -> list[TraceInputRef]:
    """解析 trace_inputs 列表中的每个 entry 为 TraceInputRef。"""
    refs: list[TraceInputRef] = []
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ValueError(f"trace_inputs[{i}] 必须是 mapping，收到: {type(entry).__name__}")
        trace_path = entry.get("trace_path", "")
        if not trace_path or not isinstance(trace_path, str):
            raise ValueError(f"trace_inputs[{i}].trace_path 缺失或非字符串")
        case_id = entry.get("case_id", "")
        if not case_id or not isinstance(case_id, str):
            raise ValueError(f"trace_inputs[{i}].case_id 缺失或非字符串")
        refs.append(TraceInputRef(trace_path=trace_path, case_id=case_id))
    return refs
