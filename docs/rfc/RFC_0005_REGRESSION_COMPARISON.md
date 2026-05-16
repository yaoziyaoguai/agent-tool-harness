# RFC 0005: Regression Comparison

## TLDR

v3.4 新增 RegressionComparator，对比 baseline vs candidate report，产出 RegressionReport。支持 metric/finding/task outcome 三级 diff + 5 种 regression warning。不修改 v3.1-v3.3 的任何对象。可独立于 v3.3 运行（single-report diff），但推荐与 v3.3 suite 配合。

---

## Decision 1: Regression Is Detected, Not Decided

### 决策

`RegressionReport.is_regression` 是 advisory flag，不自动阻止 CI。RegressionWarning 列出检测到的信号和阈值，由人工或 CI 规则决定是否 block。

### 为什么不能自动 block

- 不同项目对回归的容忍度不同
- finding 数量增加不一定代表 regression（可能发现了之前漏报的问题）
- task success rate 下降可能只影响低优先级 case

---

## Decision 2: Metric Diff Has Direction

### 决策

每个 MetricDiff 带 direction 字段：

| direction | 含义 |
|-----------|------|
| `better` | 指标改善 |
| `worse` | 指标恶化 |
| `neutral` | 无显著变化 |

Direction 由 delta 符号和 metric 含义决定（error_rate 上升 = worse，success_rate 上升 = better）。

---

## Decision 3: Five Regression Warnings

| warning | 触发条件 | 默认阈值 |
|---------|---------|---------|
| `new_task_failures` | baseline passed → candidate failed | 任何 1 个 |
| `error_rate_spike` | tool_error_rate 增长 > N% | 100% (2x) |
| `finding_explosion` | finding 总数增长 > N% | 50% |
| `new_tool_errors` | baseline 无 tool_error 的工具在 candidate 中出现 error | 任何 1 个 |
| `task_success_drop` | task_success_rate 下降 > N pp | 10 pp |

---

## Decision 4: Supports Single-Report and Suite-Level

### 决策

RegressionComparator 接受两份 report（baseline + candidate），不强制要求 suite report。单 report diff 也能工作。

---

## Acceptance Criteria

1. MetricDiff 方向判定正确
2. 5 种 warning 触发条件可测
3. RegressionReport 结构完整
4. Markdown/JSON 报告可用
5. 现有 1300+ tests 无 regression
