# RFC 0002: Evaluation Report Insight

## TLDR

v3.0 的 report 是 "finding 列表"。v3.1 在其上新增 **report-level insight layer**：Scorecard、Metrics、Grouped Findings、Actionable Recommendations。这些组件不改变 v3.0 的 EvaluationResult / Finding 结构，而是在报告渲染层提供聚合、排名和可行动建议。Markdown 和 JSON report 共享同一个 ReportInsight 数据模型。

---

## Decision 1: Add a Report-Level Insight Layer

### 问题

v3.0 的 report 以 per-eval finding 列表为主。当一条 trace 产生 30+ findings 时，reviewer 需要逐条扫描才能形成整体判断。这违背了"报告帮助人做决策"的基本目标。

### 决策

在 **不改变底层 EvaluationResult / Finding 结构**的前提下，新增一个 report-level 聚合层：

```
ExecutionTrace + EvaluationResult
    → MetricsCollector → ReportMetrics
    → FindingGrouper → GroupedFindings
    → ReportScorecard
    → RecommendationCatalog → Recommendations
    → ReportInsight（聚合以上所有）
    → MarkdownReport / JSONReport
```

### 为什么不是改现有 Finding 结构

Finding 是 Core Contract 的一部分，被所有 inspector、judge、report consumer 消费。改动 Finding 会影响整个评测链路，风险和收益不成比例。Insight 层是**纯派生**的——它消费 Finding，不修改 Finding。

### 为什么需要 scorecard / metrics / grouping / recommendations 四个组件

这四个组件回答 reviewer 的四个递进问题：

1. **Scorecard** — "这次评测整体怎样？过了没？"（5 秒）
2. **Metrics** — "数据面长什么样？调了多少工具？错了几次？"（15 秒）
3. **Grouped Findings** — "问题集中在哪？哪个工具/类别最严重？"（30 秒）
4. **Recommendations** — "我该先修什么？怎么修？"（1 分钟）

分开设计的好处：每个组件可以独立测试、独立演进、独立替换。

---

## Decision 2: Metrics Are Report Insight Data

### 问题

v3.0 有零散的 metric 计算（如 tool_call_count 在 diagnosis 中有部分统计），但没有集中的 metrics 对象。不同 report consumer 各自重复计算，容易不一致。

### 决策

`ReportMetrics` 是**单一数据源**——所有 metric 从这里取，所有 report consumer 消费同一份 metrics。

### Metrics 包含什么

| Metric | 来源 | 用途 |
|--------|------|------|
| `tool_call_count` | ExecutionTrace.tool_calls | Scorecard, "调用了多少次" |
| `tool_result_count` | ExecutionTrace.tool_results | 配对检查基数 |
| `unique_tool_count` | ToolCall.tool_name 去重 | "涉及多少个不同工具" |
| `tool_success_count` | ToolResult.status=="success" | 成功率分子 |
| `tool_error_count` | ToolResult.status=="error" | 错误次数 |
| `tool_error_rate` | error / total | Scorecard 关键指标 |
| `orphan_call_count` | tool_call 无对应 result | 数据完整性 |
| `orphan_result_count` | tool_result 无对应 call | 数据完整性 |
| `repeated_tool_call_count` | 相同 tool_name + 相同 arguments 的重复调用 | 冗余检测 |
| `response_size_chars_total` | sum(len(str(output))) | 返回内容总量 |
| `response_size_chars_by_tool` | per-tool 响应大小 | 按工具分析 |
| `estimated_response_tokens_total` | chars / 4 (估算) | token 估算 |
| `finding_count_by_severity` | EvaluationResult.findings → Counter | Scorecard 分桶 |
| `finding_count_by_category` | EvaluationResult.findings → Counter | "哪类问题最多" |
| `finding_count_by_tool` | EvaluationResult.findings → Counter | "哪个工具问题最多" |
| `judge_finding_count` | category=="judge" 的 finding 数 | advisory 数量 |

### 为什么 estimated_response_tokens 用 chars/4

不做精确 tokenizer（引入重量依赖）。chars/4 是业界常用估算（英文约 4 char/token，中文约 1.5-2 char/token），这里取保守值 4。标注为 **estimate**，不声称精确。

---

## Decision 3: Findings Need Multiple Views

### 问题

同一份 findings，reviewer 在不同场景下需要从不同维度看：

- 按 severity 看 → 先处理 critical/high
- 按 category 看 → 判断是工具设计问题还是 Agent 选择问题
- 按 tool 看 → 判断哪个工具需要优先重构

如果只提供一种排序方式，reviewer 需要自己手动重新组织。

### 决策

`FindingGrouper` 提供 **4 种分组视图**，每组内按 finding count 降序排列：

| 视图 | group_by | 排序 | 用途 |
|------|----------|------|------|
| by_severity | Finding.severity | critical → high → medium → low → info | 优先级排序 |
| by_category | Finding.category + rule_id prefix | 按 finding count 降序 | 问题类别分布 |
| by_tool | 从 evidence_ref / message 中提取 tool_name | 按 finding count 降序 | 工具级别问题排名 |
| by_rule_id_prefix | rule_id 的 top-level prefix（如 `tool_response`、`tool_spec`） | 按 finding count 降序 | 规则命中排名 |

### 不丢 finding、不重复 finding

所有分组的 finding 集合的 multiset 必须等于原始 findings 的 multiset。这是单测的核心 invariant。

### 为什么 by_tool 需要从 evidence_ref / message 提取

Finding 数据结构中没有 `tool_name` 字段。但 rule_id 和 message 中包含工具名信息（如 `tool_ergonomics.name.too_generic::my_tool`）。工具名提取规则在 FindingGrouper 中集中定义，不分散到各 inspector。

---

## Decision 4: Recommendations Are Deterministic Report Content

### 问题

v3.0 的 finding message 描述了"发现了什么问题"，但没有系统性地回答"下一步该改什么"。suggested_fix 字段只在部分 inspector（ToolDesignAuditor）中存在，且格式不统一。

### 决策

`RecommendationCatalog` 是 **确定性映射表**：`(rule_id_prefix, category, severity) → recommendation text`。

### 关键设计选择

**为什么是确定性的，不是 LLM 生成的？**

1. **离线可用** — 不依赖 LLM，CI 里随时可生成
2. **输出稳定** — 同一份 findings 每次产生相同建议
3. **覆盖已知规则** — v3.0 的 31 条 deterministic rule_id 全部有对应的 recommendation（未匹配 rule_id 走 fallback）
4. **无幻觉风险** — 不会建议不存在的东西

**推荐格式**：每条 recommendation 包含三要素：
- **What** — 问题是什么（引用 rule_id）
- **Why** — 为什么重要（引用 Anthropic 工具设计原则）
- **How to fix** — 具体修复方向（可操作、不模糊）

**示例**：

| rule_id | recommendation |
|---------|---------------|
| `tool_response.output.low_signal` | 工具输出信号过低：返回内容以 IDs/状态码为主，缺少有意义的上下文。为 `output` 增加 `context_fields`（如名称、描述、状态），帮助 Agent 做下一步推理。 |
| `tool_response.error.actionable` | 工具错误消息不可操作：当前 error 内容无法指导 Agent 或开发者定位问题。在 error 中增加 `suggested_action` 字段，含期望输入格式或修复提示。 |
| `tool_spec.description.useful_length` | 工具描述过短（<20 字符）：Agent 无法从描述中理解工具用途。将 description 扩展为 1-2 句话，说明工具做什么、何时使用、输入输出。 |
| `tool_ergonomics.name.too_generic` | 工具名过于通用：Agent 容易混淆此工具与其他工具。为工具名增加领域前缀（如 `search_documents` 而非 `search`），体现具体能力边界。 |
| `tool_pair.orphan_call` | 存在孤立 tool_call：调用了工具但没有收到 tool_result。检查 Agent runner 的工具执行链路，确保每次 tool_call 都返回 tool_result（包括 error）。 |
| `tool_call.arguments.present` | tool_call 缺少 arguments：Agent 调用了工具但未传参数。检查 Agent prompt 是否引导 Agent 在调用工具时正确填充 arguments。 |

**Fallback**：未匹配到 rule_id 的 finding，按 severity 给通用建议：
- critical/high → "定位 evidence_ref 指向的原始数据，确认是否为数据错误或 inspector 规则过严"
- medium/low → "评估是否需要修复，或标记为已知限制"
- info → "仅供参考，不需要立即行动"

---

## Decision 5: Markdown and JSON Report Share the Same Report Model

### 问题

v3.0 的 Markdown report（`render_from_core()`）直接从 bridge dict 渲染，JSON report 没有正式定义。两者如果各自维护渲染逻辑，必然出现内容不一致——Markdown 里有的信息 JSON 里没有，反之亦然。

### 决策

`ReportInsight` 是 **单一聚合对象**，包含 metrics / scorecard / grouped_findings / recommendations。

Markdown 和 JSON 渲染器都**只消费 ReportInsight**，不做独立计算：

```
ReportInsight
    ├── markdown_renderer(ReportInsight) → report.md
    └── json_renderer(ReportInsight) → report.json
```

### JSON report 结构

```json
{
  "summary": {
    "passed": false,
    "total_findings": 12,
    "errors": 3,
    "warnings": 7,
    "info": 2,
    "advisory_count": 1,
    "generated_at": "2026-05-15T10:00:00Z"
  },
  "metrics": {
    "tool_call_count": 8,
    "tool_result_count": 7,
    "unique_tool_count": 4,
    "tool_success_count": 6,
    "tool_error_count": 1,
    "tool_error_rate": 0.125,
    "orphan_call_count": 1,
    "orphan_result_count": 0,
    "repeated_tool_call_count": 2,
    "response_size_chars_total": 12400,
    "response_size_chars_by_tool": {"search": 5000, "read": 7400},
    "estimated_response_tokens_total": 3100,
    "finding_count_by_severity": {"critical": 1, "high": 2, "medium": 7, "low": 0, "info": 2},
    "finding_count_by_category": {"tool_response": 4, "tool_spec": 3, "tool_ergonomics": 2, "tool_call": 1, "tool_pair": 1, "judge": 1},
    "finding_count_by_tool": {"search": 5, "read": 3, "write": 2},
    "judge_finding_count": 1
  },
  "scorecard": {
    "passed": false,
    "total_findings": 12,
    "severity_breakdown": {"error": 3, "warning": 7, "info": 2},
    "advisory_count": 1,
    "tools_called": 4,
    "tool_errors": 1,
    "tool_error_rate": 0.125,
    "top_issue_categories": ["tool_response", "tool_spec", "tool_ergonomics"],
    "top_affected_tools": ["search", "read", "write"]
  },
  "findings": [...],
  "grouped_findings": {
    "by_severity": {...},
    "by_category": {...},
    "by_tool": {...},
    "by_rule_id_prefix": {...}
  },
  "recommendations": [...],
  "judge_findings": [...],
  "metadata": {
    "schema_version": "3.1.0",
    "generated_at": "2026-05-15T10:00:00Z",
    "signal_quality": "unknown"
  }
}
```

### Markdown report 新增段（排在现有 detailed findings 之前）

```markdown
## Scorecard
| Metric | Value |
|--------|-------|
| Passed | ❌ FAIL |
| Total Findings | 12 |
...

## Metrics
...

## Top Issues
...

## Findings by Severity
...

## Findings by Tool
...

## Recommendations
1. ...
2. ...
```

---

## Compatibility

### 不破坏的

| 对象 | 兼容方式 |
|------|---------|
| `Finding` / `RuleFinding` / `JudgeFinding` | 不修改任何字段 |
| `EvaluationResult` | 不修改，`findings` 列表不变 |
| `ReportSummary` | 不修改 |
| `core_report_bridge.py` | 不修改现有函数，新增 insight bridge 函数 |
| `MarkdownReport.render_from_core()` | 不修改签名，新增可选 insight 参数或在 render 内部构造 insight |
| 现有 1100+ tests | 全部保持通过 |

### 新增的

| 新增项 | 位置 |
|--------|------|
| `ReportMetrics` dataclass | 新模块 `report_insight.py` 或 `reports/metrics.py` |
| `MetricsCollector` | 同上 |
| `FindingGrouper` | 同上 |
| `ReportScorecard` | 同上 |
| `RecommendationCatalog` | 同上 |
| `ReportInsight` | 同上 |
| `render_insight_to_markdown()` | `markdown_report.py` 新增方法 |
| `render_insight_to_json()` | `core_report_bridge.py` 或新模块 |

---

## Acceptance Criteria

1. **Scorecard** — report 顶部展示 passed 状态和分 severity 计数，与 EvaluationResult 一致
2. **Metrics** — 15 个 metric 全部可计算，与 ExecutionTrace 原始数据一致
3. **Grouped Findings** — 4 种分组视图，不丢不重，group 内按 count 降序
4. **Recommendations** — 覆盖当前 31 条 deterministic rule_id（initial coverage，含 fallback），确定性输出，不调 LLM
5. **Markdown** — 所有新段可渲染，包含 Scorecard / Metrics / Top Issues / Findings by Severity / Findings by Tool / Recommendations
6. **JSON** — 结构稳定，所有 key 有明确类型，可被 CI 工具消费
7. **兼容** — 现有 1100+ tests 全部通过，无 regression
8. **零网络依赖** — insight 层所有计算为 deterministic，不调 LLM、不联网
