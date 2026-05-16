# V3.6 Implementation Backlog

> **Status: Implemented** — v3.6.0 落地。

## TLDR

5 个 Phase。P1 portfolio static review。P2 evidence collection。P3 improvement brief schema + generator。P4 Markdown/JSON brief output。P5 examples。

---

## Phase 依赖

```
P1: Portfolio static review (5 checks)
  ├── P2: Evidence collection (from findings/metrics/task outcomes/signals)
  └── P3: Improvement brief schema + generator (可与 P2 并行)
        └── P4: Markdown/JSON output
              └── P5: Examples / tests / docs
```

---

## P1: Portfolio static review

**目标**：ToolPortfolioReview 5 类检查。

**测试数**：21

---

## P2: Evidence collection

**目标**：从 findings、metrics、task outcomes、transcript signals 中收集引用。

**测试数**：15

---

## P3: Improvement brief schema + generator

**目标**：ToolImprovementBrief + EvidenceRef 数据结构 + per-tool/cross-tool generator。

**测试数**：9

---

## P4: Report output

**目标**：Markdown portfolio review section + improvement brief section。JSON 序列化。

**测试数**：14

---

## P5: Examples

**目标**：≥ 2 个 portfolio review 示例。

---

## 汇总

| Phase | 新增测试 |
|-------|---------|
| P1 | 21 |
| P2 | 15 |
| P3 | 9 |
| P4 | 14 |
| **合计** | **59 tests** |
