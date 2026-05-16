# RFC 0006: Transcript Confusion + Context Efficiency Analysis

## TLDR

v3.5 新增 TranscriptPatternAnalyzer 和 ContextEfficiencyAnalyzer，从 ExecutionTrace 中识别 Agent 困惑模式和上下文浪费信号。所有分析为 deterministic、零网络依赖。产出 RuleFinding（非 JudgeFinding），因为分析基于确定性模式。

---

## Decision 1: Analysis Produces RuleFinding (Not JudgeFinding)

### 决策

Transcript 和 context analysis 产生的是 `RuleFinding`，不是 `JudgeFinding`。因为这些分析基于确定性模式匹配（如"同一 tool+args 连续调用 3 次"），不涉及语义判断。

### 为什么

RuleFinding 影响 EvaluationResult.passed。如果一个 Agent 反复重试 5 次后放弃，这确实是一个"工具调用失败"——应该降低 passed。JudgeFinding 留给真正需要 LLM 语义判断的场景。

---

## Decision 2: Six Confusion Patterns (Deterministic)

### 决策

| Pattern | 检测逻辑 | 证据 |
|---------|---------|------|
| repeated_tool_retry_loop | `(tool_name, args_signature)` 在连续的 steps 中重复 ≥ 3 次 | tool_calls[i], tool_calls[i+1], tool_calls[i+2] |
| tool_switching_confusion | 在 ≤ 5 steps 窗口内，tool A → tool B → tool A → tool B 的切换 ≥ 2 个周期 | tool_calls 序列 |
| invalid_arg_retry | 同一 tool 连续调用，args 只有 1 个字段的值小幅变化 | tool_calls[i].args vs tool_calls[i+1].args |
| no_recovery_after_error | tool_result.status=="error" 后，接下来 ≤ 2 steps 内没有再调用任何工具 | tool_results + tool_calls |
| final_answer_without_support | final answer 的 fact claim 在 tool_result output 中找不到来源 | final_answer_text vs all tool_outputs |
| broad_search_loop | 同一 tool 多次调用，args 中的搜索范围单调递增 | tool_calls[].args 序列分析 |

---

## Decision 3: Five Context Inefficiency Patterns (Deterministic)

### 决策

| Pattern | 检测逻辑 | 阈值 |
|---------|---------|------|
| response_bloat | 单次 tool_result output 的 char count > median × 10 | median 由同名 tool 的历史 output 计算 |
| missing_pagination | output 包含 list/dict items ≥ 20，但 args 中无 limit/page/offset/max_results | items 数量阈值 |
| missing_concise_mode | output 字段数 ≥ 5，但无 summary/abstract/brief 等标记 | 字段数阈值 |
| low_value_large_fields | output 中最大字段占用 > 50% 字符，但 Agent 在后续 steps 中未引用该字段 | field size + 引用分析 |
| truncation_without_hint | output 以 "..." 或 "[truncated]" 结尾，但缺少 next_cursor/continuation_token/has_more | 截断标记检测 |

---

## Decision 4: No Median Reference for First Trace

### 问题

`response_bloat` 需要 median response size 作为基准。第一条 trace 没有历史数据。

### 决策

首次分析时，使用 all-time heuristic：
- 如果同名 tool 在本次 trace 中被调用 > 1 次，用本次 trace 的同名 tool median
- 如果只有 1 次调用，跳过 `response_bloat` 检测（标记为 "insufficient_data"）
- 不要求用户先"跑 N 次建立 baseline"

---

## Acceptance Criteria

1. 6 种 confusion pattern 全部可检测
2. 5 种 context inefficiency 全部可检测
3. 分析产出 RuleFinding（category="transcript" | "context"）
4. report 包含分析 section
5. recommendations 集成
6. 现有 1300+ tests 无 regression
