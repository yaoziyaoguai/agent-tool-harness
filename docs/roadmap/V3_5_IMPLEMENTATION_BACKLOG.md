# V3.5 Implementation Backlog

> **Status: Planned** — 可独立于 v3.3/v3.4。

## TLDR

5 个 Phase。P1 transcript pattern primitives。P2 confusion analyzer。P3 context efficiency analyzer。P4 report integration + recommendations。P5 examples。

---

## Phase 依赖

```
P1: Transcript pattern primitives (序列窗口、args 比较)
  ├── P2: Confusion analyzer (6 patterns)
  └── P3: Context efficiency analyzer (5 patterns) (可与 P2 并行)
        └── P4: Report integration + recommendations
              └── P5: Examples / tests / docs
```

---

## P1: Transcript pattern primitives

**目标**：序列窗口遍历、args 相似度比较、tool switching 检测、truncation 检测等底层函数。

**测试数**：~8

---

## P2: Confusion analyzer

**目标**：TranscriptPatternAnalyzer 识别 6 种 confusion signal。

**测试数**：~15

---

## P3: Context efficiency analyzer

**目标**：ContextEfficiencyAnalyzer 识别 5 种 inefficiency signal。

**测试数**：~12

---

## P4: Report integration

**目标**：Markdown/JSON 集成 transcript/context analysis section。recommendation catalog 新增对应 rule_id。

**测试数**：~5

---

## P5: Examples

**目标**：≥ 2 个含 confusion/inefficiency 的示例 trace。

---

## 汇总

| Phase | 新增测试 |
|-------|---------|
| P1 | ~8 |
| P2 | ~15 |
| P3 | ~12 |
| P4 | ~5 |
| **合计** | **~40 tests** |
