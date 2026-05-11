# Agent2Harness Core Spec

> 本文档定义 Agent Tool Harness 的核心对象、接口和评测流程。
> Core Contract 是 Demo runtime 和 Real runtime 的共同基础——
> 两边的数据都经过相同的对象传递，差异仅在 adapter 的实现方式。

---

## 1. Core Flow

```
                        ┌──────────────────────┐
                        │   ScenarioSpec        │
                        │   (评什么)             │
                        └──────────┬───────────┘
                                   │
                                   ▼
                        ┌──────────────────────┐
                        │ Agent2HarnessAdapter  │
                        │ (怎么跑)              │
                        │ .run(ScenarioSpec)    │
                        │     → ExecutionTrace  │
                        └──────────┬───────────┘
                                   │
                                   ▼
              ┌────────────────────┼────────────────────┐
              │                    ▼                    │
              │           ┌───────────────┐             │
              │           │ ExecutionTrace │             │
              │           │ (跑了什么)     │             │
              │           └───────┬───────┘             │
              │                   │                     │
              │       ┌───────────┼───────────┐         │
              │       ▼           ▼           ▼         │
              │  ┌────────┐ ┌──────────┐ ┌──────────┐  │
              │  │Finding │ │ Evidence │ │  Cost    │  │
              │  │(发现)   │ │ (证据)   │ │ (成本)   │  │
              │  └───┬────┘ └────┬─────┘ └────┬─────┘  │
              │      └───────────┼─────────────┘        │
              │                  ▼                      │
              │         ┌────────────────┐              │
              │         │EvaluationResult│              │
              │         │ (机器评分汇总)  │              │
              │         └───────┬────────┘              │
              │                 │                       │
              │                 ▼                       │
              │         ┌────────────────┐              │
              │         │ ReportSummary  │              │
              │         │ (统计摘要)     │              │
              │         └───────┬────────┘              │
              │                 │                       │
              │                 │  ← 人工 Reviewer 介入  │
              │                 ▼                       │
              │         ┌────────────────┐              │
              │         │ ReviewDecision │              │
              │         │ (人工裁决)     │              │
              │         └────────────────┘              │
              └─────────────────────────────────────────┘
```

**关键边界：** 虚线以上的所有步骤都是机器执行的（automated）；`ReviewDecision` 是人工裁决，**不由** `EvaluationResult` 自动派生。

---

## 2. Core Objects

### 2.1 已有（config 层）

| 对象 | 位置 | 职责 |
|------|------|------|
| `ToolSpec` | `config/tool_spec.py` | 工具契约：name, description, input_schema, side_effects, executor |
| `EvalSpec` | `config/eval_spec.py` | eval 配置：id, user_prompt, judge rules, expected_tool_behavior |
| `ProjectSpec` | `config/project_spec.py` | 项目元数据：name, domain, evidence_sources, pricing, budget |

### 2.2 新增（core_contract.py）

| 对象 | 类型 | 职责 |
|------|------|------|
| `ScenarioSpec` | frozen dataclass | 评测场景纯数据：scenario_id, goal, available_tools, success_criteria |
| `ToolCall` | frozen dataclass | 单次工具调用：tool_name, arguments, call_id, timestamp |
| `ToolResult` | frozen dataclass | 单次工具返回：call_id, status, output, error |
| `ExecutionTrace` | dataclass | 执行轨迹：scenario_id, tool_calls[], tool_results[], messages[], final_answer |
| `Evidence` | dataclass | 证据包：trace, artifacts, cost_usd, latency_ms, warnings, signal_quality |
| `Finding` | frozen dataclass | 评测发现基类：finding_id, severity, category, message, evidence_ref |
| `RuleFinding` | frozen dataclass | 规则发现（继承 Finding）：rule_type, rule_passed |
| `EvaluationResult` | dataclass | 机器评分汇总：scenario_id, findings[], passed, summary |
| `ReportSummary` | frozen dataclass | 统计摘要：total_scenarios, passed, failed, signal_quality |
| `ReviewDecision` | frozen dataclass | 人工裁决：decision, reviewer, notes, reviewed_at |
| `Agent2HarnessAdapter` | Protocol | adapter 接口：`run(ScenarioSpec) -> ExecutionTrace` |

### 2.3 已有但本轮未迁移的对象

| 对象 | 位置 | 说明 |
|------|------|------|
| `AgentAdapter` | `agents/agent_adapter_base.py` | 当前实际运行的 Protocol，签名含 ToolRegistry/RunRecorder |
| `AgentRunResult` | `agents/agent_adapter_base.py` | 当前 run 结果，待适配为 ExecutionTrace |
| `JudgeResult` | `judges/rule_judge.py` | 当前 judge 输出，待适配为 RuleFinding |
| `RuleCheckResult` | `judges/rule_judge.py` | 当前规则检查结果，待适配为 Finding |
| `JudgeProvider` | `judges/provider.py` | 当前 judge provider 协议 |
| `ProviderJudgeResult` | `judges/provider.py` | 当前 provider judge 结果 |

---

## 3. What belongs to Core

- **数据对象**：ToolCall, ToolResult, ExecutionTrace, Evidence, Finding, RuleFinding, EvaluationResult, ReportSummary, ReviewDecision, ScenarioSpec
- **接口**：Agent2HarnessAdapter Protocol
- **已有 Core 对象**：ToolSpec, EvalSpec, ProjectSpec（config 层）
- **信号质量标签**：signal_quality.py（5 级标签 + describe()）
- **Artifact schema**：artifact_schema.py（版本 + run_metadata）

---

## 4. What does NOT belong to Core

Core Contract **不**包含以下任何内容：

- 工具执行逻辑（那是 ToolExecutor 的事）
- Agent 推理逻辑（那是 Adapter 的事）
- Judge 评分逻辑（那是 Judge 的事）
- 报告渲染逻辑（那是 Reporter 的事）
- YAML/JSON 配置加载（那是 config/loader 的事）
- CLI 命令定义（那是 cli.py 的事）
- 示例项目（那是 examples/ 的事）
- 真实 LLM API 调用
- .env 读取
- 任何 provider 特定的配置（AnthropicConfig, OpenAIConfig 等）

---

## 5. Demo runtime 如何使用 Core

当前 Demo runtime 的组件与 Core Contract 的关系：

| Demo 组件 | 当前消费 | 未来适配 |
|-----------|---------|---------|
| `MockReplayAdapter` | `AgentAdapter` Protocol (旧) | 适配为 `Agent2HarnessAdapter`，产出 `ExecutionTrace` |
| `RuleJudge` | `EvalSpec` + `AgentRunResult` → `JudgeResult` | 产出 `RuleFinding` 列表而非 `RuleCheckResult` 列表 |
| `EvalRunner` | `AgentAdapter` (旧) + 各模块 | 消费 `Agent2HarnessAdapter` + 组装 `Evidence` |
| `TranscriptReplayAdapter` | `AgentAdapter` Protocol (旧) | 同 MockReplayAdapter |

**当前本轮不变更 Demo 组件的行为**——Core Contract 对象定义先行，适配在后。

---

## 6. Real runtime 未来如何使用 Core

未来 Real Integration 的接入路径：

```
1. RealAgentAdapter implements Agent2HarnessAdapter
   - SIGNAL_QUALITY = "real_agent"
   - run(ScenarioSpec) → ExecutionTrace (via real LLM agentic loop)

2. Real Judge (LLM) 产出 JudgeFinding (extends Finding)
   - category = "judge"
   - 附带 confidence, rubric, model 信息

3. EvalRunner 消费 ExecutionTrace + Evidence
   - RuleFinding + JudgeFinding → EvaluationResult.findings
   - report.md 同时展示规则结果和 LLM 评分

4. Human Reviewer 查看 full evidence → 创建 ReviewDecision
```

---

## 7. RuleFinding vs JudgeFinding 边界

| 维度 | RuleFinding | JudgeFinding (未来) |
|------|------------|-------------------|
| 来源 | deterministic 规则（must_call_tool 等） | LLM 语义判断 |
| 可复现性 | 100% 可复现 | 受 model/temperature 影响 |
| 证据 | 结构性事实（调了没调） | 语义质量（好不好） |
| 置信度 | 不需要（确定性的） | 需要（confidence score） |
| 角色 | 底线 checks（不可绕过） | advisory（增强信号） |

两者在 `EvaluationResult.findings` 中**并列存在**，reviewer 根据两者做最终裁决。

---

## 8. EvaluationResult vs ReviewDecision 边界

| 维度 | EvaluationResult | ReviewDecision |
|------|-----------------|----------------|
| 创建者 | 机器（Runner + Judge） | 人（Reviewer） |
| 内容 | PASS/FAIL + findings 列表 | approved / needs_revision / rejected |
| 时机 | 每次 run 自动生成 | 人工 review 后显式创建 |
| 可否自动派生 | N/A | **禁止**——不可从 EvaluationResult 自动生成 |
| 为什么需要两个 | 机器打分是信号 | 人工裁决是最终结论 |

**这是 Agent 工具评测最关键的治理边界。** LLM judge 可以帮助 reviewer 发现问题，
但"这个工具设计是否可以接受"的判断涉及产品决策、领域知识和成本权衡——
这些不是评分能替代的。

---

## 9. Why Core must not depend on Demo or Real

```
Track B (Core)  ←  Track A (Demo) 可以依赖 Core，反之禁止
Track B (Core)  ←  Track C (Real) 可以依赖 Core，反之禁止
Track A (Demo)  ←/→  Track C (Real)  互相禁止依赖
```

如果 Core 依赖 Demo（如 import MockReplayAdapter），则：
- 真实 Agent 接入时必须同时引入 demo 代码
- Demo 的行为变更可能破坏 Core contract
- 无法在 CI 中独立验证 Core 的正确性

如果 Core 依赖 Real（如 import live transport），则：
- Demo 测试时必须配置真实 API key
- Core 的 contract test 不再能 0 联网运行
- 换 provider 就要改 Core，contract 失去稳定性

---

## 10. Contract tests as proof

`tests/test_core_contract.py` 包含 19 个 contract test：

1. ToolSpec 表达工具定义
2. ScenarioSpec 引用 ToolSpec
3. ScenarioSpec 是纯数据（无 IO 逻辑）
4. ExecutionTrace 承载 tool_calls + tool_results
5. ToolCall 是不可变的
6. Evidence 打包 ExecutionTrace
7. Evidence cost/latency 可为 None
8. Finding 引用 Evidence
9. RuleFinding 继承 Finding
10. EvaluationResult 聚合 findings
11. EvaluationResult 不自动生成 ReviewDecision
12. ReviewDecision 必须显式创建
13. ReviewDecision 是不可变的
14. FakeAgentAdapter 实现 Agent2HarnessAdapter Protocol
15. Fake adapter 输入 ScenarioSpec → 输出 ExecutionTrace
16. tool_calls 和 tool_results 通过 call_id 对应
17. core_contract.py 不 import demo/cli/provider 模块
18. core_contract.py 不读取环境变量
19. ReportSummary 不替代 ReviewDecision

所有 contract test 在 CI 中 **0 联网**运行。
