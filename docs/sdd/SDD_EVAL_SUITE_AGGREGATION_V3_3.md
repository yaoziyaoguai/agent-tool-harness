# SDD: Eval Suite / Multi-trace Aggregation V3.3

> **Implementation Status: Planned** — 依赖 v3.2。

## TLDR

v3.3 新增 4 个组件：EvalSuite（manifest 加载）、SuiteResult（聚合结果）、SuiteMetrics（跨 case 指标）、SuiteReport（Markdown/JSON）。不修改 v3.1/v3.2 的任何对象。

---

## 1. EvalSuite Manifest

### 1.1 数据结构

```python
@dataclass(frozen=True)
class EvalSuite:
    suite_id: str
    name: str
    cases: list[EvalCaseRef]
    trace_inputs: list[TraceInputRef]
    metadata: dict[str, str] = field(default_factory=dict)

@dataclass(frozen=True)
class EvalCaseRef:
    case_path: str          # 相对于 suite manifest 的路径
    case_id: str            # case 的 case_id（用于匹配 trace）

@dataclass(frozen=True)
class TraceInputRef:
    trace_path: str         # 相对于 suite manifest 的路径
    case_id: str            # 关联的 case_id
```

### 1.2 加载

```python
def load_eval_suite(yaml_path: str) -> EvalSuite:
    """从 YAML manifest 加载 EvalSuite。"""
```

---

## 2. CaseResult

```python
@dataclass(frozen=True)
class CaseResult:
    case_id: str
    trace_ref: str
    task_status: str            # from TaskOutcome.status
    deterministic_passed: bool  # from EvaluationResult.passed
    finding_count: int
    error_count: int
    warning_count: int
    metrics_summary: dict[str, Any]
```

---

## 3. SuiteResult + SuiteMetrics + SuiteScorecard

```python
@dataclass(frozen=True)
class SuiteMetrics:
    mean_tool_call_count: float = 0.0
    mean_tool_error_rate: float = 0.0
    mean_findings_per_case: float = 0.0
    total_findings: int = 0
    total_tool_calls: int = 0
    total_tool_errors: int = 0
    finding_count_by_category: dict[str, int] = field(default_factory=dict)
    finding_count_by_tool: dict[str, int] = field(default_factory=dict)

@dataclass(frozen=True)
class SuiteScorecard:
    suite_passed: bool
    task_success_rate: float
    deterministic_pass_rate: float
    top_failing_categories: list[str]
    top_affected_tools: list[str]
    total_cases: int
    passed_cases: int
    failed_cases: int

@dataclass(frozen=True)
class SuiteResult:
    suite_id: str
    total_cases: int
    task_success_rate: float
    deterministic_pass_rate: float
    per_case_results: list[CaseResult]
    suite_metrics: SuiteMetrics
    suite_scorecard: SuiteScorecard
```

---

## 4. SuiteEvaluator

```python
class SuiteEvaluator:
    def evaluate(
        self,
        suite: EvalSuite,
        task_evaluator: TaskEvaluator,
        trace_loader: Callable[[str], ExecutionTrace],
    ) -> SuiteResult:
        """逐个 case 评测，产出聚合 SuiteResult。"""
```

---

## 5. 报告

### Markdown suite report

```markdown
# Eval Suite Report: Knowledge Search Suite

## Suite Scorecard
| Metric | Value |
|--------|-------|
| Total Cases | 15 |
| Task Success Rate | 73.3% |
| Deterministic Pass Rate | 86.7% |

## Top Failing Categories
1. knowledge_search (4 failures)
2. tool_response (2 failures)

## Per-Case Summary
| Case ID | Task | Deterministic |
|---------|------|--------------|
| ks-001 | FAILED | PASSED |
| ks-002 | SUCCESS | PASSED |
...
```

### JSON suite report

```json
{
  "suite_result": {
    "suite_id": "ks-suite-001",
    "total_cases": 15,
    "task_success_rate": 0.733,
    "suite_scorecard": {...},
    "suite_metrics": {...},
    "per_case_results": [...]
  }
}
```

---

## 6. 测试策略

| 测试文件 | 测试数 | 覆盖 |
|---------|--------|------|
| `tests/test_eval_suite.py` | ~8 | manifest 加载、引用解析 |
| `tests/test_suite_result.py` | ~8 | 聚合正确性 |
| `tests/test_suite_report.py` | ~5 | Markdown/JSON 输出 |

**总计：≥ 21 个新增单测。**
