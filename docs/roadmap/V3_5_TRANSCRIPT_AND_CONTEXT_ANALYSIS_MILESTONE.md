# V3.5 Milestone: Transcript Confusion + Context Efficiency Analysis

> **Status: Planned** — 设计已完成，实现未开始。可独立于 v3.3/v3.4，但 v3.2 TaskOutcome 可增强失败解释。

## TLDR

v3.1 能检查工具调用的表面正确性。v3.5 深度分析 Agent 的 transcript：为什么反复重试？为什么在两个工具间来回切换？工具返回是不是太啰嗦？产出 confusion signals 和 context inefficiency signals 两类分析。

---

## 1. 背景

Anthropic 文章强调工具设计中最常见的两类问题：
1. **Agent confusion** — Agent 不知道用哪个工具、不知道怎么用、反复失败后放弃
2. **Context inefficiency** — 工具返回了太多无关数据，浪费 token 预算

v3.1 的工具检查（D2/D4/D5/D6）能发现 surface-level 问题。v3.5 做 transcript 级别的模式分析。

---

## 2. 用户问题

| # | 问题 |
|---|------|
| 1 | "Agent 在 transcript 第 3-7 步之间反复调同一个工具 5 次，怎么回事？" |
| 2 | "Agent 先调 search，又调 read，又切回 search，是不是选工具有问题？" |
| 3 | "这个工具每次返回 50KB，Agent 只读了开头 200 字节，是不是该加 pagination？" |
| 4 | "Agent 调了工具收到 error 后没有恢复，直接给了空答案，为什么？" |

---

## 3. v3.5 核心设计

### 3.1 TranscriptPatternAnalyzer

分析 ExecutionTrace 中 tool call/result 的时间序列，识别 6 种 confusion pattern：

| Signal | 检测逻辑 | Severity |
|--------|---------|----------|
| `repeated_tool_retry_loop` | 同一 tool+args 连续 ≥ 3 次调用 | high |
| `tool_switching_confusion` | 短时间内在两个工具间来回切换 ≥ 3 次 | medium |
| `invalid_arg_retry` | 同一 tool 连续调用，只有 args 小幅变化（如改了一个字符） | high |
| `no_recovery_after_error` | tool_result error 后 Agent 没有重试或 fallback | high |
| `final_answer_without_support` | final answer 使用了 tool result 中不存在的 fact | critical |
| `broad_search_loop` | 同一 tool 多次调用，args 范围越来越宽（fallback pattern） | medium |

### 3.2 ContextEfficiencyAnalyzer

分析 tool_result 的 output，识别 5 种 context inefficiency：

| Signal | 检测逻辑 | Severity |
|--------|---------|----------|
| `response_bloat` | tool_result output 的 char count > 阈值的 10x | high |
| `missing_pagination` | output 包含大量 items 但无 page/offset 参数 | high |
| `missing_concise_mode` | output 的所有字段都是 full detail，无 summary | medium |
| `low_value_large_fields` | output 中某个字段占用 > 50% 字符但未被 Agent 使用 | medium |
| `truncation_without_hint` | output 被截断但没有 next_step 或 continuation 提示 | high |

### 3.3 Report integration

```
## Transcript Analysis
### Confusion Signals
- [high] repeated_tool_retry_loop: "search" called 5 times with same args (steps 3-7)

### Context Efficiency
- [high] response_bloat: "list_documents" returned 45KB, median is 2KB
- [medium] missing_pagination: "list_documents" returned 200 items without pagination
```

---

## 4. 依赖

- v3.1 ExecutionTrace + ReportInsight
- v3.2 TaskOutcome（可增强失败解释："task failed, likely due to repeated_tool_retry_loop"）
- 不强制依赖 v3.3/v3.4

---

## 5. 完成定义

- [ ] TranscriptPatternAnalyzer 识别 6 种 confusion signal
- [ ] ContextEfficiencyAnalyzer 识别 5 种 inefficiency signal
- [ ] report 包含 transcript/context analysis section
- [ ] recommendations 集成（根据 signal 类型生成对应修复建议）
- [ ] ≥ 25 个新增单测
- [ ] 现有 1300+ tests 无 regression
