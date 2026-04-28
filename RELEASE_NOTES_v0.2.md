# agent-tool-harness v0.2 Release Notes

> Release tag: `v0.2`
> Release commit (head at tag time): see `git log v0.2 -1` —— 由本轮 release commit 决定
> Status: **release-ready** —— deterministic audit / judge / artifact-replay 能力达到本阶段合理上限

---

## v0.2 是什么 / 不是什么

v0.2 在 v0.1 [`tag v0.1` / commit `2161193`] **最小 harness 闭环**之上，把
deterministic 信号侧做厚：让 `ToolDesignAuditor` 能识别"字段齐但语义低质量 / 浅
封装捷径话术 / 跨工具语义重叠"，让 `TraceSignalAnalyzer` 直接复盘 raw artifact
得出 contract / 调用模式 / 禁用场景违规信号，并把这些信号通过新的
`analyze-artifacts` CLI 暴露给离线 replay 用户、通过 `report.md` 暴露给真人
review。完整试用闭环写在 [`docs/TRY_IT.md`](docs/TRY_IT.md)。

> **v0.2 仍不是真实生产平台**。所有信号都是 **deterministic 启发式**：
> `ToolDesignAuditor` / `EvalQualityAuditor` / `TranscriptAnalyzer` /
> `TraceSignalAnalyzer` 都不调 LLM、不联网、不重新执行真实工具；
> `MockReplayAdapter` 仍按 `expected_tool_behavior.required_tools` 顺序回放，
> 不是真实 Agent；`RuleJudge` 仍不是 LLM Judge；`EvalGenerator` 仍是模板生成
> 不是生产级自动造题。详见下文 "Known limitations / 能力边界"。

---

## v0.2 相对 v0.1 的新增能力

### 1. ToolDesignAuditor — deterministic semantic signals（第一轮，commit `5016660`）

新增 5 类 finding，覆盖"字段齐但语义低质量"反模式：

- `right_tools.shallow_wrapper` —— 工具 description 只复述函数名 / 类型签名，
  缺乏决策上下文；
- `right_tools.semantic_overlap` —— 描述 + when_to_use 与同表其他工具词袋
  Jaccard ≥ 0.4 双向重叠（潜在诱饵 / 工具去重不彻底）；
- `prompt_spec.usage_boundary_duplicated` —— `when_to_use` 与 `when_not_to_use`
  描述重复或互相 contradicting；
- `prompt_spec.shallow_usage_boundary` —— 边界描述过短无可执行信息；
- `prompt_spec.missing_response_format` —— 工具不声明回参格式让 Agent 难规划。

`audit_tools.json` 顶层加 `signal_quality: deterministic_heuristic` +
`signal_quality_note`；命中高严重度信号时给 `semantic_risk_detected` warning。
v0.1 期间的 `tests/test_tool_design_audit_decoy_xfail.py` 已**转正**为普通 pass
测试；新一层"完全不同词汇描述同一职责的隐蔽诱饵"由 strict xfail
`tests/test_tool_design_audit_subtle_decoy_xfail.py` 钉根因，转正条件需
transcript-based 真实样本或 LLM judge（v0.3 路线）。

### 2. ToolDesignAuditor — actionable principle metadata（第二轮，commit `6a0c6ff`）

每条 finding 补 Anthropic 工具设计原则三元：

- `principle` / `principle_title` —— 把 finding 锚定到 Anthropic 五类原则
  （Right Tools / Namespacing / Meaningful Context / Token Efficiency /
  Prompt Engineer Your Tool Specs）；
- `why_it_matters` —— 一句话解释为什么这是真问题；
- `suggestion` —— 可执行的修复方向。

`MarkdownReport._render_audit_high_severity_findings` 同步渲染 actionable 三元，
并修了之前历史里 `suggested_fix` 字段读不到的 bug。下游 dashboard / CI bot 可在
不依赖任何真实模型的前提下消费这些信号。

### 3. TraceSignalAnalyzer — trace-derived deterministic 信号（第三轮，commit `6fc4e7c`）

新增模块 `agent_tool_harness/diagnose/trace_signal_analyzer.py`，与已有
`TranscriptAnalyzer` **正交并存**（前者消费 `judge.checks` 的 rule-derived
findings，后者消费 raw `tool_calls.jsonl` / `tool_responses.jsonl` payload +
`ToolSpec.output_contract` / `when_not_to_use`）。共 5 类信号：

- `tool_result_no_evidence` (high) —— output_contract 必填 evidence 但响应缺；
- `tool_result_missing_next_action` (medium) —— 同上对 next_action；
- `large_or_truncated_tool_response_without_guidance` (medium) —— JSON > 2000
  字符或带截断标记，且无 next_action 也无 token_policy.truncation_guidance；
- `repeated_low_value_tool_call` (medium) —— 同 (tool_name, args) 调 ≥2 次；
- `tool_selected_in_when_not_to_use_context` (high) —— when_not_to_use 关键词
  与 user_prompt 词袋命中 ≥2 个。

每条 signal 必带 7 字段（`signal_type` / `severity` / `evidence_refs` /
`related_tool` / `related_eval` / `why_it_matters` / `suggested_fix`），由
`tests/test_trace_signal_analyzer.py` 16 unit + e2e 集成断言钉死。
EvalRunner 在 `_diagnose` helper 中合成 TranscriptAnalyzer + TraceSignalAnalyzer
输出，写到 `diagnosis.json` 每条记录的 `tool_use_signals` 字段；`report.md`
Per-Eval Details 段渲染独立 "Trace-derived tool-use signals" 小节。
`_diagnose` 外层包 try/except 失败保全：trace_analyzer 抛异常时塞入一条
`signal_extraction_error` info 信号，不让一条规则 bug 让整份 diagnosis.json 失能。

### 4. analyze-artifacts CLI（commit `761e53e`）

新增 `python -m agent_tool_harness.cli analyze-artifacts --run RUN_DIR
--tools TOOLS_YAML [--evals EVALS_YAML] --out OUT_DIR`。让用户对**任意历史
run 目录**离线复盘 trace 信号，不必重跑 Agent；尤其能给 v0.2 第三轮**之前**
生成的老 run 补上新的 `tool_use_signals` 字段。

输出 2 个新文件：

- `tool_use_signals.json` —— 含 `schema_version` / `run_metadata.extra.command=
  "analyze-artifacts"` / `analyzed_run` / `signals_by_eval` / `signal_count` /
  `analysis_kind="trace_derived_deterministic_heuristic"` + 方法论披露字段；
- `tool_use_signals.md` —— 给人看的 Markdown，按 eval 分组列 severity / why /
  suggested fix / evidence；0 信号时仍输出完整骨架 + "No signals fired" 提示。

错误可行动：`--run` 不存在 / 目录无 JSONL / 不传 `--evals` 全部给 stderr hint，
**不假成功**；由 5 个 e2e 测试钉死（`tests/test_cli_analyze_artifacts.py`，
真实跑 `run` 子命令再跑 `analyze-artifacts`，**不用 mock**）。

### 5. TRY_IT product trial path（commit `cc70868`）

新建 [`docs/TRY_IT.md`](docs/TRY_IT.md)：从零开始的 7 步试用闭环
（`audit-tools` → `generate-evals` → `promote-evals` → `audit-evals` →
`run --mock-path good` → `run --mock-path bad` → `analyze-artifacts`），
覆盖路径 A（`runtime_debug`）+ 路径 B（`knowledge_search` 验证"换业务域也能跑"）+
边界声明 + 错误排查。配套 2 个测试钉住闭环顺序 + analyze-artifacts 必传
`--evals`，并把 TRY_IT 加入 `tests/test_doc_cli_snippets.py::DOC_PATHS`，
任何 CLI drift 都会立刻被 CI 抓到。

### 6. ROADMAP 状态同步（commit `bf54dc1`）

把 v0.2 表格行从"启动中"改为"release-readiness 评审中（4 轮已合入）"+
列出全部 commit。

---

## v0.2 完整闭环 commit 链（按 release-ready 顺序）

| # | commit | 摘要 |
|---|---|---|
| 1 | `5016660` | feat: add deterministic tool design semantic signals |
| 2 | `6a0c6ff` | feat(audit): make tool design findings actionable with Anthropic principle metadata |
| 3 | `6fc4e7c` | feat(diagnose): add trace-derived tool-use signal analyzer |
| 4 | `761e53e` | feat(cli): add analyze-artifacts for offline trace signal replay |
| 5 | `cc70868` | docs(tryit): add full v0.2 trial path with analyze-artifacts loop |
| 6 | `bf54dc1` | docs: refresh v0.2 roadmap status to release-readiness |

---

## v0.2 核心命令路径

```bash
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml --out runs/v02-audit-tools

python -m agent_tool_harness.cli generate-evals \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --source tools --out runs/v02-generated/eval_candidates.from_tools.yaml

python -m agent_tool_harness.cli promote-evals \
  --candidates runs/v02-generated/eval_candidates.from_tools.yaml \
  --out runs/v02-promoted/evals.promoted.yaml

python -m agent_tool_harness.cli audit-evals \
  --evals examples/runtime_debug/evals.yaml --out runs/v02-audit-evals

python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/v02-good --mock-path good

python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/v02-bad --mock-path bad

python -m agent_tool_harness.cli analyze-artifacts \
  --run runs/v02-bad \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/v02-analysis
```

`examples/knowledge_search/` 也可以同等替换 `--tools` / `--evals` /
`--project`，验证核心 harness 不与单一业务领域耦合。

---

## v0.2 artifacts / report 变化

- `diagnosis.json` 每条 `eval_diagnoses` 记录新增 `tool_use_signals` 数组
  （字段契约见 `docs/ARTIFACTS.md` 同名段）；
- `audit_tools.json` 每条 finding 新增 `principle` / `principle_title` /
  `why_it_matters` / `suggestion`；高严重度时顶层有 `semantic_risk_detected`；
- `report.md` Per-Eval Details 段新增 "Trace-derived tool-use signals" 小节，
  方法论披露段（Methodology Caveats）保持声明 deterministic / 非 LLM Judge；
- 新增独立 artifact `tool_use_signals.json` + `tool_use_signals.md`
  （由 `analyze-artifacts` CLI 写出，**不在 9 个 run artifact 之列**）。

---

## Known limitations / 能力边界（不允许被读者误解为已实现的能力）

- **MockReplayAdapter 不是真实 Agent**。仍按 `eval.expected_tool_behavior.
  required_tools` 顺序回放；`metrics.json` / `report.md` 顶部的
  `signal_quality: tautological_replay` 是显式披露——PASS/FAIL **不能**解读
  为"工具对真实 Agent 好用"。
- **RuleJudge 不是 LLM Judge**。`must_use_evidence` 仍是 substring 启发式，
  升级到 deterministic-strong 是 v0.2 backlog。
- **ToolDesignAuditor / EvalQualityAuditor / TraceSignalAnalyzer 全部是
  deterministic 启发式**，不调 LLM、不重新执行工具。词袋启发式无法识别
  "用同义词改写禁用场景"的诱饵，由 strict xfail
  `tests/test_tool_design_audit_subtle_decoy_xfail.py` 钉根因。
- **EvalGenerator 不是生产级自动造题**。`from_tools` / `from_tests` 给的是
  可读模板，候选默认 `review_status="candidate"` + `runnable=false`，必须
  人工补 fixture / expected_root_cause + 手动改 accepted 才能 promote。
- **PythonToolExecutor 仅做 minimal schema validation**：`required` / `type` /
  `enum` 三类最常见的契约，不是完整 JSON Schema。

---

## 未做能力（明确 v0.2 不做，等 v0.3+）

- 真实 OpenAI / Anthropic adapter；
- LLM Judge；
- MCP / HTTP / Shell executor；
- Web UI；
- `from_docs` / `from_transcripts` eval 生成；
- `TranscriptReplayAdapter`（从已有 JSONL 重放，`signal_quality` 升到
  `recorded_trajectory`）；
- held-out eval 比较；
- 大规模 benchmark；
- 多场景库；
- `from_tools._difficulty` 启发式细化；
- `unused_high_signal_tool` / `candidate_prompt_too_tautological` 信号；
- `RuleJudge.must_use_evidence` 升级为 non-substring deterministic matcher；
- `TranscriptAnalyzer` 在 report.md 加 trajectory 节选块。

---

## 后续路线（v0.3 / v1.0 简述）

- **v0.3** —— 自动化回归 / 场景库 / 真实 Agent Runtime 集成；最早接入面是
  `TranscriptReplayAdapter`（仍 deterministic 但消费真实 trajectory），随后
  才考虑 LLM Judge 与真实 OpenAI/Anthropic adapter。
- **v1.0** —— 稳定可扩展的 Agent Harness 平台。

详见 [`docs/ROADMAP.md`](docs/ROADMAP.md)。

---

## 升级 / 接入指引

- 已用 v0.1 的项目升级到 v0.2 **不需要改 tools.yaml / evals.yaml**：所有新
  finding 都是 `audit_tools.json` / `diagnosis.json` 字段扩展，向后兼容；
- 老 run 想看 trace 信号 → 跑一次 `analyze-artifacts --run OLD_RUN_DIR
  --tools TOOLS --evals EVALS --out NEW_OUT`；
- 想从零试用 v0.2 → 复制粘贴 [`docs/TRY_IT.md`](docs/TRY_IT.md) 路径 A 命令；
- 想接入自家项目 → 参考 [`docs/ONBOARDING.md`](docs/ONBOARDING.md) §1-10。

---

## 测试基线

- `ruff check .` —— All checks passed
- `pytest -q` —— 178 passed, 1 xfailed
  - 唯一 strict xfail：`tests/test_tool_design_audit_subtle_decoy_xfail.py::
    test_audit_should_flag_subtle_semantic_decoy_with_disjoint_vocabulary`
    —— 根因 = deterministic 词袋启发式无法识别同义词改写诱饵，转正条件需
    transcript-based 真实样本或 LLM judge（v0.3）。

---

## 致谢

延续 v0.1 致谢的合作者与 demo 数据贡献者。v0.2 的 trace-derived signal 设计
直接受益于 v0.1 release 后真实 onboarding 走查的反馈，以及 v0.2 候选 A 分支
的提前原型化（虽然该分支未 merge，作为对比基线在 ROADMAP 中归档）。
