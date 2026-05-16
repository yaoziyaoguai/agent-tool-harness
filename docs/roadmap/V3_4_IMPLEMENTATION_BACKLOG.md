# V3.4 Implementation Backlog

> **Status: Planned** — 依赖 v3.2，推荐 v3.3。

## TLDR

5 个 Phase。P1 diff schema。P2 metric/finding diff。P3 task outcome diff。P4 regression warnings + report。P5 examples。

---

## Phase 依赖

```
P1: Diff schema (MetricDiff, FindingDiff, TaskOutcomeDiff)
  ├── P2: Metric + Finding diff calculator
  ├── P3: Task outcome diff calculator (可与 P2 并行)
  └── P4: Regression report + warnings
        └── P5: Examples / tests / docs
```

---

## P1: Diff schema

**目标**：MetricDiff、FindingDiff、TaskOutcomeDiff、RegressionWarning、RegressionReport dataclass。

**测试数**：~5

---

## P2: Metric + Finding diff

**目标**：对比两个 ReportInsight 的 metrics 和 findings。

**测试数**：~10

---

## P3: Task outcome diff

**目标**：对比两个 TaskOutcome 列表。

**测试数**：~5

---

## P4: Regression report + warnings

**目标**：RegressionComparator、5 种 warning 检测、Markdown/JSON。

**测试数**：~8

---

## P5: Examples

**目标**：≥ 2 个 regression comparison 示例。

---

## 汇总

| Phase | 新增测试 |
|-------|---------|
| P1 | ~5 |
| P2 | ~10 |
| P3 | ~5 |
| P4 | ~8 |
| **合计** | **~28 tests** |
