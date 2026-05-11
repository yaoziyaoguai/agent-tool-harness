# Tool Adapter Design（工具适配器模块设计）

> 本文档描述 agent-tool-harness 中 Tool Adapter（Agent 适配器 + 工具执行）的设计意图、协议、实现与注册机制。
> 在源码中，对应 `agents/` 子包 + `tools/` 子包。
>
> 面向读者：eval 设计者、Coding Agent、模块维护者。

---

## 一、模块目的

Tool Adapter 模块负责两件事：

1. **Agent Adapter**（`agents/`）——把 eval case 转成 Agent 的 tool-use 行为。当前只有 deterministic replay adapter，不调真实 LLM。
2. **Tool Execution**（`tools/`）——把 tool call 转成确定的 tool response。

两者通过 `ToolRegistry` 桥接：adapter 通过 registry 执行工具，registry 通过 executor 分发执行。

---

## 二、Agent Adapter（`agents/`）

### 2.1 协议：`AgentAdapter`（`agent_adapter_base.py`）

```python
class AgentAdapter(Protocol):
    SIGNAL_QUALITY: str = UNKNOWN  # 必须显式声明

    def run(
        self, case: EvalSpec, registry: ToolRegistry, recorder: RunRecorder
    ) -> AgentRunResult: ...
```

**架构边界**：
- 负责把 eval case 转成 Agent 行为和 tool calls
- 不负责执行工具细节（调用 `ToolRegistry.execute`）
- 不负责评判成败（RuleJudge 根据 recorder 证据判断）
- 必须显式声明 `SIGNAL_QUALITY`

### 2.2 信号质量披露

每个 adapter 必须声明自己的信号质量等级：

| Adapter | `SIGNAL_QUALITY` | 含义 |
|---------|-----------------|------|
| `MockReplayAdapter` | `tautological_replay` | 按 eval 自带的 `expected_tool_behavior` 反向回放——PASS 是"设计时的自我验证"，不代表工具对真实 Agent 好用 |
| `TranscriptReplayAdapter` | `recorded_trajectory` | 从真实 transcript JSONL 回放——PASS 是"历史轨迹可复现"，比 tautological_replay 强但仍不是真实 Agent |

如果没有真实 Agent 参与（`SIGNAL_QUALITY != real_agent`），报告必须显式标注这个限制。

### 2.3 `AgentRunResult` 数据类

```python
@dataclass
class AgentRunResult:
    eval_id: str
    final_answer: str
    tool_calls: list[dict[str, Any]]
    tool_responses: list[dict[str, Any]]
```

详细证据（transcript / tool_calls / tool_responses 的逐行事件）不放在这里，而是由 `RunRecorder` 写入 JSONL。

### 2.4 MockReplayAdapter（`mock_replay_adapter.py`）

**确定性 mock replay adapter**。

工作原理：
1. 读取 `case.expected_tool_behavior.required_tools`
2. 按 `case.expected_tool_behavior.tool_sequence`（若有）顺序调用工具
3. 从 `ToolRegistry` 中按名查找 tool → executor 执行 → 拿到 ToolExecutionResult
4. 通过 RunRecorder 记录每一步（call + response）
5. 最后合成 `final_answer`（基于 eval 的 verifiable_outcome）

**为什么必须声明 `tautological_replay`**：MockReplayAdapter 的 PASS 本质上是"eval 设计时的自我验证"——它在按 eval 自己写的 expected_tool_behavior 运行。真实 Agent 可能完全不走这条路。

### 2.5 TranscriptReplayAdapter（`transcript_replay_adapter.py`）

**从真实 transcript JSONL 回放**。

工作原理：
1. 读取预录的 `transcript.jsonl`（来自真实 Agent 的运行记录）
2. 按事件顺序回放 tool_calls
3. 对每个 tool_call，从 ToolRegistry 中执行对应工具获取 response（不同于 mock——这里是真实工具执行，只是 call 序列来自历史）
4. 记录到 RunRecorder

`SIGNAL_QUALITY = recorded_trajectory`：PASS 代表"历史轨迹在当前工具实现下可复现"，不是"真实 Agent 会这样做"。

---

## 三、Tool Execution（`tools/`）

### 3.1 ToolRegistry（`registry.py`）

**工具注册表**——adapter 通过它执行工具，而非直接调 Python 函数。

```python
class ToolRegistry:
    def __init__(self, tools: list[ToolSpec], executors: dict[str, ToolExecutor] | None = None)
    def get(self, name: str) -> ToolSpec
    def execute(self, name: str, arguments: dict[str, Any]) -> ToolExecutionResult
    def list_names(self) -> list[str]
```

**架构边界**：
- 负责按 name/qualified_name 查找工具，分发执行给对应 executor
- 不负责 Agent 决策
- 不负责审计工具设计
- 不负责 judge

**命名歧义治理**：
- `qualified_name` 必须唯一（重复 → `ToolRegistryError` 立即失败）
- 短名如果重复，禁止用短名调用（必须用 `namespace.name`）
- 不静默选择第一个——工具选择错误是 Agent eval 最重要的证据之一

**执行错误不抛给 runner**：
`execute` 把 registry 查找错误和 executor 执行错误都转成 `ToolExecutionResult(success=False)` 返回。这样 recorder 能留下真实的误调用证据，而 runner 不需要 try-catch 每条工具执行。

### 3.2 ToolExecutor 协议（`executor_base.py`）

```python
class ToolExecutor(Protocol):
    def execute(self, tool: ToolSpec, arguments: dict[str, Any]) -> ToolExecutionResult: ...

@dataclass
class ToolExecutionResult:
    success: bool
    content: dict[str, Any]      # 工具返回的内容（summary / evidence / next_action）
    error: str | None = None
    metadata: dict[str, Any]     # 额外元信息
```

### 3.3 PythonToolExecutor（`python_executor.py`）

当前唯一的 executor 实现。根据 `ToolSpec` 中的配置（`executor.module` + `executor.function`）动态加载 Python 函数并执行。

**安全契约**：
- executor 不执行用户脚本之外的任意代码
- 工具函数是用户项目自己写的 Python 函数
- scaffold 不 import 用户代码——只在 run 时由 EvalRunner/Adapter 通过 ToolRegistry 调用

### 3.4 未来扩展点

| Executor 类型 | 说明 | 状态 |
|--------------|------|------|
| `python` | 当前唯一实现 | ✅ 已实现 |
| `mcp` | MCP 协议工具执行器 | v3.0 backlog |
| `http` | HTTP API 工具执行器 | v3.0 backlog |
| `shell` | Shell 命令工具执行器 | v3.0 backlog |

---

## 四、核心输入

| 输入 | 来源 | 说明 |
|------|------|------|
| `EvalSpec` | `config/eval_spec.py` | eval 用例（adapter 读取 expected_tool_behavior） |
| `ToolSpec` 列表 | `config/tool_spec.py` | 工具契约（registry 建立索引） |
| `RunRecorder` | `recorder/run_recorder.py` | 适配器用它记录 transcript/tool_calls/tool_responses |
| `tool arguments` | adapter 在 `run()` 中构造 | 传给 `registry.execute(name, arguments)` 的参数 |
| transcript JSONL | `transcript.jsonl`（历史 run） | TranscriptReplayAdapter 的输入 |

---

## 五、核心输出

- `AgentRunResult` — 一次 adapter run 的摘要（eval_id + final_answer + tool_calls + tool_responses）
- `ToolExecutionResult` — 一次工具执行的结果（success + content + error + metadata）
- 通过 `RunRecorder` 写入的 raw JSONL（transcript / tool_calls / tool_responses）

---

## 六、关键接口

| 接口 | 位置 | 稳定性 |
|------|------|--------|
| `AgentAdapter` Protocol | `agents/agent_adapter_base.py:25` | 稳定 |
| `AgentRunResult` dataclass | `agents/agent_adapter_base.py:12` | 稳定 |
| `MockReplayAdapter` | `agents/mock_replay_adapter.py` | 稳定 |
| `TranscriptReplayAdapter` | `agents/transcript_replay_adapter.py` | 稳定 |
| `ToolExecutor` Protocol | `tools/executor_base.py:31` | 稳定 |
| `ToolExecutionResult` dataclass | `tools/executor_base.py:9` | 稳定 |
| `ToolRegistry` | `tools/registry.py:20` | 稳定 |
| `PythonToolExecutor` | `tools/python_executor.py` | 稳定 |

---

## 七、不负责什么

- ❌ 不决策 Agent 策略（adapter 是 replay，不走 LLM reasoning）
- ❌ 不审计工具设计（那是 `ToolDesignAuditor` 的职责）
- ❌ 不评判 Agent 成败（那是 `RuleJudge` 的职责）
- ❌ 不管理 executor 生命周期（当前 executor 是无状态的纯函数）
- ❌ 不做工具函数的输入校验（工具函数自身负责校验）
- ❌ 不做 MCP/HTTP/Shell executor（当前只有 Python）
- ❌ 不在 `registry.execute` 失败时抛异常给 runner（统一转成 ToolExecutionResult）

---

## 八、和其他模块的关系

```
config/eval_spec.py  →  EvalSpec（adapter 读取 expected_tool_behavior）
config/tool_spec.py  →  ToolSpec（registry 建立索引）
recorder/run_recorder.py  →  RunRecorder（adapter 写入 raw JSONL）
runner/eval_runner.py  →  EvalRunner（调用 adapter.run）
judges/rule_judge.py  →  RuleJudge（消费 AgentRunResult）
```

**依赖方向**：
```
EvalRunner → AgentAdapter → ToolRegistry → ToolExecutor → Python 工具函数
```

---

## 九、测试证明方式

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/test_mock_replay_*.py` 系列 | MockReplayAdapter 的 tool sequence 回放正确性 |
| `tests/test_transcript_replay_adapter.py` | TranscriptReplayAdapter 的 transcript 回放 |
| `tests/test_python_executor_*.py` | PythonToolExecutor 执行正确性 + 异常路径 |
| `tests/test_tool_registry_*.py` 系列 | ToolRegistry 的命名歧义 / 重复 qualified_name / 未知工具 / 不支持 executor |
| `tests/test_artifact_consistency.py` | AgentRunResult → recorder → JSONL 的一致性 |

---

## 十、后续实现或重构建议

1. **MCP Executor**（v3.0）：实现 `McpToolExecutor`，支持通过 MCP 协议调外部工具。需要管理子进程生命周期 + stdio transport。

2. **真实 LLM Agent Adapter**（v3.0）：实现 `OpenAIAgentAdapter` / `AnthropicAgentAdapter`，让真实 LLM 根据 tool descriptions 做 tool-use 决策。需要在 adapter 层落地 prompt 组装、tool use loop、异常治理。

3. **ToolExecutor 热加载**：当前 executor 在 ToolRegistry 构造时注入。可考虑 executor 注册中心，让用户通过 `tools.yaml` 声明 executor type 而无需改 Python 代码。

4. **ToolSpec.side_effects 强制声明**：当前 `must_not_modify_before_evidence` 规则部分靠工具名 token 启发式判断 mutating。应要求所有工具在 `tools.yaml` 中显式声明 `side_effects.destructive`。

---

## 十一、Review Checklist（审查清单）

Tool Adapter 模块变更 Review 时，检查以下项：

- [ ] 新增 Adapter 是否显式声明 `SIGNAL_QUALITY`（不允许为 UNKNOWN）
- [ ] 新增 Adapter 是否仅通过 `ToolRegistry.execute` 执行工具（不允许绕过 registry 直接调 Python 函数）
- [ ] 新增 Adapter 是否通过 `RunRecorder` 记录所有 tool_call + tool_response
- [ ] 新增 Executor 是否实现 `ToolExecutor` Protocol
- [ ] `ToolExecutionResult` 的 `content` 是否包含 `evidence` 字段（供 `must_use_evidence` 规则消费）
- [ ] `ToolRegistry` 命名歧义处理是否正确（qualified_name 重复 → 立即失败；短名重复 → 禁止短名调用）
- [ ] `ToolRegistry.execute` 查找错误是否转成 `ToolExecutionResult(success=False)` 而不是抛异常
- [ ] TranscriptReplayAdapter 回放时 `tool_responses` 是否来自真实工具执行（不直接用 transcript 中的旧 response）
