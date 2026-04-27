# Artifact Schema 文档

> 本文档面向真实 Agent 团队：在线上接入 agent-tool-harness 后，每次 `run` 都会向
> `--out` 目录写下九个 artifact。这里集中说明字段、用途、失败时如何排查，避免读者
> 把派生视图（report.md/metrics.json）当成一手证据。

## 总览

每次 `agent_tool_harness.cli run` 都必然写入下列九个文件（即使 adapter 抛错、
ToolRegistry 初始化失败、eval 被 audit 判定不可运行，runner 也会兜底写完）。

| 文件 | 类型 | 一句话职责 | 读者优先级（失败复盘） |
|---|---|---|---|
| `transcript.jsonl` | JSONL | 面向人类复盘的事件流；按时间记录 Agent/工具/runner 视角 | ★★★ |
| `tool_calls.jsonl` | JSONL | Agent 发出的结构化工具调用，保留原始参数（含错误参数） | ★★★ |
| `tool_responses.jsonl` | JSONL | 工具返回的结构化证据，含 success/content/evidence | ★★★ |
| `metrics.json` | JSON | 派生统计；包含 signal_quality 能力边界声明 | ★★ |
| `audit_tools.json` | JSON | ToolDesignAuditor 输出（structural-only） | ★★ |
| `audit_evals.json` | JSON | EvalQualityAuditor 输出，含 runnable/findings | ★★ |
| `judge_results.json` | JSON | RuleJudge 对每个 eval 的逐规则结果 | ★★ |
| `diagnosis.json` | JSON | TranscriptAnalyzer 派生的失败现场摘要 | ★★ |
| `report.md` | Markdown | 给人看的汇总视图，**不能替代上面三件套** | ★ |

> 任何只看 `report.md` 或 `metrics.json` 就下结论的复盘都是危险的。raw artifacts
> 才是一手证据。

---

## transcript.jsonl

按时间顺序记录 user / assistant / tool / system / runner 视角的事件。每行一条 JSON。

通用字段：

- `timestamp`：UTC ISO8601；由 `RunRecorder._now()` 生成。
- `eval_id`：所属 eval；用于按 eval 过滤。
- `role`：`user` / `assistant` / `tool` / `system`。
- `type`：常见值有 `prompt`、`thought`、`tool_call`、`tool_response`、
  `final_answer`、`runner_start`、`runner_skip`、`runner_error`。
- `content`：人类可读文字内容（assistant 思考、final answer、错误说明等）。
- `metadata`：可选字典，例如 runner_error 会塞入 `error` 与 `traceback`。

排查指引：

- 看不到 `tool_call`？检查同 eval 下是否有 `runner_skip`（被 audit 判 not runnable）
  或 `runner_error`（adapter 抛错，traceback 在 metadata 里）。
- final_answer 没有引用 evidence？同步检查 `tool_responses.jsonl` 里
  `response.content.evidence` 是否真的有内容。

## tool_calls.jsonl

Agent 实际发出的工具调用流水。每行一条。

通用字段：

- `timestamp`、`eval_id`。
- `call_id`：`{eval_id}-call-{N:03d}`，与 `tool_responses.jsonl` 中同名字段对齐。
- `tool_name`、`namespace`：来自 ToolSpec。
- `arguments`：dict；**保留原始参数**，错误参数本身就是关键证据。
- `side_effects`：可选；从 ToolSpec 透传，judge 用它判断破坏性顺序。

排查指引：

- 调用顺序错？看 `diagnosis.json` 的 `tool_sequence`，再回到这里看具体 arguments。
- 同一 call_id 找不到 response？说明工具未返回；检查 `tool_responses.jsonl` 是否
  有 `success: false` 记录或干脆缺失（adapter 提前抛错）。

## tool_responses.jsonl

工具返回的结构化证据。每行一条。

通用字段：

- `timestamp`、`eval_id`、`call_id`：与 `tool_calls.jsonl` 配对。
- `tool_name`、`namespace`。
- `response`：dict，约定结构如下：
  - `success`：bool。
  - `content`：dict，常见字段 `evidence`（list of dict，每项含 `id`/`label`/`detail`）、
    `technical_id`、`summary` 等。RuleJudge 的 `must_use_evidence` 会去匹配这些 ID。
  - `error`：可选 dict；`success=false` 时填。
- `latency_ms`、`tokens_estimated`：MVP 留空，未来扩展点。

排查指引：

- `must_use_evidence` 失败？查这里是否真的返回了 `evidence` 列表，或 final_answer
  没有引用这些 ID。
- 工具异常未触发 ERROR？工具异常应以 `success=false` 写入这里，不是抛 Python 异常。

## metrics.json

派生统计 + 能力边界声明。

字段：

- `total_evals`：本次 run 的 eval 总数（含 skipped/error）。
- `runnable_evals`：减去 skipped 的可运行数量。
- `executed_evals`：实际进入 adapter 执行的数量。
- `skipped_evals`：被 EvalQualityAuditor 判 not runnable 的数量。
- `error_evals`：runner/adapter/registry 异常路径的数量。
- `passed` / `failed`：来自 RuleJudge 结果聚合。
- `total_tool_calls`：所有 eval 的工具调用累计。
- **`signal_quality`**：当前 adapter 的信号质量等级，例如 `tautological_replay`、
  `recorded_trajectory`、`real_agent`。
- **`signal_quality_note`**：人类可读说明；提醒读者 PASS/FAIL 的有效边界。

排查指引：

- `signal_quality == tautological_replay` 时，PASS/FAIL **不能**作为“工具对真实
  Agent 好用”的证据，详见 `agent_tool_harness/signal_quality.py` 与 `docs/ROADMAP.md`。

## audit_tools.json

`ToolDesignAuditor` 输出。

字段：

- `summary`：`tool_count`、`average_score`、`low_score_tools`。
- `tools`：每个 tool 的 `tool_name`、`namespace`、`overall_score`、`scores`（按
  right_tools / namespacing / meaningful_context / token_efficiency / spec_quality
  五维）、`findings`（list of dict，含 dimension/severity/message）。

排查指引：

- 全部 5.0 不代表工具好用：当前 audit 仅做 structural / completeness 检查，详见
  README 与 `docs/ROADMAP.md` 的 P0 后续 / 设计债说明。

## audit_evals.json

`EvalQualityAuditor` 输出。

字段：

- `summary`：`eval_count`、`average_score`、`not_runnable`、`low_score_evals`。
- `evals`：每条 eval 的 `eval_id`、`name`、`overall_score`、`scores`（realism /
  multi_step / verifiability / judge_flexibility / split_and_fixture）、`runnable`、
  `findings`。

排查指引：

- runner 是否跑某条 eval 由这里的 `runnable` 决定；要让 candidate 转正，必须先让
  这里 `runnable=true`。

## judge_results.json

RuleJudge 对每个 eval 的逐规则结果。

字段：

- `results`：list；每项含 `eval_id`、`passed`、`checks`。
- `checks[*].rule`：原始规则字典（含 `type` 与具体参数）。
- `checks[*].passed`：bool。
- `checks[*].message`：人类可读说明。

特别说明：runner 级失败会以伪规则形式塞入 `checks`，便于报告统一渲染：

- `eval_not_runnable`：被 EvalQualityAuditor 判跳过。
- `tool_registry_initialization_failed`：ToolRegistry 初始化异常。
- `adapter_execution_failed`：adapter 抛异常。

排查指引：

- 看哪条 check 失败 → 回到 `tool_calls.jsonl` / `tool_responses.jsonl` 找证据。
- 不要把 runner 级失败误读为模型路径错误，先看 `transcript.jsonl` 的 runner_error。

## diagnosis.json

`TranscriptAnalyzer` 派生的失败归因（deterministic heuristic，**不是 LLM Judge**）。

字段（向后兼容字段保留）：

- `results[*].eval_id`、`passed`。
- `first_tool`、`tool_sequence`：实际调用顺序。
- `missing_required_tools`：required 但未调用的工具列表。
- `issues`：list of `{type, message}`，例如 `wrong_first_tool` / `missing_required_tool`
  / `missing_evidence`（**legacy**，新代码请改读 `findings`）。
- `failed_rules`：从 judge 失败 check 中抽出的 message 列表。
- `summary`：拼接后的中文一句话总结。

字段（本轮新增，借鉴 LangSmith trace tags / OpenTelemetry span attributes / Anthropic
*Writing effective tools for agents* 的失败分类，但 **不引入任何依赖**）：

- `findings`：list of failure attribution，每条包含：
  - `type`：finding 类型，当前共 11 类：
    `runtime_error` / `skipped_non_runnable` / `tool_error` / `weak_eval_definition` /
    `audit_signal_low` / `candidate_not_reviewed` / `forbidden_first_tool` /
    `redundant_tool_calls` / `no_evidence_grounding` / `missing_required_tool` /
    `wrong_first_tool`。
  - `severity`：`high` / `medium` / `info`。
  - `category`：`tool_design` / `eval_definition` / `agent_tool_choice` / `runtime`，
    四类对齐 Anthropic 文章的失败来源分类，方便读者一眼看出"该改工具、改 eval、
    改 Agent prompt，还是修运行时"。
  - `evidence_refs`：指向 raw artifact 的可读引用（`<file>#<filter>` 形式），鼓励
    读者**回到一手证据验证**而不是相信 finding 文字。
  - `why_it_matters`：为什么这是真问题；不是单纯重复规则名。
  - `suggested_fix`：可执行的修复方向；不是空话。
  - `related_tool_or_eval`：finding 关联的工具或 eval id（可空）。
- `category_summary`：`{category: count}` 聚合，便于 CI grep。
- `root_cause_hypothesis`：一句话方向性结论（**hypothesis，不是真根因**）。
- `suggested_fixes`：去重后的全部 suggested_fix 列表。
- `what_to_check_next`：建议优先看的 raw artifact 路径列表。
- `diagnosis_kind`：固定为 `"deterministic_heuristic"`，明确告知下游不是 LLM。

排查指引：

- 这是"为什么失败"的方向性提示，不是新的判定来源。如果 diagnosis 与 judge 不一致，
  优先检查 judge 规则与 raw artifacts。
- **不允许把 `root_cause_hypothesis` 当成最终根因**——一定要按 `evidence_refs`
  打开对应 raw artifact 验证。
- 未来真实 LLM Judge / trace 接入时，将与 deterministic findings 并列输出，
  而不是替换它们；保留启发式的"可解释、可 grep、零依赖"特性。

## report.md

汇总视图，给人看。包含：

- Signal Quality banner（带 ⚠️）。
- Methodology Caveats（RuleJudge / MockReplayAdapter / Tool Design Audit / 
  TranscriptAnalyzer 的能力边界，**显式声明 diagnosis 是 deterministic heuristic 不是
  LLM Judge**）。
- Tool Design Audit / Eval Quality Audit / Agent Tool-Use Eval 摘要。
- Per-Eval Details：每个 eval 的 status / tool sequence / required tools 状态 /
  forbidden first tool / max tool calls / runtime error / **failure attribution
  (heuristic) / category breakdown / root cause hypothesis / what to check next** /
  next steps。
- Transcript-derived Diagnosis 摘要。
- **Failure Attribution**：跨 eval 按 category 聚合 finding，便于团队会议或 PR
  review 一眼找到主要痛点。
- Improvement Suggestions / Artifacts 列表。

> 任何 `report.md` 中的判定都可以追溯到上述 raw artifacts；遇到不一致以 raw 为准。

---

## 入口与扩展约束

- 字段稳定性：本文档列出的字段是 MVP 阶段的事实约定；新增字段只能扩展、不能改名
  或删除。如需破坏性变更，请同步更新本文档与 `tests/test_artifact_schema_doc.py`。
- 用户项目自定义入口：项目通过 `project.yaml` / `tools.yaml` / `evals.yaml` /
  自定义 ToolSpec.executor 控制行为，不通过修改 artifact 写入流程介入。
- 不在范围内：本文档不描述真实 LLM transcript schema、MCP/HTTP/Shell executor 行为、
  Web UI、LLM Judge；它们都属未来路线，详见 `docs/ROADMAP.md`。
