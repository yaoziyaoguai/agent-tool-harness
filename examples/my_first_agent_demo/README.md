# Level 3 my-first-agent Demo Adapter

> **定位：** Example / dogfood case——不是推荐的主路径，不要求 agent-tool-harness
> 为每个 Agent 写专用 wrapper。推荐用户优先使用外部 runner + TraceImportAdapter。
> 详见 [docs/EXTERNAL_RUNNER_WORKFLOW.md](../../docs/EXTERNAL_RUNNER_WORKFLOW.md)。

C10 Level 3 local-only wrapper dogfood：将 my-first-agent 的 safe local demo
（`agent/local_demo.py` → `run_local_demo()`）接入 agent-tool-harness 的
CLIAgentAdapter → TraceImportAdapter → CoreEvaluation 闭环。

> **Dogfood Level**: Level 3 — Real Local Agent Opt-in Wrapper Dogfood
> 详见 [docs/DOGFOODING.md](../../docs/DOGFOODING.md)

## 架构边界

- **adapter.py**: thin wrapper——读取 ScenarioSpec JSON input，调用 my-first-agent
  的 `run_local_demo()`，把 `DemoResult` 转换为 native ExecutionTrace JSON。
- 不修改 my-first-agent。
- 不读 .env / agent_log.jsonl / sessions/ / runs/。
- 不联网、不调用真实 LLM/API。

## 环境策略（Level 3 安全边界）

adapter wrapper 遵循 minimal 环境策略：

| 约束 | 值 | 说明 |
|------|-----|------|
| `env_policy` | `"minimal"` | 子进程仅继承 PATH / HOME / TMPDIR / TEMP / TMP，不继承完整宿主环境 |
| `allow_shell` | `False` | 禁止 shell 注入，command 强制使用 `list[str]` |
| `timeout_seconds` | `300.0`（默认） | 硬安全边界，超时即杀 |
| 读取 .env | **否** | 无 `dotenv` / `load_dotenv` |
| 继承宿主环境 | **否** | `env_policy="minimal"` 确保不泄漏 API key / 数据库密码等 |
| 调用真实 LLM/API | **否** | `run_local_demo()` 永远使用 FakeProvider |
| 联网 | **否** | 零 HTTP/socket 调用 |
| 修改 my-first-agent | **否** | 只通过 `sys.path` 导入，`tempfile.mkdtemp()` 作为 workspace |

这是 **Level 3 local-only wrapper dogfood**，不是 Level 4A（real LLM judge opt-in），
也不是 Level 4B（agent-self-improvement loop）。

## 用法

### 前提

设置 `MY_FIRST_AGENT_PATH` 环境变量指向 my-first-agent 项目根目录：

```bash
export MY_FIRST_AGENT_PATH=/path/to/my-first-agent
```

### 1. 直接运行 adapter

```bash
echo '{"scenario_id":"demo-test","goal":"create a demo note about testing"}' > /tmp/input.json
python examples/my_first_agent_demo/adapter.py \
  --input /tmp/input.json \
  --trace-out /tmp/trace.json
cat /tmp/trace.json
```

### 2. 通过 CLIAgentAdapter + Core Flow 运行

```python
from agent_tool_harness.assembly import build_cli_agent_core_flow
from agent_tool_harness.cli_agent import CLIAgentAdapterConfig
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.config.tool_spec import ToolSpec

tool_specs = [
    ToolSpec(
        name="write_demo_note",
        namespace="demo",
        version="1.0",
        description="写入 demo note",
        when_to_use="需要写入 demo note 时",
        when_not_to_use="不需要时",
        input_schema={
            "type": "object",
            "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"],
        },
        output_contract={"evidence": "list"},
        token_policy={"max_tokens_per_call": 1000},
        side_effects={"destructive": False},
        executor={"type": "python", "module": "write_demo_note"},
    ),
]

eval_spec = EvalSpec(
    id="level3-dogfood",
    name="Level 3 local-only dogfood",
    category="integration",
    split="test",
    realism_level="mock",
    complexity="low",
    source="test",
    user_prompt="create a demo note about Level 3 dogfood verification",
    initial_context={},
    expected_tool_behavior={"required_tools": ["demo.write_demo_note"]},
    judge={
        "rules": [
            {"type": "must_call_tool", "tool": "demo.write_demo_note"},
            {"type": "must_use_evidence"},
        ]
    },
    verifiable_outcome={"expected_root_cause": "demo completed"},
    success_criteria=["结论引用证据"],
)

result = build_cli_agent_core_flow(
    tool_specs=tool_specs,
    eval_spec=eval_spec,
    cli_agent_config=CLIAgentAdapterConfig(
        command=[
            "python", "examples/my_first_agent_demo/adapter.py",
            "--input", "{input_path}",
            "--trace-out", "{trace_output_path}",
        ],
        working_dir=".",
        # Level 3 安全边界：minimal env，不继承宿主环境
        env_policy="minimal",
        allow_shell=False,
        timeout_seconds=300.0,
    ),
    output_dir="/tmp/agent2harness-level3-dogfood",
)
print(f"passed: {result.eval_result.passed}")
```

> **注意**：示例中使用 `env_policy="minimal"`。如果 adapter 需要 `MY_FIRST_AGENT_PATH`
> 环境变量，需使用 `env_policy="inherit"` 或在 `env_allowlist` 中显式列出。
> 示例中未写入任何真实 API key、base_url 或 model 名称。

## Signal Quality

`recorded_trajectory`——wrapper 调用真实 my-first-agent 的 `run_local_demo()`，
trace 来自真实本地执行（my-first-agent 自身使用 FakeProvider），不是 mock replay。

## ReviewDecision

不自动生成——必须由人工 Reviewer 显式创建。

## Level 3 声明

- 不读取 .env
- 不联网
- 不调用真实 LLM/API
- 不继承完整宿主环境（env_policy=minimal）
- 不修改 my-first-agent
- wrapper 只做 schema 适配
- my-first-agent 自身走 FakeProvider，不调用真实 LLM/API
