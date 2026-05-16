# RFC 0004: Eval Suite / Multi-trace Aggregation

## TLDR

v3.2 解决单 task 评测。v3.3 新增 EvalSuite manifest、SuiteResult、SuiteMetrics、SuiteScorecard，把多个 eval case + 多条 trace 聚合为一份 suite report。suite-level metrics 与单 case metrics 共享同一个 ReportMetrics schema，只是数据来源从单 trace 变成多 trace 聚合。

---

## Decision 1: EvalSuite Is a Manifest File (Not Database)

### 问题

多 trace 评测的 entry list 需要持久化。数据库太重，不适合 CLI-first 工具。

### 决策

EvalSuite 是 YAML manifest 文件，包含 case 和 trace 文件路径的引用。加载时自动解析所有引用。

### 为什么选择 YAML 而非 JSON

与 project.yaml / tools.yaml / evals.yaml 风格一致。YAML 注释方便标注 case 用途。

---

## Decision 2: SuiteResult Aggregates Per-Case Results

### 决策

SuiteResult 不重复存储单 case 的完整数据，只存储：
1. 聚合指标（task_success_rate、mean_* 等）
2. 排名列表（top failing categories、top affected tools）
3. 对每个 case 的引用（case_id + status + summary）

详细 findings 仍在单 case report 中。SuiteResult 指向它们，不复制它们。

### SuiteResult schema

```python
@dataclass(frozen=True)
class SuiteResult:
    suite_id: str
    total_cases: int
    task_success_count: int
    task_failed_count: int
    task_inconclusive_count: int
    task_success_rate: float
    deterministic_pass_rate: float
    per_case_results: list[CaseResult]
    suite_metrics: SuiteMetrics
    suite_scorecard: SuiteScorecard
```

---

## Decision 3: Suite Metrics Reuse ReportMetrics Schema

### 决策

SuiteMetrics 直接使用 ReportMetrics 的字段结构，但值为跨 case 聚合（mean/sum/max）：

```python
@dataclass(frozen=True)
class SuiteMetrics:
    mean_tool_call_count: float
    mean_tool_error_rate: float
    mean_findings_per_case: float
    total_findings: int
    finding_count_by_category: dict[str, int]
    finding_count_by_tool: dict[str, int]
    total_tool_calls: int
    total_tool_errors: int
```

---

## Acceptance Criteria

1. EvalSuite manifest 可加载
2. SuiteResult 聚合正确
3. suite_metrics 与单 case 自洽
4. suite_scorecard 正确（包含 top-N、pass rate 等）
5. Markdown/JSON suite report 可用
6. 现有 1300+ tests 无 regression
