# agent-tool-harness v1.0 Release Notes

> Release tag: `v1.0`
> Release commit (head at tag time): see `git log v1.0 -1`
> Status: **release-ready** —— v1.0 第一项受控落地：deterministic
> evidence-grounding + anti-decoy 闭环；`run → replay-run → analyze-artifacts`
> 三段产品试用路径全打通

---

## v1.0 是什么 / 不是什么

v1.0 在 v0.3 (`tag v0.3` / commit `7c14782`) 基础上把 harness 的"评判可解释性"
推到 deterministic 范围内可达的最高水位：在不接真实 LLM / MCP / HTTP / Shell
/ Web UI / LLM Judge 的前提下，让 `RuleJudge` 与 `TranscriptAnalyzer` 能识别
**"final_answer 是否真的引用了所需 evidence"**、**"是否被 decoy 工具的输出诱导"**，
并在 `report.md` 的两个段落（Failure Attribution 与 Per-Eval Details）都把
`cited_refs / cited_tools / required_tools / tool_responses_had_evidence /
available_evidence_refs` 等结构化字段直接渲染给真人阅读，让用户在每条 eval
块内就能完成 grounding-failure 复盘，不再需要打开 raw JSONL。

这一轮的设计意图是 **给真实 LLM judge / 真实 Agent adapter 打证据基底**：
deterministic anti-decoy 规则只是 v1.0 在 deterministic 范围内能达到的语义
天花板，再往上必须等真实 transcript 样本与 LLM judge 接入；本轮**不**做后者。

> **v1.0 仍不是真实生产平台**。`evidence_from_required_tools` 是基于
> id/label substring 的 deterministic 匹配，**不是** semantic NLI；
> `MockReplayAdapter` 与 `TranscriptReplayAdapter` 都不调真实 LLM、不调
> `registry.execute`、不发起任何外部副作用；report 中的 grounding bullet 是
> deterministic 启发式，**不是** LLM Judge。详见下文 "Known limitations"。

---

## v1.0 相对 v0.3 的新增能力

### 1. Deterministic anti-decoy evidence grounding（commit `df7276f`）

新增 `RuleJudge.evidence_from_required_tools` 规则 + `TranscriptAnalyzer.
evidence_grounded_in_decoy_tool` finding：

- 规则路由：`evidence_from_required_tools` 检查 `final_answer` 中引用的
  evidence id/label 是否出自 `eval.expected_tool_behavior.required_tools`
  对应工具的真实输出；只引用 decoy 工具输出的 evidence → FAIL，并写入
  结构化 reason；
- TranscriptAnalyzer 联动：当 `final_answer` 引用了某 evidence id，但该 id
  来自非 required_tools → 写出 `evidence_grounded_in_decoy_tool` finding，
  payload 含 `cited_refs / cited_tools / required_tools`；
- `_MIN_EVIDENCE_REF_LEN = 3` 防短串假阳；
- `examples/runtime_debug` 与 `examples/knowledge_search` 的 `evals.yaml`
  已挂上新规则，bad path 在 v1.0 下仍 FAIL（且 finding 类型更精准）。

### 2. Grounding finding 结构化字段 + report 渲染（commit `851aa46`）

`evidence_grounded_in_decoy_tool` 与 `no_evidence_grounding` 在 finding
payload 中**结构化**暴露：

- `cited_refs`：final_answer 实际引用的 evidence id；
- `cited_tools`：这些 id 对应的工具名（用来识别"被 decoy 引导"）；
- `required_tools`：本 eval 应该使用的工具列表；
- `tool_responses_had_evidence` + `available_evidence_refs`：把
  `no_evidence_grounding` 区分成两类修复方向完全不同的子场景
  （工具根本没返回 evidence vs 工具返回了但 final_answer 没引用）。

`MarkdownReport._render_failure_attribution`（聚合段）与
`_render_eval_detail`（per-eval 段）**两段都直接读这些字段渲染**，用户在每条
eval 块内就能复盘，不必跳到聚合段也不必打开 raw JSONL。

### 3. 5 场景 decoy / grounding deterministic baseline（commit `5a10aa4`）

`tests/test_evidence_grounding.py` 覆盖 5 类 deterministic 场景作为 sample
基线：keyword-only / id-not-cited / 正确引用 / decoy-grounded /
forbidden-first-tool 上游链路 / 正向路径。本轮共 +15 测试，全部 deterministic
不依赖任何外部服务。Per-Eval Details 段也渲染 grounding bullet（commit
`5a10aa4`），让真人在 per-eval 视图就能定位 grounding 失败原因。

### 4. CLI flag 一致性 + 三段管线文档（commit `318841a`）

- `replay-run` 现接受 `--run` 作为 `--source-run` 的同义别名，与
  `analyze-artifacts --run` 体验一致；防回归测试钉死契约
  （`tests/test_transcript_replay_adapter.py::test_replay_cli_accepts_run_alias`）。
- `docs/TRY_IT.md` 新增第 10 步「v1.0 grounding bullet 解读」+ 文末
  「三类目录关系（run / replay / analysis）」段（含 ASCII 流图）。
- `docs/ARTIFACTS.md` 同步「三类目录关系」段，明确 run / replay-run /
  analyze-artifacts 三个输出目录互不修改、可作为不可变历史保留。

---

## v1.0 推荐核心命令路径

```bash
# 1) 跑一次源 run（mock_path=bad 触发 grounding 失败）
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools   examples/runtime_debug/tools.yaml \
  --evals   examples/runtime_debug/evals.yaml \
  --out     runs/v10-source-bad --mock-path bad

# 2) deterministic 重放上一步（recorded_trajectory）
python -m agent_tool_harness.cli replay-run \
  --run     runs/v10-source-bad \
  --project examples/runtime_debug/project.yaml \
  --tools   examples/runtime_debug/tools.yaml \
  --evals   examples/runtime_debug/evals.yaml \
  --out     runs/v10-replay-bad

# 3) 离线 trace 信号复盘（与 9-artifact 正交）
python -m agent_tool_harness.cli analyze-artifacts \
  --run     runs/v10-replay-bad \
  --tools   examples/runtime_debug/tools.yaml \
  --evals   examples/runtime_debug/evals.yaml \
  --out     runs/v10-analysis

# 4) 工具设计审计（启发式 + v0.2 候选 A 语义信号）
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out   runs/v10-audit-runtime
```

完整 10 步真人路径见 `docs/TRY_IT.md`。

---

## Known limitations（v1.0 仍不做的事）

- **不接真实 LLM**：所有 Agent 行为来自 `MockReplayAdapter`（结构化复制
  `expected_tool_behavior`）或 `TranscriptReplayAdapter`（重放历史 run）。
  `signal_quality` 字段会写明 `tautological_replay` / `recorded_trajectory`，
  **不是** `real_agent`。
- **不接 MCP / HTTP / Shell executor**：工具执行仍走 in-process registry。
- **不是 LLM Judge**：`RuleJudge.evidence_from_required_tools` 是基于 id/label
  substring 的 deterministic 匹配；语义级"是否真的回答了问题"需要真实
  LLM judge，属 v1.x backlog。
- **不做 Web UI / 平台化**。
- **不自动 patch 用户工具**：ToolDesignAuditor 只输出 finding + suggested_fix，
  不修改用户的 `tools.yaml`。
- **`tests/test_tool_design_audit_subtle_decoy_xfail.py` 1 strict xfail 保留**：
  静态 ToolDesignAuditor 仅看 yaml 字段无法识别 disjoint-vocabulary subtle
  decoy；与本轮 trajectory 级 anti-decoy 互补，转正条件不变（真实 trajectory
  样本聚合 / 真实 LLM judge）。

---

## v1.x / v2 路线（写入 ROADMAP，本轮**不**实现）

- **替代真实 Agent Runtime / SDK**：本项目永远是评估框架，不会变成 LangChain。
- 真实 LLM Judge / 真实 Agent adapter（OpenAI / Anthropic）。
- MCP / HTTP / Shell executor。
- Web UI、并发执行、自动 patch。
- 生产级 semantic evaluation / 自然语言理解万能分类器。
- `replay-run` 自动从 `metrics.json::run_metadata` 解析 project/tools/evals
  路径（前置：先在 `RunRecorder` 写出阶段持久化原始路径）。

详见 `docs/ROADMAP.md` "v1.0 release-readiness backlog" 与"暂不做范围"。

---

## 验证

- `ruff check .`：✅ All checks passed
- `pytest -q`：✅ **203 passed, 1 xfailed**（subtle_decoy strict xfail 预期保留）
- v1.0 release smoke 5 命令（`run --mock-path bad` → `replay-run --run` →
  `analyze-artifacts` → `audit-tools` runtime + knowledge）：✅ 全绿；
  replayed `report.md` 含 grounding bullet
  `Tool returned evidence ([...]) but final_answer did not cite any id/label`。

---

## 相对 v0.3 的 commit 列表（`git log v0.3..v1.0 --oneline`）

```
318841a feat(cli,docs): align replay-run flag and document run/replay/analysis pipeline for v1.0
5a10aa4 test(grounding): add 5-scenario decoy baseline and surface grounding details in per-eval block
851aa46 feat(report): expose evidence grounding cited refs and tool source in findings
df7276f feat(judge): add deterministic anti-decoy evidence grounding
```
