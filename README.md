# Agent Tool Harness

[English](README.en.md)

**面向 Agent 工具调用质量的离线评测与报告工具。**

消费已有 trace / JSON log / eval result，做确定性检查和评测，生成可读报告。不运行目标 Agent，不调用真实 LLM（默认），不自动修改工具。

> 最新稳定发布是 `v3.6.1`。这是 post-v3.6 architecture quality patch，不包含新 Agent runner、真实 LLM 调用或 v3.7 功能。

## 解决什么问题

| 你的问题 | 对应能力 |
|---------|---------|
| 我的 Agent 调工具有没有调对？ | v3.1 确定性检查 + 报告洞察 |
| 任务真的完成了吗？ | v3.2 任务级评测 |
| 多条 trace 全局情况怎样？ | v3.3 Eval Suite 聚合 |
| 改完 tool spec 后有没有引入回归？ | v3.4 Regression Comparison |
| Agent 为什么反复重试？工具返回是否浪费上下文？ | v3.5 Transcript + Context 分析 |
| 工具组合设计有没有结构性问题？怎么改进？ | v3.6 Portfolio Review + Improvement Brief |

## 能力链路

```
trace / JSON log
  → v3.1 导入 + 确定性检查 (37+ rules) + 报告洞察 (Scorecard/Metrics/Recommendations)
    → v3.2 任务级评测 (TaskOutcome: success/failed/inconclusive)
      → v3.3 Suite 聚合 (task_success_rate + top issues)
        → v3.4 回归对比 (baseline vs candidate)
        → v3.5 转录困惑 + 上下文效率分析 (11 种 pattern)
        → v3.6 工具组合评审 + 改进建议 (5 类检查 + evidence brief)
```

## 核心流程

```
你的 Agent / 脚本 / CI
  → 产出 tool-use trace / JSON log
    → agent-tool-harness 导入
      → 确定性检查 + 评测
        → Markdown / JSON 报告
```

## 主要能力

### v3.1 报告洞察

- **Scorecard** — 一眼看懂通过/不通过
- **Metrics** — 工具调用次数、成功率/错误率、响应大小
- **Findings 分组** — 按严重度、类别、工具分组
- **Recommendations** — 去重排序的可行动修复建议
- Markdown + JSON 双格式输出

### v3.2 任务级评测

- **EvalCase / ExpectedOutcome** — 声明式任务预期结果定义
- **6 种 Verifier** — fact、field、pattern、tool_call、no_tool_call、llm（advisory）
- **TaskOutcome** — success / failed / inconclusive 三态判定

### v3.3 Eval Suite 聚合

- **EvalSuite manifest** — YAML 驱动的多 case / 多 trace 编排
- **SuiteScorecard** — suite 级 pass/fail + task_success_rate
- **SuiteMetrics** — 跨 case 聚合指标

### v3.4 回归对比

- baseline vs candidate 全方位对比（metrics / findings / task outcomes / suite）
- 5 种自动回归警告，阈值可配置
- 只消费已有评测结果，不运行 Agent

### v3.5 Transcript + Context 分析

- **6 种 Agent 困惑模式** — 重复重试、工具切换、参数微调、无恢复、无支撑回答、搜索范围扩大
- **5 种上下文浪费信号** — 响应膨胀、缺少分页、低价值大字段、截断无提示等
- 所有分析 deterministic，不调 LLM

### v3.6 工具组合评审 + 改进建议

- **5 类结构检查** — 命名空间一致性、工具重叠、浅层包装、缺失高层工具、资源分组
- **Improvement Brief** — 含 evidence 引用的 per-tool + cross-tool 改进建议卡片
- 不自动修改 ToolSpec

### 基础设施

- **Trace 导入** — native JSON + simple_mapping 字段映射 + 诊断
- **确定性检查** — 37+ 规则，零网络依赖，决定 pass/fail
- **CLI 审计** — `audit-tools`、`audit-evals`、`audit-judge-prompts`
- **LLM judge（可选）** — 6 advisory 维度，默认不启用，需显式三重 opt-in

## 它不是什么

- **不运行你的 Agent** — 你需要用自己的 runner 产出 trace
- **默认不调真实 LLM** — 确定性规则足够决定 pass/fail
- **不自动改你的工具** — recommendations / improvement brief 是建议，不是自动修复
- **不是 LLM eval benchmark** — 不替代人工判断

## 安全边界

- 不运行目标 Agent
- 不调用真实 LLM by default
- 不读取 .env（除非显式 opt-in）
- 不自动修改 tool spec
- Signal quality 明确声明（mock replay = `tautological_replay`，不是真实 Agent 信号）

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

v3.2-v3.6 新增的报告段落（Task Outcome、Suite Result、Regression、Transcript/Context Analysis、Portfolio Review / Improvement Brief）详见 [REPORT_GUIDE](docs/REPORT_GUIDE.md)。

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
| 5 分钟上手 | [QUICKSTART](docs/QUICKSTART.md) |
| 了解完整使用流程 | [USER_GUIDE](docs/USER_GUIDE.md) |
| 看懂报告 | [REPORT_GUIDE](docs/REPORT_GUIDE.md) |
| 浏览所有示例 | [examples/README.md](examples/README.md) |
| 配置 LLM judge（可选） | [PROVIDER_CONFIG](docs/PROVIDER_CONFIG.md) |
| 了解架构或参与开发 | [DEVELOPER_GUIDE](docs/DEVELOPER_GUIDE.md) |
| 查看当前实现状态 | [CURRENT_IMPLEMENTATION](docs/CURRENT_IMPLEMENTATION.md) |
| 全部文档索引 | [INDEX](docs/INDEX.md) |
| 英文文档 | [README.en.md](README.en.md) |

## 设计渊源

本项目对齐 Anthropic Engineering 的 [Writing effective tools for agents — with agents](https://www.anthropic.com/engineering/writing-tools-for-agents) 方法论，聚焦 tool-use inspection — 对 Agent tool-use 日志和工具设计质量做检查、评测和报告。

---

> **透明度声明**：当前 mock replay 的 signal_quality 为 `tautological_replay`，不是真实 Agent 能力信号。不支持的功能详见 CURRENT_IMPLEMENTATION.md。
