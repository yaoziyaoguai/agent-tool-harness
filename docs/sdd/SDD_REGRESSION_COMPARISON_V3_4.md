# SDD: Regression Comparison V3.4

> **Implementation Status: Planned** — 依赖 v3.2，推荐 v3.3。

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

| 测试文件 | 测试数 | 覆盖 |
|---------|--------|------|
| `tests/test_metric_diff.py` | ~8 | diff 计算、direction 判定 |
| `tests/test_regression_warnings.py` | ~8 | 5 种 warning 触发/不触发 |
| `tests/test_regression_comparator.py` | ~5 | 端到端对比 |
| `tests/test_regression_report.py` | ~3 | Markdown/JSON |

**总计：≥ 24 个新增单测。**
