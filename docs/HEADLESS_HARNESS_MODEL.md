# Headless Harness Execution Model

## 1. 什么是 Headless Harness

**Headless** = 无 UI，CLI-first，文件配置驱动，输出 report。

**Harness** = 把工具配置、执行、评测、证据收集、报告生成、人工 Review 串起来的
执行与约束框架。它不是"调一下 API 看结果"的工具，而是强制执行完整评测链路的约束系统。

## 2. 核心概念：One Core Flow, two material sources

Demo 和 Real 不是两套独立的流程。它们共用同一套 **Core Flow**——Harness 定义了
对象、流程、接口和边界。Demo 使用假材料（mock adapter / fake fixture / sample
evidence）跑 Core Flow，Real 未来使用真实材料（real agent / real tool call /
live LLM judge）跑同一套 Core Flow。

```
                    Core Flow
               （对象 + 流程 + 契约）
              ┌──────────────────────┐
              │  Config → Adapter    │
              │    → Runner          │
              │    → Evaluator       │
              │    → Recorder        │
              │    → Reporter        │
              │    → Evidence        │
              │    → Human Review    │
              └──────┬───────────────┘
                     │
        ┌────────────┴────────────┐
        │                         │
  ┌─────▼──────┐          ┌───────▼────────┐
  │   Demo     │          │  Real (future) │
  │ materials  │          │  materials     │
  │            │          │                │
  │ mock       │          │ live agent     │
  │ fake       │          │ real tool call │
  │ sample     │          │ LLM judge      │
  │ RuleJudge  │          │ real cost      │
  └────────────┘          └────────────────┘
```

每一步都生成结构化 artifact，每一步的输入输出都可追溯。

详见 [DEMO_CORE_REAL_BOUNDARY.md](DEMO_CORE_REAL_BOUNDARY.md)。

Core Contract 对象定义见 [AGENT2HARNESS_CORE_SPEC.md](AGENT2HARNESS_CORE_SPEC.md)。

## 3. 当前实现链路（Demo materials on Core Flow）

> 以下链路使用假材料（MockReplayAdapter、fake fixtures、RuleJudge）跑通 Core
> Flow。**这不是另一套流程，而是同一套 Core Flow 的 demo 实例化。**

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

### Demo → Core Bridge

`demo_core_bridge.py` 提供 5 个纯函数把旧 Demo 对象映射到 Core Contract 对象：
- `agent_run_result_to_execution_trace()` — `AgentRunResult` → `ExecutionTrace`
- `execution_trace_to_evidence()` — `ExecutionTrace` → `Evidence`
- `rule_check_to_rule_finding()` — `RuleCheckResult` → `RuleFinding`
- `judge_result_to_evaluation_result()` — `JudgeResult` → `EvaluationResult`
- `build_report_summary()` — `metrics dict` → `ReportSummary`

桥接层不改旧组件行为，所有函数为纯数据转换。详见
[DEMO_TO_CORE_MIGRATION.md](DEMO_TO_CORE_MIGRATION.md)。

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

## 4. 未来真实链路（Real materials on Core Flow）

> 以下模块是 Real Integration 的扩展点。它们通过 Protocol 接口接入 Core Flow，
> **不替代 Core、不修改 Core**。所有模块当前**均未实现**。

| 未来模块 | 接入方式 | 状态 |
|---------|---------|------|
| `RealAgentAdapter` | 实现 `AgentAdapter` Protocol | ❌ not supported |
| `ProviderConfig` | 独立配置模块 | ❌ not supported |
| `JudgeProvider` (live LLM) | 实现 `JudgeProvider` Protocol | ❌ not supported |
| `EvidenceStore` | 替代 `RunRecorder` 的存储层 | ❌ not supported |
| `ReviewDecision` | 从人工 Review 到自动化决策 | ❌ not supported |

**不允许**把这些模块和当前 rule checks / mock replay 混成一个 evaluator 巨石。

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

## 6. Design lineage from Anthropic tool-use guidance

Harness 的设计 lineage 来源于 Anthropic Engineering 的
[Writing effective tools for AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
文章。该文章关注一个核心问题：**如何为 AI Agent 设计高质量的工具**。

当前实现与该文章的对齐点：

1. **5 类工具设计原则审计** — `ToolDesignAuditor` 直接实现了文章的五类原则：
   choosing the right tools / namespacing / returning meaningful context /
   optimizing for token efficiency / prompt-engineering descriptions。
   每条 finding 携带 `principle` / `principle_title` / `why_it_matters` / `suggestion`。

2. **Failure attribution 四分类** — `TranscriptAnalyzer` 的四个归因类别
   (`tool_design` / `eval_definition` / `agent_tool_choice` / `runtime`)
   对应该文章对失败来源的分析框架。

3. **signal_quality 体系** — `signal_quality.py` 实现该文章对 "honest evaluation" 的要求：
   每次 run 必须显式声明信号质量级别（`tautological_replay` / `rule_deterministic` /
   `recorded_trajectory` / `real_agent`），让 reviewer 知道当前信号的置信度边界。

4. **接口隔离** — 严格区分 mock replay / real agent adapter，rule judge / LLM judge，
   reporter / decision maker，遵循该文章对 evaluation architecture 的模块化主张。

详见 [ANTHROPIC_LINEAGE.md](ANTHROPIC_LINEAGE.md)。

## 7. 架构边界

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

## 8. Coding Agent 修改守则

后续任何 Coding Agent 在修改本项目时必须遵守：

1. **不把 rule checks 升级成 LLM judge 巨石。** 如果要加 LLM judge，新建独立的 `JudgeProvider` 实现。
2. **不把 mock replay 升级成 RealAgentAdapter 巨石。** 如果要加真实 Agent，新建独立的 `RealAgentAdapter` 实现。
3. **CLI 只做装配，不写业务逻辑。**
4. **reporter 只生成报告，不做决策。**
5. **新功能优先通过独立模块 + Protocol 接口实现，不往现有模块塞逻辑。**
6. **维护实现状态矩阵的诚实性。** 代码存在但未验证 ≠ 可用。标注为 `code exists, unverified`。
