# Runner Design（评测执行器模块设计）

> 本文档描述 agent-tool-harness 中 Runner（评测执行器）的设计意图、数据流、异常保全与编排逻辑。
> 在源码中，Runner 对应 `EvalRunner`（`runner/eval_runner.py`）。
>
> 面向读者：eval 设计者、Coding Agent、模块维护者。

---

## 一、模块目的

Runner 模块负责**编排单次 eval run 的完整生命周期**：

```
Audit → Run → Record → Judge → Diagnose → Report
```

它不是简单的"跑一遍 eval"，而是整个证据链的中枢调度器——确保即使某个环节失败（Registry 初始化错误、Adapter 抛异常、Eval 不可运行），也能产出结构化的失败 artifacts 供复盘。

---

## 二、当前实现现状

### 2.1 核心类：`EvalRunner`（`runner/eval_runner.py`）

`EvalRunner` 是一个编排器类，所有依赖（auditor、judge、analyzer、report）通过 keyword-only 构造参数注入，默认使用生产实现。

**构造参数**：

| 参数 | 类型 | 默认 | 含义 |
|------|------|------|------|
| `tool_auditor` | `ToolDesignAuditor \| None` | `ToolDesignAuditor()` | 工具设计审计器 |
| `eval_auditor` | `EvalQualityAuditor \| None` | `EvalQualityAuditor()` | Eval 质量审计器 |
| `judge` | `RuleJudge \| None` | `RuleJudge()` | 确定性规则 judge（ground truth） |
| `analyzer` | `TranscriptAnalyzer \| None` | `TranscriptAnalyzer()` | Transcript 复盘分析器 |
| `trace_signal_analyzer` | `TraceSignalAnalyzer \| None` | `None`（每次 run 内按 ToolSpec 列表重建索引） | Trace 信号分析器 |
| `report` | `MarkdownReport \| None` | `MarkdownReport()` | Markdown 报告渲染器 |
| `dry_run_provider` | `JudgeProvider \| None` | `None` | 可选旁路 JudgeProvider（advisory-only） |

### 2.2 主方法：`EvalRunner.run()`

**输入**（来自 `cli.py` 的 `run` 子命令）：
- `project: ProjectSpec` — 项目配置
- `tools: list[ToolSpec]` — 工具契约列表
- `evals: list[EvalSpec]` — eval 用例列表
- `adapter: AgentAdapter` — Agent 适配器（决定 Agent 行为）
- `out_dir: str | Path` — 输出目录

**输出**：11 个 artifact 文件：
- `transcript.jsonl` — 逐事件流（含 runner_start / runner_skip / runner_error）
- `tool_calls.jsonl` — 工具调用记录
- `tool_responses.jsonl` — 工具响应记录
- `metrics.json` — 聚合指标（含 signal_quality、judge_disagreement）
- `audit_tools.json` — 工具设计审计结果
- `audit_evals.json` — Eval 质量审计结果
- `judge_results.json` — 判定结果（含可选 dry_run_provider 旁路）
- `diagnosis.json` — 失败复盘（TranscriptAnalyzer + TraceSignalAnalyzer）
- `report.md` — 可读 Markdown 报告
- `llm_cost.json` — LLM 成本聚合（v1.6 新增，始终生成）

### 2.3 主循环状态机

```
for eval in evals:
    ├── audit 判 not_runnable → SKIP：
    │    写 runner_skip 事件到 transcript → error_judge_result → diagnose → continue
    │
    ├── adapter.run(case, registry, recorder)
    │     ├── 成功 → RuleJudge.judge → diagnose
    │     └── 抛异常 → 从 JSONL 恢复 partial run → error_judge_result → diagnose
    │
    └── 每条 eval 完成后 → dry_run_provider 旁路（若配置） → diagnose
```

### 2.4 关键设计决策

**失败保全（Failure Preservation）—— runner 是最后一道 artifact 兜底**：

任何阶段的失败（Registry 初始化、Adapter 抛异常、Eval 不可运行）都不会导致 run 整体崩溃。每种失败都被转成：
- 一条 `transcript.jsonl` 中的 `runner_error` / `runner_skip` 事件
- 一个 `error_judge_result`（`rule.type` = `tool_registry_initialization_failed` / `eval_not_runnable` / `adapter_execution_failed`）
- 一份 diagnosis 记录
- 在 `metrics.json` 中 `error_evals` / `skipped_evals` 分别计数

这样真实团队复盘时不会看到空 artifacts，而是看到"为什么没跑到工具调用"的结构化证据。

**审计-执行分离（`_runnable_by_eval`）**：

runner 不重新实现 eval 质量判断，而是**消费 EvalQualityAuditor 的结论**。`audit_evals.json` 中每个 eval 有 `runnable: bool` 字段——runner 只读这个字段决定是否执行。这确保"是否 runnable"只有一个来源，避免 audit 判不可运行但 runner 仍执行的治理漏洞。

**Advisory-only dry-run provider**：

`dry_run_provider` 的结果**永远**不覆盖 deterministic baseline。`judge_results.json` 中：
- `results[]` → 永远是 deterministic ground truth（来自 `RuleJudge`）
- `dry_run_provider.results[]` → 仅是 advisory metadata（出现条件：配置了 provider）

`metrics.judge_disagreement` 统计 advisory 与 deterministic 的分歧率，但**永远**不改变 `passed/failed` 计数。

**signal_quality 披露**：

adapter 自报的 `SIGNAL_QUALITY` 被收集并写入 `metrics.json` 和 `report.md` 顶部 banner。这是为了让真实团队不会把 `tautological_replay` 模式下的 PASS 误读为"工具对真实 Agent 好用"。

---

## 三、核心输入

| 输入 | 来源 | 说明 |
|------|------|------|
| `ProjectSpec` | `config/project_spec.py`，来自 `project.yaml` | 项目名/领域/描述/pricing/budget |
| `list[ToolSpec]` | `config/tool_spec.py`，来自 `tools.yaml` | 工具契约 |
| `list[EvalSpec]` | `config/eval_spec.py`，来自 `evals.yaml` 或 promoted 输出 | eval 用例 |
| `AgentAdapter` | `agents/agent_adapter_base.py` Protocol | 决定 Agent 行为 |
| `out_dir` | `str \| Path`，由 CLI 或调用方指定 | 输出目录 |

---

## 四、核心输出

所有输出通过 `_write_artifacts` 集中写入——成功、跳过和异常路径都走这里，避免某条异常路径漏写 report 或 JSON。

10 个 JSON/JSONL artifact + 1 个 Markdown 报告（完整列表见 §2.2）。每份 JSON artifact 带 `schema_version` + `run_metadata` 戳（同一 run 内共享 `run_id`）。

---

## 五、关键接口

| 接口 | 位置 | 稳定性 |
|------|------|--------|
| `EvalRunner.run(project, tools, evals, adapter, out_dir)` | `runner/eval_runner.py:96` | 稳定 |
| `EvalRunner.REQUIRED_ARTIFACTS` | `runner/eval_runner.py:54` | 稳定（只增不删） |
| `EvalRunner.__init__` keyword-only 参数 | `runner/eval_runner.py:70` | 实验性（dry_run_provider 是新增参数） |
| `AgentRunResult` dataclass | `agents/agent_adapter_base.py:12` | 稳定 |
| `_write_artifacts` | `runner/eval_runner.py:328` | 内部实现 |

---

## 六、不负责什么

- ❌ 不执行具体工具（由 `ToolRegistry.execute` 执行）
- ❌ 不决策 Agent 行为（由 `AgentAdapter.run` 决策）
- ❌ 不判定成败（由 `RuleJudge.judge` 判定）
- ❌ 不做语义级诊断（由 `TranscriptAnalyzer` + `TraceSignalAnalyzer` 做）
- ❌ 不渲染最终报告内容（由 `MarkdownReport.render` 渲染）
- ❌ 不审计工具/eval 质量（由 `ToolDesignAuditor` / `EvalQualityAuditor` 审计）
- ❌ 不在 audit 判 not_runnable 时强行执行
- ❌ 不让 dry_run provider 的结果覆盖 deterministic baseline

---

## 七、和其他模块的关系

```
agents/agent_adapter_base.py  →  AgentAdapter Protocol（runner 只依赖协议）
config/{project,tool,eval}_spec.py  →  Spec 对象（runner 的输入）
audit/{tool_design, eval_quality}_auditor.py  →  Auditor（runner 先审计，再决定是否 run）
tools/registry.py  →  ToolRegistry（adapter 用它执行工具）
recorder/run_recorder.py  →  RunRecorder（adapter 用它写 raw JSONL）
judges/rule_judge.py  →  RuleJudge（runner 用它做 deterministic 判定）
judges/provider.py  →  JudgeProvider（runner 用它做 advisory 旁路）
diagnose/{transcript,trace_signal}_analyzer.py  →  Analyzer（runner 用它做复盘）
reports/markdown_report.py  →  MarkdownReport（runner 用它渲染报告）
reports/cost_tracker.py  →  build_llm_cost_artifact（runner 用它写成本 JSON）
artifact_schema.py  →  stamp_artifact / make_run_metadata
signal_quality.py  →  describe（runner 用它披露信号质量）
```

**依赖方向**：runner → 所有子模块（runner 是所有子系统的汇聚点）。

---

## 八、测试证明方式

Runner 的行为通过以下间接测试覆盖（无独立 `test_runner.py`）：

| 测试文件 | 覆盖的 runner 行为 |
|---------|-------------------|
| `tests/test_e2e_*.py` 系列 | 端到端 run 全程（run good/bad 路径） |
| `tests/test_report.py` | 报告渲染中的 runner 级 metrics/skipped/error 状态 |
| `tests/test_judge_provider_skeleton.py` | dry_run_provider 旁路路径 |
| `tests/test_bootstrap_to_run.py`（examples） | bootstrap → run 完整闭环 |

---

## 九、后续实现或重构建议

1. **metrics 拆出独立模块**：当前 `_metrics()` 方法已经足够复杂（含 judge_disagreement 聚合），可考虑抽成 `runner/metrics.py`。

2. **并行 eval 执行**：当前逐条串行执行。对于无副作用的 Python 工具，可考虑并行跑多条 eval（需确保 ToolRegistry 线程安全 + recorder 按 eval_id 隔离写入）。

3. **per-eval budget hard abort**：当前 budget exceeded 只是 advisory。`project.yaml` 可加 `budget.per_eval.hard_abort: true`，让 runner 在 eval 超预算时立即中止该条。

4. **run 恢复/续跑**：当前不支持从 partial run 恢复。如果 adapter 在 eval #50 崩溃，前 49 条的 artifacts 已落盘，但 runner 没有"从 #50 续跑"的入口。

---

## 十、Review Checklist（审查清单）

Runner 模块变更 Review 时，检查以下项：

- [ ] 新增异常路径是否都有对应的 `runner_error` 事件写入 transcript
- [ ] `_write_artifacts` 是否仍是所有路径的唯一出口（不允许某条异常路径直接 return 而跳过写 artifacts）
- [ ] `runnable` 判断是否仍只消费 `EvalQualityAuditor` 的输出（不允许 runner 自己重新实现 runnable 逻辑）
- [ ] `dry_run_provider` 结果是否仍标记为 advisory-only，不覆盖 `results[].passed`
- [ ] `signal_quality` 是否仍从 adapter 自报并写入 metrics
- [ ] `run_metadata.run_id` 是否在所有 artifact 间一致
- [ ] 新增 artifact 是否同时加入 `REQUIRED_ARTIFACTS` 列表
- [ ] `_partial_run_result` 恢复逻辑在 adapter 新写入模式变更后是否仍然正确
