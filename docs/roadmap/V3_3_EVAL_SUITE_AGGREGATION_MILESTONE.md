# V3.3 Milestone: Eval Suite / Multi-trace Aggregation

> **Status: Implemented** — 5 Phase 全部完成。

## TLDR

v3.2 能判断单个任务是否完成。v3.3 把多个 eval case + 多条 trace 组成 eval suite，一次评测产出聚合报告——task success rate、deterministic pass rate、top failing categories、top affected tools、suite-level metrics。核心概念：EvalSuite manifest + SuiteResult。

---

## 1. 背景

### 1.1 v3.2 的局限

v3.2 解决的是**单个 task + 单条 trace** 的评测。实际使用时：
- 你需要跑 N 个 eval case（不同难度、不同领域）
- 你需要知道整体的 task success rate
- 你需要知道哪些类别的任务 Agent 最不擅长
- 你需要在 CI 里一次性跑完并拿到通过/不通过结论

### 1.2 为什么需要 v3.3

单 trace 评测看不到全局。v3.3 把多个评测结果聚合为一份 suite report，让 reviewer 一眼看到全局健康状况。

---

## 2. 用户问题

| # | 问题 |
|---|------|
| 1 | "我的 Agent 在 50 个 test case 上的 task success rate 是多少？" |
| 2 | "哪些类型的任务 Agent 最不擅长？" |
| 3 | "哪个工具导致的 task failure 最多？" |
| 4 | "能不能一次性跑完所有 case 然后看聚合报告？" |

---

## 3. v3.3 核心设计

### 3.1 EvalSuite manifest

```yaml
# examples/eval_suites/knowledge_search_suite.yaml
suite_id: "ks-suite-001"
name: "Knowledge Search Eval Suite"
cases:
  - case_path: "cases/ks-001.yaml"
  - case_path: "cases/ks-002.yaml"
  - case_path: "cases/ks-003.yaml"
trace_inputs:
  - trace_path: "traces/trace_001.json"
    case_id: "ks-001"
  - trace_path: "traces/trace_002.json"
    case_id: "ks-001"
metadata:
  agent_version: "2.3.0"
  harness_version: "3.3.0"
```

### 3.2 SuiteResult

```
SuiteResult
  ├── suite_id
  ├── total_cases
  ├── task_success_rate
  ├── deterministic_pass_rate
  ├── top_failing_categories
  ├── top_affected_tools
  ├── per_case_results: list[CaseResult]
  ├── suite_metrics: SuiteMetrics
  └── suite_scorecard: SuiteScorecard
```

### 3.3 SuiteMetrics

跨 case 聚合指标：
- mean_tool_call_count
- mean_tool_error_rate
- mean_findings_per_case
- finding_count_by_category (跨 case 合计)
- finding_count_by_tool (跨 case 合计)

### 3.4 SuiteScorecard

- suite 级别 passed（所有 case 都 trace-level passed）
- case 级别 pass rate
- task success rate
- top-N 问题类别/工具（跨 case）

---

## 4. 依赖

- v3.2 TaskOutcome（必需）
- v3.1 ReportInsight

---

## 5. 完成定义

- [x] EvalSuite manifest 可从 YAML 加载
- [x] SuiteResult 正确聚合
- [x] suite-level metrics 与单 case metrics 自洽
- [x] Markdown suite report 可用
- [x] JSON suite report 可用
- [x] ≥ 4 个 example eval suites
- [x] ≥ 20 个新增单测（56 个）
- [x] 现有 1498 tests 无 regression
