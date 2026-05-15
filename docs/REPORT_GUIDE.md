# 报告解读指南

v3.1 的报告在 v3.0 的 finding 列表之上，新增了报告级洞察层：Scorecard、Metrics、Findings 分组、Recommendations。你打开报告 30 秒内就能看懂整体结论和下一步该改什么。

## 报告结构

Markdown 报告（`report.md`）的段落顺序：

```
## Scorecard              ← v3.1 新增：一眼结论
## Metrics                ← v3.1 新增：基础统计
## Top Issues             ← v3.1 新增：问题排名
## Findings by Severity   ← v3.1 新增：按严重度分组
## Findings by Tool       ← v3.1 新增：按工具分组
## Recommendations        ← v3.1 新增：修复建议
## Agent Tool-Use Eval    ← 原有详细 findings
## Per-Eval Details       ← 原有逐条详情
## Review Decision        ← 人工 Review 区
```

JSON 报告包含同样的数据，适合 CI / 下游工具消费。

## Scorecard

一眼看懂结论：

| 字段 | 含义 |
|------|------|
| Passed | PASS 或 FAIL，来自确定性规则 |
| Errors | critical + high 数量 |
| Warnings | medium + low 数量 |
| Info | info 级别数量 |
| Advisory | JudgeFinding 数量 |
| Tools Called | 本次 trace 调用的工具数 |
| Tool Errors | 工具返回 error 的次数 |
| Top Issue Categories | 问题最多的 5 个类别 |
| Top Affected Tools | 问题最多的 5 个工具 |

**关键约束：** Passed 由 RuleFinding（确定性规则）决定，JudgeFinding（LLM）不影响它。

## Metrics

基础统计指标：

| 指标 | 含义 |
|------|------|
| Tool Calls | 工具调用总次数 |
| Success / Error Count | 成功/失败调用次数 |
| Error Rate | 错误率 = error_count / call_count |
| Orphan Calls | 有调用无返回的数量 |
| Orphan Results | 有返回无调用的数量 |
| Repeated Calls | 相同参数重复调用的次数 |
| Response Size | 工具返回内容的总字符数/估算 token 数 |

## Top Issues

按 finding 数量排名的问题类别。例如：
```
1. tool_response (4 findings) — 工具响应质量问题最多
2. tool_spec (3 findings) — 工具规格文档问题
```

## Findings by Severity

按严重度分组展示所有 findings：
- **critical** — 严重问题，必须修复
- **high** — 高优先级
- **medium** — 中优先级
- **low** — 低优先级
- **info** — 仅供参考

## Findings by Tool

按工具名分组，一眼看到哪个工具问题最多。例如 `search` 工具有 5 个 finding，`read` 有 3 个。

## Recommendations

从 findings 去重、排序后的可行动修复建议。每条建议包含：

| 字段 | 含义 |
|------|------|
| what | 问题是什么 |
| why | 为什么重要 |
| how_to_fix | 具体怎么修 |
| affected_count | 影响了多少条 finding |

Recommendations 是确定性生成的（不依赖 LLM），覆盖所有已知 rule_id。

## JSON 报告

JSON 报告包含以下顶层 key：

- `summary` — passed / total_findings / severity_breakdown
- `metrics` — 完整指标
- `scorecard` — scorecard 数据
- `findings` — 原始 findings 列表
- `grouped_findings` — 四维分组（by_severity / by_category / by_tool / by_rule_id_prefix）
- `recommendations` — 修复建议列表
- `judge_findings` — JudgeFinding 列表
- `metadata` — schema_version / generated_at / signal_quality

适合 CI pipeline 消费：`summary.passed` 决定 CI pass/fail，`metrics.tool_error_rate` 做阈值告警。

## 相关文档

- [USER_GUIDE](USER_GUIDE.md) — 如何生成报告
- [PROVIDER_CONFIG](PROVIDER_CONFIG.md) — 启用 LLM judge 后的 JudgeFinding 解读
