# Dogfooding

> 本文档定义 Agent2Harness 项目的 dogfood 分层和对应安全边界。
> Dogfood = "吃自己的狗粮"，即在实际使用中验证 harness 自身。

---

## Dogfood 分层

### Level 0: Unit / Integration Tests

**状态**: ✅ C9 已覆盖（97 tests: 76 CLI agent + 21 core flow integration）。

**含义**: 使用 pytest + tmp_path + fake CLI agent 验证每个模块的独立正确性。

**安全边界**: 零网络、零文件系统副作用（用 tmp_path）、deterministic。

---

### Level 1: Fake CLI Agent Dogfood

**状态**: ✅ 已完成（2026-05-13）。

**含义**: 使用 `examples/cli_agent_fake/fake_agent.py`，通过真实的
CLIAgentAdapter → TraceImportAdapter → CoreEvaluation → Report 链路跑闭环。
fake agent 是 deterministic Python 脚本，不调用真实 LLM，不读 .env。

**目标**: 验证 harness 自身可用——所有 Core Flow 组件能协同工作。

**如何运行**:

```bash
# 方式 1: 直接通过 assembly Python API
python -c "
from agent_tool_harness.assembly import build_cli_agent_core_flow
from agent_tool_harness.cli_agent import CLIAgentAdapterConfig
from agent_tool_harness.config.loader import load_tools, load_evals

tools = load_tools('examples/cli_agent_fake/project.yaml')
evals = load_evals('examples/cli_agent_fake/evals.yaml')

for eval_spec in evals:
    result = build_cli_agent_core_flow(
        tool_specs=tools,
        eval_spec=eval_spec,
        cli_agent_config=CLIAgentAdapterConfig(
            command=['python', 'examples/cli_agent_fake/fake_agent.py',
                     '--input', '{input_path}',
                     '--trace-out', '{trace_output_path}'],
            working_dir='.',
        ),
        output_dir='/tmp/agent2harness-dogfood',
    )
    print(f'eval {eval_spec.id}: passed={result.eval_result.passed}')
"
```

**安全边界**: 零网络、零 .env、零真实私密数据、deterministic。

**已知局限**: fake agent 是 mock 材料，PASS/FAIL 不代表真实 Agent 能力。
signal_quality = `recorded_trajectory`。

---

### Level 2: Toy Local CLI Agent Dogfood

**状态**: ✅ 已完成（2026-05-13）。

**含义**: 使用 `examples/cli_agent_toy/toy_agent.py`——一个非私密、最小 toy agent，
通过 CLI 命令运行。toy agent 读取 scenario input，调用可用工具（deterministic
Python 逻辑，非 LLM），产出 native trace JSON。

**目标**: 验证"外部 CLI agent 接入"模式——命令来自独立文件而非 inline Python，
但所有行为仍 deterministic。

**如何运行**:

```bash
# 直接运行 toy agent
echo '{"scenario_id":"toy-test","available_tools":["knowledge.search","trace.lookup"]}' \
  > /tmp/toy-input.json
python examples/cli_agent_toy/toy_agent.py \
  --input /tmp/toy-input.json \
  --trace-out /tmp/toy-trace.json
cat /tmp/toy-trace.json
```

**安全边界**: 零网络、零 .env、零真实私密数据、deterministic。

**与 Level 1 区别**: Level 1 使用 fake agent（只调所有 available tools），
Level 2 使用 toy agent（根据 scenario goal 决定调哪些工具），两者都是 deterministic，
但 toy agent 模拟了稍微更真实的"根据目标选择工具"行为。

---

### Level 3: Real Local Agent Opt-in Wrapper Dogfood

**状态**: ✅ 已完成（2026-05-13）。

**含义**: 使用 `examples/my_first_agent_demo/adapter.py` thin wrapper，将
my-first-agent 的 `run_local_demo()`（FakeProvider）接入 CLIAgentAdapter →
TraceImportAdapter → CoreEvaluation → Report 闭环。

**Agent 侧**: my-first-agent 自身仍使用 FakeProvider，不读 .env，不联网，不调用真实 LLM/API。

**安全边界**: wrapper 通过 `MY_FIRST_AGENT_PATH` env var 定位目标 Agent，
使用 `tempfile.mkdtemp()` 作为 workspace，不修改 my-first-agent。

**已知局限**: wrapper 依赖 my-first-agent 本地路径；trace 来自 `recorded_trajectory`。

---

### Level 4A: Real LLM Judge Dogfood（agent-tool-harness 侧）

**状态**: ✅ 已完成（2026-05-13）。

**含义**: 仅 agent-tool-harness 的 LLM JudgeProvider 调用真实 LLM/API
（anthropic-compatible 或 openai-compatible）。Agent 侧（my-first-agent wrapper）
仍使用 FakeProvider，不读 .env，不联网。

**安全门控**: `--env-file` + `--live` + `--confirm-i-have-real-key` 缺一不可。

**已知结果**: RuleJudge passed，JudgeFinding 生成（advisory），
LLM transport bad_response（响应解析已知问题，不影响 passed）。

**关键约束**: JudgeFinding 为 advisory only；RuleJudge 仍决定 EvaluationResult.passed；
ReviewDecision 不自动生成。

---

### Level 4B: Target Agent Self Real Provider Dogfood

**状态**: ❌ **deferred**（暂停，非 blocking bug）。

**原因**: 目标 Agent（my-first-agent）目前还在开发中，尚未提供稳定的 headless CLI /
`--input` / `--trace-out` / native trace export / real provider opt-in contract。
这由目标 Agent 自身开发节奏决定，不是 agent-tool-harness 的问题。

**前置条件 — target-agent readiness checklist**（缺一不可）:

1. target agent 提供 headless non-interactive CLI（可 subprocess 调用）
2. target agent 接受 `--input`（或等价 input file）
3. target agent 产出 `--trace-out`（或等价 trace output file）
4. trace 为 native 或 simple_mapping 可导入格式
5. target agent 默认 provider 为 fake/local
6. real provider 需 `--live` + 二次确认
7. secret 仅在运行时加载，不打印 key / base_url / model
8. target agent 有 `--timeout` / `--max-steps` 硬边界
9. target agent 写入仅限受控 output dir
10. human review 保持显式（ReviewDecision 不自动生成）

**本轮不做**。等目标 Agent 满足以上条件后再推进。

---

## 核心不变式

所有 dogfood level 共同遵守：
- ReviewDecision 不由机器自动生成
- RuleJudge 决定 deterministic passed
- JudgeFinding 为 advisory only
- signal_quality 必须在报告中显式披露
- 不自动读取 .env（除非用户显式 opt-in）
- 不自动调用外部 API
