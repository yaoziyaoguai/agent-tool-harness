# V3.1 Implementation Backlog

## TLDR

5 个 Phase，顺序实现，每个 Phase 独立可测、独立可合。全部实现完成后，Markdown report 和 JSON report 自动获得 insight 能力。

---

## Phase 依赖关系

```
P1: MetricsCollector
    └── P2: FindingGrouper
            ├── P3: ReportScorecard
            │       └── P5: ReportInsight Integration
            └── P4: RecommendationCatalog
                    └── P5: ReportInsight Integration
```

P3 和 P4 可并行。

---

## P1: MetricsCollector

### 目标

实现 `ReportMetrics` 和 `MetricsCollector`，从 ExecutionTrace + EvaluationResult 计算 15 个基础指标。

### 输入

- `ExecutionTrace`（tool_calls + tool_results）
- `EvaluationResult`（findings）

### 输出

- `ReportMetrics` dataclass
- `MetricsCollector.collect()` 方法

### 允许修改文件

| 文件 | 操作 |
|------|------|
| `agent_tool_harness/reports/report_insight.py` | **新建** — ReportMetrics + MetricsCollector |
| `tests/test_report_metrics.py` | **新建** |

### 测试要求

| # | 测试场景 | 断言 |
|---|---------|------|
| 1 | 空 trace（无 tool_calls，无 tool_results） | 所有 count 为 0，rate 为 0.0 |
| 2 | 正常 trace（3 calls，3 results，全部 success） | tool_call_count=3, success=3, error=0, rate=0.0 |
| 3 | 含 error 的 trace | tool_error_count=N, tool_error_rate>0 |
| 4 | 含 orphan call（call 无 result） | orphan_call_count>0, orphan_result_count=0 |
| 5 | 含 orphan result（result 无 call） | orphan_result_count>0 |
| 6 | 含重复调用（相同 tool+args 出现 2 次） | repeated_tool_call_count>=2 |
| 7 | response_size_chars_total 计算正确 | 手动 sum(len(json.dumps(...))) 对比 |
| 8 | response_size_chars_by_tool 按工具分组正确 | 检查 key 和 value 之和 |
| 9 | estimated_response_tokens_total = chars/4 | 整数除法 |
| 10 | finding_count_by_severity 统计正确 | 手动 Counter 对比 |
| 11 | finding_count_by_category 统计正确（含 rule_id prefix 子类别） | tool_response=3, tool_spec=2 等 |
| 12 | finding_count_by_tool 统计正确 | 从 rule_type/evidence_ref 提取 tool_name |
| 13 | judge_finding_count 统计正确 | category=="judge" |
| 14 | tool_error_rate 除零保护 | tool_call_count=0 → rate=0.0 |
| 15 | tool_name 为空字符串时归入 "(unknown)" bucket | 空字符串 key |

### 完成定义

- [ ] `ReportMetrics` dataclass defined（frozen=True）
- [ ] `MetricsCollector.collect()` 返回正确的 ReportMetrics
- [ ] 15+ 个单测通过
- [ ] 现有 1100+ tests 无 regression
- [ ] `ReportMetrics` 所有字段有 type annotation

### 停止条件

- 不要在这个 Phase 实现 grouping / scorecard / recommendations
- 不要修改 Finding 数据结构
- 不要引入外部依赖（如 tiktoken）

---

## P2: FindingGrouper

### 目标

实现 `FindingGrouper` 和 `GroupedFindings`，提供 4 种分组视图。

### 输入

- `list[Finding]`（来自 EvaluationResult.findings）

### 输出

- `GroupedFindings` dataclass（4 个 dict）
- `FindingGrouper.group()` 方法

### 允许修改文件

| 文件 | 操作 |
|------|------|
| `agent_tool_harness/reports/report_insight.py` | **追加** — GroupedFindings + FindingGrouper |
| `tests/test_finding_grouper.py` | **新建** |

### 测试要求

| # | 测试场景 | 断言 |
|---|---------|------|
| 1 | 空 findings | 4 个 dict 均为空 |
| 2 | 单一 severity（全 high） | by_severity 只有 "high" key，len = 原始长度 |
| 3 | 混合 severity | by_severity 的 keys 正确，每个 key 下 finding 数正确 |
| 4 | 混合 category（rule + judge + audit + signal） | by_category 的 keys 正确 |
| 5 | rule finding 按 rule_id prefix 分子类别 | tool_response 和 tool_spec 分开 |
| 6 | by_tool — 从 rule_type 提取 tool_name | tool_name 正确解析 |
| 7 | by_tool — 从 evidence_ref 提取 tool_name | fallback 提取正确 |
| 8 | by_tool — 无法提取 → "(unknown)" | 兜底逻辑 |
| 9 | by_rule_id_prefix — 按 prefix 分组 | tool_call, tool_result, tool_pair 分开 |
| 10 | 总数不变量 — sum(len(v)) = len(原始) | 每个视图分别验证 |
| 11 | ID 集合不变量 — 所有 finding_id 无遗漏 | set 比较 |
| 12 | 无重复不变量 — 同 group 内无重复 finding_id | set vs list 长度 |
| 13 | group 内按 severity 降序排列 | 检查列表顺序 |
| 14 | group 级别按 finding count 降序排列 | 检查 dict 遍历顺序 |

### 完成定义

- [ ] `GroupedFindings` dataclass defined（frozen=True）
- [ ] `FindingGrouper.group()` 返回正确的 GroupedFindings
- [ ] 14+ 个单测通过
- [ ] 所有不变量的 assertion 通过
- [ ] 现有 1100+ tests 无 regression

### 停止条件

- 不要在这个 Phase 实现 scorecard / recommendations
- 不要修改 Finding 数据结构
- 不要引入新的 tool_name 提取方式（只用 rule_type / evidence_ref / message 三种）

---

## P3: ReportScorecard

### 目标

从 ReportMetrics + GroupedFindings 生成 ReportScorecard。

### 输入

- `ReportMetrics`（来自 P1）
- `GroupedFindings`（来自 P2）
- `passed: bool`（来自 EvaluationResult.passed）

### 输出

- `ReportScorecard` dataclass（frozen=True）
- `ReportScorecard.from_metrics_and_groups()` 工厂方法

### 允许修改文件

| 文件 | 操作 |
|------|------|
| `agent_tool_harness/reports/report_insight.py` | **追加** — ReportScorecard |
| `tests/test_report_scorecard.py` | **新建** |

### 测试要求

| # | 测试场景 | 断言 |
|---|---------|------|
| 1 | passed=true 的 scorecard | scorecard.passed == True |
| 2 | passed=false 的 scorecard | scorecard.passed == False |
| 3 | 含 errors + warnings + info | severity_breakdown 正确 |
| 4 | advisory_count 与 metrics.judge_finding_count 一致 | 数值相等 |
| 5 | top_issue_categories 前 5 按 count 降序 | list 顺序和内容正确 |
| 6 | top_issue_categories < 5 个 category 时不补齐 | 真实 top-N |
| 7 | top_affected_tools 前 5 按 count 降序 | list 顺序和内容正确 |
| 8 | top_affected_tools 排除 "(unknown)" | 不包含 "(unknown)" |
| 9 | tools_called 与 metrics.unique_tool_count 一致 | 数值相等 |
| 10 | tool_errors 与 metrics.tool_error_count 一致 | 数值相等 |

### 完成定义

- [ ] `ReportScorecard` dataclass defined（frozen=True）
- [ ] `from_metrics_and_groups()` 返回正确 scorecard
- [ ] 10+ 个单测通过
- [ ] 现有 1100+ tests 无 regression

### 停止条件

- 不要在这个 Phase 实现 recommendations / Markdown 集成

---

## P4: RecommendationCatalog

### 目标

实现 deterministic 建议映射表，覆盖所有已知 rule_id。

### 输入

- `list[Finding]`（来自 EvaluationResult.findings）

### 输出

- `Recommendation` dataclass（rule_id, category, severity, what, why, how_to_fix）
- `RecommendationCatalog.recommend()` — 单个 finding → Recommendation
- `RecommendationCatalog.recommend_all()` — 批量生成（含去重）

### 允许修改文件

| 文件 | 操作 |
|------|------|
| `agent_tool_harness/reports/report_insight.py` | **追加** — Recommendation + RecommendationCatalog |
| `tests/test_recommendation_catalog.py` | **新建** |

### 测试要求

| # | 测试场景 | 断言 |
|---|---------|------|
| 1-37 | 每条已知 rule_id 有对应 recommendation | what/why/how_to_fix 均为非空字符串 |
| 38 | tool_response.output.low_signal | what 包含 "信号过低" 关键词 |
| 39 | tool_response.error.actionable | how_to_fix 包含 "suggested_action" |
| 40 | tool_spec.description.useful_length | how_to_fix 包含 "扩展" |
| 41 | tool_ergonomics.name.too_generic | how_to_fix 包含 "前缀" |
| 42 | tool_ergonomics.description.shallow_wrapper | how_to_fix 包含 "抽象层级" |
| 43 | tool_call.arguments.present | what 包含 "缺少" |
| 44 | tool_pair.orphan_call | how_to_fix 包含 "工具执行链路" |
| 45 | tool_pair.orphan_result | how_to_fix 包含 "trace 记录完整性" |
| 46 | 未知 rule_id — critical fallback | what 包含 "严重问题" |
| 47 | 未知 rule_id — high fallback | what 包含 "高优先级" |
| 48 | 未知 rule_id — medium fallback | what 包含 "中优先级" |
| 49 | 未知 rule_id — low fallback | what 包含 "低优先级" |
| 50 | 未知 rule_id — info fallback | what 包含 "仅供参考" |
| 51 | 同一 rule_id 前缀去重 | 只输出 1 条，affected_count > 1 |
| 52 | recommend_all 覆盖所有输入 finding | len(output) <= len(input)，每条 input finding 至少被一条 recommendation 覆盖 |

### 完成定义

- [ ] `Recommendation` dataclass defined（frozen=True）
- [ ] `RecommendationCatalog` 覆盖全部 37 条 rule_id
- [ ] 5 种 severity fallback 完备
- [ ] 去重逻辑正确
- [ ] 52+ 个单测通过
- [ ] 现有 1100+ tests 无 regression

### 停止条件

- 不要引入 LLM 生成的建议
- 不要加载外部建议配置文件（硬编码即可）
- 不要在建议中包含真实 URL / 文件路径（除非是已知的 project 内部路径）

---

## P5: ReportInsight Integration

### 目标

实现 `ReportInsight` 聚合对象，接入 Markdown report 和 JSON report。

### 输入

- ExecutionTrace + EvaluationResult（来自 Core Flow）
- 或直接 ReportMetrics + GroupedFindings + ReportScorecard + list[Recommendation]（来自 P1-P4）

### 输出

- `ReportInsight` dataclass（包含 metrics / scorecard / grouped_findings / recommendations / findings / judge_findings / metadata）
- `ReportInsight.from_eval()` 工厂方法
- `MarkdownReport.render_insight_section()` 方法
- `core_report_bridge.report_insight_to_json_dict()` 函数

### 允许修改文件

| 文件 | 操作 |
|------|------|
| `agent_tool_harness/reports/report_insight.py` | **追加** — ReportInsight + ReportInsightMetadata + from_eval() |
| `agent_tool_harness/reports/markdown_report.py` | **追加** — render_insight_section() |
| `agent_tool_harness/core_report_bridge.py` | **追加** — report_insight_to_json_dict() |
| `tests/test_report_insight.py` | **新建** |
| `tests/test_report_insight_markdown.py` | **新建** |
| `tests/test_report_insight_json.py` | **新建** |

### 测试要求

#### ReportInsight 集成测试

| # | 测试场景 | 断言 |
|---|---------|------|
| 1 | from_eval() 完整流程 | insight 所有字段非 None |
| 2 | 空 trace + 空 findings | metrics 全 0，groups 全空 |
| 3 | 仅 rule findings | judge_findings 为空，advisory_count=0 |
| 4 | 含 judge findings | judge_findings 长度 = category=="judge" 的数量 |
| 5 | metadata 填充正确 | schema_version, generated_at, signal_quality |
| 6 | 各组件自洽 — metrics.finding_count_by_severity == scorecard.errors+warnings+info | 数值相等 |

#### Markdown 测试

| # | 测试场景 | 断言 |
|---|---------|------|
| 1 | render_insight_section() 包含 "## Scorecard" | substring 匹配 |
| 2 | 包含 "## Metrics" | substring 匹配 |
| 3 | 包含 "## Top Issues" | substring 匹配 |
| 4 | 包含 "## Findings by Severity" | substring 匹配 |
| 5 | 包含 "## Findings by Tool" | substring 匹配 |
| 6 | 包含 "## Recommendations" | substring 匹配 |
| 7 | scorecard 表格包含 "PASS" 或 "FAIL" | substring 匹配 |
| 8 | scorecard 表格包含正确的数字 | 正则或 substring 匹配 |

#### JSON 测试

| # | 测试场景 | 断言 |
|---|---------|------|
| 1 | report_insight_to_json_dict() 返回 dict | type check |
| 2 | json_dict 包含 "summary" key | key 存在 |
| 3 | json_dict 包含 "metrics" key | key 存在 |
| 4 | json_dict 包含 "scorecard" key | key 存在 |
| 5 | json_dict 包含 "findings" key | key 存在 |
| 6 | json_dict 包含 "grouped_findings" key | key 存在 |
| 7 | json_dict 包含 "recommendations" key | key 存在 |
| 8 | json_dict 包含 "judge_findings" key | key 存在 |
| 9 | json_dict 包含 "metadata" key | key 存在 |
| 10 | summary.passed 是 bool | isinstance check |

### 完成定义

- [ ] `ReportInsight` + `ReportInsightMetadata` dataclass defined（frozen=True）
- [ ] `from_eval()` 一站式构造方法可用
- [ ] `render_insight_section()` 产出正确 Markdown 段
- [ ] `report_insight_to_json_dict()` 产出正确 JSON dict
- [ ] 6 个集成测试 + 8 个 Markdown 测试 + 10 个 JSON 测试通过
- [ ] 现有 1100+ tests 无 regression
- [ ] 可选：更新 `README.md` 或 `docs/` 中的报告示例

### 停止条件

- 不要修改 `render()` 旧方法
- 不要新增 CLI 子命令（除非后续轮次决定）
- 不要引入新依赖
- 不要修改 core_contract.py

---

## 汇总

| Phase | 新文件 | 修改文件 | 预计新增测试 |
|-------|--------|---------|------------|
| P1 | `reports/report_insight.py` (ReportMetrics + MetricsCollector), `tests/test_report_metrics.py` | — | ~15 |
| P2 | — | `reports/report_insight.py` (追加), `tests/test_finding_grouper.py` | ~14 |
| P3 | — | `reports/report_insight.py` (追加), `tests/test_report_scorecard.py` | ~10 |
| P4 | — | `reports/report_insight.py` (追加), `tests/test_recommendation_catalog.py` | ~52 |
| P5 | `tests/test_report_insight.py`, `tests/test_report_insight_markdown.py`, `tests/test_report_insight_json.py` | `reports/report_insight.py` (追加), `reports/markdown_report.py` (追加), `core_report_bridge.py` (追加) | ~24 |
| **合计** | **4 个新文件** | **3 个已有文件修改** | **~115 tests** |
