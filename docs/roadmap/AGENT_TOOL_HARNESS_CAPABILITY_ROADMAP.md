# Agent Tool Harness — Post-v3.1 Capability Roadmap

> **状态：v3.1-v3.6 全部完成（2026-05-17）。v3.6.0 已发布。**

## TLDR

v3.1.1 起步，经历 5 个版本（v3.2-v3.6），从"单条 trace 是否健康"升级到"任务是否完成 + 跨 trace 聚合 + 改前改后对比 + Agent 困惑分析 + 工具组合设计评审"。所有版本保持 harness 主线：外部 runner → trace 导入 → 检查/评测 → 报告。不内置 Agent runner，不自动修改工具。

---

## 1. v3.6.0 能力基线（全部完成）

| 层 | 能力 | 输入 → 输出 | 状态 |
|---|------|------------|------|
| Trace 导入 | native + simple_mapping | 外部 trace JSON → ExecutionTrace | ✅ |
| Trace 诊断 | 字段覆盖率、类型检查、置信度 | ExecutionTrace → TraceDiagnostics | ✅ |
| 工具调用正确性 | 9 条确定性规则 | ExecutionTrace → RuleFinding[] | ✅ |
| 工具规格质量 | 10 条确定性规则 | ToolSpec[] → RuleFinding[] | ✅ |
| 工具工效学 | 6 条确定 + 4 LLM advisory | ExecutionTrace + ToolSpec[] → RuleFinding[] + JudgeFinding[] | ✅ |
| 工具响应质量 | 6 条确定 + 2 LLM advisory | ExecutionTrace → RuleFinding[] + JudgeFinding[] | ✅ |
| LLM 辅助判断 | opt-in, advisory only | findings → JudgeFinding[] | ✅ |
| 报告洞察 (v3.1) | Scorecard + Metrics + Grouped + Recommendations | EvaluationResult + ExecutionTrace → ReportInsight | ✅ |
| 任务级评测 (v3.2) | EvalCase + 6 Verifiers + TaskOutcome | EvalCase + ExecutionTrace → TaskOutcome | ✅ |
| Suite 聚合 (v3.3) | EvalSuite + SuiteEvaluator + SuiteResult | EvalSuite + N traces → SuiteResult | ✅ |
| 回归对比 (v3.4) | baseline vs candidate 全维度 | ReportInsight ×2 → RegressionReport | ✅ |
| 转录分析 (v3.5) | 6 困惑模式 + 5 上下文浪费 | ExecutionTrace → RuleFinding[] | ✅ |
| 组合评审 (v3.6) | 5 类结构检查 + ImprovementBrief | ToolSpec[] + findings → PortfolioFinding[] + ToolImprovementBrief[] | ✅ |
| Markdown/JSON report | 双格式输出 | 各层结果 → report.md / report.json | ✅ |
| CLI 工具 | 14 个子命令 | — | ✅ |
| 中文文档体系 | README + QUICKSTART + USER_GUIDE + REPORT_GUIDE + DEVELOPER_GUIDE + CHANGELOG | — | ✅ |

---

## 2. 对照 Anthropic 工具评测闭环（全部覆盖）

Anthropic《Writing effective tools for agents — with agents》描述的完整工具评测闭环：

```
定义 eval task set → Agent loop 运行 → 检查 tool-use 正确性
→ 检查 task 是否完成 → 聚合多 trace → 对比 before/after
→ 分析 Agent 困惑 → 评审工具组合 → 产出改进建议 → 迭代
```

v3.6.0 已覆盖全部环节：

| # | 环节 | 覆盖版本 | 状态 |
|---|------|---------|------|
| 1 | eval task set / held-out test set | v3.2 EvalCase | ✅ |
| 2 | top-level task success / ground truth verifier | v3.2 TaskOutcome + 6 Verifiers | ✅ |
| 3 | multi-trace / eval suite aggregation | v3.3 EvalSuite + SuiteResult | ✅ |
| 4 | before/after regression comparison | v3.4 RegressionReport | ✅ |
| 5 | transcript-level agent confusion analysis | v3.5 TranscriptPatternAnalyzer | ✅ |
| 6 | context efficiency 深度分析 | v3.5 ContextEfficiencyAnalyzer | ✅ |
| 7 | tool portfolio / tool selection planning | v3.6 ToolPortfolioReview | ✅ |
| 8 | tool improvement brief | v3.6 ToolImprovementBrief | ✅ |

---

## 3. 版本路线（全部完成）

```
v3.2 Task-level Evaluation ✅
  └── v3.3 Eval Suite / Multi-trace Aggregation ✅
        ├── v3.4 Regression Comparison ✅
        │     └── v3.6 Tool Portfolio + Improvement Brief ✅
        └── v3.5 Transcript Confusion + Context Efficiency ✅
              └── v3.6 Tool Portfolio + Improvement Brief ✅
```

### 3.1 v3.2 Task-level Evaluation ✅

**用户问题**："我的 Agent 调工具没报错，但任务真的完成了吗？"

**核心输入**：EvalCase（含 expected_outcome）+ ExecutionTrace
**核心输出**：TaskOutcome（success/failed/inconclusive）+ verifier_results

**新增概念**：
- `EvalCase` — 结构化评测用例（task description + expected outcome + verifier 配置）
- `ExpectedOutcome` — 期望输出定义（required_facts / forbidden_facts / regex / exact / json_fields）
- `Verifier` — 可组合的确定性验证器接口
- `TaskOutcome` — 任务级别通过/不通过（独立于 trace 级别 EvaluationResult.passed）

**关键约束**：Harness 不运行 Agent。TaskOutcome 基于 trace 中的 final answer 或 tool output 验证。

### 3.2 v3.3 Eval Suite / Multi-trace Aggregation ✅

**用户问题**："我有很多条 trace 和 eval case，能不能一次跑完看全局？"

**核心输入**：EvalSuite manifest + N 条 trace + N 个 EvalCase
**核心输出**：SuiteResult（task_success_rate / deterministic_pass_rate / top failing categories / top affected tools / suite-level metrics）

**依赖**：v3.2 TaskOutcome

### 3.3 v3.4 Regression Comparison ✅

**用户问题**："我改了 tool spec / prompt，有没有引入回归？"

**核心输入**：baseline report + candidate report
**核心输出**：RegressionReport（metric_diff / finding_diff / task_outcome_diff / regression_warning）

**依赖**：v3.2 TaskOutcome（推荐 v3.3 suite aggregation）

### 3.4 v3.5 Transcript Confusion + Context Efficiency Analysis ✅

**用户问题**："Agent 为什么会在这里反复重试同一个工具？工具返回是不是太啰嗦了？"

**核心输入**：ExecutionTrace
**核心输出**：TranscriptAnalysis（confusion_signals[] + context_inefficiency_signals[]）

**依赖**：v3.1 report insight（v3.2 TaskOutcome 可增强失败解释）

### 3.5 v3.6 Tool Portfolio Review + Tool Improvement Brief ✅

**用户问题**："我的工具组合设计有没有结构性问题？怎么系统性地改进？"

**核心输入**：ToolSpec[] + findings[] + metrics + task outcomes（来自 v3.2/v3.3）
**核心输出**：PortfolioReview + ToolImprovementBrief

**依赖**：v3.1-v3.5 的累积信号

---

## 4. 版本依赖关系图

```
v3.1.1 (基线)
  │
  ├── v3.2 Task-level Evaluation ← 必须最先
  │     │
  │     ├── v3.3 Eval Suite Aggregation ← 依赖 v3.2
  │     │     │
  │     │     ├── v3.4 Regression Comparison ← 增强依赖 v3.3
  │     │     │     │
  │     │     │     └── v3.6 Tool Portfolio + Improvement Brief
  │     │     │
  │     │     └── v3.5 Transcript + Context Analysis ← 不强制依赖 v3.3
  │     │           │
  │     │           └── v3.6 Tool Portfolio + Improvement Brief
  │     │
  │     └── v3.4 Regression Comparison ← 可单 report diff，不强制依赖 v3.3
  │
  └── v3.5 Transcript + Context Analysis ← 可独立于 v3.2
```

**关键约束**：
- v3.2 是必须最先实现的版本（TaskOutcome 是 v3.3/v3.4 的输入）
- v3.3 和 v3.5 可并行（v3.5 不强制依赖 v3.3）
- v3.4 可降级为单 report diff（不强制依赖 v3.3），但有 suite aggregation 更佳
- v3.6 是收口版本，消费 v3.1-v3.5 的全部信号

---

## 5. 每个版本解决的用户问题

| 版本 | 用户问题 | 交付物 |
|------|---------|--------|
| v3.2 | "任务完成了吗？" | EvalCase + Verifier + TaskOutcome |
| v3.3 | "全局情况怎样？" | EvalSuite + SuiteResult |
| v3.4 | "改完之后变好了吗？" | RegressionReport |
| v3.5 | "Agent 为什么困惑？工具返回浪费吗？" | TranscriptAnalysis |
| v3.6 | "工具组合怎么改进？" | PortfolioReview + ImprovementBrief |

---

## 6. 每个版本的核心输入/输出

| 版本 | 输入 | 输出 |
|------|------|------|
| v3.2 | EvalCase + ExecutionTrace | TaskOutcome + TaskEvalReport |
| v3.3 | EvalSuite + N×(EvalCase + ExecutionTrace) | SuiteResult + SuiteReport |
| v3.4 | baseline report + candidate report | RegressionReport |
| v3.5 | ExecutionTrace (+ TaskOutcome) | TranscriptConfusionReport + ContextEfficiencyReport |
| v3.6 | ToolSpec[] + findings + metrics + task outcomes | PortfolioReview + ImprovementBrief |

---

## 7. 每个版本的验收标准

| 版本 | 验收标准 |
|------|---------|
| v3.2 | 5 种确定性 verifier + CompositeVerifier 可用 + TaskOutcome 正确判定 + report 包含 task-level section |
| v3.3 | suite manifest 加载 + suite 聚合正确 + suite-level metrics 与单 trace metrics 自洽 |
| v3.4 | metric diff 正确 + finding diff 正确 + 回归警告触发条件明确 |
| v3.5 | 6 种 confusion signal 可识别 + 5 种 context inefficiency signal 可识别 |
| v3.6 | portfolio review 可识别 5 类结构问题 + improvement brief 含 evidence 引用 |

---

## 8. 暂不进入近期路线的能力

| 能力 | 原因 | 替代方案 |
|------|------|---------|
| 内置真实 Agent runner | 违反 harness 不运行 Agent 原则 | 外部 runner 产出 trace 后导入 |
| Web UI / TUI | 投入产出比低，CLI + Markdown/JSON report 已满足 CI/review 需求 | 继续 CLI + 文件输出 |
| 自动修改 tool spec | "明确不做" automatic optimizer | ToolImprovementBrief 提供人工参考 |
| 自动 optimizer（改 prompt、自动重跑 Agent） | 不安全、不可审计 | 不替代人工判断 |
| trace auto mapping | 通用性不够，不同 Agent 格式差异大 | 继续 simple_mapping + 文档示例 |
| DB / graph / embedding | post-v3 future，非 tool-use inspection 核心 | — |

---

## 9. 执行原则

1. **文档先行** — 每个版本先写 RFC → SDD → Milestone → Backlog，再写代码
2. **RFC/SDD/backlog 是实现依据** — 不偏离文档中的设计决策
3. **每个版本完成后独立审计** — 对照 RFC acceptance criteria 逐项验证
4. **质量门必须包括 deterministic tests** — 每个版本新增 ≥20 个单测
5. **LLM 能力默认 advisory / opt-in** — 确定性规则是默认路径
6. **不修改 v3.1 Core Contract 对象** — 新增对象，不破坏已有 schema
7. **零网络依赖** — 确定性功能默认不联网
8. **中文优先** — 文档、注释、报告均中文优先

---

## 10. 相关文档

| 文档 | 路径 |
|------|------|
| v3.2 Milestone | [V3_2_TASK_LEVEL_EVALUATION_MILESTONE.md](V3_2_TASK_LEVEL_EVALUATION_MILESTONE.md) |
| v3.2 RFC | [../rfc/RFC_0003_TASK_LEVEL_EVALUATION.md](../rfc/RFC_0003_TASK_LEVEL_EVALUATION.md) |
| v3.2 SDD | [../sdd/SDD_TASK_LEVEL_EVALUATION_V3_2.md](../sdd/SDD_TASK_LEVEL_EVALUATION_V3_2.md) |
| v3.2 Backlog | [V3_2_IMPLEMENTATION_BACKLOG.md](V3_2_IMPLEMENTATION_BACKLOG.md) |
| v3.3 Milestone | [V3_3_EVAL_SUITE_AGGREGATION_MILESTONE.md](V3_3_EVAL_SUITE_AGGREGATION_MILESTONE.md) |
| v3.3 RFC | [../rfc/RFC_0004_EVAL_SUITE_AGGREGATION.md](../rfc/RFC_0004_EVAL_SUITE_AGGREGATION.md) |
| v3.3 SDD | [../sdd/SDD_EVAL_SUITE_AGGREGATION_V3_3.md](../sdd/SDD_EVAL_SUITE_AGGREGATION_V3_3.md) |
| v3.3 Backlog | [V3_3_IMPLEMENTATION_BACKLOG.md](V3_3_IMPLEMENTATION_BACKLOG.md) |
| v3.4 Milestone | [V3_4_REGRESSION_COMPARISON_MILESTONE.md](V3_4_REGRESSION_COMPARISON_MILESTONE.md) |
| v3.4 RFC | [../rfc/RFC_0005_REGRESSION_COMPARISON.md](../rfc/RFC_0005_REGRESSION_COMPARISON.md) |
| v3.4 SDD | [../sdd/SDD_REGRESSION_COMPARISON_V3_4.md](../sdd/SDD_REGRESSION_COMPARISON_V3_4.md) |
| v3.4 Backlog | [V3_4_IMPLEMENTATION_BACKLOG.md](V3_4_IMPLEMENTATION_BACKLOG.md) |
| v3.5 Milestone | [V3_5_TRANSCRIPT_AND_CONTEXT_ANALYSIS_MILESTONE.md](V3_5_TRANSCRIPT_AND_CONTEXT_ANALYSIS_MILESTONE.md) |
| v3.5 RFC | [../rfc/RFC_0006_TRANSCRIPT_AND_CONTEXT_ANALYSIS.md](../rfc/RFC_0006_TRANSCRIPT_AND_CONTEXT_ANALYSIS.md) |
| v3.5 SDD | [../sdd/SDD_TRANSCRIPT_AND_CONTEXT_ANALYSIS_V3_5.md](../sdd/SDD_TRANSCRIPT_AND_CONTEXT_ANALYSIS_V3_5.md) |
| v3.5 Backlog | [V3_5_IMPLEMENTATION_BACKLOG.md](V3_5_IMPLEMENTATION_BACKLOG.md) |
| v3.6 Milestone | [V3_6_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF_MILESTONE.md](V3_6_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF_MILESTONE.md) |
| v3.6 RFC | [../rfc/RFC_0007_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF.md](../rfc/RFC_0007_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF.md) |
| v3.6 SDD | [../sdd/SDD_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF_V3_6.md](../sdd/SDD_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF_V3_6.md) |
| v3.6 Backlog | [V3_6_IMPLEMENTATION_BACKLOG.md](V3_6_IMPLEMENTATION_BACKLOG.md) |
