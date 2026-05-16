# 文档索引

按你的目的查找文档，不用按文件名猜。

## 新用户

- [QUICKSTART](QUICKSTART.md) — 5 分钟上手
- [USER_GUIDE](USER_GUIDE.md) — 完整使用流程
- [REPORT_GUIDE](REPORT_GUIDE.md) — 报告解读（v3.1-v3.6）

## 示例

- [examples/README.md](../examples/README.md) — 所有示例入口
  - [trace_import](../examples/trace_import/README.md) — trace 导入示例
  - [runtime_debug](../examples/runtime_debug/) — mock replay demo
  - [eval_suites](../examples/eval_suites/) — suite 聚合示例
  - [regression_comparison_demo.py](../examples/regression_comparison_demo.py) — 回归对比 demo
  - [transcript_analysis](../examples/transcript_analysis/) — 转录/上下文分析 demo
  - [portfolio_review](../examples/portfolio_review/) — 工具组合评审 demo

## 我想接入自己的 trace

- [USER_GUIDE](USER_GUIDE.md) — 准备 trace、native 导入、simple_mapping
- [architecture/TRACE_IMPORT_ADAPTER_SPEC.md](architecture/TRACE_IMPORT_ADAPTER_SPEC.md) — trace import 技术规范
- [examples/trace_import/README.md](../examples/trace_import/README.md) — trace 导入示例

## 我想看懂报告

- [REPORT_GUIDE](REPORT_GUIDE.md) — v3.1 报告解读（Scorecard / Metrics / Findings / Recommendations）

## 我想配置真实 LLM judge

- [PROVIDER_CONFIG](PROVIDER_CONFIG.md) — LLM provider 配置指南
- [LLM_PROVIDER_CONFIG.md](LLM_PROVIDER_CONFIG.md) — 完整技术参考（开发者向）

## 我想了解项目现状和能力边界

- [CURRENT_IMPLEMENTATION.md](CURRENT_IMPLEMENTATION.md) — 当前能力矩阵和限制
- [../CHANGELOG.md](../CHANGELOG.md) — 版本变更记录
- [ROADMAP.md](ROADMAP.md) — 演进路线
- [BACKLOG.md](BACKLOG.md) — 详细 backlog
- [roadmap/AGENT_TOOL_HARNESS_CAPABILITY_ROADMAP.md](roadmap/AGENT_TOOL_HARNESS_CAPABILITY_ROADMAP.md) — 长期能力路线图（v3.1-v3.6 全部完成）

## 我想了解架构设计

- [DEVELOPER_GUIDE](DEVELOPER_GUIDE.md) — 开发者入口
- [architecture/](architecture/) — 架构设计文档
  - [AGENT2HARNESS_MAIN_FLOW.md](architecture/AGENT2HARNESS_MAIN_FLOW.md) — 核心流程
  - [AGENT2HARNESS_CORE_SPEC.md](architecture/AGENT2HARNESS_CORE_SPEC.md) — Core Contract 规范
  - [TOOL_USE_INSPECTION_SDD.md](architecture/TOOL_USE_INSPECTION_SDD.md) — 工具检查设计
  - [TRACE_IMPORT_ADAPTER_SPEC.md](architecture/TRACE_IMPORT_ADAPTER_SPEC.md) — trace 导入规范
- [rfc/](rfc/) — 架构决策记录
  - [RFC 0002](rfc/RFC_0002_EVALUATION_REPORT_INSIGHT.md) — v3.1 Report Insight
  - [RFC 0003](rfc/RFC_0003_TASK_LEVEL_EVALUATION.md) — v3.2 Task-level Evaluation
  - [RFC 0004](rfc/RFC_0004_EVAL_SUITE_AGGREGATION.md) — v3.3 Suite Aggregation
  - [RFC 0005](rfc/RFC_0005_REGRESSION_COMPARISON.md) — v3.4 Regression Comparison
  - [RFC 0006](rfc/RFC_0006_TRANSCRIPT_AND_CONTEXT_ANALYSIS.md) — v3.5 Transcript + Context
  - [RFC 0007](rfc/RFC_0007_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF.md) — v3.6 Portfolio + Brief
- [sdd/](sdd/) — 设计文档
  - [SDD v3.1](sdd/SDD_EVALUATION_REPORT_INSIGHT_V3_1.md) — Report Insight
  - [SDD v3.2](sdd/SDD_TASK_LEVEL_EVALUATION_V3_2.md) — Task-level Evaluation
  - [SDD v3.3](sdd/SDD_EVAL_SUITE_AGGREGATION_V3_3.md) — Suite Aggregation
  - [SDD v3.4](sdd/SDD_REGRESSION_COMPARISON_V3_4.md) — Regression Comparison
  - [SDD v3.5](sdd/SDD_TRANSCRIPT_AND_CONTEXT_ANALYSIS_V3_5.md) — Transcript + Context
  - [SDD v3.6](sdd/SDD_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF_V3_6.md) — Portfolio + Brief

## 我想参与开发

- [DEVELOPER_GUIDE](DEVELOPER_GUIDE.md) — 开发环境、测试、代码风格
- [roadmap/](roadmap/) — 版本规划和实现 backlog
  - [能力路线图总览](roadmap/AGENT_TOOL_HARNESS_CAPABILITY_ROADMAP.md)
  - v3.1: [milestone](roadmap/V3_1_EVALUATION_REPORT_INSIGHT_MILESTONE.md) | [backlog](roadmap/V3_1_IMPLEMENTATION_BACKLOG.md)
  - v3.2: [milestone](roadmap/V3_2_TASK_LEVEL_EVALUATION_MILESTONE.md) | [RFC](rfc/RFC_0003_TASK_LEVEL_EVALUATION.md) | [SDD](sdd/SDD_TASK_LEVEL_EVALUATION_V3_2.md) | [backlog](roadmap/V3_2_IMPLEMENTATION_BACKLOG.md)
  - v3.3: [milestone](roadmap/V3_3_EVAL_SUITE_AGGREGATION_MILESTONE.md) | [RFC](rfc/RFC_0004_EVAL_SUITE_AGGREGATION.md) | [SDD](sdd/SDD_EVAL_SUITE_AGGREGATION_V3_3.md) | [backlog](roadmap/V3_3_IMPLEMENTATION_BACKLOG.md)
  - v3.4: [milestone](roadmap/V3_4_REGRESSION_COMPARISON_MILESTONE.md) | [RFC](rfc/RFC_0005_REGRESSION_COMPARISON.md) | [SDD](sdd/SDD_REGRESSION_COMPARISON_V3_4.md) | [backlog](roadmap/V3_4_IMPLEMENTATION_BACKLOG.md)
  - v3.5: [milestone](roadmap/V3_5_TRANSCRIPT_AND_CONTEXT_ANALYSIS_MILESTONE.md) | [RFC](rfc/RFC_0006_TRANSCRIPT_AND_CONTEXT_ANALYSIS.md) | [SDD](sdd/SDD_TRANSCRIPT_AND_CONTEXT_ANALYSIS_V3_5.md) | [backlog](roadmap/V3_5_IMPLEMENTATION_BACKLOG.md)
  - v3.6: [milestone](roadmap/V3_6_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF_MILESTONE.md) | [RFC](rfc/RFC_0007_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF.md) | [SDD](sdd/SDD_TOOL_PORTFOLIO_AND_IMPROVEMENT_BRIEF_V3_6.md) | [backlog](roadmap/V3_6_IMPLEMENTATION_BACKLOG.md)
- [archive/REVIEW_CHECKLIST.md](archive/REVIEW_CHECKLIST.md) — PR review 自检清单

## 历史记录

- [archive/](archive/) — dogfood 记录、历史迁移文档、旧实验记录
