# V3.6 Milestone: Tool Portfolio Review + Tool Improvement Brief

> **Status: Implemented in v3.6.0** — 设计已落地。依赖 v3.1-v3.5 的累积信号。

## TLDR

v3.1-v3.5 提供了单个工具、单条 trace、单个 task 的检查和分析。v3.6 收口：从工具组合级别评审设计问题（命名空间一致性、工具重叠、浅封装泛滥、缺失高层 workflow 工具），并从累积的 findings/metrics/task outcomes 中收集证据，产出结构化 ToolImprovementBrief。

---

## 1. 背景

Anthropic 文章强调工具设计不只是单个工具的 spec 写得好不好，更是**工具组合**的设计质量：
- 工具之间有没有命名空间一致性？
- 有没有功能重叠让人混淆？
- 有没有浅封装 API 而非提供领域语义？
- 有没有缺失的高层 workflow 工具？

v3.6 从 v3.1-v3.5 的累积信号中提取 portfolio 级别的评审和改进建议。

---

## 2. 用户问题

| # | 问题 |
|---|------|
| 1 | "我的 15 个工具里，哪些应该合并？" |
| 2 | "search_docs 和 find_documents 有什么区别？Agent 是不是也分不清？" |
| 3 | "有 3 个工具只是 API 的浅封装，是不是该提高抽象层级？" |
| 4 | "我的工具组合里有没有缺少关键 workflow 工具？" |
| 5 | "能不能给我一份结构化的改进 brief，我可以直接贴到 PR 里或给 Claude Code review？" |

---

## 3. v3.6 核心设计

### 3.1 ToolPortfolioReview

静态分析 + 信号聚合，检查 5 类结构问题：

| 检查维度 | 检测方式 | 信号来源 |
|---------|---------|---------|
| namespacing consistency | 工具名 pattern 一致性（namespace.action_resource） | ToolSpec[].name |
| overlapping tools | 工具名编辑距离 < 阈值 + 功能描述相似 | ToolSpec[].name + ToolSpec[].description |
| shallow wrapper portfolio | 工具名匹配 CRUD 后缀 + description 中无领域语义 | ToolSpec[].name + ToolSpec[].description |
| missing higher-level tool | 多个 low-level 工具覆盖同一 workflow，缺少组合入口 | findings（frequently_chained_tools from D4） |
| tool grouping by resource | 工具按资源域分组，发现不均衡 | ToolSpec[].name pattern |

### 3.2 ToolImprovementBrief

结构化改进建议文档，不自动修改任何文件：

```
ToolImprovementBrief
  ├── tool_name
  ├── priority (critical/high/medium/low)
  ├── category (spec_quality / ergonomics / response / portfolio)
  ├── evidence: list[EvidenceRef]
  │   ├── finding_refs: list[str]
  │   ├── metric_values: dict[str, float]
  │   ├── task_outcome_refs: list[str]
  │   └── transcript_signal_refs: list[str]
  ├── current_state: str
  ├── recommended_state: str
  ├── rationale: str
  └── effort_estimate: str
```

### 3.3 不自动修改

ToolImprovementBrief 提供 what/why/how，但**不自动修改 tool spec、不自动改代码、不自动重跑 Agent**。改进 brief 供人工 review 或 Claude Code 辅助修改时参考。

---

## 4. 依赖

- v3.1 ToolSpec + findings + metrics + recommendations
- v3.2 TaskOutcome（evidence 增强）
- v3.3 suite aggregation（跨 case 证据增强，推荐但非强制）
- v3.4 regression comparison（改进前后对比增强，推荐但非强制）
- v3.5 confusion/context signals（evidence 增强，推荐但非强制）

---

## 5. 完成定义

- [ ] ToolPortfolioReview 覆盖 5 类结构问题
- [ ] ToolImprovementBrief 含 evidence 引用
- [ ] Markdown/JSON brief 输出可用
- [ ] 不自动修改 tool spec
- [ ] ≥ 20 个新增单测
- [ ] 现有 1300+ tests 无 regression
