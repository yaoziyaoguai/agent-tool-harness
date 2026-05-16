# SDD: Task-level Evaluation V3.2

> **Implementation Status: Planned** — 设计完成，实现未开始。

## TLDR

v3.2 在 v3.1 的 trace-level inspection 之上新增 5 个组件：EvalCase、ExpectedOutcome、Verifier（6 种实现）、TaskOutcome、TaskEvaluator。所有确定性组件零网络依赖。LLM verifier optional/advisory/explicit。TaskOutcome 不影响 EvaluationResult.passed。

---

## 1. EvalCase

### 1.1 数据结构

```python
@dataclass(frozen=True)
class EvalCase:
    case_id: str
    task: str                           # 用户问题描述
    input: dict[str, Any]               # 初始上下文
    expected_outcome: ExpectedOutcome
    trace_ref: str | None = None        # 可选，关联已有 trace
    tags: list[str] = field(default_factory=list)
    difficulty: str = "medium"          # easy / medium / hard
    metadata: dict[str, str] = field(default_factory=dict)
```

### 1.2 字段说明

| 字段 | 类型 | 必需 | 说明 |
|------|------|------|------|
| case_id | str | 是 | 全局唯一标识 |
| task | str | 是 | 给 Agent 的任务描述 |
| input | dict | 是 | 初始上下文（如对话历史、系统 prompt） |
| expected_outcome | ExpectedOutcome | 否 | 可以为空（仅人工判定） |
| trace_ref | str | 否 | 关联已有 trace 的 scenario_id |
| tags | list[str] | 否 | 分类标签 |
| difficulty | str | 否 | 难度等级 |
| metadata | dict | 否 | 自定义元数据 |

### 1.3 加载方式

EvalCase 可从 YAML 加载：

```yaml
case_id: "ks-001"
task: "找到生产环境最近一次部署失败的根本原因并给出修复建议"
input:
  context: "生产环境 deploy-service 在 2026-05-15 14:30 部署失败"
expected_outcome:
  required_facts:
    - "root cause"
    - "fix recommendation"
  forbidden_facts:
    - "restart production without approval"
difficulty: "medium"
tags: ["knowledge_search", "production"]
```

---

## 2. ExpectedOutcome

### 2.1 数据结构

```python
@dataclass(frozen=True)
class ExpectedOutcome:
    required_facts: list[str] = field(default_factory=list)
    forbidden_facts: list[str] = field(default_factory=list)
    expected_json_fields: dict[str, Any] = field(default_factory=dict)
    exact_answer: str | None = None
    regex_patterns: list[str] = field(default_factory=list)
    human_notes: str | None = None
```

### 2.2 字段说明

| 字段 | 说明 | 默认值 |
|------|------|--------|
| required_facts | Agent 答案必须包含的事实（case-insensitive substring） | [] |
| forbidden_facts | Agent 答案禁止包含的事实 | [] |
| expected_json_fields | Agent 输出的 JSON 必须包含的字段（递归子集匹配） | {} |
| exact_answer | 精确答案（字符串 strip 后相等） | None |
| regex_patterns | 答案必须匹配的正则表达式列表 | [] |
| human_notes | 人工审核备注（不参与自动判定） | None |

### 2.3 语义

ExpectedOutcome 中的所有字段都是"同时生效"的。如果定义了 `required_facts` 和 `forbidden_facts`，两者都通过才算通过。如果只定义了 `human_notes` 而没有任何可自动验证的字段，TaskOutcome.status = inconclusive。

---

## 3. Verifier

### 3.1 Protocol

```python
class Verifier(Protocol):
    def verify(
        self,
        answer_text: str,
        tool_outputs: list[dict[str, Any]],
    ) -> VerifierResult:
        ...
```

### 3.2 VerifierResult

```python
@dataclass(frozen=True)
class VerifierResult:
    verifier_name: str
    passed: bool
    matched: list[str]
    missing: list[str]
    details: str
```

### 3.3 具体实现

#### ContainsRequiredFacts

```python
class ContainsRequiredFacts:
    def __init__(self, required_facts: list[str]):
        self.required_facts = required_facts

    def verify(self, answer_text: str, tool_outputs) -> VerifierResult:
        answer_lower = answer_text.lower()
        matched = [f for f in self.required_facts if f.lower() in answer_lower]
        missing = [f for f in self.required_facts if f.lower() not in answer_lower]
        return VerifierResult(
            verifier_name="contains_required_facts",
            passed=len(missing) == 0,
            matched=matched,
            missing=missing,
            details=f"matched {len(matched)}/{len(self.required_facts)} required facts",
        )
```

#### ForbiddenFactsAbsent

```python
class ForbiddenFactsAbsent:
    def __init__(self, forbidden_facts: list[str]):
        self.forbidden_facts = forbidden_facts

    def verify(self, answer_text: str, tool_outputs) -> VerifierResult:
        answer_lower = answer_text.lower()
        found = [f for f in self.forbidden_facts if f.lower() in answer_lower]
        return VerifierResult(
            verifier_name="forbidden_facts_absent",
            passed=len(found) == 0,
            matched=[],
            missing=found,  # "missing" = found forbidden facts
            details=f"found {len(found)} forbidden facts" if found else "no forbidden facts found",
        )
```

#### JsonFieldMatch

```python
class JsonFieldMatch:
    def __init__(self, expected_fields: dict[str, Any]):
        self.expected_fields = expected_fields

    def verify(self, answer_text: str, tool_outputs) -> VerifierResult:
        # 在所有 tool_outputs 中搜索匹配的 JSON 子集
        ...
```

#### ExactMatch

```python
class ExactMatch:
    def __init__(self, expected: str):
        self.expected = expected.strip()

    def verify(self, answer_text: str, tool_outputs) -> VerifierResult:
        passed = answer_text.strip() == self.expected
        return VerifierResult(
            verifier_name="exact_match",
            passed=passed,
            matched=[self.expected] if passed else [],
            missing=[] if passed else [self.expected],
            details="exact match" if passed else f"expected '{self.expected[:50]}...'",
        )
```

#### RegexMatch

```python
class RegexMatch:
    def __init__(self, patterns: list[str]):
        self.patterns = [re.compile(p) for p in patterns]

    def verify(self, answer_text: str, tool_outputs) -> VerifierResult:
        matched = [p.pattern for p in self.patterns if p.search(answer_text)]
        missing = [p.pattern for p in self.patterns if not p.search(answer_text)]
        return VerifierResult(
            verifier_name="regex_match",
            passed=len(missing) == 0,
            matched=matched,
            missing=missing,
            details=f"matched {len(matched)}/{len(self.patterns)} patterns",
        )
```

#### CompositeVerifier

```python
class CompositeVerifier:
    def __init__(self, verifiers: list[Verifier], mode: str = "all"):
        self.verifiers = verifiers
        self.mode = mode  # "all" (AND) | "any" (OR)

    def verify(self, answer_text: str, tool_outputs) -> VerifierResult:
        results = [v.verify(answer_text, tool_outputs) for v in self.verifiers]
        if self.mode == "all":
            passed = all(r.passed for r in results)
        else:
            passed = any(r.passed for r in results)
        ...
```

---

## 4. TaskOutcome

### 4.1 数据结构

```python
@dataclass(frozen=True)
class TaskOutcome:
    case_id: str
    status: str  # "success" | "failed" | "inconclusive"
    verifier_results: list[VerifierResult]
    missing_facts: list[str]
    matched_facts: list[str]
    reason: str
    evidence_refs: list[str]
    evaluation_id: str | None = None  # 关联的 EvaluationResult id
```

### 4.2 状态判定逻辑

```
if no verifiers defined:
    status = "inconclusive"
elif all verifier_results passed:
    status = "success"
elif any verifier_result failed:
    status = "failed"
else:
    status = "inconclusive"
```

### 4.3 与 EvaluationResult 的关系

- `TaskOutcome.evaluation_id` 可引用 EvaluationResult，但不强制
- `TaskOutcome.status` 不影响 `EvaluationResult.passed`
- 报告同时展示两层结果：trace-level 和 task-level

---

## 5. TaskEvaluator

### 5.1 接口

```python
class TaskEvaluator:
    def evaluate(
        self,
        eval_case: EvalCase,
        trace: ExecutionTrace,
        eval_result: EvaluationResult | None = None,
    ) -> TaskOutcome:
        ...
```

### 5.2 流程

```
1. 从 trace 提取 final answer text（按 Decision 6 的优先级）
2. 从 eval_case.expected_outcome 构造 verifier 列表
3. 运行所有 verifier
4. 判定 status
5. 包装为 TaskOutcome
```

### 5.3 Final Answer 提取

按以下优先级：

1. `trace.final_answer` — 如果 trace schema 有该字段
2. 最后一条 tool_result 的 `output["answer"]` 或 `output["content"]`
3. 最后一条 tool_result 的 `output` 的 JSON string
4. 如果全部无法提取 — 返回 inconclusive

---

## 6. Report Integration

### 6.1 Markdown 新增段

```markdown
## Task Outcome

| Case ID | Status | Verifier | Result |
|---------|--------|----------|--------|
| ks-001 | FAILED | contains_required_facts | 1/2 facts matched |
| ks-001 | PASSED | forbidden_facts_absent | no forbidden facts |

### Missing Facts
- fix recommendation

### Matched Facts
- root cause
```

### 6.2 JSON 新增 key

```json
{
  "task_outcome": {
    "case_id": "ks-001",
    "status": "failed",
    "verifier_results": [...],
    "missing_facts": ["fix recommendation"],
    "matched_facts": ["root cause"],
    "reason": "Agent identified root cause but did not provide actionable fix recommendation"
  }
}
```

---

## 7. LLM Verifier (Optional)

### 7.1 接口

```python
class LLMVerifier:
    def verify(
        self,
        answer_text: str,
        expected_outcome: ExpectedOutcome,
        transport: OpenAITransport | AnthropicTransport,
    ) -> JudgeFinding:
        ...
```

### 7.2 约束

- 默认不启用（`--llm-verifier` flag）
- 产出 JudgeFinding，标记 `source="llm_verifier"`
- 不影响 TaskOutcome.status
- 零网络依赖时（未指定 llm-verifier），完全不加载 transport

---

## 8. 测试策略

| 测试文件 | 测试数 | 覆盖场景 |
|---------|--------|---------|
| `tests/test_eval_case.py` | ~5 | schema 创建、YAML 加载、验证 |
| `tests/test_verifiers.py` | ~20 | 6 种 verifier 的 pass/fail/edge |
| `tests/test_task_outcome.py` | ~8 | 状态判定、verifier 结果聚合 |
| `tests/test_task_evaluator.py` | ~8 | 端到端、final answer 提取 |
| `tests/test_task_report.py` | ~5 | Markdown/JSON 包含 task section |

**总计：≥ 46 个新增单测。**

---

## 9. 模块组织

```
agent_tool_harness/
├── task_eval/
│   ├── __init__.py
│   ├── eval_case.py          # EvalCase + ExpectedOutcome
│   ├── verifiers.py          # Verifier Protocol + 6 实现
│   ├── task_outcome.py       # TaskOutcome + VerifierResult
│   └── task_evaluator.py     # TaskEvaluator + final answer 提取
├── reports/
│   └── markdown_report.py    # 新增 task outcome section
├── core_report_bridge.py     # 新增 task_outcome_to_json_dict()
└── ...
```
