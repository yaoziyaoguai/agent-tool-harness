# Headless Harness Execution Model

## 1. 什么是 Headless Harness

**Headless** = 无 UI，CLI-first，文件配置驱动，输出 report。

**Harness** = 把工具配置、执行、评测、证据收集、报告生成、人工 Review 串起来的
执行与约束框架。它不是"调一下 API 看结果"的工具，而是强制执行完整评测链路的约束系统。

## 2. 核心概念

```
Config (YAML)
  → Tool Adapter (Agent 工具调用)
    → Runner (编排)
      → Evaluator (判定)
        → Reporter (报告)
          → Evidence (证据)
            → Human Review (人工审查)
              → Decision (决策)
```

每一步都生成结构化 artifact，每一步的输入输出都可追溯。

## 3. 当前实现链路

### Config → Spec

`project.yaml` / `tools.yaml` / `evals.yaml` 经 `config/loader.py` 解析为
`ProjectSpec` / `ToolSpec` / `EvalSpec` 对象。格式校验严格（required fields +
type checks），失败即拒绝。

### Mock/Demo Execution

`MockReplayAdapter` 按 `--mock-path good|bad` 分支回放工具调用：
- good 路径：按 `case.expected_tool_behavior.required_tools` 推导调用序列
- bad 路径：故意偏离（选禁止工具 / 漏调必须工具）

`ToolRegistry` 通过 `tools.yaml` 的 `executor.module` 发现并调用真实工具函数。
工具响应写入 `tool_calls.jsonl` + `tool_responses.jsonl`。

> 关键约束：`run` 命令当前硬编码 `MockReplayAdapter`。不支持注入自定义 `AgentAdapter`。

### Deterministic Checks

`RuleJudge` 做确定性规则匹配：
- `must_use_evidence` — 包含 evidence id 子串
- `required_tools` — 调用顺序与数量
- `forbidden_first_tool` — 第一步不应使用的工具
- `max_tool_calls` — 最大调用次数
- `verifiable_outcome` — root_cause 匹配

`RuleJudge` 是 baseline，**不是 LLM 语义判定**。它无法判断回答语义是否正确。

### Report Generation

`MarkdownReport` 生成 10 个 artifact 中的人类可读报告。每次 run 都会声明
`signal_quality`（tautological_replay / recorded_trajectory 等），
让 reviewer 知道本次信号的置信度边界。

### Human Review

报告是派生视图。失败复盘必须回到原始 artifact：
`transcript.jsonl` → `tool_calls.jsonl` → `tool_responses.jsonl` → `judge_results.json` → `diagnosis.json`

人工判断失败归因于：工具设计 / eval 设计 / Agent 路径 / 证据处理。

## 4. 未来真实链路

```
ProjectAdapter   → 适配用户项目的真实 runtime
RealAgentAdapter → 调用真实 LLM (OpenAI/Anthropic/DeepSeek)
ProviderConfig   → 模型配置 (API Key / Base URL / Model)
JudgeProvider    → LLM judge (语义评分，替代 deterministic rules)
EvidenceStore    → 结构化证据存储与追溯
ReviewDecision   → 从人工 Review 到自动化决策
```

> 这些模块当前**均未实现**。它们是未来独立设计的目标，**不允许**和当前
> rule checks / mock replay 混成一个 evaluator 巨石。

## 5. 当前实现状态矩阵

| 组件 | 状态 | 说明 |
|------|------|------|
| CLI | ✅ implemented | 13 个子命令 |
| Config Loader | ✅ implemented | YAML → Spec |
| MockReplayAdapter | ✅ implemented | good/bad 分支 |
| TranscriptReplayAdapter | ✅ implemented | 历史轨迹重放 |
| RuleJudge | ✅ implemented | deterministic 规则 |
| ToolDesignAuditor | ✅ implemented | heuristic |
| MarkdownReport | ✅ implemented | 10 artifact + report.md |
| CostTracker | ✅ implemented | advisory-only |
| TraceSignalAnalyzer | ✅ implemented | 5 类 deterministic 信号 |
| TranscriptAnalyzer | ✅ implemented | failure attribution |
| Bootstrap/Scaffold | ✅ implemented | AST 扫描生成 draft |
| LiveAnthropicTransport | ⚠️ code exists, unverified | 从未对真实端点验证 |
| AnthropicCompatibleJudgeProvider | ⚠️ offline ok, live unverified | live 模式从未跑通 |
| RealAgentAdapter | ❌ not supported | 无实现 |
| JudgeProvider (live) | ❌ not supported | 代码存在但未验证 ≠ 可用 |
| Web UI | ❌ not supported | — |
| MCP executor | ❌ not supported | — |
| HTTP/Shell executor | ❌ not supported | — |
| Python SDK | ❌ not supported | `__init__.py` 只导出版本号 |

## 6. 架构边界

### CLI 是 thin adapter
CLI 只负责解析参数、装配组件、调用 runner。不允许在 CLI 层写业务逻辑。

### rule checks ≠ LLM judge
当前 deterministic rule checks 是 baseline，不是"差一点的 LLM judge"。
未来 LLM judge 必须通过独立的 `JudgeProvider` 接口接入，不能往 `RuleJudge` 里塞逻辑。

### mock replay ≠ RealAgentAdapter
`MockReplayAdapter` 是 demo/prototype 工具。未来真实 Agent 执行必须通过独立的
`RealAgentAdapter` 实现 `AgentAdapter` Protocol，不能往 `MockReplayAdapter` 里塞逻辑。

### reporter ≠ decision maker
Reporter 只生成报告。最终判定由 Human Review 完成。报告不得自动做"通过/不通过"决策。

### human review 是最终决策点
在 Harness 链路中，人是最终解释者和决策者。所有 artifact 是辅助人类判断的证据，
不是自动裁决的结果。

## 7. Coding Agent 修改守则

后续任何 Coding Agent 在修改本项目时必须遵守：

1. **不把 rule checks 升级成 LLM judge 巨石。** 如果要加 LLM judge，新建独立的 `JudgeProvider` 实现。
2. **不把 mock replay 升级成 RealAgentAdapter 巨石。** 如果要加真实 Agent，新建独立的 `RealAgentAdapter` 实现。
3. **CLI 只做装配，不写业务逻辑。**
4. **reporter 只生成报告，不做决策。**
5. **新功能优先通过独立模块 + Protocol 接口实现，不往现有模块塞逻辑。**
6. **维护实现状态矩阵的诚实性。** 代码存在但未验证 ≠ 可用。标注为 `code exists, unverified`。
