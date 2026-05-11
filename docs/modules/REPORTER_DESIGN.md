# Reporter Design（报告器模块设计）

> 本文档描述 agent-tool-harness 中 Reporter（报告器）的设计意图、报告结构、成本追踪与渲染逻辑。
> 在源码中，Reporter 对应 `reports/` 子包：`markdown_report.py` + `cost_tracker.py`。
>
> 面向读者：eval 设计者、Coding Agent、模块维护者。

---

## 一、模块目的

Reporter 模块负责**把一次 run 的所有 artifact 聚合成面向人工 review 的可读摘要**。

它由两部分组成：
- **MarkdownReport**（`markdown_report.py`）：生成 `report.md`，是人工复盘的主要入口
- **CostTracker**（`cost_tracker.py`）：生成 `llm_cost.json`，聚合所有 advisory 的 token usage + 估算成本

核心设计原则：报告是**派生视图**，不能替代 raw JSONL artifacts 作为一手证据。所有判定和指标都从已有 artifact 字段派生，不做二次判定。

---

## 二、MarkdownReport（`markdown_report.py`）

### 2.1 报告结构（6 个必需段）

| 段 | 内容 | 数据来源 |
|----|------|---------|
| **Signal Quality** | adapter 自报的信号质量等级 + 说明 | `metrics.signal_quality` |
| **Methodology Caveats** | 5 条方法论免责声明（RuleJudge 是启发式、MockReplay 不是真实 Agent 等） | 静态文本 |
| **Tool Design Audit** | 工具数量/均分/低分工具/warnings/high-severity findings | `audit_tools.json` |
| **Eval Quality Audit** | eval 数量/均分/not_runnable 列表 | `audit_evals.json` |
| **Agent Tool-Use Eval** | total/passed/failed/skipped/errors + 每条 eval 的 PASS/FAIL 列表 | `metrics.json` |
| **Per-Eval Details** | 每条 eval 的 tool sequence / required tools 状态 / failure attribution / trace signals / next steps | `judge_results.json` + `diagnosis.json` |
| **Dry-run JudgeProvider**（条件渲染） | advisory provider 结果 + disagreement 分歧率 | `judge_results.json::dry_run_provider` |
| **Cost Summary**（条件渲染） | advisory-only token usage + estimated cost | `llm_cost.json` |
| **Failure Attribution** | 所有 eval finding 按 category 分桶聚合 | `diagnosis.json::results` |
| **Artifacts** | 10 个 artifact 文件清单 + 链接到 ARTIFACTS.md | 静态文本 |

### 2.2 渲染方法：`MarkdownReport.render()`

**输入**（keyword-only）：
- `project: dict` — 项目名/领域/描述
- `metrics: dict` — 聚合指标（来自 `EvalRunner._metrics()`）
- `audit_tools: dict` — 工具审计结果
- `audit_evals: dict` — eval 审计结果
- `judge_results: dict` — 判定结果
- `diagnosis: dict` — 诊断结果
- `llm_cost: dict | None` — 成本聚合（可选，保持向后兼容）

**输出**：Markdown 字符串（由 `EvalRunner._write_artifacts` 写入 `report.md`）。

### 2.3 关键设计决策

**可行动性原则**：
每个 eval 在 Per-Eval Details 中渲染：
- Tool sequence（调用了什么，按顺序）
- Required tools OK/Missing 状态
- Forbidden first tool 触发情况
- Max tool calls violation
- Runtime error / skipped reason
- Failure attribution（每 finding 含 severity / category / why_it_matters / suggested_fix / evidence_refs）
- Trace-derived tool-use signals
- Next steps（人类可行动建议）

每段末尾的 next-step 建议基于已有 artifact 字段派生，不引入新判定来源。

**Status 细分（PASS / FAIL / SKIPPED / ERROR）**：

`_derive_status` 把 runner 级异常从 FAIL 中拆出来：
- `eval_not_runnable` → SKIPPED
- `tool_registry_initialization_failed` / `adapter_execution_failed` → ERROR
- 其他 → FAIL

避免读者把"链路异常"误读为"Agent 工具选择失败"。

**Dry-run provider 渲染**：
- 单 advisory 模式：显示 provider/mode/passed/agrees_with_deterministic/rationale
- 多 advisory 模式：显示 majority_passed + vote_distribution + 逐 advisory 展开
- error 条目必须显示 error_code + 脱敏 message + suggested_fix（来自 deterministic 静态表 `_ADVISORY_SUGGESTED_FIX`）
- 段首显式声明"不改变 deterministic pass/fail"

**evidence grounding 结构化渲染**：
- `evidence_grounded_in_decoy_tool`：渲染 cited_refs / cited_tools / required_tools
- `no_evidence_grounding`：区分"工具返回了 evidence 但 Agent 没引用"和"工具根本没返回 evidence"

---

## 三、CostTracker（`cost_tracker.py`）

### 3.1 `build_llm_cost_artifact()`

把 `judge_results.json::dry_run_provider.results[]` 中每条 advisory 的 `usage` / `attempts_summary` / `retry_count` 聚合成 `llm_cost.json`。

**输出 schema**（`COST_SCHEMA_VERSION = 2`）：

| 字段 | 含义 |
|------|------|
| `totals` | 跨所有 advisory 的合计（advisory_count / tokens_in / tokens_out / retry_count_total / error_count / estimated_cost_usd / budget_exceeded_count） |
| `per_eval` | 按 eval_id 分组的 advisory 列表，含 `estimated_cost_usd` / `budget_status` / `cap_breached_by` |
| `cost_unknown_reasons` | "为什么没法算 cost"的去重原因清单 |
| `estimated_cost_usd` | **永远 None**（框架不替你报账承诺；真实数字在 `totals.estimated_cost_usd`） |
| `estimated_cost_note` | 永远含 advisory-only 措辞 |
| `pricing_config` | 回写用户配置的 pricing（方便复盘用哪份价格表） |
| `budget_config` | 回写用户配置的 budget |

### 3.2 关键设计决策

**永不编造数字**：
当 advisory 没有 `usage` 时，不编造数字，而是写 `cost_unknown_reason`。原因分类：
- `"recorded mode does not report token usage"`
- `"offline_fixture without usage field"`
- `"fake_transport response missing usage field"`
- `"advisory errored ({error_code}); no usage available"`

**pricing 只接受用户显式声明**：
- 不提供隐式默认价格（如 Anthropic 官方定价）——避免价格表过时导致误导
- 不匹配的 model 直接写入 `cost_unknown_reasons`，不私自估算
- 只支持 USD currency（MVP 阶段，混 currency 拒绝估算）

**per-eval budget cap**（v1.8）：
- `budget_status ∈ {ok, exceeded, not_applicable}`
- `cap_breached_by` 列出具体哪项 cap 被突破
- cap 是"或"关系——任意一项被破就 `exceeded`
- budget exceeded 是 advisory finding，不中断当前 run

**顶层 `estimated_cost_usd` 永远 None**：
这是故意设计——让顶层永远是"框架不替你报账"承诺，真实聚合数字在 `totals.estimated_cost_usd`。防止任何人误把顶层数字当账单。

---

## 四、核心输入

| 输入 | 来源 | 说明 |
|------|------|------|
| `metrics` | `EvalRunner._metrics()` | 聚合指标 |
| `audit_tools` | `ToolDesignAuditor.audit()` | 工具审计 |
| `audit_evals` | `EvalQualityAuditor.audit()` | eval 审计 |
| `judge_results` | `RuleJudge` + `dry_run_provider` | 判定结果 |
| `diagnosis` | `TranscriptAnalyzer` + `TraceSignalAnalyzer` | 诊断结果 |
| `llm_cost` | `build_llm_cost_artifact()` | 成本聚合（cost_tracker 的输入是 dry_run_results） |
| `pricing` / `budget` | `ProjectSpec`（来自 `project.yaml`） | 可选的定价/预算配置 |

---

## 五、核心输出

- `report.md`（MarkdownReport.render 的字符串输出）— 人工复盘入口
- `llm_cost.json`（build_llm_cost_artifact 的 dict 输出）— 成本追溯 artifact

---

## 六、关键接口

| 接口 | 位置 | 稳定性 |
|------|------|--------|
| `MarkdownReport.render(**kwargs) -> str` | `reports/markdown_report.py:77` | 稳定 |
| `MarkdownReport.REQUIRED_SECTIONS` | `reports/markdown_report.py:68` | 稳定（只增不删） |
| `build_llm_cost_artifact(dry_run_results, pricing, budget) -> dict` | `reports/cost_tracker.py:207` | 实验性（schema 在演进） |
| `COST_SCHEMA_VERSION` | `reports/cost_tracker.py:63` | 稳定（只增不删，SemVer） |
| `_ADVISORY_SUGGESTED_FIX` | `reports/markdown_report.py:9` | 稳定（新增 error_code 时需同步新增映射） |

---

## 七、不负责什么

- ❌ 不重新计算判定（所有判定来自 RuleJudge）
- ❌ 不重新诊断失败（所有诊断来自 TranscriptAnalyzer/TraceSignalAnalyzer）
- ❌ 不调用任何 LLM / 网络 / 外部 API
- ❌ 不做真实计费——`estimated_cost_usd` 永远是 advisory-only，不是账单
- ❌ 不做跨 run 聚合 / dashboard（v1.8 只覆盖单 run 维度）
- ❌ 不提供隐式默认价格（不声明的 model 视为 unknown）
- ❌ 不做 JSON / HTML / PDF 报告变体（当前只有 Markdown）

---

## 八、和其他模块的关系

```
runner/eval_runner.py  →  EvalRunner（调用 MarkdownReport.render + build_llm_cost_artifact）
judges/rule_judge.py  →  JudgeResult（消费判定结果）
judges/provider.py  →  ProviderJudgeResult（消费 advisory 结果）
diagnose/transcript_analyzer.py  →  TranscriptAnalyzer findings（消费诊断结果）
diagnose/trace_signal_analyzer.py  →  TraceSignalAnalyzer signals（消费 trace 信号）
config/project_spec.py  →  ProjectSpec（消费 pricing/budget 配置）
```

报告是只读消费者——它汇总所有 artifact 字段但**不**修改任何 artifact。所有数据都从 JSON/JSONL 中已有字段派生。

---

## 九、测试证明方式

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/test_report.py` | MarkdownReport 渲染正确性、必需段存在、dry_run provider 段渲染、cost summary 段渲染 |
| `tests/test_cost_tracker.py` 系列 | usage 聚合 / pricing 查找 / budget cap 判定 / cost_unknown_reasons |
| `tests/test_markdown_report_*.py` | per-eval detail 段渲染 / failure attribution 段 / evidence grounding 渲染 |

---

## 十、后续实现或重构建议

1. **报告模板化**：当前 `render()` 方法把所有 Markdown 拼接逻辑集中在一个方法里（248 行）。如果未来需要支持多种报告格式（HTML/JSON/PDF），应先把报告结构抽象成中间表示（sections 列表），再分别渲染。

2. **跨 run 成本聚合**：`build_llm_cost_artifact` 当前只覆盖单 run。可新增 `build_project_cost_artifact(run_dirs)` 跨 run 聚合。

3. **交互式报告**：当前是静态 Markdown。未来 Web UI 可让 reviewer 在每条 eval 上展开/折叠 detail、点击 evidence_refs 跳转到 raw JSONL。

4. **per-eval budget hard abort**：当前 budget exceeded 只是 advisory。`project.yaml` 可加 `budget.per_eval.hard_abort: true`。

---

## 十一、Review Checklist（审查清单）

Reporter 模块变更 Review 时，检查以下项：

- [ ] 新增报告段是否仅读取已有 artifact 字段（不引入新判定来源）
- [ ] Methodology Caveats 是否仍反映当前信号质量边界
- [ ] Dry-run provider 段是否仍显式声明"不改变 deterministic pass/fail"
- [ ] Advisory error 条目是否显示 error_code + suggested_fix
- [ ] `_ADVISORY_SUGGESTED_FIX` 表是否覆盖所有新增 error_code
- [ ] Cost Summary 段是否仍声明 "advisory-only"
- [ ] `estimated_cost_usd` 顶层是否仍为 None（且 `estimated_cost_note` 含 advisory-only 措辞）
- [ ] per-eval detail 是否渲染了 evidence_refs（引导读者回 raw artifacts 验证）
- [ ] 新增渲染字段是否做了 None 安全检查（不因缺失字段崩报告整体）
