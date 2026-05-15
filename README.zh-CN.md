# Agent Tool Harness

[English](README.md)

一个本地 tool-use trace 检查、评测与报告生成工具。

**agent-tool-harness 不运行你的 Agent。**
它只负责评估你已有的 Agent runner、脚本、CI 或日志产出的 tool-use trace。

## 它能做什么

- **导入** native Agent2Harness trace JSON，或通过简单字段映射导入自定义格式
- **诊断** trace 质量 — 字段覆盖率、类型检查、置信度评估、mapping dry-run
- **检查** tool-use 正确性 — call_id 唯一性、调用/结果配对、参数有效性、孤儿检测（9 条规则）
- **检查** tool spec 质量 — description 完整度、input_schema 是否存在、参数文档、output contract（10 条规则）
- **检查** tool ergonomics — 命名清晰度、命名空间重叠、wrapper 检测、action-resource 模式（6 条规则）
- **检查** tool response 质量 — output 是否存在、错误是否可行动、信号强度、上下文充分性（6 条规则）
- **评测** 以确定性 RuleFinding 决定 pass/fail — 无需 LLM
- **建议** 以 fake-testable LLM judge rubric 提供辅助分析 — 6 个建议维度，不影响 pass/fail
- **报告** 以结构化 JSON artifact 和 Markdown 摘要输出结果
- **审计** 工具设计、评测质量和 judge prompt
- **生成** 候选评测，并支持审阅后提升为正式评测
- **脚手架** 从 Python 源码 AST 扫描生成 draft tools.yaml、evals.yaml 和 fixtures

所有能力均为本地、离线、默认零网络依赖。

## 它不做什么

- **不运行目标 Agent** — 你运行你的 Agent；harness 只导入和评估 trace
- **不管理你的 API key** — 默认不加载 .env，不存储 key，不做 secret 管理
- **不默认调用真实 LLM** — 真实 LLM judge 需要显式三重 opt-in（`--live --confirm-i-have-real-key --env-file`）
- **不自动修复工具** — 不做 optimizer，不修 prompt，不自动修改工具
- **不自动生成 ReviewDecision** — 人工 review 是显式且必须的
- **不提供 batch / 多 trace 评测**
- **不提供 review UI**
- **不内置 CLIAgentAdapter** — 内置 agent runner 已移除

## 核心主流程

```
你的 Agent runner / 脚本 / CI
  → 产出 tool-use trace / log (JSON)
    → TraceImportAdapter 导入 trace
      → CoreEvaluation 评测 tool use
        → Report (Markdown + JSON artifacts)
          → Human Review
```

两种导入模式：

| 模式 | 适用场景 |
|------|----------|
| `native` | 你的 trace 已经符合 [native Agent2Harness schema](docs/TRACE_IMPORT_ADAPTER_SPEC.md) |
| `simple_mapping` | 你的 trace 使用不同的字段名 — 通过 `SimpleMappingConfig` 映射 |

如果你的 trace 是 JSONL、stdout 或 CSV，先写一个小的转换脚本产出 native-schema JSON。
详见 [External Runner Workflow](docs/EXTERNAL_RUNNER_WORKFLOW.md)。

## 快速开始

### 安装

```bash
git clone https://github.com/yaoziyaoguai/agent-tool-harness.git
cd agent-tool-harness
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 验证安装
python -m pytest tests/ -q
```

### 导入 trace 并评测

推荐工作流：你的外部 runner 产出 trace → harness 导入并评测。

```bash
python -c "
from agent_tool_harness.trace_import import import_trace_as_evidence
from agent_tool_harness.core_evaluation import CoreEvaluation, EvalSpec

# 1. 导入 native-schema trace
evidence = import_trace_as_evidence('examples/trace_import/native_trace.json')
trace = evidence.trace
print(f'已导入: scenario={trace.scenario_id}')
print(f'  tool_calls={len(trace.tool_calls)} tool_results={len(trace.tool_results)}')
print(f'  signal_quality={evidence.signal_quality}')

# 2. 运行确定性 tool-use 检查（不需要 LLM）
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

# 3. 查看确定性检查结果
print(f'评测通过: {result.passed}')
print(f'发现项: {len(result.findings)} (severity: high→ERROR, medium→WARNING, info→advisory)')
for f in result.findings:
    print(f'  [{f.severity}] {f.message[:140]}')
"
```

这个最小示例运行了 9 条确定性 tool-use 正确性检查（D2：call_id 唯一性、调用/结果配对、参数有效性、孤儿检测）加上 RuleJudge — **零网络、零 API key、零 .env**。

`passed` 可能为 `False`，如果 eval_spec 没有 `judge.rules` 配置——对裸导入这是正常现象。
完整 v3.1.0 评测还支持 D4（tool ergonomics）、D5（response quality）、D6（tool spec quality）inspector，
可通过向 `CoreEvaluation` 构造函数传入对应实例来启用。

## 最小 trace 示例

一个最小 native-schema trace（[`examples/trace_import/native_trace.json`](examples/trace_import/native_trace.json)）：

```json
{
  "scenario_id": "knowledge_search_regression",
  "tool_calls": [
    {
      "call_id": "call-1",
      "tool_name": "kb.search.search_articles",
      "arguments": {"query": "SSO session loss after password reset", "limit": 5}
    }
  ],
  "tool_results": [
    {
      "call_id": "call-1",
      "tool_name": "kb.search.search_articles",
      "status": "success",
      "output": {"articles": [{"id": "kb-0042", "title": "SSO Session Loss: Root Cause Analysis"}]},
      "error": null
    }
  ],
  "final_answer": "Root cause: race condition in SSO session storage layer...",
  "messages": [],
  "observations": []
}
```

核心字段说明：
- `scenario_id` — 场景标识，用于关联评测配置
- `tool_calls` — Agent 发出的工具调用列表，每条包含 `call_id`、`tool_name`、`arguments`
- `tool_results` — 工具返回结果列表，通过 `call_id` 与 `tool_calls` 配对
- `final_answer` — Agent 的最终回答，可选

## 判断模型

agent-tool-harness 将发现项分为三层，边界清晰：

| 层 | 决定 `passed`？ | 来源 | 说明 |
|----|-----------------|------|------|
| **RuleFinding** | **是** | 确定性规则 | call_id 唯一性、调用/结果配对、参数存在性、spec 完整度 — 5 个 inspector 共 37+ 条规则 |
| **JudgeFinding** | **否**（仅建议） | LLM judge rubric（可选） | tool choice 合理性、工效学、响应质量 — 6 个建议维度 |
| **ReviewDecision** | **否**（仅人工） | 人工 reviewer | 审阅所有证据后的最终接受/拒绝 |

关键属性：
- `EvaluationResult.passed` 仅由确定性 RuleFinding 决定
- JudgeFinding 始终是建议性质（`severity: "info"`），永远不改变 pass/fail 结果
- ReviewDecision 永远不会被自动生成 — 必须由人显式创建

详见 [Agent2Harness Main Flow](docs/AGENT2HARNESS_MAIN_FLOW.md)。

## 真实 LLM judge（非默认，需显式 opt-in）

真实 LLM judge 不是默认路径。要启用需要同时使用三个标志：

```bash
python -m agent_tool_harness.cli run-core-flow \
  --live --confirm-i-have-real-key --env-file .env \
  --judge-provider llm \
  ...
```

已验证的 transport：
- **openai-compatible** — 已通过真实 LLM smoke 验证
- **anthropic-compatible** — 已通过真实 LLM smoke 验证

未验证的路径（代码存在但未做 live smoke）：
- openai-native — 未经真实端点测试
- anthropic-native — 未经真实端点测试
- anthropic_compatible_live — legacy 路径，不推荐新使用

关键约束：即使启用了真实 LLM judge，JudgeFinding 仍然是 advisory only，**不影响** `EvaluationResult.passed`。LLM 不参与 ReviewDecision。

详见 [LLM Provider Config](docs/LLM_PROVIDER_CONFIG.md) 和 [Dogfood 记录](docs/DOGFOOD_REAL_LLM_001.md)。

## 文档地图

| 类别 | 文档 | 内容 |
|------|------|------|
| **入门** | [`docs/START_HERE.md`](docs/START_HERE.md) | 30 秒判断是否适合你 |
| | [`docs/ONBOARDING.md`](docs/ONBOARDING.md) | 最小上手路径和命令速查表 |
| | [`examples/trace_import/README.md`](examples/trace_import/README.md) | Trace 导入示例 |
| **用户指南** | [`docs/EXTERNAL_RUNNER_WORKFLOW.md`](docs/EXTERNAL_RUNNER_WORKFLOW.md) | 外部 runner → trace 导入工作流 |
| | [`docs/TRACE_IMPORT_ADAPTER_SPEC.md`](docs/TRACE_IMPORT_ADAPTER_SPEC.md) | Trace 导入规范（native + simple mapping） |
| | [`docs/CLI_USAGE.md`](docs/CLI_USAGE.md) | 完整 CLI 命令参考 |
| | [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | YAML 配置文件格式 |
| | [`docs/PROJECT_INTEGRATION.md`](docs/PROJECT_INTEGRATION.md) | 接入你自己的项目 |
| | [`docs/LLM_PROVIDER_CONFIG.md`](docs/LLM_PROVIDER_CONFIG.md) | 真实 LLM judge opt-in 配置 |
| **参考** | [`docs/ARTIFACTS.md`](docs/ARTIFACTS.md) | Artifact schema 参考和版本策略 |
| **架构** | [`docs/AGENT2HARNESS_MAIN_FLOW.md`](docs/AGENT2HARNESS_MAIN_FLOW.md) | 核心流程：Trace → Evidence → Evaluation → Report |
| | [`docs/TOOL_USE_INSPECTION_SDD.md`](docs/TOOL_USE_INSPECTION_SDD.md) | Tool-use inspection 设计 |
| | [`docs/CURRENT_IMPLEMENTATION.md`](docs/CURRENT_IMPLEMENTATION.md) | 诚实的能力矩阵 |
| | [`docs/HEADLESS_HARNESS_MODEL.md`](docs/HEADLESS_HARNESS_MODEL.md) | Harness 执行模型 |
| | [`docs/DEMO_CORE_REAL_BOUNDARY.md`](docs/DEMO_CORE_REAL_BOUNDARY.md) | Demo / Core / Real 分层边界 |
| **规划** | [`docs/ROADMAP.md`](docs/ROADMAP.md) | 完整演进路线（Tracks A–D） |
| | [`docs/BACKLOG.md`](docs/BACKLOG.md) | 详细 backlog |
| **历史** | [`docs/DOGFOOD_REAL_LLM_001.md`](docs/DOGFOOD_REAL_LLM_001.md) | 真实 LLM dogfood 记录（2026-05-12） |

## v3.1 报告洞察

v3.1 在 v3.0 的确定性检查之上，新增了**报告级洞察层**。不再是一份扁平的 finding 列表，而是结构化的、可快速浏览的评测报告：

| 组件 | 它告诉你什么 |
|------|-------------|
| **Scorecard** | 一眼看懂通过/不通过，以及 error/warning/advisory 分桶计数 |
| **Metrics** | 工具调用次数、成功率/错误率、响应大小、孤儿调用检测 |
| **Grouped Findings** | 按严重度、类别、受影响工具分组的 findings — 快速发现模式 |
| **Recommendations** | 去重、排序、可行动的修复建议，包含"什么问题 / 为什么 / 怎么修" |

所有组件均为**确定性计算、零网络依赖、不需要 LLM**。它们自动丰富 Markdown 报告（`report.md`）和 JSON artifact 输出 — 无需额外参数。

### 报告示例

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
1. [critical] 缺少 arguments — 工具: search (2 次)
2. [high] 输出信号过低 — 工具: read (1 次)

## Recommendations
1. search: 确保每次调用都传入必需的 arguments 参数
2. read: 检查工具返回的 output 是否包含足够上下文
```

详见 [`docs/sdd/SDD_EVALUATION_REPORT_INSIGHT_V3_1.md`](docs/sdd/SDD_EVALUATION_REPORT_INSIGHT_V3_1.md)。

## v3.1.0 范围

当前 v3.1.0 聚焦于单 trace 检查与评测，并提供结构化洞察报告。已实现：

- [x] 外部 runner → trace/log 导入作为主要接入路径
- [x] Native trace 导入 + simple field mapping 导入
- [x] Trace diagnostics — 字段覆盖率、类型检查、置信度评估、mapping dry-run
- [x] Tool-use 正确性检查 — 9 条确定性规则
- [x] Tool spec 质量检查 — 10 条确定性规则
- [x] Tool ergonomics 确定性提示 — 6 条规则
- [x] Tool response 质量确定性提示 — 6 条规则
- [x] Fake-testable LLM judge rubric 框架 — 6 个建议维度
- [x] Markdown 报告 + 结构化 JSON artifact
- [x] RuleFinding 决定确定性 passed
- [x] JudgeFinding 仅为 advisory，ReviewDecision 仅人工
- [x] 14 个 CLI 子命令 — audit、scaffold、replay、bootstrap、preflight 等
- [x] **Report Insight** — Scorecard、Metrics、Grouped Findings、Recommendations（Markdown + JSON）
- [x] **MetricsCollector** — 从 ExecutionTrace + EvaluationResult 计算 15 项聚合指标
- [x] **FindingGrouper** — 按严重度、类别、工具、规则前缀分桶
- [x] **RecommendationCatalog** — 去重、排序、可行动的修复建议

后续版本可能继续增强 metrics、批量评测和 review 工作流。
详见 [`docs/ROADMAP.md`](docs/ROADMAP.md)。

## 设计渊源

本项目对齐 Anthropic Engineering 的 [Writing effective tools for agents — with agents](https://www.anthropic.com/engineering/writing-tools-for-agents) 方法论。核心聚焦 **tool-use inspection** — 对 Agent tool-use 日志和工具设计质量做检查、评测和报告。
