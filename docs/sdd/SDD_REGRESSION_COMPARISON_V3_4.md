# SDD: Regression Comparison V3.4

> **Implementation Status: Implemented in v3.4.0** — P1-P5 全部完成。本文档保留作为历史设计依据。

## TLDR

v3.4 新增 4 个组件：MetricDiff、FindingDiff、TaskOutcomeDiff、RegressionComparator。不修改已有对象。

---

## 1. 核心数据结构

```python
@dataclass(frozen=True)
class MetricDiff:
    metric_name: str
    baseline_value: float
    candidate_value: float
    delta: float
    direction: str  # "better" | "worse" | "neutral"

@dataclass(frozen=True)
class FindingDiff:
    category: str
    baseline_count: int
    candidate_count: int
    delta: int
    new_rule_ids: list[str]
    resolved_rule_ids: list[str]

@dataclass(frozen=True)
class TaskOutcomeDiff:
    case_id: str
    baseline_status: str
    candidate_status: str
    change: str  # "new_failure" | "new_success" | "unchanged"

@dataclass(frozen=True)
class RegressionWarning:
    warning_type: str
    severity: str
    threshold: str
    actual: str
    message: str

@dataclass(frozen=True)
class RegressionReport:
    baseline_id: str
    candidate_id: str
    is_regression: bool
    metric_diffs: list[MetricDiff]
    finding_diffs: list[FindingDiff]
    task_outcome_diffs: list[TaskOutcomeDiff]
    regression_warnings: list[RegressionWarning]
```

---

## 2. RegressionComparator

```python
class RegressionComparator:
    def __init__(self, thresholds: RegressionThresholds | None = None):
        self.thresholds = thresholds or RegressionThresholds()

    def compare(
        self,
        baseline: ReportInsight,
        candidate: ReportInsight,
        baseline_task_outcomes: list[TaskOutcome] | None = None,
        candidate_task_outcomes: list[TaskOutcome] | None = None,
    ) -> RegressionReport:
        ...
```

### RegressionThresholds

```python
@dataclass(frozen=True)
class RegressionThresholds:
    error_rate_spike_pct: float = 100.0   # 2x
    finding_explosion_pct: float = 50.0   # 50%
    task_success_drop_pp: float = 10.0    # 10 pp
```

---

## 3. 报告格式

### Markdown

```markdown
# Regression Report: baseline → candidate

## Summary
| Metric | Baseline | Candidate | Delta | Direction |
|--------|----------|-----------|-------|-----------|
| Tool Error Rate | 5.0% | 12.0% | +7.0pp | ⬆ worse |
| Task Success Rate | 80.0% | 75.0% | -5.0pp | ⬇ worse |

## Regression Warnings
- ⚠ error_rate_spike: Tool error rate increased from 5% to 12% (threshold: 2x)
- ⚠ task_success_drop: Task success dropped from 80% to 75% (threshold: 10pp)

## Newly Failing Tasks
| Case ID | Baseline | Candidate |
|---------|----------|-----------|
| ks-003 | SUCCESS | FAILED |
```

---

## 4. 测试策略

实际测试组织（v3.4.0）：

| 测试文件 | 测试数 | 覆盖 |
|---------|--------|------|
| `tests/test_regression_schema.py` | 25 | frozen dataclass 不可变性、JSON 序列化、direction/change 态 |
| `tests/test_regression_comparator.py` | 71 | _direction、compute_metric_diffs、compute_finding_diffs、_determine_change、compute_task_outcome_diffs、compute_suite_diff、compute_regression_warnings、RegressionComparator.compare |
| `tests/test_regression_report.py` | 8 | Markdown 渲染、所有 section、空报告、完整报告 |

**合计：104 deterministic tests。** 全量回归 1609 passed, 1 xfailed。

> 原始计划估计 ≥24 个测试，实际实现远超预期——comparator/diff 模块需要覆盖 5 种 warning 检测、9 个核心指标对比、五态 change 判定、边界条件和编排集成。
