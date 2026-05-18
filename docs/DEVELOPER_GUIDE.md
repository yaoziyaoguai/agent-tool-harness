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
├── config/                 # YAML 配置解析（ToolSpec, EvalSpec, loader）
├── judges/                 # JudgeProvider（RuleJudge, FakeJudgeProvider, LLMJudgeProvider）
├── secrets.py              # SecretSource 抽象（显式 env file / OS env / mapping）
├── reports/                # 报告 contract / composer / legacy Markdown wrapper
├── audit/                  # 审计工具（ToolDesignAuditor, EvalQualityAuditor）
├── scaffold/               # AST 扫描生成 draft 配置
├── diagnose/               # trace 诊断分析
├── runner/                 # EvalRunner 编排
├── task_eval/              # v3.2 task-level evaluation（EvalCase, Verifier, TaskOutcome）
├── suite_eval/             # v3.3 suite aggregation（SuiteResult, SuiteScorecard, SuiteMetrics）
├── regression/             # v3.4 baseline/candidate comparison（RegressionReport）
├── analysis/               # v3.5 transcript/context deterministic analysis
└── portfolio/              # v3.6 portfolio review + improvement brief
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

## Secret 边界

真实 LLM 相关 secret 的新代码路径必须走 `SecretSource`：

- `EnvFileSecretSource(path)` — 只读取显式传入的 env file，不自动读取当前目录 `.env`
- `OsEnvSecretSource()` — 只在 CLI / factory 已通过 `--allow-os-env` gate 后使用
- `MappingSecretSource(mapping)` — 测试用内存 secret

`AnthropicCompatibleConfig.from_secret_source(source)` 是新路径。旧
`AnthropicCompatibleConfig.from_env()` 仅保留为 deprecated compatibility
constructor：无参调用不会读取 `os.environ`；只有显式
`allow_os_environ=True` 才走历史 OS env 兼容路径。

开发规则：
- 不在 provider / preflight / CLI 内部无参调用 `from_env()`
- 不读取 `.env` 内容，除非用户显式传 `--env-file PATH`
- 不打印 `api_key` / `base_url` 原值
- 不放宽 `--live` + `--confirm-i-have-real-key` + secret source 的 gate

## Report section contract

v3.1-v3.6 的报告段通过 `agent_tool_harness/reports/section_contract.py` 统一：

- `ReportSection` — 稳定 `section_id`、标题、排序优先级和延迟 `render()`
- `RenderedSection` — 已渲染 Markdown + 可选 JSON shape
- `compose_sections()` — 一次渲染后同时产出 Markdown / JSON，避免重复调用 section renderer
- `render_sections_markdown()` / `sections_to_json_dict()` — 兼容 helper，内部走同一 composition 边界

priority 使用命名常量表达当前顺序：task outcome、suite result、regression、
analysis、portfolio。新增 section 应优先使用 `PRIORITY_*` 常量；确需插入时在
相邻 band 之间取值，不要在业务 adapter 里散落裸数字。

架构边界：composer 只认识 `ReportSection`，不读取 `TaskOutcome`、
`SuiteResult`、`RegressionReport`、analysis finding 或 portfolio brief 的内部字段。
各业务模块通过 adapter 暴露 section：

- `task_eval.render.task_outcome_report_section()`
- `suite_eval.render.suite_report_section()`
- `regression.regression_report.regression_report_section()`
- `analysis.render.analysis_report_section()`
- `portfolio.render.portfolio_report_section()`

`MarkdownReport.render_from_core(..., sections=[...])` 是兼容入口，可同时组合
v3.1 insight、v3.2 task、v3.3 suite、v3.4 regression、v3.5 analysis、
v3.6 portfolio sections。旧 `task_outcome=` / `suite_result=` 参数仍保留，
内部会转成 `ReportSection`。

## 如何新增 report section

1. 在所属业务模块内实现 Markdown / JSON 渲染，保持对象知识留在本模块。
2. 增加一个 `*_report_section(domain_object)` adapter，返回 `ReportSection`。
3. 选择稳定 `section_id` 和 `priority`，避免 heading 重复。
4. 在 `tests/test_report_section_composition.py` 或 focused test 中覆盖：
   多 section 共存、JSON 可序列化、不修改输入对象。
5. 不把新业务渲染逻辑继续塞进 `reports/markdown_report.py`。

`reports/markdown_report.py` 现在负责 legacy artifact report 和 public API wrapper；
Core Flow 实际渲染在 `reports/core_report_renderer.py`，suite/task/regression/
analysis/portfolio 的 section 细节由各自模块负责。`render_analysis_section()` 和
`render_portfolio_section()` 是 deprecated compatibility wrapper；新代码不要直接
调用它们，应使用对应模块的 `analysis_report_section()` /
`portfolio_report_section()`。

JSON serialization 也尽量靠近模块边界：task/suite 的 `*_to_json_dict()` 由各自
`render.py` 拥有，`core_report_bridge.py` 只保留旧函数名的 thin wrapper。

## Live transport 配置

`LiveAnthropicTransport` 已是 legacy transport，默认仍 disabled。它的 timeout
使用显式 `timeout_s` 参数；构造函数不默认读取 `os.environ`。如果未来需要 env
兼容，应在 CLI / factory 的显式 opt-in 层解析后传入 transport。

## 版本策略

最新稳定发布是 `v3.6.1`。它是 post-v3.6 architecture quality patch，不是新功能线。
不要为这批维护工作创建 `v3.7` 叙述。

## 架构文档

- [architecture/AGENT2HARNESS_MAIN_FLOW.md](architecture/AGENT2HARNESS_MAIN_FLOW.md) — 核心流程
- [architecture/AGENT2HARNESS_CORE_SPEC.md](architecture/AGENT2HARNESS_CORE_SPEC.md) — Core Contract
- [architecture/TOOL_USE_INSPECTION_SDD.md](architecture/TOOL_USE_INSPECTION_SDD.md) — 工具检查设计
- [architecture/TRACE_IMPORT_ADAPTER_SPEC.md](architecture/TRACE_IMPORT_ADAPTER_SPEC.md) — trace 导入规范
- [architecture/DEMO_CORE_REAL_BOUNDARY.md](architecture/DEMO_CORE_REAL_BOUNDARY.md) — 分层边界

## RFC / SDD

v3.1+ 各版本的架构决策记录和设计文档：

- [rfc/RFC_0002_EVALUATION_REPORT_INSIGHT.md](rfc/RFC_0002_EVALUATION_REPORT_INSIGHT.md) — v3.1 Report Insight RFC
- [sdd/SDD_EVALUATION_REPORT_INSIGHT_V3_1.md](sdd/SDD_EVALUATION_REPORT_INSIGHT_V3_1.md) — v3.1 Report Insight SDD
- [rfc/RFC_0003_TASK_LEVEL_EVALUATION.md](rfc/RFC_0003_TASK_LEVEL_EVALUATION.md) — v3.2 Task-level Evaluation RFC
- [sdd/SDD_TASK_LEVEL_EVALUATION_V3_2.md](sdd/SDD_TASK_LEVEL_EVALUATION_V3_2.md) — v3.2 Task-level Evaluation SDD
- [rfc/RFC_0004_EVAL_SUITE_AGGREGATION.md](rfc/RFC_0004_EVAL_SUITE_AGGREGATION.md) — v3.3 Suite Aggregation RFC
- [sdd/SDD_EVAL_SUITE_AGGREGATION_V3_3.md](sdd/SDD_EVAL_SUITE_AGGREGATION_V3_3.md) — v3.3 Suite Aggregation SDD
- [rfc/RFC_0005_REGRESSION_COMPARISON.md](rfc/RFC_0005_REGRESSION_COMPARISON.md) — v3.4 Regression Comparison RFC
- [sdd/SDD_REGRESSION_COMPARISON_V3_4.md](sdd/SDD_REGRESSION_COMPARISON_V3_4.md) — v3.4 Regression Comparison SDD
- [rfc/RFC_0006_TRANSCRIPT_AND_CONTEXT_ANALYSIS.md](rfc/RFC_0006_TRANSCRIPT_AND_CONTEXT_ANALYSIS.md) — v3.5 Transcript + Context Analysis RFC
- [sdd/SDD_TRANSCRIPT_AND_CONTEXT_ANALYSIS_V3_5.md](sdd/SDD_TRANSCRIPT_AND_CONTEXT_ANALYSIS_V3_5.md) — v3.5 Transcript + Context Analysis SDD
- [rfc/RFC_0007_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF.md](rfc/RFC_0007_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF.md) — v3.6 Tool Portfolio + Improvement Brief RFC
- [sdd/SDD_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF_V3_6.md](sdd/SDD_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF_V3_6.md) — v3.6 Tool Portfolio + Improvement Brief SDD

## 路线图

- [ROADMAP.md](ROADMAP.md) — 演进路线（Tracks A-D）
- [BACKLOG.md](BACKLOG.md) — 详细 backlog
- [roadmap/AGENT_TOOL_HARNESS_CAPABILITY_ROADMAP.md](roadmap/AGENT_TOOL_HARNESS_CAPABILITY_ROADMAP.md) — 长期能力路线图（v3.1→v3.6 全部完成）
- v3.1: [milestone](roadmap/V3_1_EVALUATION_REPORT_INSIGHT_MILESTONE.md) | [backlog](roadmap/V3_1_IMPLEMENTATION_BACKLOG.md)
- v3.2: [milestone](roadmap/V3_2_TASK_LEVEL_EVALUATION_MILESTONE.md) | [backlog](roadmap/V3_2_IMPLEMENTATION_BACKLOG.md)
- v3.3: [milestone](roadmap/V3_3_EVAL_SUITE_AGGREGATION_MILESTONE.md) | [backlog](roadmap/V3_3_IMPLEMENTATION_BACKLOG.md)
- v3.4: [milestone](roadmap/V3_4_REGRESSION_COMPARISON_MILESTONE.md) | [backlog](roadmap/V3_4_IMPLEMENTATION_BACKLOG.md)
- v3.5: [milestone](roadmap/V3_5_TRANSCRIPT_AND_CONTEXT_ANALYSIS_MILESTONE.md) | [backlog](roadmap/V3_5_IMPLEMENTATION_BACKLOG.md)
- v3.6: [milestone](roadmap/V3_6_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF_MILESTONE.md) | [backlog](roadmap/V3_6_IMPLEMENTATION_BACKLOG.md)

## 变更记录

- [../CHANGELOG.md](../CHANGELOG.md) — 版本变更记录

## 历史归档

- [archive/](archive/) — dogfood 记录、历史迁移文档、旧实验记录
