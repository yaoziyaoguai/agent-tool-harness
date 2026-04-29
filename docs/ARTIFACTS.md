# Artifact Schema 文档

> 本文档面向真实 Agent 团队：在线上接入 agent-tool-harness 后，每次 `run` 都会向
> `--out` 目录写下十个 artifact（v1.6 起新增 `llm_cost.json`）。这里集中说明字段、
> 用途、失败时如何排查，避免读者把派生视图（report.md/metrics.json）当成一手证据。

## 总览

每次 `agent_tool_harness.cli run` 都必然写入下列十个文件（即使 adapter 抛错、
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
| `llm_cost.json` | JSON | advisory-only 成本预估（v1.6 起每 run 必写；顶层 `estimated_cost_usd` 永远 `null`，**不是真实账单**） | ★ |
| `report.md` | Markdown | 给人看的汇总视图，**不能替代上面三件套** | ★ |

> 任何只看 `report.md` 或 `metrics.json` 就下结论的复盘都是危险的。raw artifacts
> 才是一手证据。

## schema_version 与 run_metadata（最小解析契约）

所有派生 JSON artifact（metrics / audit_tools / audit_evals / judge_results /
diagnosis）以及 `generate-evals` 写出的 `eval_candidates.yaml` 与 `promote-evals`
写出的 `evals.yaml` 片段，**顶层都带两条额外字段**：

- `schema_version`：字符串，当前为 `"1.0.0"`。语义遵循 SemVer：
  - PATCH（1.0.x）：纯字段新增 / 文档补充 / bug 修复，下游无需改动；
  - MINOR（1.x.0）：新增字段或新增 finding 类型，下游兼容老版本仍能解析；
  - MAJOR（x.0.0）：删字段 / 改字段语义 / 改类型，下游必须升级。
- `run_metadata`：dict，至少包含：
  - `run_id`：UUID4，用于把同一次 run 的多份 artifact 串起来复盘；可被环境变量
    `AGENT_TOOL_HARNESS_RUN_ID` 显式覆盖（CI build id 透传）；
  - `generated_at`：UTC ISO8601；
  - `project_name` / `eval_count`：上下文自描述；
  - `extra`：调用方塞少量 hint，例如 `command="run"` / `mock_path="bad"`。

这是**最小解析契约**，**不是** OpenTelemetry / OpenInference / W3C trace context；
不引入任何 SDK，不承担分布式追踪。raw JSONL 不打戳——它们是事件流，逐行独立；
其字段约定由本 schema_version 配合下文字段说明共同表达。完整设计写在
`agent_tool_harness/artifact_schema.py` 的 docstring。

`promote-evals` 输出的 evals.yaml 还会额外带 `promote_summary`：
- `promoted_ids`：被搬运的候选 id 列表；
- `skipped`：list of `{id, reason}`，告诉审核者下一步要补什么。

`generate-evals` 输出的候选文件会额外带 `warnings`：
- 非空时表示候选质量有可见风险（`empty_input` / `all_unrunnable` /
  `missing_review_notes` / `high_missing_context` / `cheating_prompt_suspect`）；
- 仅是提示，不是失败；CLI 退出码仍为 0。

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

- `schema_version`、`run_metadata`：与所有派生 JSON artifact 同模式打戳，
  方便下游版本协商与 run 关联。
- `summary`：
  - `tool_count`、`average_score`、`low_score_tools`；
  - `warnings`（list[str]）：顶层风险信号，例如 `empty_input` 或
    `semantic_risk_detected: <tools>`——CI / 远程消费者一眼看到"score 高 ≠
    没问题"；
  - `signal_quality`（v0.2 候选 A 起）：当前固定为 `deterministic_heuristic`，
    与 MockReplayAdapter 的 `tautological_replay` 同模式披露；
  - `signal_quality_note`：人类可读边界声明，明确 auditor 不读源码、不调用
    工具、不做 LLM 语义判定。
- `tools`：每个 tool 的 `tool_name`、`qualified_name`、`overall_score`、
  `category_scores`（按 right_tools / namespacing / meaningful_context /
  token_efficiency / prompt_spec 五维 = Anthropic 工具设计 5 类原则）、
  `findings`。每条 finding 字段：
  - `rule_id`：唯一规则 id，前缀对应原则；
  - `severity`：`high` / `medium` / `low`；
  - `message`：问题是什么（人类可读）；
  - `suggestion`：怎么修（人类可读）；
  - `principle`（v0.2 第二轮新增）：从 rule_id 派生的原则 token，下游不必
    解析字符串就能按原则归类；
  - `principle_title`（v0.2 第二轮新增）：人类可读的 Anthropic 原则标题
    （例如 "Choosing the right tools (Anthropic principle 1)"）；
  - `why_it_matters`（v0.2 第二轮新增，可选）：为什么必须改——本轮在 high
    severity 关键 finding（`right_tools.shallow_wrapper` /
    `right_tools.semantic_overlap` / `prompt_spec.usage_boundary_duplicated`）
    上首先填充。

排查指引：

- 全部 5.0 仍不代表工具好用：当前 audit 仍是 deterministic 启发式，**不读
  源码、不调用工具、不做 LLM 语义判断**。`signal_quality` 字段由 audit 自报，
  不允许在没有真实 transcript / LLM judge 的情况下偷偷升级。
- 看 `summary.warnings` 是否含 `semantic_risk_detected` —— 这是"score 高但
  仍有高严重度语义信号"的反误读护栏，必须人工 review。
- v0.1 `tests/test_tool_design_audit_decoy_xfail.py` 已被 v0.2 候选 A
  解决并转正为 `tests/test_tool_design_audit_decoy.py`；剩余更深一层
  "字段齐全 + 无捷径话术 + 用完全不同词汇描述同一职责" 的诱饵 gap 由
  `tests/test_tool_design_audit_subtle_decoy_xfail.py` 用 strict xfail 钉
  根因，转正条件需 transcript / LLM judge，详见 `docs/ROADMAP.md`。

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

### 可选字段：`dry_run_provider`（v1.1 第二轮新增）

只有当用户调 `run --judge-provider recorded --judge-recording PATH` 时
才出现的旁路 metadata 段：

```jsonc
{
  "results": [...],                    // v1.0 deterministic baseline，绝不被覆盖
  "dry_run_provider": {
    "schema_version": "1.1.0-skeleton",
    "results": [
      {
        "eval_id": "...",
        "provider": "recorded",        // 当前只有 rule / recorded；未来扩展 mock_llm 等
        "mode": "dry_run",             // deterministic | dry_run | recorded
        "schema_version": "1.1.0-skeleton",
        "deterministic_passed": false, // 与上方 results[].passed 对比用
        "passed": true,                // provider 自报；不会修改 results[].passed
        "agrees_with_deterministic": false,
        "rationale": "...",            // 可选，advisory 文本
        "confidence": 0.9,             // 可选 [0,1]
        "rubric": "..."                // 可选
      },
      {
        "eval_id": "...",
        "provider": "recorded",
        "mode": "dry_run",
        "schema_version": "1.1.0-skeleton",
        "deterministic_passed": false,
        "error": {                     // recording 缺失或 provider 异常
          "type": "missing_recording", // 或 provider_error
          "message": "..."
        }
      }
    ]
  }
}
```

**关键约束（与 v1.0 兼容性挂钩）**：

- 默认 `run` 不带 `--judge-provider` 时该字段**不存在**，与 v1.0 字节兼容；
- `dry_run_provider.results[].passed` **不会**改写 `results[].passed`——
  deterministic baseline 永远是 ground truth；
- 缺 recording 时 entry 必含 `error` 字段，**绝不**伪造 `passed: true`；
- `report.md` 在 `## Dry-run JudgeProvider (advisory only)` 段会显式声明
  "DO NOT change deterministic pass/fail"。

**fixture schema**（`--judge-recording` 接收的 yaml/json）：

```yaml
judgments:
  <eval_id>:
    passed: true|false   # 必填
    rationale: "..."     # 可选
    confidence: 0.9      # 可选 [0,1]
    rubric: "..."        # 可选
```

### v1.x CompositeJudgeProvider 路径（dry-run，仍不接真实 LLM）

当 CLI 用 `--judge-provider composite --judge-recording PATH` 启动时，
`dry_run_provider.results[]` 每条 entry 在 v1.1 第二轮基础上**额外**带：

- `provider="composite"` / `mode="composite"`；
- `passed`：与 deterministic baseline 一致（Composite 透传 deterministic，
  `ProviderJudgeResult.passed` 不会被 advisory 改写）；
- `deterministic_result`: `{provider, mode, passed}`；
- `advisory_result`: `{provider, mode, passed, rationale, confidence, rubric}`；
- `agreement`: bool，**真正**的 deterministic vs advisory 一致性；
- `agrees_with_deterministic`: bool，由于 Composite 透传 deterministic，
  恒为 `true`——分析"与 deterministic 是否分歧"应当读 `agreement`，
  不要读这个字段。

同时 `metrics.json` 多顶层字段 `judge_disagreement`：

```jsonc
{
  "judge_disagreement": {
    "schema_version": "1.1.0-skeleton",
    "total": 1,         // dry_run_results 总条数
    "agree": 0,         // advisory == deterministic 计数
    "disagree": 1,      // advisory != deterministic 计数
    "error": 0,         // 缺 recording / provider 异常计数（不计入分歧率）
    "disagreement_rate": 1.0   // disagree / (agree + disagree); null 表示无有效判定
  }
}
```

`report.md` 的 `## Dry-run JudgeProvider (advisory only)` 段会先打印一条
`Disagreement summary` 概览，再逐条列 `provider_passed / deterministic_passed
/ agrees / advisory=...` 详情；`DO NOT change deterministic pass/fail`
免责声明保留。

**这是 dry-run / advisory，**未接真实 LLM judge，未来真实 provider 落地
所需环境变量（`AGENT_TOOL_HARNESS_LLM_PROVIDER` /
`AGENT_TOOL_HARNESS_LLM_BASE_URL` / `AGENT_TOOL_HARNESS_LLM_API_KEY` /
`AGENT_TOOL_HARNESS_LLM_MODEL`）见仓库根 `.env.example`，当前 v1.x **完全
不读取**这些变量。

### v1.x 第二轮 AnthropicCompatibleJudgeProvider 路径（offline / fake transport）

CLI `--judge-provider anthropic_compatible_offline` 会从 4 个
`AGENT_TOOL_HARNESS_LLM_*` 环境变量读 config（`__repr__` 屏蔽
api_key 与 base_url），并把 provider 包在 `CompositeJudgeProvider` 里。
本轮**仍然没有真实 HTTP 实现**——provider 只能：

- 走 offline_fixture（`--judge-recording PATH`，与 recorded 同 schema），或
- 由测试注入 `FakeJudgeTransport`（in-process）。

每条 entry 在 Composite 段基础上**额外**可能出现：

- `model`: env `AGENT_TOOL_HARNESS_LLM_MODEL` 的值（**不会**写 base_url 与
  api_key 到 artifact）。
- 当 advisory 走错误路径，entry 不带 `passed`，而是带：
  - `error.type` ∈ `missing_config / disabled_live_provider / auth_error /
    rate_limited / network_error / timeout / bad_response / provider_error`；
  - `error.message`：模板化字符串，**绝不**含 raw exception / Authorization
    / response body / api_key / base_url。
- 此时 `metrics.judge_disagreement.error += 1`，**不**计入 `agree/disagree`。

契约由 `tests/test_anthropic_compatible_provider.py` 的 8 条测试钉死，包括
"artifact 不泄漏 fake key/base_url"与"CLI monkeypatch 禁 socket 后仍跑通"
两条不开网络硬约束。

### judge-provider-preflight 输出（live readiness 本地侧自检；v1.4 已扩展为四态）

CLI `python -m agent_tool_harness.cli judge-provider-preflight --out
runs/<dir>` 写出两份 artifact，**纯本地、不联网、不读取真实 key 值**：

- `preflight.json`：结构化结果，schema 由 `PreflightReport` dataclass 锁
  死。顶层字段：`schema_version`（`"1.0.0-preflight"`）、`provider`、
  `live_mode_enabled`（恒 `False`，preflight **本身**永远不联网）、
  `config_status`（仅含 `*_set` 布尔与 `missing_fields` KEY 名列表，**不**
  含值）、`gitignore_status`、`env_example_status`、`provider_self_test`
  （8 类 error taxonomy 全脱敏扫描）、`summary`（`ready_for_live` /
  `config_complete` / `gitignore_safe` / `env_example_safe` /
  `error_taxonomy_safe` / `live_optin_status` / `live_intent` /
  `live_confirmed`）、`actionable_hints`。
- `preflight.md`：人类可读摘要，按"通过 / 警告 / 行动项"分段。

**v1.4 起 `summary.live_optin_status` 是四态**：
- `disabled`：默认；未传 `--live`；
- `opt_in_incomplete`：传了 `--live` 但缺 `--confirm-i-have-real-key`；
- `opted_in_no_transport`：双标志齐但 4 项 safety check 至少一项未绿（仍
  保留 v1.3 字面值兼容）；
- `live_ready`：双标志齐 **且** config_complete + gitignore_safe +
  env_example_safe + error_taxonomy_safe **全绿** → `ready_for_live=True`。
  **preflight 本身仍不联网**——这只是给真实用户的"前置条件全部通过"信号；
  真实 live HTTP 仍需用户在自己环境主动构造 `LiveAnthropicTransport(...,
  live_enabled=True, live_confirmed=True)` 并跑 `run --judge-provider
  anthropic_compatible_live --live --confirm-i-have-real-key`（**不**传
  `--judge-fake-transport-fixture`）才会触发。

**关键安全约束**：本 artifact **绝不**包含 `api_key` / `base_url` /
`model` 字面值。即使 env 已设置真实值，也只反映 `*_set` 布尔。

契约由 `tests/test_judge_provider_preflight.py` 的 13 条测试钉死，包括
"artifact 不泄漏 fake key/base_url/model"、"CLI monkeypatch 禁 socket 后
仍跑通"、"v1.4 live_ready 终态正向案例"三类不开网络硬约束。

## diagnosis.json

`TranscriptAnalyzer` 派生的失败归因（deterministic heuristic，**不是 LLM Judge**）。

### v1.5 第二轮 report.md 多 advisory 渲染（关联 judge_results.json）

`report.md → ## Dry-run JudgeProvider (advisory only)` 段在 v1.5 第二轮起，
对每个 eval 的 multi-advisory 投票额外输出**缩进 sub-bullet**：

- 正常 advisory：`provider/mode passed=... confidence=... rationale=...
  recording_ref=...`；
- 错误 advisory：`error_code: <slug> — <脱敏 message>` + `suggested_fix:
  <静态 deterministic 提示>`，**绝不**写真实 key/url/Authorization。

reviewer 因此不用打开 `judge_results.json` 即可定位"哪条 advisory 与
deterministic 分歧 / 出错的 advisory 该怎么修"。`_ADVISORY_SUGGESTED_FIX`
覆盖 9 类 error_code（missing_recording / missing_config /
disabled_live_provider / 6 类 transport），未识别 → 通用 fallback hint。
契约由 `tests/test_markdown_report_multi_advisory.py` 6 条测试钉死。

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
  - `type`：finding 类型，当前共 12 类：
    `runtime_error` / `skipped_non_runnable` / `tool_error` / `weak_eval_definition` /
    `audit_signal_low` / `candidate_not_reviewed` / `forbidden_first_tool` /
    `redundant_tool_calls` / `no_evidence_grounding` / `missing_required_tool` /
    `wrong_first_tool` / **`evidence_grounded_in_decoy_tool`**（v1.0 第一项新增，
    deterministic anti-decoy：final_answer 引用的 evidence 全部来自非 required 工具
    时触发；与 `must_use_evidence` 通过/失败正交，专门暴露"看似 grounded 实际走错
    路"的 trajectory）。
  - **`evidence_grounded_in_decoy_tool` 专属字段**（v1.0 候选 A）：
    `cited_refs`（list[str]，final_answer 实际引用的 evidence id/label）/
    `cited_tools`（list[str]，这些 evidence 来自的工具名）/
    `required_tools`（list[str]，eval 期望的 required_tools）。report.md 直接读
    这些结构化字段渲染，不解析 evidence_refs 字符串。
  - **`no_evidence_grounding` 专属字段**（v1.0 候选 A）：
    `tool_responses_had_evidence`（bool，区分子场景：True=工具返回了 evidence 但
    Agent 没引用，应改 prompt；False=工具根本没返回 evidence，应改 output_contract）/
    `available_evidence_refs`（list[str]，工具实际可用的 evidence id/label）。
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
- `tool_use_signals`（v0.2 第三轮新增）：list of trace-derived deterministic
  signal，由 `TraceSignalAnalyzer` 直接消费 raw `tool_calls.jsonl` /
  `tool_responses.jsonl` payload + `ToolSpec.output_contract` /
  `when_not_to_use` 派生。**与 `findings` 正交并存**——前者来自 judge 规则，
  本字段来自工具契约 + 调用模式。每条字段：
  - `signal_type`：`tool_result_no_evidence` /
    `tool_result_missing_next_action` /
    `large_or_truncated_tool_response_without_guidance` /
    `repeated_low_value_tool_call` /
    `tool_selected_in_when_not_to_use_context` 之一；
  - `severity`：`high` / `medium` / `info`；
  - `evidence_refs`：指回 `tool_responses.jsonl#call_id=...` /
    `tools.yaml#name=...` 等可 grep 锚点；
  - `related_tool` / `related_eval`：信号关联对象；
  - `why_it_matters` / `suggested_fix`：中文学习型解释 + 可行动建议。
  阈值与边界详见 `agent_tool_harness/diagnose/trace_signal_analyzer.py`
  顶层 docstring。空列表 `[]` 表示分析器没识别到模式异常（**不**等价于
  "工具响应一定健康"——deterministic 启发式有边界）。

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

## llm_cost.json（v1.6 新增）

由 `EvalRunner` 在每次 `run` 子命令产生；从 `judge_results.json::dry_run_provider`
聚合而来，**advisory-only**，不是真实账单。

字段：

- `schema_version`（int，当前 1）：本 artifact schema 版本，"只增不删"承诺。
- `totals`：跨所有 advisory 的合计：
  - `advisory_count`：本 run 共多少条 advisory 结果（按 entry × advisories 展开）；
  - `with_usage_count`：实际带 token usage 的 advisory 条数；
  - `tokens_in` / `tokens_out`：累加（任何缺失字段按 0 计，不 fabricate）；
  - `retry_count_total`：累加 LiveAnthropicTransport retry/backoff 次数；
  - `error_count`：errored advisory 计数（不计入 token）。
- `per_eval`：`[{eval_id, advisories: [{provider, mode, model, usage,
  attempts_summary, retry_count, error_code}]}]`。
- `cost_unknown_reasons`：`[{reason, count}]` 去重列表，解释"为什么没法
  算 cost"（如 ``"recorded mode does not report token usage"``）。
- `estimated_cost_usd`：v1.6 永远 None（v1.7+ 会引入 price 注入）；
- `estimated_cost_note`：明确声明"deterministic stats only;
  advisory-only and MUST NOT be used as a billing source"。

**反模式硬约束**：

- 永远不把 None token 数当 0 后偷偷算成 cost；
- 永远不把 advisory error 漏算到 cost_unknown_reasons；
- 永远不把 raw key / base_url 写入本 artifact——所有 secret 已在
  provider 层脱敏。

排查路径：

- 想知道"这次 run 共调了多少 token / 重试了多少次"？读 `totals`；
- 想知道"为什么没 token 数"？读 `cost_unknown_reasons`；
- 想知道单条 advisory 的 retry 决策？看
  `per_eval[].advisories[].attempts_summary`。

---

## audit_judge_prompts.json / audit_judge_prompts.md（v1.6 `audit-judge-prompts` CLI 输出）

由 `python -m agent_tool_harness.cli audit-judge-prompts --prompts PATH --out DIR` 写出，
对将要发给 LLM Judge 的 prompt + rubric 做 deterministic 启发式安全审计。

输入文件结构（yaml/json 二选一）：

```yaml
prompts:
  - id: my-prompt-1
    prompt: "..."
    rubric: "..."
```

`audit_judge_prompts.json` 字段：

- `summary`：`{prompt_count, finding_count, by_severity:
  {critical, high, medium}}`；
- `findings`：`[{prompt_id, rule_id, severity, description, evidence}]`；
- `rules`：所有 rule_id 的元数据（severity + description）。

7 类启发式 rule_id：

| rule_id | severity | 触发条件 |
| --- | --- | --- |
| `prompt_too_short` | high | prompt 文本 <80 字符 |
| `missing_evidence_refs_placeholder` | high | 未引用 evidence_refs / transcript / artifact 占位 |
| `missing_pass_fail_rubric` | high | rubric 无 PASS/FAIL/通过/失败 关键词 |
| `missing_grounding_requirement` | medium | 未要求模型基于 evidence/事实判断 |
| `contains_key_like_string` | critical | 出现 sk- / Bearer / 长 hex 等 key 字面 |
| `instructs_secret_disclosure` | critical | 引导模型披露 key/secret/credential |
| `advisory_treated_as_truth` | high | 暗示 advisory 输出就是最终结果 |

**硬约束**：

- 启发式 ≠ 语义级安全验证；通过 audit 不代表 prompt 在生产中安全；
- finding 的 `evidence` 字段对 key 字面**自动脱敏**（只保留前 4 字符 +
  长度），任何 audit artifact 都不会把 raw key 写回；
- 本 audit 永远不调 LLM、不联网；可在 CI 任意频次跑。

排查路径：

- critical/high finding 必须在合入新 prompt 前修掉；
- 想理解某条 finding 为什么触发？看 `rules[rule_id].description` + `evidence`；
- 想新增检测规则？编辑 `agent_tool_harness/audit/judge_prompt_auditor.py::_RULES`
  并补对应测试。

---

## tool_use_signals.json / tool_use_signals.md（analyze-artifacts CLI 输出）

由 `python -m agent_tool_harness.cli analyze-artifacts --run RUN_DIR --tools TOOLS_YAML
[--evals EVALS_YAML] --out OUT_DIR` 写出，是离线 trace-derived 信号复盘的产物，
**与 10 个 run artifact 是不同概念**：

- `tool_use_signals.json` 字段：
  - `schema_version` / `run_metadata`（其中 `extra.command="analyze-artifacts"`）；
  - `analyzed_run`：传入的 run 目录路径；
  - `signals_by_eval`：`{eval_id: [signal, ...]}`，每条 signal 字段与
    `diagnosis.json` 的 `tool_use_signals` 完全一致（见上节）；
  - `signal_count`：聚合计数；
  - `analysis_kind`：固定为 `"trace_derived_deterministic_heuristic"`；
  - `analysis_kind_note`：方法论披露——**不是 LLM Judge，不是语义级证明**。
- `tool_use_signals.md`：给人看的 Markdown，按 eval 分组列 severity / why /
  suggested fix / evidence；0 信号时仍输出完整骨架 + "No deterministic
  trace-derived signals fired" 提示。

为什么独立成 CLI 而不是只读 `diagnosis.json`：用户拿到一份历史 run（甚至是 v0.2
第三轮之前生成的老 run），那份 `diagnosis.json` 里**根本没有**新的
`tool_use_signals` 字段；本命令让用户只用 `--run` + `--tools` 就能离线把信号补出来。

边界声明：

- **不**调 LLM、**不**重跑 Agent、**不**重跑工具——纯 replay；
- 不传 `--evals` 时 `tool_selected_in_when_not_to_use_context` 信号会被跳过
  （依赖 `user_prompt`）；CLI 会写 stderr warning 提示；
- 与 `report.md` 的 "Trace-derived tool-use signals" 段相同的信号定义和阈值
  （详见 `agent_tool_harness/diagnose/trace_signal_analyzer.py` 顶层 docstring）。

---

## 入口与扩展约束

- 字段稳定性：本文档列出的字段是 MVP 阶段的事实约定；新增字段只能扩展、不能改名
  或删除。如需破坏性变更，请同步更新本文档与 `tests/test_artifact_schema_doc.py`。
- 用户项目自定义入口：项目通过 `project.yaml` / `tools.yaml` / `evals.yaml` /
  自定义 ToolSpec.executor 控制行为，不通过修改 artifact 写入流程介入。
- 不在范围内：本文档不描述真实 LLM transcript schema、MCP/HTTP/Shell executor 行为、
  Web UI、LLM Judge；它们都属未来路线，详见 `docs/ROADMAP.md`。
- 想要"复制粘贴跑一遍"的最短试用路径（含 `analyze-artifacts` 离线复盘）→
  见 [`docs/TRY_IT.md`](./TRY_IT.md)。

## 三类目录关系（run / replay-run / analyze-artifacts）

CLI 当前对外有三种"输出目录"，承接关系如下；任何一步**不**会修改前一步目录里
的文件，前一步目录可作为不可变历史保留：

```
run --out runs/A          (signal_quality=tautological_replay)
   │  10 个 artifact，含 transcript / tool_calls / tool_responses / metrics / audit_tools / audit_evals / judge_results / diagnosis / llm_cost / report
   ▼
replay-run --run runs/A --out runs/B   (signal_quality=recorded_trajectory，
   │                                    --source-run 与 --run 同义)
   │  从 A 重放出新一份完整 10 个 artifact，PASS/FAIL 由当前规则重新评判，
   │  但 Agent 行为严格来自 A 的 transcript（不调 LLM、不调真实工具）
   ▼
analyze-artifacts --run runs/{A|B} --out runs/C
   │  离线 trace 信号复盘：写出 tool_use_signals.json + tool_use_signals.md，
   │  与 run/replay 的 10 个 artifact 正交（不重新评判，只对 raw payload 做
   │  contract / 模式层信号挖掘）
```

为什么把这三件事拆成独立 CLI：保证每一步都能在没有真实 LLM / 真实工具的环境里
deterministic 复盘；让 CI / PR review / 离线 incident postmortem 都能复用同一套
artifact 而不必重跑 Agent。

---

## replay-run 产物（v0.3 新增 CLI）

由 `python -m agent_tool_harness.cli replay-run --run RUN_DIR
--project ... --tools ... --evals ... --out OUT_DIR` 写出（`--source-run` 是同义
别名，与 `analyze-artifacts --run` 体验一致）。

**与 10 个标准 run artifact 是同一套结构**——`replay-run` 把已有 run 当
"录像带"deterministic 重放，输出目录里仍然是 `transcript.jsonl` /
`tool_calls.jsonl` / `tool_responses.jsonl` / `metrics.json` /
`audit_tools.json` / `audit_evals.json` / `judge_results.json` /
`diagnosis.json` / `llm_cost.json` / `report.md` 一共 10 个 artifact，可以被 `analyze-artifacts`
和任何下游分析继续消费。

但有 4 处与原 run 不同的标记，方便复盘者识别"这是 replay 不是真实 run"：

1. `metrics.json::signal_quality == "recorded_trajectory"`，
   `signal_quality_note` 写明 "Trajectory replayed from a previously
   recorded transcript; useful for regression but not a fresh Agent decision."
2. `transcript.jsonl` 顶部第一条事件是
   `{"role": "system", "type": "runner.replay_summary",
   "metadata": {"source_run": "...", "source_tool_call_count": N,
   "source_tool_response_count": N, "source_transcript_event_count": N,
   "signal_quality": "recorded_trajectory"}}`
3. 每条 `tool_call` / `tool_response` 都带
   `replayed_from = {"source_run": "...", "source_timestamp": "..."}`，
   并保留源的 `call_id`，让 call ↔ response 的关联与源 run 完全一致。
4. 当源 run **缺**某条 eval 的记录时，`transcript.jsonl` 会写一条
   `{"role": "system", "type": "runner.replay_warning"}` 事件，
   `final_answer` 留空，`judge_results.json` 中该 eval deterministic FAIL——
   绝**不**伪造 PASS。

边界声明：

- **不**调 LLM、**不**调 `registry.execute`、**不**发起任何外部副作用。
  工具响应直接来自源 `tool_responses.jsonl`。重新执行 stateful 工具会让
  trajectory 偏离原始证据，违背"录像带"语义。
- 信号质量**不是** `real_agent`——历史 trajectory 不等于"当前模型对当前
  工具集还会做出同样选择"。
- 详细模块边界、未来扩展点（`--diff PREV_RUN` 等）见
  `agent_tool_harness/agents/transcript_replay_adapter.py` 顶层 docstring
  和 `docs/ROADMAP.md` v0.3 段。
