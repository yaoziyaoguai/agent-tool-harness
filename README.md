# Agent Tool Harness

[English](README.en.md)

**Agent Tool Harness 是一个本地 Agent tool-use trace 检查、评测与报告生成工具。**

它不负责运行你的 Agent。它只处理外部 Agent / 脚本 / CI 产出的 trace JSON 日志，做确定性检查和评测，最后生成可读报告。

## 它解决什么问题

用你自己的 Agent runner 跑完 Agent 后，你可能会问：

- 我的 Agent 调工具有没有调对？call_id 是否一一配对？
- tool spec 写得好不好？会不会让 Agent 容易用错？
- tool response 有没有足够上下文？错误信息能不能帮助定位问题？
- 有没有工具名重叠、命名空间混乱的问题？
- 最后能不能生成一份可读的评测报告，方便 PR review 或 CI 消费？

agent-tool-harness 就是回答这些问题的。

## 核心流程

```
你的 Agent / 脚本 / CI
  → 产出 tool-use trace / JSON log
    → agent-tool-harness 导入
      → 确定性检查 + 评测
        → Markdown / JSON 报告
```

## 主要能力

**Trace 导入：**
- native trace JSON 直接导入
- simple_mapping 字段映射，适配不同 Agent 的输出格式
- trace 诊断：字段覆盖率、类型检查、置信度评估

**确定性检查（37+ 规则，不需要 LLM）：**
- 工具使用正确性 — call_id 唯一性、调用/结果配对、参数有效性
- 工具规格质量 — description 完整度、input_schema、output contract
- 工具工效学 — 命名清晰度、命名空间重叠、wrapper 检测
- 工具响应质量 — output 信号强度、错误可行动性、上下文充分性

**CLI 审计工具：**
- `audit-tools` — 工具契约确定性启发式审计
- `audit-evals` — eval 质量审计
- `audit-judge-prompts` — judge prompt 安全审计

**LLM 辅助判断（可选，默认不启用）：**
- 6 个 advisory 维度
- RuleFinding 仍然决定 pass/fail，JudgeFinding 仅供参考
- 需要显式 opt-in：`--live --confirm-i-have-real-key --env-file`

**v3.1 报告洞察：**
- **Scorecard** — 一眼看懂通过/不通过，error/warning/advisory 分桶
- **Metrics** — 工具调用次数、成功率/错误率、响应大小
- **Findings 分组** — 按严重度、类别、工具分组，快速定位问题
- **Recommendations** — 去重排序的可行动修复建议
- Markdown + JSON 双格式输出

## 它不是什么

- 它不运行你的 Agent — 你需要用自己的 runner 产出 trace
- 它默认不调真实 LLM — 确定性规则足够决定 pass/fail
- 它不会自动改你的工具 — 不做 optimizer，不修 prompt
- 它不会自动生成 Review 结论 — 人工 Review 是显式且必须的

## 快速开始

```bash
git clone https://github.com/yaoziyaoguai/agent-tool-harness.git
cd agent-tool-harness
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 验证安装
python -m pytest tests/ -q
```

### 导入一条 trace 并评测

不需要 .env，不需要 API key，不需要联网：

```bash
python -c "
from agent_tool_harness.trace_import import import_trace_as_evidence
from agent_tool_harness.core_evaluation import CoreEvaluation, EvalSpec

# 导入 native-schema trace
evidence = import_trace_as_evidence('examples/trace_import/native_trace.json')
trace = evidence.trace
print(f'已导入: scenario={trace.scenario_id}')

# 运行确定性检查（不需要 LLM）
eval_spec = EvalSpec(
    id=trace.scenario_id, name=trace.scenario_id,
    category='knowledge_search', split='dev', realism_level='recorded',
    complexity='simple', source='external_runner',
    user_prompt='Find root cause and recommendation',
    initial_context={}, verifiable_outcome={},
    success_criteria=['identify root cause', 'provide recommendation'],
    expected_tool_behavior={}, judge={},
)
result = CoreEvaluation().evaluate(evidence, eval_spec)
print(f'评测通过: {result.passed}')
for f in result.findings:
    print(f'  [{f.severity}] {f.message[:140]}')
"
```

### 跑一遍 mock replay demo

```bash
# 1) 审计工具契约
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out /tmp/harness-demo/audit

# 2) 从工具生成候选 eval
python -m agent_tool_harness.cli generate-evals \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --source tools \
  --out /tmp/harness-demo/candidate_evals.yaml

# 3) 候选 eval 审核后转正
python -m agent_tool_harness.cli promote-evals \
  --candidates /tmp/harness-demo/candidate_evals.yaml \
  --out /tmp/harness-demo/evals.yaml

# 4) 审计刚转正的 eval 质量
python -m agent_tool_harness.cli audit-evals \
  --evals /tmp/harness-demo/evals.yaml \
  --out /tmp/harness-demo/audit-evals

# 5) mock replay — good path（预期 PASS）
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out /tmp/harness-demo/good --mock-path good

# 6) mock replay — bad path（预期 FAIL，验证 judge 没有退化）
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out /tmp/harness-demo/bad --mock-path bad

# 7) 查看报告
cat /tmp/harness-demo/good/report.md
```

## 报告长什么样

v3.1 报告包含以下段落：

```
## Scorecard
| 字段 | 值 |
|------|-----|
| 通过 | 不通过 |
| 错误 | 2 |
| 警告 | 4 |

## Metrics
工具调用: 5 | 成功率: 60% | 错误率: 40%

## Top Issues
1. [critical] 缺少 arguments — 工具: search
2. [high] 输出信号过低 — 工具: read

## Recommendations
1. search: 确保每次调用都传入必需的 arguments 参数
2. read: 检查工具返回的 output 是否包含足够上下文
```

## 什么时候需要真实 LLM judge

默认不需要。确定性 RuleFinding 已经足够决定 pass/fail。

真实 LLM judge 是可选功能，仅在你想获得额外的 advisory 信号时启用。启用后 JudgeFinding 仍然是参考性质，不改变 pass/fail 结果。

```bash
# 启用真实 LLM judge（需要显式三重 opt-in）
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out /tmp/harness-demo/llm-judge \
  --core-flow --judge-provider llm \
  --llm-config examples/llm_providers.example.yaml \
  --llm-provider openai-compatible \
  --env-file .env --live --confirm-i-have-real-key
```

## 文档导航

| 我想... | 看这里 |
|---------|--------|
| 快速上手 | [QUICKSTART](docs/QUICKSTART.md) |
| 了解完整使用流程 | [USER_GUIDE](docs/USER_GUIDE.md) |
| 看懂 v3.1 报告 | [REPORT_GUIDE](docs/REPORT_GUIDE.md) |
| 配置真实 LLM judge | [PROVIDER_CONFIG](docs/PROVIDER_CONFIG.md) |
| 查看当前实现状态和限制 | [CURRENT_IMPLEMENTATION](docs/CURRENT_IMPLEMENTATION.md) |
| 了解架构或参与开发 | [DEVELOPER_GUIDE](docs/DEVELOPER_GUIDE.md) |
| 查看全部文档 | [INDEX](docs/INDEX.md) |

## 设计渊源

本项目对齐 Anthropic Engineering 的 [Writing effective tools for agents — with agents](https://www.anthropic.com/engineering/writing-tools-for-agents) 方法论，聚焦 tool-use inspection — 对 Agent tool-use 日志和工具设计质量做检查、评测和报告。

---

> **透明度声明**：当前 mock replay 的 signal_quality 为 `tautological_replay`，不是真实 Agent 能力信号。不支持的功能详见 CURRENT_IMPLEMENTATION.md。
