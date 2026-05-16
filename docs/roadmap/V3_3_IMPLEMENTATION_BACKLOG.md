# V3.3 Implementation Backlog

> **Status: Implemented** — 5 Phase 全部完成，56 测试通过。

## TLDR

5 个 Phase。P1 EvalSuite manifest 加载。P2 SuiteEvaluator + CaseResult。P3 SuiteMetrics + SuiteScorecard 聚合。P4 报告集成。P5 examples。

---

## Phase 依赖

```
P1: EvalSuite manifest
  └── P2: SuiteEvaluator + CaseResult
        └── P3: SuiteMetrics + SuiteScorecard
              └── P4: Suite report (Markdown + JSON)
                    └── P5: examples / tests / docs
```

---

## P1: EvalSuite manifest

### 目标

EvalSuite 数据结构 + YAML 加载。

### 测试数: ~8

---

## P2: SuiteEvaluator + CaseResult

### 目标

逐个 case 评测，产出 CaseResult 列表。

### 测试数: ~8

---

## P3: SuiteMetrics + SuiteScorecard

### 目标

从 CaseResult 列表聚合出 suite-level metrics 和 scorecard。

### 测试数: ~8

---

## P4: Suite report

### 目标

Markdown + JSON suite report。

### 测试数: ~5

---

## P5: Examples

### 目标

≥ 4 个 example eval suites。

---

## 汇总

| Phase | 新增测试 |
|-------|---------|
| P1 | ~8 |
| P2 | ~8 |
| P3 | ~8 |
| P4 | ~5 |
| P5 | — |
| **合计** | **~29 tests** |
