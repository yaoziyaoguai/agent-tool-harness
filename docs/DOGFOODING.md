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

### Level 3: Real Local Agent Opt-in Dogfood

**状态**: ❌ 尚未实施。

**含义**: 用户明确指定一个真实本地 Agent 项目和命令，Agent2Harness 通过
CLIAgentAdapter 运行它并收集 trace。

**前置条件**（缺一不可）:
1. 用户显式授权
2. 用户提供 `--agent-config` 指向真实项目 YAML
3. 用户显式配置 `working_dir`
4. 用户提供 `--env-file` 或 `--allow-os-env`
5. 用户理解真实 Agent 会执行 subprocess 并可能访问本地文件

**本轮不做**。必须等用户明确授权后才推进。

---

### Level 4: Real LLM / External API Dogfood

**状态**: ❌ 尚未实施。

**含义**: 真实 Agent 内部可能调用真实 LLM/API。需要完整的安全模型。

**前置条件**（缺一不可）:
1. Level 3 所有前置条件
2. `--live --confirm-i-have-real-key` 双标志
3. 用户已配置 provider API key
4. 用户理解 API 调用会产生费用

**本轮不做**。必须等用户手动配置 key 并明确授权。

---

## 核心不变式

所有 dogfood level 共同遵守：
- ReviewDecision 不由机器自动生成
- RuleJudge 决定 deterministic passed
- JudgeFinding 为 advisory only
- signal_quality 必须在报告中显式披露
- 不自动读取 .env（除非用户显式 opt-in）
- 不自动调用外部 API
