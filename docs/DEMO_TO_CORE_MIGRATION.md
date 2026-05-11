# Demo-to-Core Migration

> 本文档描述如何把现有 Demo runtime（MockReplayAdapter / TranscriptReplayAdapter /
> RuleJudge）的输出桥接到 Agent2Harness Core Contract 对象。

---

## 1. 为什么需要这次迁移

Core Contract（`core_contract.py`）定义了 Demo 和 Real 共用的运行时对象——
`ToolCall`, `ToolResult`, `ExecutionTrace`, `Evidence`, `Finding`, `RuleFinding`,
`EvaluationResult`, `ReportSummary`, `ReviewDecision`。这些对象已经存在并通过了
19 个 contract test。

但当前 Demo runtime 的实际数据流仍然是：

```
MockReplayAdapter.run() → AgentRunResult (list[dict] tool_calls/responses)
RuleJudge.judge() → JudgeResult (list[RuleCheckResult])
EvalRunner._write_artifacts() → JSON artifacts (plain dict)
```

没有任何环节产出或消费 Core Contract 对象。这意味着：
- Core Contract 只是"纸面上的定义"，没有被实际链路验证
- 未来 RealAgentAdapter 接入时，没有现成的桥接代码可以参考
- contract test 中的 FakeAgentAdapter 验证了接口形状，但没有验证"真实旧对象能否映射到新对象"

**本次迁移的目标不是替换旧链路，而是架一座桥——让旧对象可以映射到 Core Contract
对象，验证映射是可行且正确的。**

---

## 2. 当前旧 Demo Flow（迁移前）

```
EvalSpec
  → MockReplayAdapter.run(case, registry, recorder)
    → AgentRunResult(
        eval_id: str,
        final_answer: str,
        tool_calls: list[dict],     # ← plain dict，非 ToolCall
        tool_responses: list[dict],  # ← plain dict，非 ToolResult
      )
  → RuleJudge.judge(case, run_result)
    → JudgeResult(
        eval_id: str,
        passed: bool,
        checks: list[RuleCheckResult],  # ← 非 RuleFinding
      )
  → EvalRunner._write_artifacts()
    → JSON files (plain dict)
```

**旧对象结构（关键字段）：**

`AgentRunResult.tool_calls[i]`：
```python
{
    "call_id": str,
    "eval_id": str,
    "tool_name": str,
    "arguments": dict,
    "qualified_name": str,    # 可选
    "side_effects": dict,     # 可选
}
```

`AgentRunResult.tool_responses[i]`：
```python
{
    "call_id": str,
    "eval_id": str,
    "tool_name": str,
    "response": {
        "success": bool,
        "content": dict,      # 含 evidence、technical_id 等
        "error": str | None,
    },
}
```

`JudgeResult.checks[i]`（RuleCheckResult）：
```python
RuleCheckResult(
    rule: dict,     # {"type": "must_call_tool", "tool": "search", ...}
    passed: bool,
    message: str,
)
```

---

## 3. 目标 Core Flow（迁移后）

```
EvalSpec
  → MockReplayAdapter.run(case, registry, recorder)
    → AgentRunResult (不变——不改旧 adapter)
  → demo_core_bridge.agent_run_result_to_execution_trace()
    → ExecutionTrace(
        scenario_id: str,
        tool_calls: list[ToolCall],       # ← Core Contract 对象
        tool_results: list[ToolResult],   # ← Core Contract 对象
        final_answer: str,
      )
  → demo_core_bridge.execution_trace_to_evidence()
    → Evidence(trace=..., signal_quality=...)
  → RuleJudge.judge(case, run_result)
    → JudgeResult (不变——不改旧 judge)
  → demo_core_bridge.judge_result_to_evaluation_result()
    → EvaluationResult(
        scenario_id: str,
        findings: list[RuleFinding],  # ← Core Contract 对象
        passed: bool,
      )
  → demo_core_bridge.build_report_summary()
    → ReportSummary(...)
```

**关键设计决策：桥接层不改旧组件。**

---

## 4. 最小迁移策略

### 4.1 新增模块：`agent_tool_harness/demo_core_bridge.py`

提供以下纯函数（无副作用、无 IO）：

| 函数 | 输入 | 输出 | 职责 |
|------|------|------|------|
| `agent_run_result_to_execution_trace` | `AgentRunResult` | `ExecutionTrace` | dict→ToolCall/ToolResult 映射 |
| `execution_trace_to_evidence` | `ExecutionTrace`, `signal_quality` | `Evidence` | 打包 trace 为 evidence |
| `rule_check_to_rule_finding` | `RuleCheckResult` | `RuleFinding` | 单条规则结果→RuleFinding |
| `judge_result_to_evaluation_result` | `JudgeResult` | `EvaluationResult` | 聚合 judge 输出 |
| `build_report_summary` | `metrics: dict` | `ReportSummary` | 统计摘要 |

### 4.2 不改动的组件

- `MockReplayAdapter` — 仍然产出 `AgentRunResult`
- `TranscriptReplayAdapter` — 仍然产出 `AgentRunResult`
- `RuleJudge` — 仍然产出 `JudgeResult`
- `EvalRunner` — 仍然消费旧 `AgentAdapter` Protocol
- `cli.py` — 仍然通过 `assembly.py` 获取 adapter

### 4.3 桥接函数不负责

- 不执行工具
- 不调 LLM
- 不读/写磁盘
- 不修改输入对象（immutable 风格——创建新对象）
- 不生成 `ReviewDecision`（那是人工 Reviewer 的事）
- 不 import demo/cli/provider 模块

---

## 5. 非目标

- **不替换** MockReplayAdapter / RuleJudge
- **不修改** EvalRunner 的编排逻辑
- **不让** CLI 直接消费 Core Contract 对象
- **不实现** RealAgentAdapter
- **不实现** LLM Judge
- **不改变** 任何 CLI 行为
- **不改变** 任何现有测试的行为

---

## 6. 分阶段方法

### Phase 5a（本轮）：桥接函数 + 表征测试

- 新增 `demo_core_bridge.py`（5 个纯函数）
- 新增 `test_demo_to_core_bridge.py`（12+ 测试）
- 验证旧对象可以正确映射到 Core Contract 对象

### Phase 5b（后续）：EvalRunner 消费 Core Contract

- EvalRunner 内部使用 bridge 函数，产出 `Evidence` + `EvaluationResult`
- artifact 写入逻辑不变（仍写 JSON）
- 这是让 Core Flow 真正跑起来的步骤

### Phase 5c（后续）：旧 Adapter 适配 Agent2HarnessAdapter

- `MockReplayAdapter` / `TranscriptReplayAdapter` 新增 `run_scenario(ScenarioSpec) -> ExecutionTrace` 方法
- 或创建 wrapper class 实现 `Agent2HarnessAdapter` Protocol

---

## 7. 验收标准

- [ ] `demo_core_bridge.py` 包含 5 个桥接函数
- [ ] `test_demo_to_core_bridge.py` 包含 12+ 个测试
- [ ] 所有 contract test 继续通过（19 个）
- [ ] 所有现有测试继续通过（无 regression）
- [ ] bridge 模块不 import demo/cli/provider 模块
- [ ] bridge 模块不读取 .env
- [ ] ruff 检查通过
- [ ] `ReviewDecision` 不由任何 bridge 函数自动生成
- [ ] CLI 行为不变（`run --mock-path good` 仍然通过）
