# Anthropic Lineage — 设计来源

本项目**不是**一个泛化的 CLI demo 或 LLM provider 框架。

它的设计意图来源于 Anthropic Engineering 的工具设计方法论：
**"Writing effective tools for AI agents—using AI agents"**。

> 项目吸收 Anthropic 的工具设计思想，当前实现只是第一阶段 headless CLI prototype。
> Anthropic 文章中的完整愿景（真实 LLM agentic loop、LLM judge）不能包装为当前已实现能力。

---

## 1. Source of intent

项目最初参考 Anthropic Engineering 的文章 **"Writing effective tools for AI agents"**，
关注一个核心问题：**如何为 AI Agent 设计高质量的工具**。

这篇文章是产品意图来源，不是当前能力承诺。当前项目实现了其中的**工具设计审计**
部分，以 headless CLI prototype 的形态落地。

---

## 2. Anthropic tool design principles

当前 `ToolDesignAuditor`（`agent_tool_harness/audit/tool_design_auditor.py`）
直接实现了文章的五类工具设计原则：

| # | Principle token | Anthropic principle | 审计维度 |
|---|----------------|---------------------|---------|
| 1 | `right_tools` | Choosing the right tools | 工具粒度是否匹配工作流边界；是否含捷径诱饵 |
| 2 | `namespacing` | Namespacing your tools | 工具命名空间是否清晰、防冲突 |
| 3 | `meaningful_context` | Returning meaningful context | 输出是否含 summary/evidence/next_action |
| 4 | `token_efficiency` | Optimizing for token efficiency | 是否有分页/过滤/截断策略 |
| 5 | `prompt_spec` | Prompt-engineering descriptions | when_to_use/when_not_to_use 是否面向 Agent |

每条 finding 携带 `principle` / `principle_title` / `why_it_matters` / `suggestion`，
让审计结果可以追溯到具体原则。

此外，`TranscriptAnalyzer` 的 failure attribution 四分类（`tool_design` /
`eval_definition` / `agent_tool_choice` / `runtime`）也对齐文章对失败来源的分析框架。

---

## 3. What the current prototype implements

- **工具设计审计** — 基于 5 类原则的 deterministic 启发式检查
- **eval 质量审计** — eval 结构完整性检查
- **mock replay infrastructure** — good/bad 分支回放工具调用
- **deterministic rule checks** — must_use_evidence / required_tools / forbidden_first_tool
- **transcript / tool call artifacts** — 10 个结构化 artifact 输出
- **report + diagnosis** — 含 signal_quality 声明和方法论边界警告
- **human review support** — report 是 evidence presentation，不是自动裁决

---

## 4. What the current prototype does NOT implement

- 真实 Agent runtime 集成（无 `RealAgentAdapter`）
- 真实工具选择正确性评测
- 真实工具执行正确性评测
- LLM judge 语义评分
- 基于真实 provider 的 cost / latency evidence（`llm_cost.json` 永远是 advisory-only）
- 真实世界 Agent 质量的自动 pass/fail
- 生产级 benchmark 平台

`signal_quality.py` 明确声明：**Anthropic 的文章主张 evaluation 必须由真实 LLM
agentic loop 驱动**。当前 `MockReplayAdapter` 的 `signal_quality = tautological_replay`
是 knowingly incomplete 的占位实现。

---

## 5. Demo vs future harness boundary

| 当前 demo | 不是 | 未来 harness |
|----------|------|-------------|
| mock replay | ≠ 真实 Agent eval | RealAgentAdapter |
| deterministic rule checks | ≠ LLM judge | JudgeProvider (LLM) |
| report generation | ≠ 最终裁决 | Human review |
| tool design audit | = 工具设计审计（已对齐文章）| 可扩展更深 |
| advisory-only cost | ≠ 真实账单 | ProviderConfig |

---

## 6. Design risks

- **丢失 lineage**：如果文档不声明设计来源，项目会退化成"不知道为什么这样设计"的普通 CLI checker
- **过早接 LLM provider**：如果在工具设计审计未稳固前接入真实 LLM，项目会变成泛化 LLM wrapper
- **巨石化 rule evaluator**：如果把 rule checks 逐步升级成 LLM judge 巨石，违反接口隔离原则
- **mock 与 real 耦合**：如果把 mock replay 和 RealAgentAdapter 混在同一个类里，形成架构债
- **LiveAnthropicTransport 腐烂**：v1.3 起存在的未验证代码，如果继续不验证也不删除，会误导新贡献者

---

## 7. How future work should inherit the article

以下模块均为 **future / planned**，当前未实现：

| 未来模块 | 继承的文章思想 | 状态 |
|---------|--------------|------|
| `RealAgentAdapter` | evaluation 必须由真实 LLM agentic loop 驱动 | ❌ not supported |
| `JudgeProvider` (LLM) | 语义评分替代 deterministic rules | ❌ not supported |
| `ProviderConfig` | 模型选择 / cost / latency 可观测 | ❌ not supported |
| `EvidenceStore` | 结构化证据存储与追溯 | ❌ not supported |
| `ReviewDecision` | 从人工 Review 到自动化决策 | ❌ not supported |

实现这些模块时，必须通过独立的 Protocol 接口接入，不允许往 `MockReplayAdapter` /
`RuleJudge` 里塞逻辑。
