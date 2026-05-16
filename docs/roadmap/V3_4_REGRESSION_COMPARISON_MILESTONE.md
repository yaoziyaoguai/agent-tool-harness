# V3.4 Milestone: Regression Comparison

> **Status: Planned** — 设计已完成，实现未开始。依赖 v3.2 TaskOutcome，推荐 v3.3 suite aggregation。

## TLDR

v3.2/v3.3 能评测当前版本。v3.4 对比 baseline vs candidate，回答"我改了 tool spec / prompt / agent 之后，有没有引入回归？"支持 metric diff、finding diff、task outcome diff，产出可读的回归报告。

---

## 1. 背景

改动 tool spec 或 prompt 后，你最关心：
- 一样的 eval cases，task success rate 是变好还是变差？
- 新增了多少 findings？
- 哪些之前通过的 case 现在失败了？
- 哪些工具的 finding 数量明显变化？

v3.4 对比两份 report（baseline、candidate），自动发现正向/负向变化。

---

## 2. 用户问题

| # | 问题 |
|---|------|
| 1 | "改了 tool spec 之后 task success rate 从 80% 掉到 60%，具体哪些 case 失败了？" |
| 2 | "改了 prompt 后 tools/a 的 error 从 3 个增到 12 个，正常吗？" |
| 3 | "能不能自动判断是不是回归？" |
| 4 | "在 CI 里每次 commit 都跑回归对比，有 regression 就 block merge" |

---

## 3. v3.4 核心设计

### 3.1 RegressionReport

```
RegressionReport
  ├── baseline: ReportSummary
  ├── candidate: ReportSummary
  ├── metric_diffs: list[MetricDiff]
  ├── finding_diffs: list[FindingDiff]
  ├── task_outcome_diffs: list[TaskOutcomeDiff]
  ├── regression_warnings: list[RegressionWarning]
  └── is_regression: bool
```

### 3.2 MetricDiff

比较两个 report 的 metrics：

| metric | baseline | candidate | delta | direction |
|--------|----------|-----------|-------|-----------|
| tool_error_rate | 0.05 | 0.12 | +0.07 | worse |
| task_success_rate | 0.80 | 0.75 | -0.05 | worse |
| finding_count | 8 | 5 | -3 | better |

### 3.3 RegressionWarning

自动检测以下模式：
- **New failures**：baseline passed、candidate failed 的 task
- **Error rate spike**：tool_error_rate 增长 > 阈值（默认 2x）
- **Finding explosion**：finding 总数增长 > 阈值（默认 50%）
- **New tool errors**：baseline 未出现的 tool_error 在 candidate 中出现
- **Task success drop**：task_success_rate 下降 > 阈值（默认 10pp）

### 3.4 对比范围

支持三级对比：
1. **Single-report diff**：两个 report 直接对比（不依赖 v3.3）
2. **Suite diff**：两个 suite report 对比（推荐，依赖 v3.3）
3. **Multi-suite trend**：多个 suite report 的时间线对比（未来）

---

## 4. 依赖

- v3.2 TaskOutcome（必需）
- v3.3 suite aggregation（推荐，非强制）
- v3.1 ReportInsight

---

## 5. 完成定义

- [ ] MetricDiff 计算正确
- [ ] FindingDiff 计算正确
- [ ] TaskOutcomeDiff：识别新增失败、修复的 case
- [ ] 5 种 RegressionWarning 触发条件明确且可测
- [ ] Markdown regression report 包含对比表和 warning 列表
- [ ] JSON regression report 可消费
- [ ] ≥ 20 个新增单测
- [ ] 现有 1300+ tests 无 regression
