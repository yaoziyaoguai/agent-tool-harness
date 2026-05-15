# V3.1 Milestone: Evaluation Report Insight

> **Status: Completed in v3.1.0 (2026-05-15)** — P1-P5 全部落地，42 个集成测试通过，1329 tests 零 regression。

## TLDR

v3.0 能发现很多问题，但报告还不够"洞察化"。v3.1 在 v3.0 的 deterministic inspection + LLM advisory rubric 之上，新增 **report-level insight layer**：Scorecard、Metrics、Grouped Findings、Actionable Recommendations。用户打开报告 30 秒内就能看懂整体评价结论和下一步优先改什么。

---

## 1. 背景

### 1.1 v3.0 已经解决什么

v3.0 完成了 single-trace tool-use inspection and evaluation 主线：

| 模块 | 能力 | 产出 |
|------|------|------|
| Trace Import (D1) | native + simple mapping, field coverage, type diagnostics, dry-run | ExecutionTrace |
| Tool-use Correctness (D2) | 9 trace-level invariant rules | RuleFinding |
| Tool Spec Quality (D6) | 10 deterministic rules | RuleFinding |
| Tool Ergonomics (D4) | 6 deterministic rules + 4 LLM advisory rubric dimensions | RuleFinding + JudgeFinding |
| Tool Response Quality (D5) | 6 deterministic rules + 2 LLM advisory rubric dimensions | RuleFinding + JudgeFinding |
| Core Flow | ScenarioSpec → ExecutionTrace → Evidence → CoreEvaluation → EvaluationResult → Report | EvaluationResult + ReportSummary |
| Markdown Report | render_from_core() | report.md |

**31 deterministic rules** across **4 inspectors** (D2/D6/D4/D5), plus **6 LLM advisory rubric dimensions** across 2 inspectors (D4/D5). LLM advisory dimensions are advisory only, not deterministic rules.

### 1.2 v3.1 为什么继续做 report insight

v3.0 能发现很多问题，但报告还是"finding 列表"。用户看到 findings 后，还需要自己判断：

- 这次评测整体情况如何？
- 是否通过？
- error / warning / advisory 分别有多少？
- 哪些工具问题最多？
- 问题主要集中在哪些类别？
- 下一步优先改什么？
- 这份报告能不能更方便人工 review / PR review / CI 消费？

v3.1 的目标：**把 finding 列表升级为可读、可诊断、可行动的评测报告**。

---

## 2. 用户问题

| # | 问题 | 影响 |
|---|------|------|
| 1 | finding 太多，不容易快速判断重点 | reviewer 需要逐条扫描，30 个 finding 的 trace 需要 5+ 分钟才能形成判断 |
| 2 | report 缺少整体 scorecard | 没有"通过/不通过"的一眼结论，也没有 error/warning/advisory 分桶计数 |
| 3 | metrics 不集中 | tool_call_count、tool_error_rate 等基础统计散落在各模块，report 里看不到 |
| 4 | findings 没有按 severity / category / tool 分组 | 同一条工具的 5 个问题可能分散在报告的 5 个不同位置 |
| 5 | recommendations 不够集中 | 用户需要自己从 finding message 里推导"下一步该改什么" |

---

## 3. v3.1 目标

### 3.1 Evaluation Scorecard

报告顶部「一页纸」结论：

- **passed** — 一眼可见
- **total findings** — 总数
- **errors / warnings / info** — 按 severity 分桶
- **advisory count** — JudgeFinding 数量
- **tools called** — 本次 trace 调用了多少工具
- **tool errors** — 工具返回 error 的次数
- **top issue categories** — 问题最多的 3-5 个类别
- **top affected tools** — 问题最多的 3-5 个工具

### 3.2 Metrics Summary

从 ExecutionTrace + findings 自动计算的基础指标：

- `tool_call_count` — 总工具调用次数
- `tool_result_count` — 总工具返回次数
- `unique_tool_count` — 不重复工具数
- `tool_success_count` / `tool_error_count` — 成功/失败调用次数
- `tool_error_rate` — 错误率
- `orphan_call_count` / `orphan_result_count` — 孤立调用/返回数
- `repeated_tool_call_count` — 重复调用次数
- `response_size_chars_total` / `response_size_chars_by_tool` — 返回内容大小
- `estimated_response_tokens_total` — 估算 token 数
- `finding_count_by_severity` / `finding_count_by_category` / `finding_count_by_tool` — finding 分桶计数
- `judge_finding_count` — LLM judge finding 总数

### 3.3 Grouped Findings

同一份 findings，三种聚合视图：

1. **By severity** — critical → high → medium → low → info
2. **By category** — rule → judge → audit → signal（以及子类别如 tool_response / tool_spec / tool_ergonomics / tool_call）
3. **By tool** — 按 tool_name 聚合，一眼看到哪个工具问题最多

每种视图都保留原始 finding 引用，reviewer 可以下钻。

### 3.4 Actionable Recommendations

从 finding 的 rule_id / category / severity **确定性派生**的修复建议：

- 不是 LLM 生成的
- 不是模糊的"请检查工具设计"
- 每条建议指向具体 rule_id 和修复方向
- 例如：`tool_response.output.low_signal` → "为工具输出增加 context_fields，确保返回内容包含有意义的上下文而非仅 IDs"

### 3.5 Markdown / JSON Report Polish

- **Markdown** — 新增 Scorecard → Metrics → Top Issues → Grouped Findings → Recommendations 段，排在现有 detailed findings 之前
- **JSON** — 新增 `summary` / `metrics` / `scorecard` / `grouped_findings` / `recommendations` 顶层 key，与 Markdown 共享同一 ReportInsight 数据模型
- JSON report 供 CI / 下游工具消费（如 GitHub Actions summary、Slack notification、dashboard）

---

## 4. 典型用户场景

### 场景 A：本地调试单条 trace

```
$ ath inspect trace.json --report-output report.md
```

用户在终端看到 passed/failed，打开 report.md 后：
1. 读 Scorecard（5 秒）— 知道 passed=false，3 errors，1 warning
2. 看 Top Issues（10 秒）— tool_response 问题最多
3. 扫 Recommendations（10 秒）— 知道先修 tool output 的 context_fields
4. 需要时下钻到 Findings by Tool 看具体哪个工具的哪个调用出问题

### 场景 B：PR review 一份 agent trace report

reviewer 在 PR 里看到 `report.md`：

1. Scorecard 表一眼判断"这个 PR 的工具变更是否引入新问题"
2. Top affected tools 快速定位变更范围
3. Grouped Findings 按 severity 折叠，先看 critical/high

### 场景 C：CI 里保存 JSON report

```
$ ath inspect trace.json --report-output report.json --format json
```

CI pipeline 消费 `report.json`：
- `summary.passed` → 决定 CI pass/fail
- `metrics.tool_error_rate` → 如果 > 阈值，发 warning
- `scorecard.top_issue_categories` → 贴到 PR comment
- `recommendations` → 自动生成修复提示

### 场景 D：人工 review tool-use quality

quality reviewer 打开 report.md：
1. 先看 Scorecard 和 Metrics 建立全局认知
2. 再看 Grouped Findings by tool，按工具逐个 review
3. 对每个工具看 Recommendations 里对应 rule_id 的建议
4. 需要时跳转 detailed findings 看原始 evidence_ref

---

## 5. 完成定义

用户打开报告 **30 秒内**能看懂：

- [x] **passed 状态** — 一眼可见
- [x] **error / warning / advisory 数量** — 分 severity 计数
- [x] **tool calls / tool errors** — 本次 trace 基础统计
- [x] **top issue categories** — 排名前 3-5 的问题类别
- [x] **top affected tools** — 排名前 3-5 的问题工具
- [x] **recommended next actions** — 优先级排序的修复建议

### 可验证标准

| 标准 | 验证方式 |
|------|---------|
| Scorecard 中的 passed 与 EvaluationResult.passed 一致 | 单测 |
| finding 计数与 EvaluationResult.findings 一致 | 单测 |
| metrics 数值与 ExecutionTrace 原始数据一致 | 单测 |
| grouping 不丢 finding、不重复 finding | 单测 |
| recommendations 的 rule_id 映射全覆盖 | 单测 |
| Markdown report 包含所有新段且可渲染 | snapshot / substring 测试 |
| JSON report 包含所有新 key 且 schema 稳定 | JSON shape 测试 |
| v3.0 兼容 — 现有 EvaluationResult / Finding 结构不变 | 现有测试全部通过 |

---

## 6. Phase 概览

| Phase | 名称 | 内容 | 依赖 |
|-------|------|------|------|
| P1 | MetricsCollector | ReportMetrics + MetricsCollector | 无 |
| P2 | FindingGrouper | 4 种分组视图 | P1 |
| P3 | ReportScorecard | scorecard 生成 + top-N 排名 | P1, P2 |
| P4 | RecommendationCatalog | deterministic 建议映射 | P1（不依赖 P2/P3，可与 P2/P3 并行） |
| P5 | ReportInsight Integration | 聚合对象 + Markdown/JSON 接入 | P1-P4 |

详见 [V3_1_IMPLEMENTATION_BACKLOG.md](V3_1_IMPLEMENTATION_BACKLOG.md)。

---

## 7. 明确不在此 milestone

- 不引入 Trace Onboarding / auto mapping
- 不重新规划 v3.0 已完成内容（D1-D6 inspectors）
- 不修改 EvaluationResult / RuleFinding / JudgeFinding 数据结构
- 不做 LLM 生成的 recommendations
- 不做 Web UI / dashboard
- 不做 batch / multi-trace evaluation（那是 post-v3 future work）
- 不做自动 optimizer（不改 tool spec、不改 Agent prompt）
