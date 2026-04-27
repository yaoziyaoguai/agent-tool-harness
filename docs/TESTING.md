# Testing

本项目测试的目标是查出架构边界问题，不是追求表面通过率。

## 测试纪律

不允许：

- 通过放宽断言来追求通过；
- 删除关键断言；
- 把失败测试改成空测试；
- 忽略 bad path；
- 只看 Agent 最终回答，不看 tool calls 和 tool responses。
- 为了让测试通过而降低 artifact 完整性要求；
- 把框架核心写死到 `examples/runtime_debug` 的业务逻辑上。

允许 xfail，但必须满足：

- reason 写清楚为什么现在不能过；
- 写清楚未来转正条件；
- 不能覆盖当前 MVP 必须可运行的能力。

当前 strict xfail 测试（1 个）：

- `tests/test_tool_design_audit_decoy_xfail.py::test_audit_should_flag_semantic_decoy_tool`
  钉住 `ToolDesignAuditor` 不能识别语义诱饵工具的能力 gap。详见 `docs/ROADMAP.md`
  的 “xfail 测试” 章节与转正条件。

## signal_quality 测试纪律

`tests/test_signal_quality.py` 锁定框架级信号质量披露契约：

- `MockReplayAdapter.SIGNAL_QUALITY` 必须是 `tautological_replay`，不允许偷偷升级；
- EvalRunner 必须把 adapter 的 `SIGNAL_QUALITY` 透传到 `metrics.json`；
- MarkdownReport 顶部必须出现 “Signal Quality” 段；
- adapter 没声明时必须兜底 `unknown` 而不是裸崩。

任何修改 `signal_quality` 等级或披露行为的改动都必须同步更新这组测试和
`docs/ROADMAP.md` 的“信号质量”章节。

## 改测试前的判断顺序

当实现和测试冲突时，先判断：

1. 实现是否违反架构边界；
2. 测试是否表达了真实需求；
3. 需求是否缺少清晰边界；
4. 是否需要更新 Roadmap 或 ARCHITECTURE。

只有确认测试本身错误时，才修改测试语义。不能把失败测试改成“永远能过”的占位。

## xfail 模板

未来新增 xfail 时，reason 应包含：

- 当前为什么不能通过；
- 依赖的未来能力；
- 转正条件；
- 为什么不影响当前 MVP 质量门槛。

示例：

```python
@pytest.mark.xfail(
    reason=(
        "需要 TranscriptReplayAdapter 读取真实历史 transcript；"
        "转正条件：replay adapter 进入 P0 当前范围，并有 fixture 覆盖 bad path。"
    )
)
```

## 如何运行

```bash
python -m pytest -q
```

如果安装了 ruff：

```bash
python -m ruff check .
```

如果当前 Python 没有安装 ruff，但项目虚拟环境存在：

```bash
.venv/bin/python -m ruff check .
```

## 覆盖范围

当前测试覆盖：

- `tools.yaml` 加载；
- `evals.yaml` 加载；
- Tool Design Audit 能发现坏工具；
- Eval Quality Audit 能发现弱 eval；
- Eval Generator from_tools 能生成候选 eval，且不生成“请调用某工具”的作弊题；
- Eval Generator from_tests 能抽取 docstring/xfail reason，并标记不可运行候选；
- PythonToolExecutor 能调用 demo 工具；
- RuleJudge good path 成功；
- RuleJudge bad path 失败；
- run 后生成所有 artifacts；
- `report.md` 包含关键章节。
- 文档保留证据契约、非目标范围和 xfail 转正规则；
- 当前阶段没有实现真实模型 adapter、MCP/HTTP/Shell executor 或 Web UI。
- adapter 抛错时 runner 仍生成复盘 artifacts；
- audit 判定不可运行时 runner 不执行 adapter；
- MockReplayAdapter 可使用自定义工具名，不依赖 runtime_debug demo；
- ToolRegistry 对歧义短名不静默覆盖；
- PythonToolExecutor 校验 required/type 并正确绑定单参数函数；
- RuleJudge 拒绝空 root cause 和未引用具体 evidence 的答案。
- loader 支持 tools/evals list root，并对重复 eval id、错误 entry 类型和错误字段类型报 ConfigError。
- candidate 必须保留 candidate/review 语义：`from_tools` / `from_tests` 输出
  必须含 `review_status="candidate"` / `review_notes` (list) / `difficulty` /
  `runnable` / `missing_context` / `source`；不允许生成“请调用某工具”的作弊题。
- report 必须包含 Per-Eval Details 段，并展示 tool sequence、required tools 状态、
  forbidden first tool 触发、max tool calls 违规、runtime/skipped 原因、
  signal_quality 提醒。
- artifact schema 必须有 `docs/ARTIFACTS.md` 文档，并包含全部 9 个 artifact 名称；
  README 与 ARCHITECTURE 必须引用该文档。
- `examples/bad_configs/` 中的每个坏 fixture 必须被 `tests/test_bad_configs.py`
  锁定其错误信息：包括空 tools/evals warn、scalar root、bad entry、duplicate qualified
  tool name（runner 须保全成 `tool_registry_initialization_failed` artifact）、
  duplicate eval id、tool 缺 `when_to_use`/`output_contract` 时的 audit finding、
  eval 缺 `verifiable_outcome` 时被标 `not_runnable`。
- 反补丁回归测试（`tests/test_anti_patch.py`）必须钉住三条根因边界：
  (1) 核心包不允许出现 demo 业务符号（如 `runtime_trace_event_chain` /
  `lookup_session_failure`）——防止 demo bleed 反复回潮；
  (2) `EvalQualityAuditor` 必须给出 `judge.tautological_must_call_tool` finding，
  当 judge 仅有一条 `must_call_tool` 且指向 `required_tools[0]` 时；
  (3) `from_tools` 候选 `review_notes` 必须包含 anti-tautology 提醒文本。
- `tests/test_runnable_and_evidence_grounding.py` 钉住两组根因边界：
  (a) `EvalQualityAuditor.runnable` 必须穿透字段层只看实际值——
  `initial_context: {trace_id: ""}` / `verifiable_outcome: {expected_root_cause: ""}` /
  `expected_tool_behavior: {required_tools: []}` 都必须给针对性 high finding 并标
  not_runnable；`evidence_ids` 可作为 `expected_root_cause` 的合法替代（反补丁对照）；
  (b) `RuleJudge.must_use_evidence` 必须三条同时满足才放行——final answer 含
  `evidence`/`证据`、至少一次成功 tool_response 含非空 evidence id、答案引用其中
  至少一个 id；中文证据路径正常识别；失败工具返回的 evidence 不计入。
- `tests/test_failure_attribution.py` 钉住 6 类 failure attribution 根因边界：
  (1) `forbidden_first_tool`——bad path 第一步命中禁用工具时必须出现 high
  severity / `agent_tool_choice` category finding，且 report 渲染出 Suggested fix；
  (2) `missing_required_tool`——必须把缺失的具体工具名 bind 到 finding 与 report；
  (3) `no_evidence_grounding`——final_answer 含 evidence 关键字但 tool_responses
  为空时必须归因；防止 Agent "嘴上说有证据" 反模式被漏掉；
  (4) `runtime_error`——adapter 抛错必须归到 `runtime` category，并且 analyzer
  **不再**生成 `agent_tool_choice` 类 finding，避免对没机会真实选工具的 eval 误导；
  (5) `skipped_non_runnable`——audit 判 not_runnable 时归到 `eval_definition`
  category 而非 agent 行为；
  (6) 报告必须包含顶层 **Failure Attribution** 段、`Root cause hypothesis`、
  `What to check next`、以及"deterministic heuristic"措辞——防止 diagnosis 被
  误传成"真实根因"或"LLM Judge 输出"。
- `tests/test_p1b_promote_warnings_schema.py` 钉住第八阶段 P1B 三组根因边界：
  (1) **promote-evals 硬约束**——promoter 必须只搬运 `review_status="accepted"`
  + `runnable=true` + `initial_context` 非空 + `verifiable_outcome.expected_root_cause`
  非空 + `judge.rules` 非空的候选；needs_review / rejected / runnable=false /
  缺字段必须被 skip 并写明 reason；默认禁覆盖已有文件，需 `--force`；promoted
  YAML 必须能被 `load_evals()` 直接读，闭环 promote→audit-evals→run；
  (2) **CandidateWriter warnings**——必须能识别并写入 5 类质量警告
  （`empty_input` / `all_unrunnable` / `missing_review_notes` /
  `high_missing_context` / `cheating_prompt_suspect`），且对干净候选不发明假警告
  （防止 warning 通胀降低信号价值）；
  (3) **artifact schema_version 一致性**——run 成功 / 失败两条路径下，metrics /
  audit_tools / audit_evals / judge_results / diagnosis 顶层必须都带
  `schema_version` 与 `run_metadata.run_id`；同一次 run 五份 artifact 共享同一
  `run_id`；CLI audit-tools / audit-evals / generate-evals / promote-evals 输出
  也带戳；CLI promote-evals 0 条 promoted 仍返回 0，遇已有文件返回 2 并提示
  --force（防止退出码语义被悄悄改成"质量不足=失败"）。
- `tests/test_from_tools_judge_quality.py` 钉住"`from_tools` 候选阶段必须默认就降低
  tautological / 自证风险"这条根因（候选 B 转正后的回归保险）：
  (1) 默认 judge 必须含 `must_use_evidence` + `must_not_modify_before_evidence`
  等语义/防御性规则；跑完 EvalQualityAuditor 不应再被报
  `judge.tautological_must_call_tool`；
  (2) 默认 `success_criteria` 必须含反 tautology 文案；新增 finding
  `verifiability.success_criteria_only_required_tools` 必须能识别"只把
  required_tools 复述成准则"的伪装，但**不**误伤含 evidence/根因/行为关键词的
  正常 eval；
  (3) 工具契约缺关键字段（`when_to_use` / `when_not_to_use` / `output_contract` /
  `output_contract.required_fields` 含 `evidence` / `input_schema.properties` 含
  `response_format`）时，候选必须落到 `review_status="needs_review"` +
  `runnable=false`，且能被 promoter 的硬约束自然 skip（reason 包含 review_status）；
  (4) 契约齐全只是缺 fixture/expected_root_cause 时仍保持 `review_status="candidate"`，
  避免错误升级 needs_review；
  (5) `_scrub_cheating_signals` 必须在去工具名之外再兜底替换"动词+工具/tool"共现；
  (6) 治理硬约束：本轮新增/重写的 helper 必须有中文学习型 docstring（关键词扫描），
  防止下次 refactor 把注释一并删掉退化为纯英文 API doc。

## 如何检查 artifacts

运行：

```bash
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-good \
  --mock-path good
```

然后检查：

- `runs/demo-good/transcript.jsonl`
- `runs/demo-good/tool_calls.jsonl`
- `runs/demo-good/tool_responses.jsonl`
- `runs/demo-good/judge_results.json`
- `runs/demo-good/diagnosis.json`
- `runs/demo-good/report.md`

失败时优先看：

1. `tool_calls.jsonl` 的第一步工具；
2. `tool_responses.jsonl` 的 evidence；
3. `judge_results.json` 的 failed checks；
4. `diagnosis.json` 的 first_tool、missing_required_tools、issues。

## Artifact 完整性门槛

一次 `run` 只有同时满足以下条件，才算可复盘：

- 9 个必需 artifacts 全部存在；
- `transcript.jsonl` 非空；
- `tool_calls.jsonl` 非空；
- `tool_responses.jsonl` 非空；
- `judge_results.json` 至少有一条 result；
- `diagnosis.json` 至少有一条 result；
- `report.md` 包含 Tool Design Audit、Eval Quality Audit、Agent Tool-Use Eval、Transcript-derived Diagnosis、Improvement Suggestions。

## good path / bad path

good path：

```bash
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-good \
  --mock-path good
```

预期：

- 第一工具调用 `runtime_trace_event_chain`；
- 再调用 `runtime_inspect_checkpoint`；
- 最终根因为 `input_boundary`；
- RuleJudge 判成功。

bad path：

```bash
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-bad \
  --mock-path bad
```

预期：

- 第一工具调用 `tui_inspect_snapshot`；
- 不调用 `runtime_trace_event_chain`；
- 最终误判为 UI rendering；
- RuleJudge 判失败；
- TranscriptAnalyzer 指出第一步工具错误、缺少关键工具和缺少 evidence。
