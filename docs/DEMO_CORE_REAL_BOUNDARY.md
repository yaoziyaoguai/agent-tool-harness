# Demo / Core / Real Boundary

## 1. Why this boundary exists

当前项目处于一个危险的中间状态：mock replay（Demo）已经能跑通全链路，但缺乏真实
Agent 评测能力（Real）。如果不显式定义 Core——即 Demo 和 Real **共享**的那套流程、
对象和契约——两大风险会同时发生：

- **Demo 污染 Core**：为了 demo 方便修改 Core contract，导致未来真实接入时契约
  已变形。
- **Real 污染 Demo**：未验证的 Real Integration 代码（LiveAnthropicTransport、
  AnthropicCompatibleJudgeProvider）混在源码中，让 demo 用户误以为"接真实 LLM
  很快就能跑通"。

本文件的目的是：**把 Core 提取出来，让 Demo 和 Real 都成为 Core 的外部消费者，
而不是让它们互相污染。**

## 2. One Core Flow, two runtime material sources

Demo 不是另一套简化流程。Demo 是使用 mock / fake / sample materials 跑同一套
Agent2Harness Core Flow。

```
                    ┌─────────────────────────────┐
                    │         Core Flow            │
                    │                             │
                    │  ToolSpec → ScenarioSpec    │
                    │    → ExecutionTrace         │
                    │    → Evidence → Finding     │
                    │    → Report → Human Review  │
                    │                             │
                    └──────────┬──────────────────┘
                               │
              ┌────────────────┴────────────────┐
              │                                 │
    ┌─────────▼──────────┐          ┌───────────▼──────────┐
    │   Demo Materials   │          │  Real Materials      │
    │                    │          │                      │
    │  MockReplayAdapter │          │  RealAgentAdapter    │
    │  Fake fixtures     │          │  ProviderConfig      │
    │  Sample evidence   │          │  JudgeProvider (LLM) │
    │  RuleJudge         │          │  EvidenceStore       │
    │  Deterministic     │          │  Cost/latency real   │
    └────────────────────┘          └──────────────────────┘
```

两者共用 Core Flow，分叉在 **Adapter / Provider / Executor / Evidence** 四个扩展点。

## 3. What belongs to Core

Core 负责定义**世界应该长什么样、对象如何流动、流程顺序、接口契约**。

### 3.1 Core 负责

| 职责 | 当前实现 |
|------|---------|
| Spec 对象定义 | `config/` — ProjectSpec, ToolSpec, EvalSpec |
| AgentAdapter Protocol | `agents/agent_adapter_base.py` — `AgentAdapter` + `AgentRunResult` |
| JudgeProvider Protocol | `judges/provider.py` — `JudgeProvider` + `ProviderJudgeResult` |
| ToolExecutor Protocol | `tools/executor_base.py` |
| ToolRegistry | `tools/registry.py` |
| EvalRunner 编排 | `runner/eval_runner.py` — 接受 adapter/judge 接口，不硬编码实现 |
| RunRecorder | `recorder/run_recorder.py` — 10 个 artifact 的写入契约 |
| artifact schema | `artifact_schema.py` — schema_version + run_metadata |
| signal_quality | `signal_quality.py` — 5 级信号质量枚举 |
| ToolDesignAuditor | `audit/tool_design_auditor.py` — 五类原则审计（不依赖 Agent runtime） |
| EvalQualityAuditor | `audit/eval_quality_auditor.py` — eval 结构完整性（不依赖 Agent runtime） |
| TranscriptAnalyzer | `diagnose/transcript_analyzer.py` — failure attribution（消费已记录的事实） |
| TraceSignalAnalyzer | `diagnose/trace_signal_analyzer.py` — trace 信号分析（消费已记录的事实） |
| MarkdownReport | `reports/markdown_report.py` — 报告渲染（消费 JSON artifact） |
| CostTracker | `reports/cost_tracker.py` — 成本聚合（不区分 fake/real 数据源） |

### 3.2 Core 不负责

- fake 数据、demo 样例、sample fixtures
- 真实 API key、真实 provider 调用、真实 LLM 决策
- 真实项目 runtime 接入
- 最终人工裁决（Core 提供证据，人做决策）

### 3.3 Core 禁止

- `import examples` — Core 不依赖教学样例
- 读取 `.env` — Core 不接触密钥
- 知道 OpenAI / Anthropic / DeepSeek — Core 不依赖具体 provider
- 散落 `if demo / if real` 分支 — Core 对两套材料一视同仁
- 为 demo 方便改变 contract — demo 适应 Core，不是 Core 迁就 demo
- 为 real complexity 污染 demo path — real 通过独立模块接入

## 4. What belongs to Demo

Demo 负责用假材料跑通 Core Flow，证明 Core 的流程和契约是可工作的。

### 4.1 Demo 负责

- 使用 examples/ 下的假材料跑通 Core Flow
- 教学和 smoke test
- baseline deterministic checks（RuleJudge）
- 帮用户理解 report 和 human review 的工作流
- 让新用户在 5 分钟内看到端到端闭环

### 4.2 Demo 组件

| 组件 | 路径 | 说明 |
|------|------|------|
| MockReplayAdapter | `agents/mock_replay_adapter.py` | good/bad 分支回放 |
| TranscriptReplayAdapter | `agents/transcript_replay_adapter.py` | 历史轨迹重放 |
| RuleJudge | `judges/rule_judge.py` | deterministic baseline，本身是 Core 接口的实现 |
| RuleJudgeProvider | `judges/provider.py` | RuleJudge 的 provider 包装 |
| RecordedJudgeProvider | `judges/provider.py` | 从 fixture 回放预录判定 |
| CompositeJudgeProvider | `judges/provider.py` | 多 advisory 聚合投票 |
| JudgePromptAuditor | `audit/judge_prompt_auditor.py` | judge prompt 安全/格式审计 |
| Bootstrap/Scaffold | `scaffold/` | AST 扫描生成 draft tools.yaml |
| examples/ | `examples/` | 教学样例数据 |
| FakeTransport | `judges/provider.py` | fake HTTP transport (CI safe) |

### 4.3 Demo 不负责

- 真实 Agent 评测
- 真实 LLM judge
- 真实项目 runtime 接入
- 真实 cost / latency evidence
- 生产 benchmark

### 4.4 Demo 约束

- Demo 可以复用 Core，但不能决定 Core 的设计
- Demo 不应该成为 README 和 docs 的主线（主线是 Core）
- Demo PASS/FAIL 必须标注 `signal_quality: tautological_replay`

## 5. What belongs to Real Integration

Real Integration 未来负责接入真实世界：真实 Agent runtime、真实 LLM judge、
真实 cost/latency、真实 evidence store。

### 5.1 Real Integration 组件（future / planned）

| 未来模块 | 状态 | 说明 |
|---------|------|------|
| RealAgentAdapter | ❌ not supported | 调用真实 LLM agentic loop |
| ProviderConfig | ❌ not supported | model / API key / base URL / budget |
| JudgeProvider (live LLM) | ❌ not supported | 语义评分替代 deterministic rules |
| EvidenceStore | ❌ not supported | 结构化证据存储与追溯 |
| LiveTransport (verified) | ⚠️ code exists, unverified | LiveAnthropicTransport 从未对真实端点验证 |
| ReviewWorkflow | ❌ not supported | 从人工 Review 到自动化决策 |

### 5.2 Real Integration 必须

- 显式 opt-in（`--live --confirm-i-have-real-key`）
- 不默认读取 `.env`
- 不默认调用真实 API
- 不默认消费 token
- 不自动把 LLM judge 输出当最终结论
- 不污染 Demo path

### 5.3 Real Integration 接入方式

所有 Real 组件通过 **Protocol 接口** 接入 Core，不修改 Core 代码：

```
Core: AgentAdapter Protocol
  ├── Demo: MockReplayAdapter
  └── Real: RealAgentAdapter (future)

Core: JudgeProvider Protocol
  ├── Demo: RuleJudgeProvider / RecordedJudgeProvider / CompositeJudgeProvider
  └── Real: OpenAIJudgeProvider / AnthropicJudgeProvider (future)

Core: ToolExecutor Protocol
  ├── Current: PythonExecutor
  └── Future: MCPExecutor / HTTPExecutor / ShellExecutor
```

## 6. Shared contracts

| Contract | 定义位置 | Demo 实现 | Real 实现 (future) |
|----------|---------|----------|-------------------|
| AgentAdapter | `agent_adapter_base.py` | MockReplayAdapter, TranscriptReplayAdapter | RealAgentAdapter |
| JudgeProvider | `judges/provider.py` | RuleJudgeProvider, RecordedJudgeProvider, CompositeJudgeProvider | AnthropicJudgeProvider, OpenAIJudgeProvider |
| ToolExecutor | `tools/executor_base.py` | PythonExecutor | MCPExecutor, HTTPExecutor, ShellExecutor |
| ToolRegistry | `tools/registry.py` | (shared) | (shared) |
| RunRecorder | `recorder/run_recorder.py` | (shared) | EvidenceStore |
| EvalRunner | `runner/eval_runner.py` | (shared) | (shared) |

## 7. Divergence points

| 维度 | Demo | Real (future) |
|------|------|---------------|
| Agent 行为来源 | mock 回放（good/bad 分支） | 真实 LLM agentic loop |
| Tool 执行 | PythonExecutor（本地函数调用） | 可扩展 executor |
| Judge 判定 | deterministic RuleJudge + fake providers | LLM judge + RuleJudge baseline |
| signal_quality | tautological_replay / recorded_trajectory | real_agent |
| cost/latency | advisory-only (`estimated_cost_usd` 永远 null) | 真实账单 |
| evidence | 10 个本地 JSON/JSONL artifact | EvidenceStore（结构化存储与追溯） |
| 安全模型 | 离线、不联网、零密钥 | 双标志 opt-in + env var |

## 8. Forbidden dependencies

```
✅ 允许的依赖方向：
   Demo ──→ Core
   Real ──→ Core

❌ 禁止的依赖方向：
   Core ──→ Demo      (Core 不能 import MockReplayAdapter)
   Core ──→ Real      (Core 不能 import LiveAnthropicTransport)
   Demo ──→ Real      (Demo 不能 import RealAgentAdapter)
   Real ──→ Demo      (Real 不能 import examples/)
```

当前违规：`cli.py` 中 `run` 命令直接 `from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter`。
这是 Demo → CLI 的 hard-wire，CLI 本身作为 Core 的装配层不应硬编码 Demo adapter。
修复方式（future）：CLI 接受 `--adapter` 参数或通过 project.yaml 配置 adapter 类型，
默认可暂时保持 MockReplayAdapter（backward-compat），但必须支持注入。

## 9. Configuration boundary

| 配置类型 | 文件 | 归属 |
|---------|------|------|
| 项目元数据 | `project.yaml` | Core |
| 工具契约 | `tools.yaml` | Core |
| Eval 用例 | `evals.yaml` | Core |
| Provider 配置 | `provider.yaml` (future) | Real Integration |
| API key / base URL | env var（`ANTHROPIC_API_KEY` 等） | Real Integration |
| Budget / pricing | `project.yaml` 内嵌 | Core（格式）+ Real（实际值） |
| Mock path | CLI `--mock-path good|bad` | Demo |

Core 配置（project.yaml / tools.yaml / evals.yaml）不应包含 provider-specific
字段（api_key、base_url、model）。这些字段属于 Real Integration 配置，
未来通过独立文件或 env var 注入。

## 10. Testing boundary

| 测试类型 | 证明什么 | 不证明什么 |
|---------|---------|-----------|
| Demo tests | demo 能跑通 Core Flow | 真实 Agent 能力 |
| Contract tests | Core 对象和接口稳定 | 实现正确性 |
| Real integration tests | 真实 LLM 调用正确 | —（未来，需显式 opt-in） |
| Doc consistency tests | 文档引用不腐烂 | 文档内容正确 |

测试约束：
- Demo tests 不能因为 demo 方便而迫使 Core 迁就 demo
- Contract tests 必须能在 CI（0 联网）中跑
- Real integration tests 必须显式 opt-in，不能默认跑
- 不能为了 test suite 变绿而把 strict xfail 转正或删除

## 11. How future Coding Agents should modify this project

### 11.1 修改 Core 时

1. Core 修改只影响 contract / flow / spec / artifact schema
2. 如果修改了 Protocol，必须同步更新所有实现（Demo + 未来的 Real）
3. Core 不能新增对 examples/ 的依赖
4. Core 不能新增对 `.env` / API key / 具体 provider 的依赖

### 11.2 新增 Demo 时

1. Demo 组件放在现有 `agents/` / `judges/` 等目录中，通过命名约定区分
   （`mock_*`、`fake_*`、`recorded_*`）
2. 新增 Demo 必须实现对应的 Core Protocol
3. Demo 的 `SIGNAL_QUALITY` 必须诚实声明

### 11.3 新增 Real 时

1. Real 组件通过独立的 Protocol 实现接入，**不修改 Core**
2. Real 组件必须在模块 docstring 中声明 opt-in 要求
3. Real 组件不能自动读取 `.env` 或调用外部 API（除非显式 opt-in）
4. Real 测试必须标记 `@pytest.mark.real_integration`，CI 默认不跑

### 11.4 修改 CLI 时

1. CLI 只做装配，不写业务逻辑
2. 新增 adapter 类型时，CLI 应支持注入而非硬编码
3. `--live` 标志触发时，必须检查 `--confirm-i-have-real-key` 双标志

### 11.5 修改 docs 时

1. 更新 `CURRENT_IMPLEMENTATION.md` 的实现状态矩阵
2. 更新 `HEADLESS_HARNESS_MODEL.md` 如涉及执行模型变更
3. 更新本文件如涉及边界变更
4. 运行 doc consistency tests 确认无死链
