# SDD: Tool Portfolio Review + Tool Improvement Brief V3.6

> **Implementation Status: Implemented** — v3.6.0 落地。

## TLDR

v3.6 新增 4 个组件：ToolPortfolioReview、PortfolioFinding、ToolImprovementBrief、EvidenceRef。不修改已有对象。不自动修改 tool spec。

---

## 1. PortfolioFinding

```python
@dataclass(frozen=True)
class PortfolioFinding:
    check_name: str              # namespacing_consistency | overlapping_tools | ...
    severity: str
    affected_tools: list[str]
    description: str
    suggestion: str
    evidence: list[str]          # 引用的 ToolSpec name、finding_id 等
```

---

## 2. ToolPortfolioReview

### 2.1 接口

```python
class ToolPortfolioReview:
    def review(
        self,
        tool_specs: list[ToolSpec],
        findings: list[Finding] | None = None,
        task_outcomes: list[TaskOutcome] | None = None,
        transcript_signals: list[RuleFinding] | None = None,
    ) -> list[PortfolioFinding]:
        ...
```

### 2.2 5 个检查方法

| 方法 | 检测逻辑 |
|------|---------|
| `_check_namespacing()` | 统计不符合 `\w+\.\w+` 格式的工具名比例 |
| `_check_overlap()` | 编辑距离 ≤ 2 的工具对 |
| `_check_shallow_wrappers()` | 工具名含 `get_`/`set_`/`create_`/`delete_` 且 description 无领域词 |
| `_check_missing_higher_level()` | D4 `frequently_chained_tools` signal 集合 |
| `_check_resource_grouping()` | 按 tool_name prefix 分组，检查分布 |

---

## 3. ToolImprovementBrief

### 3.1 数据结构

```python
@dataclass(frozen=True)
class EvidenceRef:
    finding_ids: list[str] = field(default_factory=list)
    metric_values: dict[str, float] = field(default_factory=dict)
    task_outcome_ids: list[str] = field(default_factory=list)
    transcript_signal_types: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class ToolImprovementBrief:
    tool_name: str
    priority: str                # critical | high | medium | low
    category: str                # spec_quality | ergonomics | response | portfolio
    evidence: EvidenceRef
    current_state: str
    recommended_state: str
    rationale: str
    effort_estimate: str         # small | medium | large
```

### 3.2 生成方式

```python
class ToolImprovementBriefGenerator:
    def generate_per_tool(
        self,
        tool_name: str,
        findings: list[Finding],
        metrics: ReportMetrics,
        task_outcomes: list[TaskOutcome] | None = None,
    ) -> ToolImprovementBrief:
        ...

    def generate_cross_tool(
        self,
        portfolio_findings: list[PortfolioFinding],
    ) -> list[ToolImprovementBrief]:
        ...
```

---

## 4. 报告格式

### Markdown

```markdown
## Tool Portfolio Review

### Namespacing Consistency
- ⚠ 5/15 tools (33%) do not follow "namespace.action_resource" pattern
- Affected: search, read, write, delete, update
- Suggestion: Rename to "doc_search", "doc_read", etc.

### Overlapping Tools
- ⚠ "search_docs" vs "find_documents"
- Suggestion: Merge or clarify difference in description

## Tool Improvement Briefs

### search (priority: high)
- **Current State**: Tool name too generic, response often bloated
- **Recommended**: Rename to "doc_search", add "max_results" parameter
- **Evidence**: 3 findings (tool_ergonomics.name.too_generic ×1, response_bloat ×2)
- **Effort**: small
```

---

## 5. 测试策略

| 测试文件 | 测试数 | 覆盖 |
|---------|--------|------|
| `tests/test_portfolio_review.py` | ~12 | 5 类检查各 2-3 scenario |
| `tests/test_improvement_brief.py` | ~8 | brief 生成、evidence 引用完整 |
| `tests/test_portfolio_report.py` | ~3 | Markdown/JSON |

**总计：≥ 23 个新增单测。**
