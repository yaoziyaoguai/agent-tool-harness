# Tool-Use Inspection SDD

> **定位**: agent-tool-harness 的后续核心方向——围绕 Agent tool-use logs 做工具检查、评测和质量报告。
> **对齐**: Anthropic [Writing effective tools for agents — with agents](https://www.anthropic.com/engineering/writing-tools-for-agents)。
> **状态**: SDD defined (2026-05-13), implementation pending — 6 modules spec'd, none yet implemented beyond existing RuleJudge/ToolDesignAuditor foundation.

---

## 1. Core Purpose

agent-tool-harness 的核心不是运行各种真实 Agent。

**核心主线：**

```
External Agent Runner / 用户脚本 / CI / 手工命令
    → Agent tool-use JSON / JSONL / trace / log
    → TraceImportAdapter / mapping config
    → ExecutionTrace
    → Evidence
    → Tool-use inspection
    → CoreEvaluation
    → RuleFinding + optional JudgeFinding
    → Report
    → Human Review
```

**职责划分：**

| 角色 | 负责 | 不负责 |
|------|------|--------|
| External runner / 用户 | 启动 Agent、管理 key、联网、provider、捕获日志、输出 trace | — |
| agent-tool-harness | 导入 trace、提取 Evidence、检查 tool-use、评测工具行为、生成报告、human review | 不启动 Agent、不管理 secrets、不实现 Agent runtime |

agent-tool-harness **不运行 Agent**。所有 Agent 启动由外部 runner/CI/用户脚本负责。

---

## 2. Anthropic Effective Tools Alignment

以下 6 个模块将 Anthropic《Writing effective tools for agents — with agents》的思想映射为 agent-tool-harness 的具体能力。

三个评判边界（贯穿所有模块）：

| 评判层 | 性质 | 决定什么 |
|--------|------|---------|
| **RuleFinding** | deterministic | 决定 `EvaluationResult.passed`。适合 schema / pairing / required tool / forbidden tool / grounding 等确定性检查。 |
| **JudgeFinding** | optional LLM-assisted, advisory only | 不改变 passed。适合 tool choice reasonableness / argument quality / answer faithfulness / ambiguous tool design 分析。 |
| **ReviewDecision** | human explicit only | 最终裁决。不由 LLM 自动生成，不由 report 自动生成。 |

**当前不做自动 optimizer：** 不自动改 tool spec、不自动改 Agent prompt、不自动重跑 Agent。
未来可做 human-guided optimization recommendations。

---

### Module 1: Trace Import and Mapping Stability

**对应文章思想：** evaluation logging foundation——没有稳定 trace，无法评测工具质量。

**当前状态：** TraceImportAdapter (native + simple_mapping) 已实现 (83 tests)。JSONL importer 未实现。

**后续能力方向：**

| 能力 | 状态 | 说明 |
|------|------|------|
| native trace schema | ✅ done | 直接导入 ExecutionTrace JSON |
| simple mapping | ✅ done | YAML 字段映射导入非标准格式 |
| JSONL importer | 🔜 future | 逐行 JSON 事件流 → ExecutionTrace |
| mapping diagnostics | 🔜 future | 字段覆盖率报告、缺失字段提示 |
| field type diagnostics | 🔜 future | 类型错误报告（expected string, got int） |
| list item diagnostics | 🔜 future | 数组元素级别问题定位 |
| trace confidence level | 🔜 future | wrapper_bridge / simple_mapping / native provenance 标注 |
| mapping dry-run | 🔜 future | 不产生 ExecutionTrace，仅校验 mapping 有效性 |

---

### Module 2: Tool-use Correctness Checks

**对应文章思想：** testing tools with agents——通过日志检查 Agent 是否正确使用了工具。

**当前状态：** RuleJudge 已有 must_call_tool / forbidden_first_tool / must_use_evidence。其余未实现。

**规则目录（deterministic — RuleFinding）：**

| 类别 | 规则 | 状态 |
|------|------|------|
| Schema | `tool_call` has `call_id` | ✅ TraceImportAdapter validation |
| Pairing | `tool_result` can pair with `call_id` | ✅ TraceImportAdapter validation |
| Identity | `tool_name` preserved across call-result pair | ✅ TraceImportAdapter validation |
| Arguments | `arguments` present and structurally valid | 🔜 future |
| Status | `status` is valid ("success" / "error") | ✅ TraceImportAdapter validation |
| Output | `output` or `error` at least one non-empty | ✅ TraceImportAdapter validation |
| Uniqueness | no duplicate `call_id` | 🔜 future |
| Orphan | no orphan `tool_call` (missing result) | ✅ TraceImportAdapter cross-ref |
| Orphan | no orphan `tool_result` (missing call) | 🔜 future |
| Expected | required tool called per eval spec | ✅ RuleJudge must_call_tool |
| Forbidden | forbidden tool not called | ✅ RuleJudge forbidden_first_tool |
| Order | required tool call order | 🔜 future |
| Fallback | fallback tool after tool error | 🔜 future |
| Retry | retry behavior patterns | 🔜 future |
| Grounding | final_answer grounded in tool_result | 🔜 future |

---

### Module 3: Tool Metrics

**对应文章思想：** evaluation feedback loops——从日志统计工具使用行为，反推设计问题。

**当前状态：** 未实现。Cost / latency tracking deferred。

**指标目录（future — Tool Metrics Phase）：**

| 指标 | 说明 |
|------|------|
| `tool_call_count` | 总工具调用次数 |
| `tool_error_count` | 工具返回 error 的次数 |
| `tool_error_rate` | error / total |
| `redundant_call_count` | 相同工具+相同参数重复调用 |
| `invalid_argument_count` | 参数校验失败的调用 |
| `tool_response_size_chars` | 工具返回内容大小分布 |
| `estimated_response_tokens` | 估算 token 数 |
| `task_runtime` | 端到端任务耗时 |
| `tool_latency` | per-tool 调用延迟 |
| `repeated_same_tool_calls` | 连续多次相同工具 |
| `missing_result_rate` | tool_call 无对应 tool_result 的比例 |

**说明：** latency / token / cost 之前 deferred，在 Tool Metrics Phase 中实现。

---

### Module 4: Tool Ergonomics Evaluation

**对应文章思想：** choosing the right tools / namespacing tools / thinking about tool granularity。
工具应该适合 Agent 使用，而不是只做低级 API wrapper。

**当前状态：** ToolDesignAuditor 有基础启发式检查。未系统化。

**检查方向（deterministic hints + optional LLM judge advisory）：**

| 检查项 | 说明 | 评判方式 |
|--------|------|---------|
| tool too low-level | 工具粒度过细，只是 DB CRUD 或 HTTP wrapper | deterministic hint + LLM advisory |
| tool overlap | 多个工具功能重叠 | deterministic hint (name/keyword overlap) |
| namespace clarity | 工具命名空间是否清晰 | deterministic (namespace 结构检查) |
| ambiguous tool names | 工具名是否可能混淆 | deterministic (name similarity check) |
| too many similar tools | 相似工具数量过多 | deterministic (count + similarity threshold) |
| frequently chained tools | 常被连续调用的工具对——可能应合并为 higher-level tool | 🔜 future (pattern mining) |
| list-all anti-pattern | list/get-all 工具可能应为 search/filter | deterministic hint |
| missing higher-level domain tool | 发现工具链组合但缺少对应的领域工具 | 🔜 future (LLM advisory) |
| wrong tool selected | Agent 选了错误的工具（工具名/描述重叠导致） | 🔜 future (LLM advisory) |

---

### Module 5: Tool Response Quality

**对应文章思想：** returning meaningful context / token efficiency / helpful errors。
工具返回内容帮助 Agent 做下一步推理。

**当前状态：** 未实现。

**检查方向（deterministic hints + optional LLM judge advisory）：**

| 检查项 | 说明 | 评判方式 |
|--------|------|---------|
| response has context | 返回包含有意义上下文，不只是 IDs | deterministic hint + LLM advisory |
| response too verbose | 返回过于冗长 | deterministic (size threshold) |
| IDs without names | 只返回 ID 无名称/标题 | deterministic hint (pattern match) |
| missing fields for next call | 返回缺少下一步调用需要的字段 | 🔜 future (LLM advisory) |
| pagination guidance | 分页结果是否含分页信息 | deterministic hint |
| output too large | 返回超过合理大小 | deterministic (size threshold) |
| error message actionable | 错误消息是否可操作 | deterministic hint + LLM advisory |
| error includes schema | 错误是否包含期望 schema 或修复提示 | deterministic hint (keyword match) |
| concise/detailed mode | 是否提供简洁/详细两种模式 | deterministic hint |
| final_answer faithfulness | final_answer 是否忠实用 tool_result | 🔜 future (LLM advisory) |

---

### Module 6: Tool Spec Quality

**对应文章思想：** prompt-engineering tool descriptions and specs / tool descriptions matter enormously。

**当前状态：** ToolDesignAuditor 和 bootstrap 有基础检查。未系统化。

**检查方向（deterministic hints）：**

| 检查项 | 说明 |
|--------|------|
| description clarity | tool description 是否清晰、包含足够上下文 |
| purpose distinct | 与其他工具描述区分度 |
| parameter names unambiguous | 参数名是否无歧义 |
| input schema strict | input_schema 是否完整（type / properties / required） |
| output schema documented | output_contract 是否定义 |
| examples present | 是否有使用示例 |
| destructive annotated | 破坏性操作是否标注 side_effects |
| open-world side-effect annotated | 外部世界副作用是否标注 |
| auth / secret requirements | 认证/密钥需求是否文档化 |
| response format documented | 返回格式是否说明 |
| when_to_use / when_not_to_use | 使用/不使用场景是否完整 |
| token_policy defined | 是否定义 max_tokens_per_call |

---

## 3. Next-Phase Priorities

从 "继续跑真实 Agent" 转向 "tool-use inspection 能力建设"：

**Phase 1 — Foundation (当前 → 近期):**
1. Tool-use inspection rule catalog spec（Module 2 规则集完整 spec）
2. Trace import diagnostics（Module 1 mapping diagnostics / field coverage）
3. Tool-use correctness checks 实现（Module 2 未实现的 deterministic rules）
4. Evidence quality report

**Phase 2 — Inspection (近期 → 中期):**
5. Tool spec quality checks（Module 6）
6. Tool ergonomics evaluation hints（Module 4 deterministic 部分）
7. Tool response quality hints（Module 5 deterministic 部分）
8. LLM judge rubric for tool-use quality（Module 4+5 LLM advisory 部分）

**Phase 3 — Metrics & Batch (中期 → 远期):**
9. Tool metrics phase（Module 3）
10. Batch / multi-trace evaluation
11. Human review UX

**明确 defer：**
- Level 4B target-agent self real provider dogfood
- complex universal agent runner
- automatic trace repair
- LLM auto mapping
- automatic optimizer loop
- cost / latency until Tool Metrics Phase
- parallel evaluation until batch phase

---

## 4. Design Principles

1. **RuleJudge deterministic — passed 由规则决定** — schema / pairing / required tool / forbidden tool / grounding 等确定性规则决定 EvaluationResult.passed
2. **LLM Judge advisory only** — 不改变 passed，不生成 ReviewDecision
3. **ReviewDecision human explicit only** — 不由机器自动生成
4. **不自动修改工具** — optimizer 只做 recommendation，不做自动 rewrite
5. **离线优先** — 所有 deterministic 检查零网络依赖
6. **证据驱动** — 每个 finding 引用具体 trace 位置

---

## 5. References

- [Anthropic: Writing effective tools for agents — with agents](https://www.anthropic.com/engineering/writing-tools-for-agents)
- [AGENT2HARNESS_MAIN_FLOW.md](AGENT2HARNESS_MAIN_FLOW.md)
- [REAL_AGENT_INTEGRATION_SDD.md](REAL_AGENT_INTEGRATION_SDD.md)
- [EXTERNAL_RUNNER_WORKFLOW.md](EXTERNAL_RUNNER_WORKFLOW.md)
- [ROADMAP.md](ROADMAP.md)
- [BACKLOG.md](BACKLOG.md)
