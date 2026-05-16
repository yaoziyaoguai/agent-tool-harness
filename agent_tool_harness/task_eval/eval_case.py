"""EvalCase 和 ExpectedOutcome —— v3.2 任务级评测的输入 schema。

架构边界
--------
- **负责**：定义结构化评测用例（EvalCase）和期望输出（ExpectedOutcome）的数据结构，
  提供 YAML/dict 反序列化入口。
- **不负责**：不执行验证逻辑（那是 Verifier 的事）、不生成 TaskOutcome、
  不访问文件系统以外的 IO（YAML 加载是唯一 IO 入口）。
- **为什么 ExpectedOutcome 的所有字段都是可选 list/dict/None**：
  不同 eval case 需要不同的验证组合。空 ExpectedOutcome（所有字段默认空）
  表示"仅人工判定"，TaskEvaluator 会产出 status=inconclusive。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExpectedOutcome:
    """期望输出定义 —— Agent 完成任务后应满足的 ground truth。

    设计原则（来自 RFC 0003 Decision 2）：
    - 所有字段同时生效（AND 语义）。如果定义了 required_facts 和 forbidden_facts，
      两者都通过才算通过。
    - 所有字段默认空——空 ExpectedOutcome 表示"无法自动判定"。
    - required_facts / forbidden_facts 用 case-insensitive substring 匹配，
      避免引入 NLP 依赖。
    - regex_patterns 仍然是确定性的——不调 LLM。
    """

    required_facts: list[str] = field(default_factory=list)
    """Agent 答案必须包含的事实列表（case-insensitive 子串匹配）。"""

    forbidden_facts: list[str] = field(default_factory=list)
    """Agent 答案禁止包含的事实列表（case-insensitive 子串匹配）。"""

    expected_json_fields: dict[str, Any] = field(default_factory=dict)
    """期望 Agent 输出的 JSON 字段（递归子集匹配）。"""

    exact_answer: str | None = None
    """精确答案字符串（strip 后完全相等）。"""

    regex_patterns: list[str] = field(default_factory=list)
    """答案必须匹配的正则表达式列表（全部匹配才算通过）。"""

    human_notes: str | None = None
    """人工审核备注——不参与自动判定，仅供 reviewer 参考。"""


@dataclass(frozen=True)
class EvalCase:
    """一次结构化评测用例。

    设计原则（来自 RFC 0003 Decision 1-2）：
    - EvalCase 是纯数据对象——描述"测什么"，不描述"怎么测"。
    - expected_outcome 可为空——此时 TaskEvaluator 产出 inconclusive。
    - trace_ref 可选——允许先定义 eval case 再关联 trace。
    - difficulty / tags / metadata 用于分类和筛选，不影响判定逻辑。

    字段说明：
    - case_id: 全局唯一标识，用于 cross-referencing TaskOutcome
    - task: 给 Agent 的任务描述（用户问题）
    - input: 初始上下文（对话历史、系统 prompt 等）
    - expected_outcome: 期望输出，空则表示仅人工判定
    - trace_ref: 可选，关联已有 trace 的 scenario_id
    - tags: 分类标签（如 deployment、production）
    - difficulty: 难度等级（easy / medium / hard），默认 medium
    - metadata: 自定义元数据（如所有者、创建日期）
    """

    case_id: str
    task: str
    input: dict[str, Any] = field(default_factory=dict)
    expected_outcome: ExpectedOutcome = field(default_factory=ExpectedOutcome)
    trace_ref: str | None = None
    tags: list[str] = field(default_factory=list)
    difficulty: str = "medium"
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        """校验必填字段非空。

        frozen=True dataclass 用 object.__setattr__ 绕过冻结限制做校验——
        这是 Python dataclass 的标准 post_init 校验模式。
        """
        if not self.case_id or not isinstance(self.case_id, str):
            raise ValueError("EvalCase.case_id 必须是非空字符串")
        if not self.task or not isinstance(self.task, str):
            raise ValueError("EvalCase.task 必须是非空字符串")
        if self.difficulty not in ("easy", "medium", "hard"):
            raise ValueError(
                f"EvalCase.difficulty 必须是 'easy'/'medium'/'hard'，"
                f"当前值: {self.difficulty!r}"
            )


# ---------------------------------------------------------------------------
# 反序列化
# ---------------------------------------------------------------------------


def load_eval_case_from_dict(data: dict[str, Any]) -> EvalCase:
    """从 dict 构造 EvalCase。

    期望的 dict 结构（与 YAML 格式一致）：
        {
            "case_id": "ks-001",
            "task": "找到生产环境部署失败的根本原因",
            "input": {"context": "..."},
            "expected_outcome": {
                "required_facts": ["root cause"],
                "forbidden_facts": ["restart production"],
                "regex_patterns": ["error: .+ at .+"]
            },
            "trace_ref": null,
            "tags": ["deployment"],
            "difficulty": "medium",
            "metadata": {}
        }

    expected_outcome 键可选——不传则使用默认空 ExpectedOutcome。
    """
    case_id = data.get("case_id", "")
    task = data.get("task", "")

    # 构造 ExpectedOutcome
    outcome_data: dict[str, Any] = data.get("expected_outcome") or {}
    expected_outcome = ExpectedOutcome(
        required_facts=list(outcome_data.get("required_facts", [])),
        forbidden_facts=list(outcome_data.get("forbidden_facts", [])),
        expected_json_fields=dict(outcome_data.get("expected_json_fields", {})),
        exact_answer=outcome_data.get("exact_answer"),
        regex_patterns=list(outcome_data.get("regex_patterns", [])),
        human_notes=outcome_data.get("human_notes"),
    )

    return EvalCase(
        case_id=str(case_id),
        task=str(task),
        input=dict(data.get("input", {})),
        expected_outcome=expected_outcome,
        trace_ref=data.get("trace_ref"),
        tags=list(data.get("tags", [])),
        difficulty=str(data.get("difficulty", "medium")),
        metadata={str(k): str(v) for k, v in data.get("metadata", {}).items()},
    )


def load_eval_case_from_yaml(path: str | Path) -> EvalCase:
    """从 YAML 文件加载单个 EvalCase。

    使用 PyYAML 的 safe_load 防止任意代码执行。
    文件必须包含 EvalCase 的顶层 dict——不支持多文档 YAML。
    """
    import yaml

    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"EvalCase YAML 文件不存在: {path}")

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError(
            f"EvalCase YAML 必须是顶层 dict/mapping，"
            f"当前类型: {type(data).__name__}"
        )

    return load_eval_case_from_dict(data)
