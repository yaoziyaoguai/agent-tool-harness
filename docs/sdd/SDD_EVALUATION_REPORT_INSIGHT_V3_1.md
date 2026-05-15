# SDD: Evaluation Report Insight V3.1

> **Implementation Status: Completed in v3.1.0 (2026-05-15)** — 所有 6 个组件按 SDD 实现，42 个集成测试通过，1329 tests 零 regression。

## TLDR

在 v3.0 的 ExecutionTrace + EvaluationResult 之上，新增 **6 个组件**：ReportMetrics、MetricsCollector、FindingGrouper、ReportScorecard、RecommendationCatalog、ReportInsight。所有组件为 deterministic、零网络依赖。Markdown 和 JSON report 共享同一 ReportInsight 数据模型。不修改任何 v3.0 Core Contract 对象。

---

## 1. ReportMetrics

### 1.1 数据结构

```python
@dataclass(frozen=True)
class ReportMetrics:
    """一次 evaluation run 的聚合指标。"""

    # --- Tool call 统计 ---
    tool_call_count: int = 0
    tool_result_count: int = 0
    unique_tool_count: int = 0

    # --- 成功/失败 ---
    tool_success_count: int = 0
    tool_error_count: int = 0
    tool_error_rate: float = 0.0

    # --- 数据完整性 ---
    orphan_call_count: int = 0
    orphan_result_count: int = 0

    # --- 冗余 ---
    repeated_tool_call_count: int = 0

    # --- 响应大小 ---
    response_size_chars_total: int = 0
    response_size_chars_by_tool: dict[str, int] = field(default_factory=dict)
    estimated_response_tokens_total: int = 0

    # --- Finding 统计 ---
    finding_count_by_severity: dict[str, int] = field(default_factory=dict)
    finding_count_by_category: dict[str, int] = field(default_factory=dict)
    finding_count_by_tool: dict[str, int] = field(default_factory=dict)
    judge_finding_count: int = 0
```

### 1.2 字段说明

| 字段 | 计算方式 |
|------|---------|
| `tool_call_count` | `len(trace.tool_calls)` |
| `tool_result_count` | `len(trace.tool_results)` |
| `unique_tool_count` | `len(set(c.tool_name for c in trace.tool_calls))` |
| `tool_success_count` | `sum(1 for r in trace.tool_results if r.status == "success")` |
| `tool_error_count` | `sum(1 for r in trace.tool_results if r.status == "error")` |
| `tool_error_rate` | `tool_error_count / max(tool_call_count, 1)` |
| `orphan_call_count` | `tool_call.call_id` 不在 `tool_results` 的 `call_id` 集合中的数量 |
| `orphan_result_count` | `tool_result.call_id` 不在 `tool_calls` 的 `call_id` 集合中的数量 |
| `repeated_tool_call_count` | 同一 `(tool_name, json.dumps(arguments, sort_keys=True, default=str))` 重复出现 ≥2 次的调用次数 |
| `response_size_chars_total` | `sum(len(json.dumps(r.output)))` for all tool_results |
| `response_size_chars_by_tool` | 同上按 `tool_name` 分组 |
| `estimated_response_tokens_total` | `response_size_chars_total // 4` |
| `finding_count_by_severity` | `Counter(f.severity for f in eval_result.findings)` |
| `finding_count_by_category` | `Counter(f.category for f in eval_result.findings)` 或按 rule_id prefix（见 FindingGrouper） |
| `finding_count_by_tool` | 从 finding 的 finding_id / evidence_ref / message 提取 tool_name → Counter |
| `judge_finding_count` | `sum(1 for f in eval_result.findings if f.category == "judge")` |

> **说明**：`tool_success_count` 是状态指标，只看 `status=="success"`。output 是否有意义（如 low_signal、context_fields）由 D5 response quality findings 和 recommendations 表达，不在此处与 success status 混在一起。

### 1.3 边界条件

| 条件 | 行为 |
|------|------|
| `trace.tool_calls` 为空 | 所有 count 为 0，rate 为 0.0 |
| `trace.tool_results` 为空 | success/error 为 0，orphan_call_count = tool_call_count |
| `eval_result.findings` 为空 | 所有 finding_count_* 为空 dict |
| `tool_name` 为空字符串 | 计入 `"(unknown)"` bucket |
| `response_size_chars_total` 极大（>10M chars） | 不截断，标注为 estimate；`estimated_response_tokens_total = chars // 4` 是粗估算（适用于英文为主 trace，中文等 CJK 文本偏差可能较大，v3.1 不作为精确 token accounting） |

---

## 2. MetricsCollector

### 2.1 接口

```python
class MetricsCollector:
    """从 ExecutionTrace + EvaluationResult 计算 ReportMetrics。"""

    def collect(
        self,
        trace: ExecutionTrace,
        eval_result: EvaluationResult,
    ) -> ReportMetrics:
        ...
```

### 2.2 输入

| 参数 | 类型 | 来源 |
|------|------|------|
| `trace` | `ExecutionTrace` | adapter.run() 或 TraceImportAdapter |
| `eval_result` | `EvaluationResult` | CoreEvaluation.evaluate() |

### 2.3 输出

`ReportMetrics` — 见 §1。

### 2.4 设计约束

- **不修改输入** — trace 和 eval_result 只读
- **不调 LLM** — 纯计算
- **不访问文件系统** — 不读写 JSON/artifact 文件
- **不依赖外部库** — 只用 stdlib `json`、`collections.Counter`

### 2.5 `response_size_chars_by_tool` 计算

```python
by_tool: dict[str, int] = {}
for result in trace.tool_results:
    size = len(json.dumps(result.output))
    by_tool[result.tool_name or "(unknown)"] = by_tool.get(result.tool_name or "(unknown)", 0) + size
```

### 2.6 `repeated_tool_call_count` 计算

```python
from collections import Counter
# 只计重复的（count >= 2）
# 使用 json.dumps 以保留完整参数等价性，支持 nested dict/list
call_counts = Counter(
    (c.tool_name, json.dumps(c.arguments, sort_keys=True, default=str))
    for c in trace.tool_calls
)
repeated = sum(cnt for _, cnt in call_counts.items() if cnt >= 2)
```

### 2.7 `finding_count_by_category` 策略

`Finding.category` 在 v3.0 中的值为 `"rule" | "judge" | "audit" | "signal"`。对于 `category="rule"` 的 finding，进一步按 `rule_type` 的 **top-level prefix** 分子类别。

> **术语**：代码中 `RuleFinding` 的字段名为 `rule_type`（如 `tool_response.output.low_signal`）。文档中 `rule_id` 在 recommendation catalog 上下文中指同一概念——`Recommendation.rule_id` 的值取自 `Finding.rule_type`。`rule_id_prefix` 表示 top-level namespace（`tool_pair` / `tool_spec` / `tool_response` 等），由 `rule_type` 按 `.` 分割的第一段得到。实现时应读取 `getattr(finding, "rule_type", None)`，兼容 `JudgeFinding`（无此字段）。

| rule_id 前缀 | 子类别 |
|-------------|--------|
| `tool_call.*` | `tool_call` |
| `tool_result.*` | `tool_result` |
| `tool_pair.*` | `tool_pair` |
| `tool_response.*` | `tool_response` |
| `tool_spec.*` | `tool_spec` |
| `tool_ergonomics.*` | `tool_ergonomics` |

这样 `finding_count_by_category` 的粒度足够区分"工具响应问题"和"工具规格问题"。

> **说明**：`audit` 和 `signal` buckets 是 defensive / future-compatible buckets。v3.1 P1 不要求新增 audit / signal finding producer。当前主要 category 来源仍是 `rule` / `judge`，以及 rule_id prefix 推导出的子类别。如果没有 audit / signal findings，bucket 可以为空或省略，具体按 JSON schema 设计决定。

---

## 3. FindingGrouper

### 3.1 接口

```python
@dataclass(frozen=True)
class GroupedFindings:
    """同一份 findings 的四种聚合视图。"""
    by_severity: dict[str, list[Finding]]
    by_category: dict[str, list[Finding]]
    by_tool: dict[str, list[Finding]]
    by_rule_id_prefix: dict[str, list[Finding]]


class FindingGrouper:
    """按多种维度对 findings 分组。"""

    def group(self, findings: list[Finding]) -> GroupedFindings:
        ...
```

### 3.2 分组规则

#### by_severity

- key = `Finding.severity`（`"critical"`, `"high"`, `"medium"`, `"low"`, `"info"`）
- group 内**保持原始 findings 顺序**（时序稳定）
- 空 severity 的 finding → 归入 `"(unknown)"` bucket

#### by_category

- 对 `category="rule"` 的 finding，key = rule_id 的 top-level prefix（如 `tool_response`、`tool_spec`）
- 对 `category="judge"` 的 finding，key = `"judge"`
- 对 `category="audit"` 的 finding，key = `"audit"`
- 对 `category="signal"` 的 finding，key = `"signal"`
- 无法归类的 → `"(other)"` bucket
- group 内**按 severity 降序**排列（critical 在前）

#### by_tool

- 从 finding 中提取关联的 tool_name：
  1. 从 `finding_id` 字段中解析（格式：`rule_id_prefix::tool_name`，如 `tool_ergonomics.name.too_generic::my_tool` → `my_tool`；`tool_pair.orphan_call::call_id` → 仅得到 call_id，v3.1 可先归入 `"(unknown)"`，后续再通过 trace call_id→tool_name 映射增强）
  2. 从 `evidence_ref` 字段中解析（如 `tool_calls::call_id=c1` → 查 trace.tool_calls 获取 tool_name）
  3. 从 `message` 中解析（如 "Tool 'search' has ..."）
  4. 无法提取 → `"(unknown)"` bucket
- group 内**按 severity 降序**排列

> **best-effort extraction**：上述 tool_name 提取是 best-effort 策略。rule_type / rule_id 字段不编码具体 tool_name（如 `tool_pair.orphan_call` 不含 tool 信息），`finding_id` 也不保证一定包含 tool_name。预期覆盖率 60%-80%（基于当前 v3.0 finding 样本估计）。P2 实现时应用真实 finding 样本验证覆盖率。`FindingGrouper` 不得假设 `rule_type` 携带 tool_name。

#### by_rule_id_prefix

- key = rule_id 的 top-level prefix（用 `.` 分割取第一段）。**注意**：代码中 `Finding` 的字段名为 `rule_type`，此处的 `rule_id` / `rule_id_prefix` 语义上等同于 `rule_type` 值。`FindingGrouper` 应使用 `getattr(finding, "rule_type", None)` 读取，以兼容 `JudgeFinding`（可能无此字段）。

- key = rule_id 的 top-level prefix（用 `.` 分割取第一段）
- group 内**按 finding count 降序**排列（命中最多的规则排在前面）

### 3.3 不变量

| 不变量 | 验证方式 |
|--------|---------|
| 所有 group 的 finding 总数 = 原始 findings 总数 | 单测 assert |
| 所有 group 的 finding ID 集合 = 原始 findings ID 集合 | 单测 assert |
| 无 duplicate finding（同一 finding_id 不出现在同一 group 两次） | 单测 assert |

### 3.4 排序约定

- 所有 group-level 排序：**按 finding 数量降序**。数量相同则按 key 字母序。
- group 内部排序：**按 severity 降序**（critical → high → medium → low → info），同 severity 按 finding_id 字母序。

---

## 4. ReportScorecard

### 4.1 数据结构

```python
@dataclass(frozen=True)
class ReportScorecard:
    """报告「一页纸」结论。"""
    passed: bool
    total_findings: int
    errors: int          # severity in ("critical", "high")
    warnings: int        # severity in ("medium", "low")
    info: int            # severity == "info"
    advisory_count: int  # category == "judge" 的 finding 数
    tools_called: int    # unique_tool_count
    tool_errors: int     # tool_error_count
    top_issue_categories: list[str]   # 前 5 个按 finding count 降序
    top_affected_tools: list[str]     # 前 5 个按 finding count 降序
```

### 4.2 生成方式

`ReportScorecard` 是纯 dataclass（value object），不包含复杂 factory method。构造逻辑放在独立 builder 函数中：

```python
def make_scorecard(
    metrics: ReportMetrics,
    groups: GroupedFindings,
    passed: bool,
) -> ReportScorecard:
    """从 metrics + groups 构建 ReportScorecard。"""
    ...
```

### 4.3 计算规则

| 字段 | 来源 |
|------|------|
| `passed` | `eval_result.passed` |
| `total_findings` | `len(eval_result.findings)` |
| `errors` | `metrics.finding_count_by_severity.get("critical", 0) + metrics.finding_count_by_severity.get("high", 0)` |
| `warnings` | `metrics.finding_count_by_severity.get("medium", 0) + metrics.finding_count_by_severity.get("low", 0)` |
| `info` | `metrics.finding_count_by_severity.get("info", 0)` |
| `advisory_count` | `metrics.judge_finding_count` |
| `tools_called` | `metrics.unique_tool_count` |
| `tool_errors` | `metrics.tool_error_count` |
| `top_issue_categories` | `groups.by_category` 前 5 个 category（按 finding count 降序） |
| `top_affected_tools` | `metrics.finding_count_by_tool` 前 5 个 tool（按 count 降序，排除 "(unknown)"） |

> **severity_breakdown 映射**：JSON `scorecard.severity_breakdown` 使用三档聚合展示，与 `finding_count_by_severity`（五级原始 severity）的关系如下：
>
> | `severity_breakdown` | 来源（五级 → 三档） |
> |:---:|------|
> | `error` | `critical` + `high` |
> | `warning` | `medium` + `low` |
> | `info` | `info` |
>
> `finding_count_by_severity` 保留五级原始数据（`critical` / `high` / `medium` / `low` / `info`），供需要细分查看的 consumer 使用。`scorecard.severity_breakdown` 提供简化的三档视图。两者不冲突——JSON consumer 不应将两者理解为矛盾。

### 4.4 Markdown 渲染

```markdown
## Scorecard

| Metric | Value |
|--------|-------|
| Passed | ✅ PASS / ❌ FAIL |
| Total Findings | 12 |
| Errors | 3 |
| Warnings | 7 |
| Info | 2 |
| Advisory | 1 |
| Tools Called | 4 |
| Tool Errors | 1 |
| Top Issue Categories | tool_response (4), tool_spec (3), tool_ergonomics (2) |
| Top Affected Tools | search (5), read (3), write (2) |
```

---

## 5. RecommendationCatalog

### 5.1 接口

```python
@dataclass(frozen=True)
class Recommendation:
    rule_id: str
    category: str
    severity: str
    what: str       # 问题描述
    why: str        # 为什么重要
    how_to_fix: str # 具体修复方向

> **术语**：`Recommendation.rule_id` 是 recommendation catalog 的 key，其值取自 `Finding.rule_type`（如 `tool_response.output.low_signal`）。`RecommendationCatalog` 内部按 `rule_id` 查找映射表，未匹配的走 §5.4 fallback。

class RecommendationCatalog:
    def recommend(self, finding: Finding) -> Recommendation:
        ...

    def recommend_all(self, findings: list[Finding]) -> list[Recommendation]:
        ...
```

### 5.2 映射表（initial coverage follows current v3.0 rule IDs）

> **说明**：以下映射覆盖当前 v3.0 代码中已落地的 31 条 deterministic rule_id。对未匹配的 rule_id 走 §5.4 fallback。未来新增 inspector 规则时应同步扩展此表。

#### tool_response 类

| rule_id | what | why | how_to_fix |
|---------|------|-----|------------|
| `tool_response.success.output_present` | 成功的工具调用未返回 output | Agent 无法从工具调用中获取信息 | 确保 tool_result.status=="success" 时 output 非空 |
| `tool_response.failure.error_present` | 失败的工具调用未返回 error 消息 | Agent 不知道调用为什么失败 | 确保 tool_result.status=="error" 时 error 字段包含错误原因 |
| `tool_response.output.size_reasonable` | 工具输出过大 | 浪费 token 预算，可能超出上下文窗口 | 为工具增加分页或 `max_results` 参数；或让 output 只返回摘要 |
| `tool_response.output.low_signal` | 工具输出信号过低 | 返回内容以 IDs/状态码为主，缺少有意义的上下文 | 为 output 增加 `context_fields`（名称、描述、状态），帮助 Agent 做下一步推理 |
| `tool_response.error.actionable` | 工具错误消息不可操作 | 当前 error 内容无法指导 Agent 或开发者定位问题 | 在 error 中增加 `suggested_action` 字段，含期望输入格式或修复提示 |
| `tool_response.output.context_fields_present` | 工具输出缺少上下文字段 | Agent 无法将结果关联到用户意图 | 确保 output 包含 name/title/description 等上下文字段，而非仅数据 |

#### tool_spec 类

| rule_id | what | why | how_to_fix |
|---------|------|-----|------------|
| `tool_spec.description.exists` | 工具缺少 description | Agent 无法选择正确的工具 | 为工具添加描述其用途和时机的 description |
| `tool_spec.description.useful_length` | 工具描述过短（<20 字符） | Agent 无法从描述中理解工具用途 | 将 description 扩展为 1-2 句话，说明做什么、何时使用、输入输出 |
| `tool_spec.input_schema.exists` | 工具缺少 input_schema | Agent 不知道传什么参数 | 添加 JSON Schema 格式的 input_schema |
| `tool_spec.parameter.name.explicit` | 参数名不明确 | Agent 可能传错参数名或值 | 使用描述性参数名，在 input_schema 中为每个参数添加 description |
| `tool_spec.required_parameter.documented` | 必填参数未标注 | Agent 可能遗漏必填参数 | 在 input_schema 的 required 数组中列出所有必填参数 |
| `tool_spec.output_contract.documented` | 输出格式未文档化 | Agent 不知道工具返回什么 | 添加 output_contract，描述返回字段的类型和含义 |
| `tool_spec.side_effects.documented` | 副作用未声明 | Agent 可能执行不可逆操作而不自知 | 在工具描述中标注是否有副作用（读/写/删除） |
| `tool_spec.when_to_use.documented` | 使用场景未说明 | Agent 不知道该在什么时候调用此工具 | 添加 when_to_use 描述使用场景 |
| `tool_spec.when_not_to_use.documented` | 禁用场景未说明 | Agent 可能在错误的场景调用此工具 | 添加 when_not_to_use 描述不应使用此工具的情况 |
| `tool_spec.token_policy.defined` | token 策略未定义 | 工具返回可能消耗过多 token | 定义 token_policy，说明工具输出的典型 token 消耗 |

#### tool_ergonomics 类

| rule_id | what | why | how_to_fix |
|---------|------|-----|------------|
| `tool_ergonomics.name.too_generic` | 工具名过于通用 | Agent 容易混淆功能相似的工具 | 为工具名增加领域前缀（如 `doc_search` 而非 `search`） |
| `tool_ergonomics.name.namespace_present` | 工具缺少命名空间 | 工具名之间缺乏层次结构 | 使用 `namespace.action_resource` 格式命名工具 |
| `tool_ergonomics.names.overlap` | 工具名重叠 | Agent 无法区分功能相近的工具 | 为每个工具明确其与其他工具的差异，或合并重叠工具 |
| `tool_ergonomics.too_many_similar_tools` | 相似工具过多 | Agent tool selection 难度增加 | 考虑将相似工具合并为带参数的单一工具 |
| `tool_ergonomics.description.shallow_wrapper` | 工具是 API 的浅封装 | 工具粒度过细，Agent 需要多次调用 | 提升工具抽象层级，提供领域语义而非 CRUD 操作 |
| `tool_ergonomics.action_resource_clarity` | 工具名中动作/资源关系不清 | Agent 无法从名字推断工具功能 | 确保工具名清晰表达"在什么资源上执行什么操作" |

#### tool_call / tool_pair 类

| rule_id | what | why | how_to_fix |
|---------|------|-----|------------|
| `tool_call.arguments.present` | tool_call 缺少 arguments | Agent 调用工具时未传参数 | 检查 Agent prompt 是否引导 Agent 在调用时正确填充 arguments |
| `tool_call.arguments.is_object` | arguments 不是有效 JSON object | 工具执行器无法解析参数 | 确保 Agent 输出格式正确，arguments 为 JSON object |
| `tool_call.call_id.duplicate` | 重复的 call_id | 无法区分不同的工具调用 | 确保 Agent runner 为每次调用生成唯一 call_id |
| `tool_call.tool_name.non_empty` | tool_name 为空 | 无法确定调用了哪个工具 | 确保 Agent 在每次 tool_call 中明确指定 tool_name |
| `tool_result.call_id.duplicate` | 重复的 result call_id | 无法确定 result 对应哪个调用 | 确保工具执行器为每个 result 使用唯一 call_id |
| `tool_result.tool_name.non_empty` | result 的 tool_name 为空 | 无法追溯工具调用来源 | 确保 tool_result 包含 tool_name |
| `tool_result.status.valid` | 无效的 status 值 | 下游无法判断调用是否成功 | 确保 status 为 "success" 或 "error" |
| `tool_pair.orphan_call` | 存在孤立 tool_call | tool_call 没有对应的 tool_result，数据不完整 | 检查 Agent runner 的工具执行链路，确保每次调用都有返回 |
| `tool_pair.orphan_result` | 存在孤立 tool_result | tool_result 没有对应的 tool_call，数据异常 | 检查 trace 记录完整性，确认 call_id 匹配 |

### 5.3 去重策略

`recommend_all()` 对同一 rule_id 前缀的多个 finding 去重：只生成一条 recommendation（附加 affected count）。避免 report 中 recommendations 列表冗长。

```python
# 例：3 条 tool_response.output.low_signal → 合并为 1 条 recommendation
# "工具输出信号过低 (affected: 3 calls)"
```

### 5.4 Fallback

```python
_FALLBACK_TEMPLATES = {
    "critical": "{rule_id}: 严重问题，立即检查 evidence_ref 指向的原始数据。",
    "high": "{rule_id}: 高优先级问题，在修复 medium/low 问题之前处理。",
    "medium": "{rule_id}: 中优先级问题，评估是否需要修复或标记为已知限制。",
    "low": "{rule_id}: 低优先级问题，可在后续迭代中处理。",
    "info": "{rule_id}: 仅供参考，不需要立即行动。",
}
```

---

## 6. ReportInsight

### 6.1 数据结构

```python
@dataclass(frozen=True)
class ReportInsight:
    """Report-level 聚合对象——Markdown 和 JSON report 的单一数据源。"""
    metrics: ReportMetrics
    scorecard: ReportScorecard
    grouped_findings: GroupedFindings
    recommendations: list[Recommendation]
    findings: list[Finding]          # 原始 findings（透传）
    judge_findings: list[JudgeFinding]  # 仅 judge category 的 findings
    metadata: ReportInsightMetadata


@dataclass(frozen=True)
class ReportInsightMetadata:
    schema_version: str = "3.1.0"
    generated_at: str = ""
    signal_quality: str = "unknown"
```

### 6.2 工厂方法

```python
class ReportInsight:
    @staticmethod
    def from_eval(
        trace: ExecutionTrace,
        eval_result: EvaluationResult,
        signal_quality: str = "unknown",
    ) -> "ReportInsight":
        """一站式构造 ReportInsight。"""
        collector = MetricsCollector()
        metrics = collector.collect(trace, eval_result)

        grouper = FindingGrouper()
        groups = grouper.group(eval_result.findings)

        scorecard = make_scorecard(
            metrics, groups, eval_result.passed
        )

        catalog = RecommendationCatalog()
        recommendations = catalog.recommend_all(eval_result.findings)

        judge_findings = [
            f for f in eval_result.findings if f.category == "judge"
        ]

        return ReportInsight(
            metrics=metrics,
            scorecard=scorecard,
            grouped_findings=groups,
            recommendations=recommendations,
            findings=eval_result.findings,
            judge_findings=judge_findings,
            metadata=ReportInsightMetadata(
                generated_at=datetime.utcnow().isoformat() + "Z",
                signal_quality=signal_quality,
            ),
        )
```

---

## 7. Markdown Report Integration

### 7.1 新增方法

在 `MarkdownReport` 中新增：

```python
def render_insight_section(self, insight: ReportInsight) -> str:
    """渲染 insight 段（Scorecard + Metrics + Top Issues + Grouped Findings + Recommendations）。
    
    返回 Markdown 字符串，可插入现有 render_from_core() 的 detailed findings 之前。
    """
```

### 7.2 推荐 Markdown 结构

```markdown
# Agent Tool Harness Report (Core Flow)

## Signal Quality
...

## Methodology Caveats
...

## Scorecard                    ← 新增
| Metric | Value |
|--------|-------|
| ...    | ...   |

## Metrics                      ← 新增
| Metric | Value |
|--------|-------|
| Tool Calls | 8 |
| Tool Results | 7 |
| ...

## Top Issues                   ← 新增
1. tool_response (4 findings)
2. tool_spec (3 findings)
...

## Findings by Severity         ← 新增
### critical (1)
- ...

### high (2)
- ...

### medium (7)
- ...

## Findings by Tool             ← 新增
### search (5 findings)
- ...

### read (3 findings)
- ...

## Recommendations              ← 新增
1. **tool_response.output.low_signal**: ...

## Agent Tool-Use Eval (Core Flow)  ← 现有
...

## Per-Eval Details                ← 现有
...

## Review Decision                 ← 现有
...
```

### 7.3 与现有 render_from_core() 的关系

**选定方式 A**：`render_from_core()` 内部调用 `ReportInsight.from_eval()`，自动插入 insight 段。

- 新 insight section（Scorecard → Metrics → Top Issues → Findings by Severity → Findings by Tool → Recommendations）排在现有 `## Agent Tool-Use Eval (Core Flow)` detailed findings 之前。
- `render()` 旧方法保持不变，不受影响。
- Insight 只影响 Core Flow 路径（`render_from_core()`），不影响单 eval render 路径。
- 不修改 `core_contract.py`。
- 测试需覆盖：旧 `render()` 路径不回归；新 `render_from_core()` 包含 Scorecard / Metrics / Top Issues / Recommendations 段。

---

## 8. JSON Report Shape

### 8.1 新增桥接函数

在 `core_report_bridge.py` 中新增：

```python
def report_insight_to_json_dict(insight: ReportInsight) -> dict[str, Any]:
    """把 ReportInsight 序列化为 JSON 兼容 dict。"""
```

### 8.2 完整 JSON Schema（参考）

```json
{
  "summary": {
    "passed": "bool",
    "total_findings": "int",
    "errors": "int",
    "warnings": "int",
    "info": "int",
    "advisory_count": "int",
    "generated_at": "string (ISO8601)"
  },
  "metrics": {
    "tool_call_count": "int",
    "tool_result_count": "int",
    "unique_tool_count": "int",
    "tool_success_count": "int",
    "tool_error_count": "int",
    "tool_error_rate": "float",
    "orphan_call_count": "int",
    "orphan_result_count": "int",
    "repeated_tool_call_count": "int",
    "response_size_chars_total": "int",
    "response_size_chars_by_tool": "{string: int}",
    "estimated_response_tokens_total": "int",
    "finding_count_by_severity": "{string: int}",
    "finding_count_by_category": "{string: int}",
    "finding_count_by_tool": "{string: int}",
    "judge_finding_count": "int"
  },
  "scorecard": {
    "passed": "bool",
    "total_findings": "int",
    "severity_breakdown": "{error: int, warning: int, info: int}",
    "advisory_count": "int",
    "tools_called": "int",
    "tool_errors": "int",
    "tool_error_rate": "float",
    "top_issue_categories": ["string (max 5)"],
    "top_affected_tools": ["string (max 5)"]
  },
  "findings": ["Finding[] — 透传 evaluation_result_to_report_dict()"],
  "grouped_findings": {
    "by_severity": "{string: [Finding]}",
    "by_category": "{string: [Finding]}",
    "by_tool": "{string: [Finding]}",
    "by_rule_id_prefix": "{string: [Finding]}"
  },
  "recommendations": [
    {
      "rule_id": "string",
      "category": "string",
      "severity": "string",
      "what": "string",
      "why": "string",
      "how_to_fix": "string",
      "affected_count": "int"
    }
  ],
  "judge_findings": ["JudgeFinding[] — 透传"],
  "metadata": {
    "schema_version": "3.1.0",
    "generated_at": "string (ISO8601)",
    "signal_quality": "string"
  }
}
```

---

## 9. 测试策略

### 9.1 MetricsCollector 单测

| 测试文件 | `tests/test_report_metrics.py` |
|----------|-------------------------------|
| 测试场景 | 空 trace、正常 trace、含 error 的 trace、含 orphan 的 trace、含重复调用的 trace |
| 断言 | 每个 metric 值与手动计算一致 |
| 测试数 | 约 15-20 个 |

### 9.2 FindingGrouper 单测

| 测试文件 | `tests/test_finding_grouper.py` |
|----------|-------------------------------|
| 测试场景 | 空 findings、单一 severity、混合 severity、混合 category、混合 tool、边界 tool_name |
| 关键不变量 | 总数相等、ID 集合相等、无重复 |
| 测试数 | 约 15-20 个 |

### 9.3 RecommendationCatalog 单测

| 测试文件 | `tests/test_recommendation_catalog.py` |
|----------|-------------------------------|
| 测试场景 | 每条已知 rule_id 有对应的 recommendation；未知 rule_id 走 fallback；同一 rule_id 去重 |
| 断言 | recommendation 的 what/why/how_to_fix 非空；不同 severity 的 fallback 正确 |
| 测试数 | 约 20-25 个（使用参数化测试覆盖 31 条 rule_id + fallback 场景） |

### 9.4 ReportScorecard 单测

| 测试文件 | `tests/test_report_scorecard.py` |
|----------|-------------------------------|
| 测试场景 | passed=true、passed=false、空 findings、仅 warnings、top-N 截断 |
| 断言 | passed/errors/warnings/info 与 metrics 一致；top-N 为正确的 top-N |
| 测试数 | 约 10 个 |

### 9.5 ReportInsight 集成测试

| 测试文件 | `tests/test_report_insight.py` |
|----------|-------------------------------|
| 测试场景 | 完整 from_eval() 流程、空 trace、仅 rule findings、含 judge findings |
| 断言 | insight 的所有组件非 None、metrics/scorecard/groups/recommendations 自洽 |
| 测试数 | 约 8-10 个 |

### 9.6 Markdown snapshot / substring 测试

| 测试文件 | `tests/test_report.py`（追加） 或 `tests/test_report_insight_markdown.py` |
|----------|-------------------------------|
| 测试场景 | 固定 findings 输入 → render_insight_section() → 断言关键子串存在 |
| 断言 | 输出包含 "## Scorecard"、"## Metrics"、"## Recommendations" 等；scorecard 表格包含正确的 passed 状态和数字 |
| 测试数 | 约 5-8 个 |

### 9.7 JSON shape 测试

| 测试文件 | `tests/test_report_insight_json.py` |
|----------|-------------------------------|
| 测试场景 | report_insight_to_json_dict() → 断言所有顶层 key 存在、类型正确 |
| 断言 | json_dict["summary"]["passed"] 为 bool；json_dict["metrics"]["tool_call_count"] 为 int；json_dict["grouped_findings"] 包含 4 个 key |
| 测试数 | 约 8-10 个 |

### 9.8 兼容性测试

| 测试文件 | 不新增 |
|----------|--------|
| 要求 | 现有 1100+ tests 全部通过，零 regression |
| 验证 | `pytest` 全量运行 |

---

## 10. 模块组织

### 推荐文件布局

```
agent_tool_harness/
├── reports/
│   ├── __init__.py
│   ├── markdown_report.py      # 新增 render_insight_section()
│   ├── cost_tracker.py         # 不变
│   └── report_insight.py       # 新文件 — 包含以下所有类
│       ├── ReportMetrics
│       ├── MetricsCollector
│       ├── FindingGrouper
│       ├── GroupedFindings
│       ├── ReportScorecard
│       ├── Recommendation
│       ├── RecommendationCatalog
│       ├── ReportInsight
│       └── ReportInsightMetadata
├── core_report_bridge.py       # 新增 report_insight_to_json_dict()
└── ...
```

所有新类放在 `agent_tool_harness/reports/report_insight.py` 一个文件中（约 400-600 行），避免过早拆分造成 import 复杂度。

### 为什么不建独立模块文件

- 6 个类之间互相引用（ReportInsight 包含所有其他类）
- 放在同一文件避免循环 import
- 总行数在 800 行以内，符合"小文件"原则
- 如果未来单个类膨胀到 300+ 行，再拆分
