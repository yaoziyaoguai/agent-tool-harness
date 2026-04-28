# Architecture

Agent Tool Harness 的核心链路是：

`Audit -> Generate -> Audit Evals -> Run -> Record -> Judge -> Diagnose -> Report`

这个顺序不是为了流程好看，而是为了避免直接把模型最终回答当成成功证据。先检查工具契约，再生成候选 eval，再审计 eval 质量，最后运行并记录 raw transcript，才能回答 Agent 是否真的会正确使用工具。

## 当前阶段非目标

第二阶段只强化注释、架构文档、Roadmap 和测试纪律，不扩展运行能力。

当前仍然不实现：

- 真实 OpenAI/Anthropic adapter
- MCP/HTTP/Shell executor
- Web UI
- 自动修改用户工具代码
- 复杂 LLM Judge
- 并发执行或大规模 benchmark
- from_transcripts / from_docs 等更强 eval 生成
- held-out vs training 的真实对比与基线 diff

这些能力只能保留在 Roadmap 中，不能以“顺手补齐”的方式进入 MVP 主线。

## 信号质量披露（与 Anthropic 文章方法论的差距）

Anthropic 的 *Writing effective tools for agents* 主张 evaluation 必须由真实 LLM agentic
loop 驱动，从 trajectory 中观察 Agent 是否能正确选用工具。当前 harness 仍只有
`MockReplayAdapter`，它直接把 eval 自带的 `expected_tool_behavior.required_tools` 反向
回放给 RuleJudge，因此 PASS 在结构上是必然的。

为了不让真实团队把这种 PASS 误读为评估信号，框架在 `agent_tool_harness/signal_quality.py`
里定义了显式的 **信号质量等级**：

- `tautological_replay`：当前 MockReplayAdapter 默认等级；
- `rule_deterministic`：未来基于规则但不直接照抄 eval 期望的 adapter；
- `recorded_trajectory`：v0.3 第一项已上线的 `TranscriptReplayAdapter`，
  从已有 run 目录 deterministic 重放，不调 LLM、不调 `registry.execute`；
- `real_agent`：未来真实 OpenAI/Anthropic adapter；
- `unknown`：兜底等级，提醒读者“adapter 未声明”。

`AgentAdapter` 协议要求每个实现显式声明 `SIGNAL_QUALITY`。EvalRunner 把这个标签写入
`metrics.json` 的 `signal_quality` / `signal_quality_note`，MarkdownReport 在报告顶部
渲染为 banner。**任何看到 `tautological_replay` 的 run，PASS/FAIL 都不能作为“工具是否
对真实 Agent 好用”的依据。**

这是 MVP 阶段的诚实披露，不是评分；它只解决“信号边界要不要被显式告知”这一问题。
真正缩小与 Anthropic 文章的差距，需要等真实 LLM adapter（计划见 Roadmap）。

## 证据契约

每次 run 的一手证据是三个 JSONL 文件：

- `transcript.jsonl`：用户、assistant、tool 事件流，服务人工复盘；
- `tool_calls.jsonl`：Agent 发出的结构化工具调用，必须保留原始参数；
- `tool_responses.jsonl`：工具返回的结构化结果，包含 success/content/error/metadata。

其余文件是派生证据：

- `metrics.json`：运行统计；
- `audit_tools.json`：工具设计审计结果；
- `audit_evals.json`：eval 质量审计结果；
- `judge_results.json`：规则判定结果；
- `diagnosis.json`：从 transcript/tool calls 派生的失败解释；
- `report.md`：给人 review 的汇总视图。

报告不能替代 raw artifacts。任何 bug 复盘都应先回到 JSONL。

详细字段约定与排查指引见 [docs/ARTIFACTS.md](ARTIFACTS.md)。

## 候选 eval 审核流程

`EvalGenerator`（`from_tools` / `from_tests`）输出的是 **候选 (candidate)**，不是正式
eval。架构上把“生成”和“转正”刻意分开，是因为：

- 生成阶段没有真实用户上下文，候选必须经过人工 review；
- 框架不能擅自让 candidate 进入 `evals.yaml`，否则会造成 audit/run 阶段的“假信号”；
- 候选携带 `review_status` / `review_notes` / `difficulty` / `runnable` /
  `missing_context` / `source` 字段，专门服务审核流程。

转正流程：

```
generate-evals --source tools|tests
   → 候选 YAML (顶层 key: schema_version / run_metadata / warnings / eval_candidates)
   → 人工补 initial_context / expected_root_cause / judge.rules
   → 把 review_status 改为 "accepted"
   → promote-evals --candidates ... --out evals.promoted.yaml
        （非交互、机械搬运、默认禁覆盖）
   → audit-evals 必须 runnable=true 且 findings 为空
   → 与正式 eval 一起 commit；review_status / review_notes 可保留作审核痕迹
```

CLI **不提供**交互式 reviewer，但 P1B 已落地非交互 promoter；它只做"已审核条目
机械搬运 + 硬约束二次校验"，不做 audit、不改 prompt、不替人决定，也不 fallback
（任何缺字段都拒绝该候选并写明 reason）。完整能力边界见 `docs/ROADMAP.md` 中
"v0.1 — 最小 harness 跑起来" 一节关于 candidate review / promote-evals 的说明，以及
v0.2 backlog 中标注为"P1B"的 promoter 根因约束。

## 模块职责

### config

负责加载 `project.yaml`、`tools.yaml`、`evals.yaml` 并转成 `ProjectSpec`、`ToolSpec`、`EvalSpec`。

不负责审计质量，不执行工具，不判定 eval 成败。

### audit

`ToolDesignAuditor` 按五类 Agent 工具原则审计工具契约：

- right tools
- namespacing
- meaningful context
- token efficiency
- prompt/spec quality

**当前能力边界（重要）：** 这是 **structural / completeness + deterministic 启发式**
检查，不是语义级质量判断。它只读 `tools.yaml` 字段，不读 Python 工具源码、不调用
工具看真实输出。**字段齐全 ≠ 工具好用**。

v0.2 候选 A 已新增 `right_tools.shallow_wrapper`（捷径话术诱饵）/
`right_tools.semantic_overlap`（description+when_to_use 词袋 Jaccard ≥ 0.4 双向重叠）/
`prompt_spec.usage_boundary_duplicated` / `prompt_spec.shallow_usage_boundary` /
`prompt_spec.missing_response_format` 等 finding；`audit_tools.json` 顶层会显式写
`signal_quality: deterministic_heuristic` + `signal_quality_note`，并在命中高严重度信号
时给 `semantic_risk_detected` warning，让 CI/远程消费者一眼看到"score 高 ≠ 没问题"。

仍然存在的根因型 gap：当诱饵工具**字段齐全 + 无捷径话术 + 用完全不同词汇描述与主
工具同一职责**时（词袋几乎不重合），deterministic 启发式仍判 5.0 满分。这一 gap
由 `tests/test_tool_design_audit_subtle_decoy_xfail.py` 用 strict xfail 钉根因，
转正条件需要 transcript-based 工具调用样本或 LLM judge——详见 `docs/ROADMAP.md`。

`EvalQualityAuditor` 审计 eval 是否真实、多步、可验证、不过拟合唯一策略，并检查 split/fixture/runnable。

audit 不运行 Agent，也不调用工具。

### eval_generation

`EvalGenerator` 从 tools 或 tests 生成候选 eval。

它不覆盖正式 `evals.yaml`。候选缺上下文时必须标记 `runnable: false` 和 `missing_context`。

`CandidateWriter` 把候选写盘时会顺手 collect 五类 warning（empty_input /
all_unrunnable / missing_review_notes / high_missing_context /
cheating_prompt_suspect）作为顶层字段，避免审核者只看终端就漏掉质量风险。

`CandidatePromoter` 是非交互转正器：读已审核的候选 YAML，按硬约束
（`review_status="accepted"` / `runnable=true` / `initial_context` 非空 /
`verifiable_outcome.expected_root_cause` 非空 / `judge.rules` 非空）筛掉不合格
条目，把剩下的搬运到 `evals:` 顶层下。**它不做 audit、不改 prompt、不替人下决定**；
拒绝时给出明确 reason，让审核者知道下一步要补什么。默认禁止覆盖已存在文件，需
显式 `--force`。

### artifact_schema

`agent_tool_harness/artifact_schema.py` 定义全框架解析契约的根：

- `ARTIFACT_SCHEMA_VERSION="1.0.0"`：当前版本号；
- `make_run_metadata(...)`：返回带 `run_id`（UUID4，可被
  `AGENT_TOOL_HARNESS_RUN_ID` 环境变量覆盖）/ `generated_at` / `project_name` /
  `eval_count` / `extra` 的 dict；
- `stamp_artifact(payload, run_metadata)`：幂等地把 `schema_version` /
  `run_metadata` 注入到 payload 顶层（**不**包裹原结构，保持下游字段访问路径
  不变）。

raw JSONL 不打戳——事件流逐行独立，加一行假事件会污染时序；它们的字段约定由
`docs/ARTIFACTS.md` 和 schema_version 共同表达。

### tools

`ToolRegistry` 负责按工具名查找 `ToolSpec` 并分发到 executor。

`PythonToolExecutor` 是 MVP 的本地 Python executor，只负责导入函数并调用。

tools 层不负责 Agent 工具选择，也不负责 judge。

### agents

`AgentAdapter` 定义 Agent 行为接口。

`MockReplayAdapter` 提供 `good` 和 `bad` 两条可复现路径：

- good：按 `expected_tool_behavior.required_tools` 调用关键工具，并引用可验证 evidence；
- bad：优先按 judge 的 `forbidden_first_tool` 选择错误首步，模拟可复现失败路径。

MVP 先用 mock/replay，是为了把 recorder、judge、diagnosis、report 做成可测闭环。
MockReplayAdapter 不应硬编码 `examples/runtime_debug` 的工具名；demo 只是配置输入，真实
OpenAI/Anthropic adapter 后续替换 adapter 层即可。

### recorder

`RunRecorder` 负责写：

- `transcript.jsonl`
- `tool_calls.jsonl`
- `tool_responses.jsonl`
- `metrics.json`
- `audit_tools.json`
- `audit_evals.json`
- `judge_results.json`
- `diagnosis.json`
- `report.md`

recorder 不评判好坏。它只保证失败可以复盘。

recorder 的边界非常重要：它不能过滤错误参数，也不能吞掉失败工具响应。错误调用和失败返回本身就是评估证据。

EvalRunner 会在 adapter 抛错、registry 初始化失败或 eval 被 audit 判定不可运行时写入
runner 事件，并继续生成派生 artifacts。这样失败原因不会只停留在 Python traceback 里。

### judges

`RuleJudge` 根据 tool calls、tool responses 和 final answer 做 deterministic 判定。

当前支持：

- `must_call_tool`
- `must_call_one_of`
- `forbidden_first_tool`
- `max_tool_calls`
- `expected_root_cause_contains`
- `must_use_evidence`
- `must_not_modify_before_evidence`
- `evidence_from_required_tools`（v1.0 第一项 deterministic anti-decoy）

**v1.1 第一项受控启动：JudgeProvider abstraction**。
新增 `agent_tool_harness/judges/provider.py` 暴露 `JudgeProvider` Protocol +
`RuleJudgeProvider`（透传 RuleJudge，`mode="deterministic"`）+
`RecordedJudgeProvider`（in-process 字典 dry-run，`mode="dry_run"`）+
`CompositeJudgeProvider`（v1.x 第一轮新增：把 deterministic + advisory 并列，
透传 deterministic 给 `passed`，advisory 信息放进 `extra={agreement,
deterministic_result, advisory_result}`）+ `MissingRecordingError`。第二轮把
provider 接入 EvalRunner：可选 `dry_run_provider` 注入；当配置时
`judge_results.json` 多顶层字段 `dry_run_provider`（含 `schema_version +
results[]`），CLI 增加 `--judge-provider {recorded,composite}
--judge-recording PATH`，`report.md` 新段
`## Dry-run JudgeProvider (advisory only)`。Composite 路径下 `metrics.json`
进一步多 `judge_disagreement = {schema_version, total, agree, disagree,
error, disagreement_rate}` 顶层字段，**优先**按 `entry.agreement` 计数
（advisory vs deterministic 真实分歧）。**deterministic baseline 永远是
ground truth**——dry-run/recorded/composite 结果绝不覆盖 `results[].passed`。
缺 recording / fixture 文件 / 顶层字段时 CLI 立即 exit 2 + 可行动 hint。
契约由 `tests/test_judge_provider_skeleton.py` + `tests/test_eval_runner_judge_provider.py`
共 16 条测试钉死（其中 v1.x 第一轮新增 4 条，含"Composite 路径 monkeypatch
禁用 socket 后仍跑通"的不开网络硬约束）。

**v1.x 第二轮**：再新增 `AnthropicCompatibleJudgeProvider`（同文件）+
`AnthropicCompatibleConfig`（4 个 `AGENT_TOOL_HARNESS_LLM_*` 环境变量；
`__repr__` 屏蔽 api_key 与 base_url）+ `JudgeTransport` Protocol 注入
seam（本轮**只**接受 `FakeJudgeTransport`，无 live HTTP 实现）+ 稳定
**error taxonomy 8 类**（`missing_config / disabled_live_provider /
auth_error / rate_limited / network_error / timeout / bad_response /
provider_error`）+ `_safe_message` 模板化错误消息（绝不 echo raw exception
/ Authorization / response body）。Provider **返回**带 `error_code` 的
`ProviderJudgeResult`（不抛异常）→ EvalRunner 转 `entry.error` →
`judge_disagreement.error` 桶，杜绝吞异常假成功。CLI 新增
`--judge-provider anthropic_compatible_offline`，默认无 env 时不崩溃
（artifact 中 entry.error.type=`missing_config`）。新增 8 条契约测试
`tests/test_anthropic_compatible_provider.py` 钉死：6 类错误脱敏 / 配置
不泄漏 / artifact 不泄漏 fake key/base_url / monkeypatch 禁 socket 仍跑通。
详见 `docs/ROADMAP.md` v1.x 第二轮段、`.env.example` 占位符。

**v1.x 第三轮 / v1.4**：新增 `agent_tool_harness/judges/preflight.py` +
`judge-provider-preflight` CLI —— 真实 LLM judge live **之前**的"本地侧
最后一道闸"。**纯本地、preflight 本身永远不联网、不读取真实 key 值**：
检查 4 项 env 字段齐全度 / `.gitignore` 是否忽略 `.env` / `.env.example`
是否仅含占位符 / 8 类 error taxonomy message 用真实 key/base_url 做泄漏
扫描。输出 `preflight.json` + `preflight.md`，**绝不**写入 api_key /
base_url 字面值。`summary.live_optin_status` 是四态（v1.4 起）：
`disabled / opt_in_incomplete / opted_in_no_transport / live_ready`；只有
四态全绿 + 双标志齐时 `ready_for_live=True`，否则 `False`。**preflight
本身仍不联网**——`ready_for_live=True` 只是给真实用户的"前置条件全部通过"
信号，真实 live HTTP 必须由用户在自己环境主动构造 `LiveAnthropicTransport
(...,live_enabled=True, live_confirmed=True)` 触发（v1.4 已落地骨架与
CLI 入口，详见 `docs/V1_4_LIVE_TRANSPORT_IMPLEMENTATION.md`）。契约由
`tests/test_judge_provider_preflight.py` 13 条测试钉死。

**v1.4 LiveAnthropicTransport + CLI live-ready 入口**：
`agent_tool_harness/judges/provider.py::LiveAnthropicTransport` 是基于
标准库 `http.client` 的真实 HTTPS transport 骨架；默认 `live_enabled=False
or live_confirmed=False` → 立即抛 `disabled_live_provider`，不触碰 socket。
`http_factory` 注入点让 19 条契约测试覆盖全部 HTTP / 异常路径，CI **绝不**
真实联网。CLI `run --judge-provider anthropic_compatible_live` 装配：
fake fixture > LiveAnthropicTransport(双标志) > 永远先过 `missing_config`
硬检查；CI / smoke 用 `--judge-fake-transport-fixture PATH` 注入
`FakeJudgeTransport`。详见 `docs/V1_4_LIVE_TRANSPORT_IMPLEMENTATION.md`。

### diagnose

`TranscriptAnalyzer` 把 raw artifacts（transcript / tool_calls / tool_responses /
judge_results / audit_tools / audit_evals）交叉关联，派生 **failure attribution**：
每条 finding 含 `type / severity / category / evidence_refs / why_it_matters /
suggested_fix / related_tool_or_eval`。当前共 11 类 finding，落到四个 category：

- `tool_design`：工具描述/契约/audit 信号弱（`audit_signal_low` 等）。
- `eval_definition`：eval 写得不完整或 audit 判 not_runnable
  （`weak_eval_definition`、`skipped_non_runnable`、`candidate_not_reviewed`）。
- `agent_tool_choice`：Agent 选错入口、缺关键工具、无 evidence grounding、
  冗余调用（`forbidden_first_tool`、`missing_required_tool`、`wrong_first_tool`、
  `no_evidence_grounding`、`redundant_tool_calls`）。
- `runtime`：链路异常（`runtime_error`、`tool_error`）。

attribution 的设计参考了 LangSmith / LangGraph 的 trace tags、OpenTelemetry 的
span attributes、Anthropic *Writing effective tools for agents* 的失败分类、以及
G-Eval 风格 rubric——但 **本轮明确不引入 LangSmith / OTel SDK / LLM Judge / 
tracing 新依赖**，所有 finding 都是 deterministic 启发式。

边界声明：

- analyzer **不替代 RuleJudge**：PASS/FAIL 仍以 judge 为准，attribution 只解释方向。
- analyzer **不是 LLM Judge**：`root_cause_hypothesis` 是 hypothesis，不是真根因；
  必须按 `evidence_refs` 回到 raw artifact 验证。
- runtime 类 finding 出现时，analyzer 会主动跳过 `agent_tool_choice` 类 finding，
  避免对没机会真实选工具的 eval 错误归因。

#### TraceSignalAnalyzer（v0.2 第三轮新增）

`agent_tool_harness/diagnose/trace_signal_analyzer.py`。它与
`TranscriptAnalyzer` **正交并存**：

- TranscriptAnalyzer 主要消费 `judge.checks`（rule-derived），回答
  "哪些规则失败了 → 归到哪个 category"；
- TraceSignalAnalyzer 直接消费 raw `tool_calls.jsonl` /
  `tool_responses.jsonl` payload + `ToolSpec.output_contract` /
  `when_not_to_use`，回答 "工具是否兑现自己的契约 / 调用模式是否
  浪费 / Agent 是否进入了工具自报的禁用场景"。

输出落到每条 diagnosis 的 `tool_use_signals` 字段（与 `findings` 共存，
**不替换**它），共 5 类 deterministic 信号：

- `tool_result_no_evidence`：output_contract 声明返回 evidence 但响应缺/为空；
- `tool_result_missing_next_action`：契约要 next_action 但响应缺；
- `large_or_truncated_tool_response_without_guidance`：响应大或带截断
  标记，且既无 next_action 也无 token_policy.truncation_guidance；
- `repeated_low_value_tool_call`：同一 (tool_name, arguments) 调 ≥2 次；
- `tool_selected_in_when_not_to_use_context`：工具的 when_not_to_use
  关键词与 eval user_prompt 取交集 ≥2 个。

边界声明（**重要**）：

- 全部 deterministic 启发式，不调 LLM、不调 MCP、不重新执行工具；
- 词袋启发式无法识别"用同义词改写禁用场景"——这类 case 仍由
  strict xfail `tests/test_tool_design_audit_subtle_decoy_xfail.py`
  钉住，等待 v0.3 transcript-based 样本或 LLM judge；
- 阈值（如 `_LARGE_RESPONSE_CHAR_THRESHOLD = 2000` / 关键词命中 ≥2）
  写在模块顶层常量，调整前必须重跑 `tests/test_trace_signal_analyzer.py`
  的反向断言保护 `examples/runtime_debug` 不被误伤；
- 提供 `analyze_run_dir(run_dir, tools=...)` helper 用于对历史 run
  目录独立复盘，并通过 `analyze-artifacts` CLI 暴露给真实用户
  （`agent_tool_harness/cli.py::_analyze_artifacts`，输出
  `tool_use_signals.json` + `tool_use_signals.md`，详见
  `docs/ARTIFACTS.md` 与 README "CLI 用法"段）。CLI 是离线 replay 工具，
  **不**调 LLM、**不**重跑 Agent、**不**重跑工具、**不**替代 RuleJudge。

### reports

`MarkdownReport` 聚合 audit、metrics、judge 和 diagnosis，输出 `report.md`。

报告不隐藏 raw artifacts，review 时仍应回看 JSONL。本轮新增：

- 每个 eval 的 Per-Eval Details 中渲染完整 finding 列表（含 severity、category、
  evidence_refs、suggested_fix）+ root cause hypothesis + what to check next。
- 顶层 **Failure Attribution** 段按 category 聚合所有 eval 的 finding，便于 PR
  review / 周会一眼看到本次 run 的主要痛点类别。
- Methodology Caveats 显式声明"diagnosis 是 deterministic heuristic 不是 LLM Judge"。

## 扩展边界

### Adapter

真实模型接入应实现 `AgentAdapter`，并继续通过 `RunRecorder` 写 transcript/tool calls/tool responses。

计划中的 adapter：

- OpenAI adapter
- Anthropic adapter
- replay transcript adapter

### Executor

新的工具执行方式应实现 `ToolExecutor` 协议并注册到 `ToolRegistry`。

计划中的 executor：

- MCP executor
- HTTP executor
- Shell executor

### Judge

当前只实现 deterministic `RuleJudge`。后续可以新增 LLM Judge，但不能替代 raw transcript 和 deterministic rules。

当前 RuleJudge 已做基础防误判：

- 空 `expected_root_cause_contains` 不会通过；
- `must_use_evidence` 要求最终回答引用工具返回的 evidence id/label；
- `must_not_modify_before_evidence` 优先读取 tool call 上的 `side_effects`。

## 失败归因流程

当一次 eval 失败时，按这个顺序定位：

1. `audit_tools.json`：工具契约是否让 Agent 容易选错或拿不到 evidence；
2. `audit_evals.json`：eval 是否真实、多步、可验证，是否缺 fixture；
3. `tool_calls.jsonl`：第一步工具、调用顺序、参数是否符合任务；
4. `tool_responses.jsonl`：工具是否返回了足够 evidence 和 next_action；
5. `judge_results.json`：具体是哪条规则失败；
6. `diagnosis.json`：失败是否属于错误第一步、缺关键工具、缺 evidence 等结构性问题。

如果只能通过最终回答判断成败，说明 eval 或 judge 还不合格。

## 变更守卫

新增能力前必须回答：

- 它是否扩大了当前 MVP 范围；
- 是否需要新的 adapter/executor/judge 边界；
- 是否会绕过 RunRecorder；
- 是否仍能生成全部 artifacts；
- bad path 是否仍会失败；
- 是否需要更新 Roadmap 和测试纪律文档。

## 为什么不写死用户项目逻辑

这个 harness 是通用框架。用户项目差异必须通过这些方式注入：

- `project.yaml`
- `tools.yaml`
- `evals.yaml`
- adapter
- executor
- judge
- evidence source

`examples/runtime_debug` 只是 demo，不能进入框架核心逻辑。
