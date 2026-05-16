# RFC 0007: Tool Portfolio Review + Tool Improvement Brief

## TLDR

v3.6 新增 ToolPortfolioReview（工具组合级别设计评审）和 ToolImprovementBrief（含 evidence 引用的结构化改进建议）。不自动修改任何文件。所有分析 deterministic。LLM 可辅助生成 brief 文本，但默认不启用。

---

## Decision 1: Portfolio Review Is Static + Signal-Aggregated

### 决策

ToolPortfolioReview 结合两类分析：
1. **静态分析** — 只读 ToolSpec 元数据（名称、描述），不需要 trace
2. **信号聚合** — 消费 v3.1-v3.5 的 findings/metrics/task outcomes/transcript signals

---

## Decision 2: Five Portfolio Checks

### 决策

| # | 检查 | 类型 | 检测逻辑 |
|---|------|------|---------|
| 1 | namespacing consistency | 静态 | 工具名不匹配 `namespace.action_resource` 格式的比例 > 30% |
| 2 | overlapping tools | 静态 | 名称编辑距离 ≤ 2 且 description 相似度高 |
| 3 | shallow wrapper portfolio | 静态 | 工具名匹配 CRUD 后缀 + description 中无领域词汇 |
| 4 | missing higher-level tool | 信号 | D4 `frequently_chained_tools` 出现 ≥ 3 次 |
| 5 | tool grouping by resource | 静态 | 按 resource 分组后，某些 resource 的工具数异常多/少 |

---

## Decision 3: Improvement Brief Is Human-Readable, Not Machine-Executable

### 决策

ToolImprovementBrief 的设计目标是给**人**（或 Claude Code）看：
- current_state → recommended_state 是自然语言描述
- evidence 引用可追溯（含具体 finding_id / metric 名称 / task outcome case_id）
- effort_estimate 是 rough estimate（small/medium/large），不是 man-hours

### 为什么不是 structured diff

automatic patch 是不安全的——改变 tool spec 可能影响生产 Agent 行为。ImprovementBrief 提供有证据的建议，由人做最终决策。

---

## Decision 4: Evidence Collection From All Previous Versions

### 决策

ToolImprovementBrief.evidence 从以下来源收集：

| 来源 | 引用内容 |
|------|---------|
| v3.1 findings | finding_id + rule_id + severity |
| v3.1 metrics | metric 名 + 值 |
| v3.1 recommendations | recommendation.rule_id |
| v3.2 task outcomes | case_id + status |
| v3.3 suite results | suite_id + task_success_rate |
| v3.4 regression reports | metric_delta |
| v3.5 transcript signals | signal type + steps |

---

## Decision 5: Brief Is Per-Tool and Cross-Tool

### 决策

两种 brief：
1. **Per-Tool Brief** — 针对单个工具的改进建议（来自 findings、metrics、signals）
2. **Cross-Tool Brief** — 针对工具组合的建议（来自 portfolio review："合并 tool A 和 tool B"、"新增 workflow tool W"）

---

## Acceptance Criteria

1. ToolPortfolioReview 覆盖 5 类检查
2. ToolImprovementBrief 含 evidence 引用（可追溯到 finding/metric/task outcome）
3. Per-tool brief 和 cross-tool brief 均可生成
4. 不自动修改任何文件
5. Markdown/JSON 输出可用
6. 现有 1300+ tests 无 regression
