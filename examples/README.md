# Examples

所有示例按能力分组。每个示例不依赖真实 LLM、不依赖 .env、不依赖网络。

## 快速入口

| 我想体验... | 运行这个 |
|------------|---------|
| trace 导入 + 确定性检查 | `python -c "..."` → [QUICKSTART](../docs/QUICKSTART.md) |
| mock replay 全链路 | `runtime_debug/` + CLI `run` |
| 任务级评测 | `eval_suites/` |
| 回归对比 | `python regression_comparison_demo.py` |
| 转录/上下文分析 | `python transcript_analysis/demo_analysis.py` |
| 工具组合评审 | `python portfolio_review/demo_portfolio.py` |

## 按能力浏览

### trace 导入（v3.0）

- [trace_import/](trace_import/) — native trace JSON 示例 + simple_mapping 说明

### 报告洞察（v3.1）

- [runtime_debug/](runtime_debug/) — mock replay 全链路（tools.yaml → audit → run → report.md）

### 任务级评测（v3.2）

- [eval_suites/](eval_suites/) — EvalSuite YAML 示例（minimal / full / multi-trace / regression）
- [knowledge_search/](knowledge_search/) — 知识搜索场景完整示例（tools + evals + demo_tools）
- [bootstrap_to_run/](bootstrap_to_run/) — AST 扫描 → 生成配置 → 审核 → 跑测 的完整流程

### Suite 聚合（v3.3）

- [eval_suites/](eval_suites/) — suite manifest + suite evaluator 示例

### 回归对比（v3.4）

- [regression_comparison_demo.py](regression_comparison_demo.py) — 5 个场景：回归检测、改善检测、自定义阈值

### Transcript + Context 分析（v3.5）

- [transcript_analysis/demo_analysis.py](transcript_analysis/demo_analysis.py) — 困惑模式 + 上下文浪费检测
- [transcript_analysis/context_inefficiency_trace.json](transcript_analysis/context_inefficiency_trace.json) — 示例 trace 数据

### 工具组合评审 + 改进建议（v3.6）

- [portfolio_review/demo_portfolio.py](portfolio_review/demo_portfolio.py) — 5 类检查 + brief 生成 + Markdown/JSON 输出

## 配置参考

- [runtime_debug/](runtime_debug/) — `project.yaml` / `tools.yaml` / `evals.yaml` 完整示例
- [knowledge_search/](knowledge_search/) — `tools.yaml` 5000+ 行复杂示例
- [bad_configs/](bad_configs/) — 常见配置错误示例（用于理解校验规则）
- [llm_providers.example.yaml](llm_providers.example.yaml) — LLM provider 配置模板

## 更多场景

- [realistic_offline_tool_trial/](realistic_offline_tool_trial/) — 离线工具试运行完整演示
- [fake_transport_fixtures/](fake_transport_fixtures/) — fake transport fixture（CI 安全）

## 下一步

- 接入你自己的 trace：[USER_GUIDE](../docs/USER_GUIDE.md)
- 看懂报告：[REPORT_GUIDE](../docs/REPORT_GUIDE.md)
- 了解架构：[DEVELOPER_GUIDE](../docs/DEVELOPER_GUIDE.md)
