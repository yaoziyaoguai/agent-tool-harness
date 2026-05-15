# 开发者指南

本文档面向想了解架构、参与开发或扩展 agent-tool-harness 的开发者。

## 项目概览

agent-tool-harness 是一个 headless CLI tool-use inspection platform。核心流程：

```
外部 trace JSON → TraceImportAdapter → ExecutionTrace → CoreEvaluation → Report
```

关键设计原则：
- **确定性优先** — RuleFinding 决定 pass/fail，LLM 是最后手段
- **离线优先** — 默认不联网、不需要 API key
- **接口隔离** — RuleFinding ≠ JudgeFinding，Core ≠ Demo ≠ Real
- **证据驱动** — 每一步产出结构化 artifact

## 开发环境

```bash
git clone https://github.com/yaoziyaoguai/agent-tool-harness.git
cd agent-tool-harness
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# 运行测试
python -m pytest tests/ -q

# 代码检查
ruff check agent_tool_harness tests
```

## 代码结构

```
agent_tool_harness/
├── core_contract.py        # 核心数据对象（ExecutionTrace, EvaluationResult, Finding 等）
├── core_evaluation.py      # CoreEvaluation 编排层
├── core_report_bridge.py   # 报告数据转换桥接
├── trace_import.py         # TraceImportAdapter（native + simple_mapping）
├── cli.py                  # CLI 入口（14 个子命令）
├── config/                 # YAML 配置解析
├── judges/                 # JudgeProvider（RuleJudge, FakeJudgeProvider, LLMJudgeProvider）
├── reports/                # 报告渲染（MarkdownReport, ReportInsight, CostTracker）
├── audit/                  # 审计工具（ToolDesignAuditor, EvalQualityAuditor）
├── scaffold/               # AST 扫描生成 draft 配置
├── diagnose/               # trace 诊断分析
└── runner/                 # EvalRunner 编排
```

## 如何新增 Inspector

Inspector 是确定性规则检查器。在 `agent_tool_harness/` 下新建模块：

1. 实现检查逻辑，消费 `ExecutionTrace`，产出 `list[RuleFinding]`
2. 在 `CoreEvaluation` 中注入新 inspector
3. 在 `RecommendationCatalog` 中新增对应 rule_id 的建议映射
4. 编写测试（参考 `tests/` 中已有 inspector 测试）

## 如何新增 Report Insight 组件

v3.1 的 Report Insight 组件在 `agent_tool_harness/reports/report_insight.py`：

- `ReportMetrics` + `MetricsCollector` — 聚合指标
- `FindingGrouper` + `GroupedFindings` — findings 分组
- `ReportScorecard` + `make_scorecard()` — 评分卡
- `Recommendation` + `RecommendationCatalog` — 修复建议
- `ReportInsight` + `from_eval()` — 聚合根

所有组件均为 frozen dataclass，通过 `from_eval()` 一站式构造。

## 架构文档

- [architecture/AGENT2HARNESS_MAIN_FLOW.md](architecture/AGENT2HARNESS_MAIN_FLOW.md) — 核心流程
- [architecture/AGENT2HARNESS_CORE_SPEC.md](architecture/AGENT2HARNESS_CORE_SPEC.md) — Core Contract
- [architecture/TOOL_USE_INSPECTION_SDD.md](architecture/TOOL_USE_INSPECTION_SDD.md) — 工具检查设计
- [architecture/TRACE_IMPORT_ADAPTER_SPEC.md](architecture/TRACE_IMPORT_ADAPTER_SPEC.md) — trace 导入规范
- [architecture/DEMO_CORE_REAL_BOUNDARY.md](architecture/DEMO_CORE_REAL_BOUNDARY.md) — 分层边界

## RFC / SDD

- [rfc/RFC_0002_EVALUATION_REPORT_INSIGHT.md](rfc/RFC_0002_EVALUATION_REPORT_INSIGHT.md) — v3.1 Report Insight RFC
- [sdd/SDD_EVALUATION_REPORT_INSIGHT_V3_1.md](sdd/SDD_EVALUATION_REPORT_INSIGHT_V3_1.md) — v3.1 Report Insight SDD

## 路线图

- [ROADMAP.md](ROADMAP.md) — 演进路线（Tracks A-D）
- [BACKLOG.md](BACKLOG.md) — 详细 backlog
- [roadmap/V3_1_EVALUATION_REPORT_INSIGHT_MILESTONE.md](roadmap/V3_1_EVALUATION_REPORT_INSIGHT_MILESTONE.md) — v3.1 milestone
- [roadmap/V3_1_IMPLEMENTATION_BACKLOG.md](roadmap/V3_1_IMPLEMENTATION_BACKLOG.md) — v3.1 实现 backlog

## 历史归档

- [archive/](archive/) — dogfood 记录、历史迁移文档、旧实验记录
