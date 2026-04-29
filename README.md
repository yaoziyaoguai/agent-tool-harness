# Agent Tool Harness

Agent Tool Harness 是一个 **Agent 工具检查、评估集生成与工具使用评估框架**。

它不是普通单测框架，也不是只验证函数能不能跑。它关注的是：工具作为确定性系统和非确定性 Agent 之间的契约，是否足够适合 Agent 使用；eval 是否真实、多步、可验证；Agent 在运行时是否真的按正确证据链调用工具。

本项目吸收 Anthropic Engineering 的工具设计方法论：[Writing effective tools for AI agents—using AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)。MVP 对应五类工具设计原则：

- Choosing the right tools for agents
- Namespacing your tools
- Returning meaningful context from tools
- Optimizing tool responses for token efficiency
- Prompt-engineering tool descriptions and specs

## ⚠️ 当前阶段能力边界（请先看这一段）

Agent Tool Harness 目前是 **MVP**，与 Anthropic 文章方法论存在已知差距：

- **MockReplayAdapter 不是真实 Agent。** 它直接读取 `eval.expected_tool_behavior.required_tools` 并按顺序回放，导致 RuleJudge 的“通过”在结构上是必然的。每次 run 的 `metrics.json` 与 `report.md` 顶部都会显示 `signal_quality: tautological_replay` 的能力边界声明——**PASS/FAIL 不能被解读为“工具对真实 Agent 好用”**。
- **Tool Design Audit 是 deterministic 启发式（v0.2 候选 A 已强化）**：检查字段齐全（`namespace` / `output_contract` / `token_policy` / `side_effects` 等）+ 名称/描述/边界关键词共现，**不读 Python 工具源码、不调用工具看真实输出、不做 LLM 语义判断**。字段写得齐 ≠ 工具真的好用。v0.2 候选 A 已新增 `right_tools.shallow_wrapper`（捷径话术诱饵）/ `right_tools.semantic_overlap`（描述+when_to_use 词袋 Jaccard ≥ 0.4 双向重叠）/ `prompt_spec.usage_boundary_duplicated` / `prompt_spec.shallow_usage_boundary` / `prompt_spec.missing_response_format` 等 finding；audit_tools.json 顶层会写 `signal_quality: deterministic_heuristic` + `signal_quality_note` + 在命中高严重度信号时给 `semantic_risk_detected` warning，让 CI 一眼看到"score 高 ≠ 没问题"。**仍然无法识别**字段齐全、无捷径话术、用完全不同词汇描述同一职责的"隐蔽诱饵"——这是 deterministic 启发式根本限制，由 `tests/test_tool_design_audit_subtle_decoy_xfail.py` 用 strict xfail 钉根因，转正需 transcript-based 样本或 LLM judge（详见 `docs/ROADMAP.md`）。
- **RuleJudge 不是 LLM Judge**：只做 deterministic rule 匹配；`must_use_evidence` 仍是“包含 evidence id 子串”的轻量校验，不做语义级判定。
- **PythonToolExecutor 的 minimal schema validation 不是完整 JSON Schema**：只覆盖 `required` / `type` / `enum` 三类最容易导致误调用的契约。
- **Eval Generator 不是生产级自动生成器**：`from_tools` 给出可读模板，`from_tests` 仅做静态扫描；候选默认不可运行，需要人工补 fixture/expected_root_cause 才能转正。
- **TraceSignalAnalyzer（v0.2 第三轮新增）也只是 deterministic 启发式**：从已有 `tool_calls.jsonl` / `tool_responses.jsonl` payload + `ToolSpec.output_contract` / `when_not_to_use` 复盘出 5 类信号（contract 缺 evidence/next_action / 大响应或截断无指引 / 同 args 重复调用 / when_not_to_use 词袋命中 ≥2）写入 `diagnosis.json` 的 `tool_use_signals` 字段。**不调 LLM、不调 MCP、不重新执行工具、不读自然语言语义**——同义词改写的禁用场景仍会漏。详见 `docs/ARCHITECTURE.md` Diagnose 段。
- **真实 OpenAI/Anthropic adapter、MCP executor、HTTP/Shell executor、LLM Judge、from_transcripts/from_docs eval 生成、held-out 比较、Web UI 都属未来路线**。

进度与能力边界以 `docs/ROADMAP.md` 为准；架构与失败归因以 `docs/ARCHITECTURE.md` 为准。
v0.1 release-ready 摘要见 [`RELEASE_NOTES_v0.1.md`](RELEASE_NOTES_v0.1.md)（commit `0dcb8e7`）。
v0.2 release-ready 摘要见 [`RELEASE_NOTES_v0.2.md`](RELEASE_NOTES_v0.2.md)（trace-derived signals + analyze-artifacts CLI + TRY_IT product trial path）。
v0.3 release-ready 摘要见 [`RELEASE_NOTES_v0.3.md`](RELEASE_NOTES_v0.3.md)（TranscriptReplayAdapter + replay-run CLI；deterministic recorded-trajectory replay）。
v1.0 release-ready 摘要见 [`RELEASE_NOTES_v1.0.md`](RELEASE_NOTES_v1.0.md)（deterministic anti-decoy evidence grounding + grounding/decoy report 渲染 + run/replay/analyze 三段管线对齐）。
v1.1 release-ready 摘要见 [`RELEASE_NOTES_v1.1.md`](RELEASE_NOTES_v1.1.md)（JudgeProvider abstraction + EvalRunner dry-run/recorded provider 集成；不接真实 LLM、不联网、不需要密钥）。

**v1.2 release-ready 摘要见 [`RELEASE_NOTES_v1.2.md`](RELEASE_NOTES_v1.2.md)**（CompositeJudgeProvider + judge_disagreement metrics、AnthropicCompatibleJudgeProvider offline/fake-transport skeleton + 8 类错误 taxonomy 脱敏、`judge-provider-preflight` 本地侧自检 CLI；**仍完全不接真实 LLM、不联网、不需要密钥**）。

> v1.x 第一轮（已合入 main，已被 v1.2 收口）：新增 `CompositeJudgeProvider` + `metrics.json::judge_disagreement` 分歧率统计 + `--judge-provider composite` CLI。
>
> v1.x 第二轮（已合入 main，已被 v1.2 收口）：新增 `AnthropicCompatibleJudgeProvider` offline / fake-transport skeleton + 稳定 error taxonomy（8 类）+ `--judge-provider anthropic_compatible_offline` CLI。
>
> v1.x 第三轮（已合入 main，已被 v1.2 收口）：新增 `judge-provider-preflight` CLI。详见 [`RELEASE_NOTES_v1.2.md`](RELEASE_NOTES_v1.2.md)。
>
> v1.3 第一轮（**已合入 main，待发版**）：`CompositeJudgeProvider` 支持多 advisory majority-vote 聚合（Python API；CLI 留 v1.3 第二轮）；`judge-provider-preflight` 新增 `--live` + `--confirm-i-have-real-key` 双标志契约（**任意组合下都不发任何网络请求**）；新增 `docs/V1_3_LIVE_TRANSPORT_DESIGN.md`（未来 `LiveAnthropicTransport` 仅设计）。**仍完全不接真实 LLM、不联网、不需要密钥**。
>
> v1.4 第一项（**已合入 main，待发版**）：基于 v1.3 设计实现 `LiveAnthropicTransport` 骨架（标准库 `http.client`，**零新增依赖**）；默认完全 disabled，必须 `live_enabled=True` + `live_confirmed=True` + 4 个 env var 完整才有资格调网络；`http_factory` 注入点让 CI / smoke 用 fake connection 覆盖全部错误路径；新增 `docs/V1_4_LIVE_TRANSPORT_IMPLEMENTATION.md`。**CI / smoke 仍完全不联网；任何真实 live 调用必须由用户在自己环境中显式构造 transport 触发**。
>
> v1.4 第二轮（**已合入 main，待发版**）：`run` 子命令新增 `--judge-provider anthropic_compatible_live` + `--live` / `--confirm-i-have-real-key` / `--judge-fake-transport-fixture` 三组旗标；新增 `examples/fake_transport_fixtures/runtime_debug.yaml` 示例 fixture；新增 6 条 CLI 契约测试（含 socket 禁用 + key/url 字面值泄漏扫描）。**CI 仍 0 联网；任何真实 live 必须由用户在自己环境配 env + 双标志 + 不传 fake fixture 才会触发**。
>
> v1.4 release notes：见 [RELEASE_NOTES_v1.4.md](RELEASE_NOTES_v1.4.md)（live-ready fake transport MVP）。
>
> v1.5 第一轮（**已合入 main，待发版**）：`run` 子命令新增 `--judge-advisory NAME:PATH` 可重复 flag，把 v1.3 多 advisory majority-vote Python API 接到 CLI；NAME 仅支持 `recorded` / `anthropic_compatible_offline` / `anthropic_compatible_fake`，**绝不**接受任何 live transport NAME；与 `--judge-provider` 互斥。新增 6 条契约测试。**CI 仍 0 联网；不需要真实密钥**。
>
> v1.5 第二轮（**已合入 main，待发版**）：MarkdownReport 多 advisory 可读性扩展——`report.md` 在 majority/votes 概览下为每条 advisory 输出 `provider/passed/rationale/confidence` 或 `error_code/suggested_fix` 缩进子条目，让 reviewer 不用打开 JSON 即可定位分歧与错误。`_ADVISORY_SUGGESTED_FIX` 静态映射覆盖 9 类 error_code。新增 6 条渲染契约测试。**仍是文档/可读性强化，不是真实 LLM Judge**。
>
> v1.5 release notes：见 [RELEASE_NOTES_v1.5.md](RELEASE_NOTES_v1.5.md)（multi-advisory CLI + report readability MVP）。
>
> v1.6 第一轮（**已合入 main，待发版**）：补齐三处 live readiness 治理空缺——
> (a) `LiveAnthropicTransport` 新增 retry/backoff 治理（默认 `max_attempts=1` 与 v1.5 字节兼容；只对 rate_limited / network_error / timeout 三类做指数退避；非 retryable 永不重试；CI 用 `sleep_fn` 注入 fake clock 钉死序列）；
> (b) 新增 `runs/<dir>/llm_cost.json` artifact + MarkdownReport `Cost Summary` 段，**advisory-only 不是真实账单**，永远不 fabricate token，缺失自动写 `cost_unknown_reason`；
> (c) 新增 `audit-judge-prompts` CLI 子命令 + `agent_tool_harness/audit/judge_prompt_auditor.py` 7 类启发式（含 sk- key 字面、引导泄漏 secret、把 advisory 当 ground truth 等），输出 `audit_judge_prompts.json` + `.md`；附 `examples/judge_prompts.yaml` 示例 fixture。新增 25 条契约测试。**仍 0 新增依赖、CI 0 联网、不调真实 LLM**。
>
> v1.6 release notes：见 [RELEASE_NOTES_v1.6.md](RELEASE_NOTES_v1.6.md)（retry/backoff + cost + judge prompt audit MVP）。

> v1.7 第一轮（**已合入 main**）：product-hardening + release-readiness 治理——
> (a) 新增 [docs/TRY_IT_v1_7.md](docs/TRY_IT_v1_7.md) 端到端串联 v1.6 三件套
> （preflight + audit-judge-prompts + run --mock-path bad + replay-run +
> analyze-artifacts + llm_cost.json）的产品试用路径；
> (b) 新增 `tests/test_docs_cli_snippets.py`，钉死 README/TRY_IT/ONBOARDING
> 中所有 `python -m agent_tool_harness.cli <sub>` 片段必须真实存在 + 关键
> CLI 子命令必须有用户可见文档入口 + ARTIFACTS.md 必须保留 advisory-only
> 措辞，防止 docs ↔ CLI 漂移；
> (c) 新增 `tests/test_artifact_consistency.py`，跨所有 .json artifact 钉死
> `schema_version` 顶层字段必须存在 + 任何 artifact 不得出现 sk- key /
> Authorization Bearer / Bearer token 字面 + `llm_cost.estimated_cost_usd`
> 必须为 null + preflight 默认 `summary.ready_for_live` 必须 false。
> v1.7 release notes：见 [RELEASE_NOTES_v1.7.md](RELEASE_NOTES_v1.7.md)。

> **v2.0 Internal Trial Ready（已 release）**：v2.0 是主线终点，定位为
> **公司内部小团队可以本地 clone / 安装 / 按 [docs/INTERNAL_TRIAL.md](docs/INTERNAL_TRIAL.md)
> 端到端跑通**的离线优先 Agent Tool Evaluation Harness。第一次接入的内部
> 团队请直接进入 [docs/INTERNAL_TRIAL_QUICKSTART.md](docs/INTERNAL_TRIAL_QUICKSTART.md)
> 一页 5 条命令版（10-15 分钟最小闭环），完整版见
> [docs/INTERNAL_TRIAL.md](docs/INTERNAL_TRIAL.md)；想拿一份**统一启动包导航**
> （把定位 / Quickstart / 接入 / 看结果 / 排查 / 命令 / 反馈 / 不包含能力 /
> v3.0 触发条件 / 安全 9 区块串好的 umbrella 页）见
> [docs/INTERNAL_TRIAL_LAUNCH_PACK.md](docs/INTERNAL_TRIAL_LAUNCH_PACK.md)；
> 想拿自己的 AI Tool 自助跑（不依赖 maintainer）见
> [docs/INTERNAL_TEAM_SELF_SERVE_TRIAL.md](docs/INTERNAL_TEAM_SELF_SERVE_TRIAL.md)
> 与 [docs/templates/INTERNAL_TRIAL_REQUEST_TEMPLATE.md](docs/templates/INTERNAL_TRIAL_REQUEST_TEMPLATE.md)；
> 反馈用 [docs/INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md](docs/INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md)
> 提交结构化反馈（含 5 分钟极简版）。
>
> v1.8 起 `project.yaml` 支持 advisory `pricing` + per-eval
> `budget_cap`（max_tokens_total / max_cost_usd）；`runs/<dir>/llm_cost.json`
> 顶层 `estimated_cost_usd` 永远 `null`，明细在 `totals.estimated_cost_usd`，
> 永远是 advisory，**不是真实账单**。
>
> v1.9 起新增 `tests/test_docs_cli_schema_drift.py`（schema-driven CLI
> 片段 drift 检查）+ `tests/test_internal_trial_readiness.py`（v2.0 边界
> 防回归 + 文档诚实性 governance）。
>
> **v2.0 不包含**（属 v3.0+ backlog，**不是**企业级多租户 SaaS、**不是**
> 真实托管 LLM Judge 自动评估服务）：真实 OpenAI/Anthropic live LLM
> Judge 自动评估服务、MCP/HTTP/Shell executor、Web UI、自动 patch 用户工具、
> 大规模 benchmark/leaderboard、托管平台计费。详见
> `docs/ROADMAP.md` "v2.0 不包含" 段。
>
> v2.0 release notes：见 [RELEASE_NOTES_v2.0.md](RELEASE_NOTES_v2.0.md)。

## 快速开始

> **内部小组试用（推荐先看）**：复制 5 条命令跑通 10-15 分钟最小闭环 →
> [docs/INTERNAL_TRIAL_QUICKSTART.md](docs/INTERNAL_TRIAL_QUICKSTART.md)；
> 完整接入路径见 [docs/INTERNAL_TRIAL.md](docs/INTERNAL_TRIAL.md)；
> 拿自己的 AI Tool 自助跑见
> [docs/INTERNAL_TEAM_SELF_SERVE_TRIAL.md](docs/INTERNAL_TEAM_SELF_SERVE_TRIAL.md)。
>
> 第一次接入的开发者团队可看 [docs/ONBOARDING.md](docs/ONBOARDING.md)（10 分钟接入路径）；
> 想直接复制粘贴跑一遍 v0.2 完整闭环（含 `analyze-artifacts`）请看
> [docs/TRY_IT.md](docs/TRY_IT.md)；
> 常见坏配置对照表见 [examples/bad_configs/README.md](examples/bad_configs/README.md)。
>
> 下面命令统一使用 `python -m`，假设你**已经激活当前项目的虚拟环境**
> （例如 `source .venv/bin/activate`）。如果没有虚拟环境，请把 `python` 替换为
> 你自己的解释器路径，例如 `.venv/bin/python`。

```bash
# 0) 健康检查
python -m pytest -q

# 1) 审计工具契约
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out runs/audit-tools

# 2) 从工具生成 eval 候选（候选不是正式 eval，必须 review）
python -m agent_tool_harness.cli generate-evals \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --source tools \
  --out runs/generated/eval_candidates.from_tools.yaml

# 3) 人工 review 候选 → 把合格条目的 review_status 改为 "accepted"
#    （细节见 docs/ONBOARDING.md "如何把候选转成 accepted"；
#     不允许用脚本批量改 status 跳过 review）

# 4) 把 accepted 候选机械搬运成正式 eval
python -m agent_tool_harness.cli promote-evals \
  --candidates runs/generated/eval_candidates.from_tools.yaml \
  --out runs/generated/evals.promoted.yaml

# 5) 审计 promoted（先看刚 promote 出的文件，再回去比对你正式 evals.yaml）
python -m agent_tool_harness.cli audit-evals \
  --evals runs/generated/evals.promoted.yaml \
  --out runs/audit-evals-promoted

# 5b) 顺便审计 demo 自带的正式 evals（用于对照 baseline）
python -m agent_tool_harness.cli audit-evals \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/audit-evals

# 6) 跑 good 路径——预期 PASS
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-good \
  --mock-path good

# 7) 跑 bad 路径——预期 FAIL
#    good 全 PASS、bad 全 FAIL 才能证明 judge 没退化成同义复读；
#    如果两条命令结果一样，先回头看 docs/ONBOARDING.md 第 6 步排查。
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-bad \
  --mock-path bad
```

## 为什么不是普通单测

普通单测通常验证“函数输入 X 是否输出 Y”。Agent tool-use eval 还必须回答：

- Agent 第一步是否选对工具；
- 参数是否来自真实上下文；
- 工具返回了什么 evidence；
- Agent 是否缺少关键工具调用；
- 最终结论是否引用证据；
- judge 规则失败在哪里；
- 失败应归因于工具设计、eval 设计、Agent 路径还是证据处理。

因此每次 run 都生成 raw artifacts，而不是只看最终回答。

## 当前阶段边界

当前代码库仍处于 MVP/治理强化阶段。它只提供可复现的 mock replay 闭环，不接真实模型。

当前不实现真实 OpenAI/Anthropic adapter、MCP/HTTP/Shell executor、Web UI、自动 patch、复杂 LLM Judge、并发执行或大规模 benchmark。这些方向记录在 Roadmap 中，进入实现前需要单独 review。

当前 mock replay 已从 `evals.yaml` 和 `tools.yaml` 推导工具路径，不要求用户项目复用
`examples/runtime_debug` 的工具名；但它仍然只是 deterministic replay，不代表真实模型能力。

## 配置文件

`project.yaml` 描述用户项目：

- `project.name`
- `project.domain`
- `project.description`
- `evidence_sources`
- `domain_taxonomy.issue_categories`
- `domain_taxonomy.evidence_types`

`tools.yaml` 描述工具契约和执行方式：

- `name`
- `namespace`
- `version`
- `description`
- `when_to_use`
- `when_not_to_use`
- `input_schema`
- `output_contract`
- `token_policy`
- `side_effects`
- `executor`

`tools.yaml` 可以使用 `tools: [...]` 包裹，也可以直接使用 list root。结构字段如
`input_schema`、`output_contract`、`token_policy`、`side_effects`、`executor` 必须是 mapping。

`evals.yaml` 描述 eval case：

- `id`
- `name`
- `category`
- `split`
- `realism_level`
- `complexity`
- `source`
- `user_prompt`
- `initial_context`
- `verifiable_outcome`
- `success_criteria`
- `expected_tool_behavior`
- `judge`

`evals.yaml` 可以使用 `evals: [...]` 包裹，也可以直接使用 list root。`id` 必须唯一；
`initial_context`、`verifiable_outcome`、`expected_tool_behavior`、`judge` 必须是 mapping；
`success_criteria`、`missing_context` 必须是 list。

## CLI 用法

> **v2.x bootstrap（可选，加速第一次接入）**：用 ast 静态扫描你的工具源码
> 生成 draft `tools.yaml`（**绝不** import / 执行用户代码、不联网、不读 .env）：
> ```bash
> python -m agent_tool_harness.cli scaffold-tools \
>   --source path/to/your/tool_modules \
>   --out my_team/tools.draft.yaml
> ```
> 输出文件头固定写 `generated draft / review required / does not execute tools
> / does not read secrets / not production-approved`；所有需要业务语义的字段
> （`when_to_use` / `output_contract` / `token_policy` / `side_effects`）一律
> 写 `TODO(reviewer):`。reviewer 补完 TODO → 跑 `audit-tools` 验证 → 才能用于
> 正式 `run`。详见 `agent_tool_harness/scaffold/from_python_ast.py`。
>
> **bootstrap 第二步**（draft tools.yaml → draft evals.yaml + 占位 fixtures）：
> ```bash
> python -m agent_tool_harness.cli scaffold-evals \
>   --tools my_team/tools.draft.yaml \
>   --out my_team/evals.draft.yaml
> python -m agent_tool_harness.cli scaffold-fixtures \
>   --tools my_team/tools.draft.yaml \
>   --out-dir my_team/fixtures.draft
> ```
> 每条 eval `runnable: false` + 业务字段 TODO；每个 fixture 文件头写
> `example only / not real tool output`。reviewer 把 TODO 全部替换成真实业务
> 内容并把 `runnable` 改 true → 跑 `audit-evals` 验证 → 才能用于 `run`。
> 详见 `agent_tool_harness/scaffold/from_tools_yaml.py`。
>
> **bootstrap 第三步**（一眼看出 chain 是否健康 + 还差几步能进入正式 eval）：
> ```bash
> python -m agent_tool_harness.cli validate-generated \
>   --tools my_team/tools.draft.yaml \
>   --evals my_team/evals.draft.yaml \
>   --fixtures-dir my_team/fixtures.draft
> ```
> 校验：YAML 合法、披露行存在、`required_tools` 引用一致、TODO 计数、
> `runnable=true` 残留 TODO（最危险情景）等。`pass`/`warning` → exit 0；
> `fail` → exit 2。详见 `agent_tool_harness/scaffold/validate_generated.py`。
>
> **bootstrap-to-run 完整闭环 sample**（v2.x）：见
> `examples/bootstrap_to_run/`，提供已 review 完的 `tools.reviewed.yaml` /
> `evals.reviewed.yaml` + 安全纯函数 `sample_tools.py`，可直接跑
> `validate-generated --strict-reviewed`（reviewed 契约：TODO=fail / 必须
> 至少 1 条 runnable）+ `run --mock-path good` 出 10 件套 artifact。

审计工具：

```bash
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out runs/audit-tools
```

从工具生成 eval 候选：

```bash
python -m agent_tool_harness.cli generate-evals \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --source tools \
  --out runs/generated/eval_candidates.from_tools.yaml
```

从测试生成 eval 候选：

```bash
python -m agent_tool_harness.cli generate-evals \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --source tests \
  --tests tests/ \
  --out runs/generated/eval_candidates.from_tests.yaml
```

审计 eval：

```bash
python -m agent_tool_harness.cli audit-evals \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/audit-evals
```

运行 good/bad replay（**必须两条都跑**——只跑 good 看不出 judge 是否退化为同义复读）：

```bash
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-good \
  --mock-path good

python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-bad \
  --mock-path bad
```

> `--mock-path good|bad` 选择的是 `MockReplayAdapter` 的回放分支，**好/坏的差异由
> eval 自带的 `expected_tool_behavior` 与 fixture 决定**，不是 CLI 自动制造。
> 在你自家的 eval 上跑 `--mock-path bad` 看到 PASS 通常说明你只写了 good
> fixture——这是 ONBOARDING 走查里最常见的隐性断点。

离线复盘已有 run 的 trace-derived signals（v0.2 第三轮新增 CLI）：

```bash
python -m agent_tool_harness.cli analyze-artifacts \
  --run runs/demo-bad \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-analysis
```

输出：
- `tool_use_signals.json`（带 `schema_version` / `run_metadata` / `signals_by_eval` /
  `analysis_kind=trace_derived_deterministic_heuristic`）；
- `tool_use_signals.md`（按 eval 分组列 severity / why / suggested fix / evidence）。

> 这条命令**只是** replay 已有 raw artifact，**不会**调 LLM、不会重跑 Agent、
> 不会重跑工具。它复用 `TraceSignalAnalyzer` 5 类 deterministic 信号，目的是让
> "拿到一份历史 run（甚至是 v0.2 第三轮之前生成的老 run）" 也能补出 trace 信号。
> `--evals` 是可选的，但不传时 `tool_selected_in_when_not_to_use_context` 信号
> 会被跳过（依赖 `user_prompt`）。

把已有 run 当"录像带"deterministic 重新跑一遍完整 EvalRunner 闭环（v0.3 新增 CLI）：

```bash
python -m agent_tool_harness.cli replay-run \
  --source-run runs/demo-bad \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-replayed-bad
```

输出：与 `run` 命令一样的 10 个 artifact，但 `metrics.signal_quality =
recorded_trajectory`，每条 `tool_call` / `tool_response` 都带
`replayed_from = {source_run, source_timestamp}`，`transcript.jsonl` 顶部
有一条 `runner.replay_summary` 事件标识本次为 replay。

> `replay-run` 严格不调用 LLM、**不调用** `registry.execute`——工具响应
> 直接来自源 `tool_responses.jsonl`。这是"录像带"的本意：重新执行 stateful
> 工具会让 trajectory 偏离原始证据。详细边界见
> `agent_tool_harness/agents/transcript_replay_adapter.py` 顶层 docstring。

## Artifacts

每次 `run` 都会生成（即"完整跑一次 eval"才会有 10 个产物）：

- `transcript.jsonl`
- `tool_calls.jsonl`
- `tool_responses.jsonl`
- `metrics.json`
- `audit_tools.json`
- `audit_evals.json`
- `judge_results.json`
- `diagnosis.json`
- `llm_cost.json`（v1.6 起 advisory-only 成本预估，**不是真实账单**；顶层 `estimated_cost_usd` 永远 `null`）
- `report.md`

这些文件用于复盘 Agent 的真实事件链路。失败时先看 `tool_calls.jsonl` 和 `tool_responses.jsonl`，再看 `judge_results.json` 与 `diagnosis.json`。

> 其它 subcommand 各自只写**一个**文件——它们不是 `run`，不会生成 10 件套：
> `audit-tools` → `audit_tools.json`；`audit-evals` → `audit_evals.json`；
> `generate-evals` → 你 `--out` 指定的 candidates YAML；`promote-evals` → 你
> `--out` 指定的 evals YAML。CLI 在 stdout 会明确打印 `wrote <path>` 自报实际产物。

`metrics.json` 和 `report.md` 顶部还会显示 `signal_quality`（默认值 `tautological_replay`），告诉你“本次 run 的 PASS/FAIL 信号到底是什么级别”。这是当前 MVP 与 Anthropic 文章方法论差距的显式标记，详见 `agent_tool_harness/signal_quality.py` 和 `docs/ROADMAP.md`。

## 如何写自己的 tools.yaml

工具描述应该像教新同事，而不是像给另一个函数写 API 注释。一个合格工具应说明：

- 它适合解决什么真实工作流；
- 什么时候不要用；
- 输入参数的业务语义；
- 输出里的 summary、evidence、next_action、technical_id；
- token 策略，如 pagination/filter/range/max_output_tokens；
- 副作用，如 destructive/open_world_access；
- executor 类型和入口。

## 如何写自己的 evals.yaml

一个强 eval 应该：

- 像真实用户问题，不泄露工具名；
- 需要多步工具调用；
- 有 initial_context 或 fixture；
- 有 verifiable_outcome；
- 允许合理替代路径，避免过拟合唯一调用顺序；
- 用 judge 规则检查 transcript 和 tool calls。

## 生成 eval 候选

`from_tools` 会根据工具契约生成候选 eval，但不会覆盖正式 `evals.yaml`。缺少 fixture 或 expected_root_cause 时会标记 `runnable: false`。

`from_tests` 会扫描 pytest 测试函数名、docstring、xfail reason 和 regression 命名线索。静态扫描无法构造 initial_context 时，也会标记 `runnable: false`。

每个候选额外携带审核字段（详见 `docs/ARTIFACTS.md` 与下面的“候选审核流程”）：

- `review_status`：默认 `candidate`，需要人工 review 后改成 `accepted` 才能 promote；
  当工具契约本身就缺关键字段（`when_to_use` / `output_contract.evidence` /
  `response_format` 等）时，generator 会自动写 `needs_review`，此时正确做法是回
  `tools.yaml` 修工具契约而不是改 eval 绕过——详见
  [docs/ONBOARDING.md §4](docs/ONBOARDING.md) "看到 review_status: needs_review 怎么办"。
  其它合法值：`rejected`（review 后判定不该转正）。promoter 只搬运 `accepted`。
- `review_notes`：审核 checklist；说明候选为什么仍是候选（缺 fixture / 缺 root cause /
  prompt 需要核对真实性等）。
- `difficulty`：把 `complexity` 映射成 `trivial` / `single_step` / `multi_step` /
  `unknown`，便于审核分流。
- `runnable` / `missing_context` / `source`：保持原有语义。

## 候选 eval 审核流程

`generate-evals` 输出的是 **候选 (candidate)**，**不是正式 eval**。框架不会自动把它们
合并进 `evals.yaml`，必须经过下面流程才能转正：

1. **生成**：`agent-tool-harness generate-evals --source tools|tests ...` 写到候选 YAML
   文件（顶层 key 是 `eval_candidates`，与正式 `evals` 区别明显）。文件还会带顶层
   `warnings` 字段，列出可见质量风险（empty_input / all_unrunnable /
   missing_review_notes / high_missing_context / cheating_prompt_suspect）；CLI 同
   时把这些 warning 写到 stderr。
2. **审核**：人工逐条对照 `review_notes`，补 `initial_context` / `expected_root_cause` /
   `judge.rules`，确认 `user_prompt` 真的来自真实用户问题。审核通过后把
   `review_status` 改为 `accepted`（其它合法值 `needs_review` / `rejected` 会被
   promoter 跳过）。
3. **转正（非交互）**：

   ```bash
   python -m agent_tool_harness.cli promote-evals \
     --candidates runs/generated/eval_candidates.from_tools.yaml \
     --out evals.promoted.yaml
   # 默认禁止覆盖；如确实要覆盖加 --force
   ```

   promoter 只搬运 `review_status="accepted"` + `runnable=true` + 字段齐全
   （`initial_context` / `verifiable_outcome.expected_root_cause` /
   `judge.rules` 非空）的候选。每条被 skip 的候选都会在输出文件的
   `promote_summary.skipped` 与 stderr 里给出明确 reason，告诉审核者下一步要补什么。
   即使 0 条搬运也返回退出码 0（"质量不足"≠"CLI 失败"）。
4. **本地验证**：对 promoted YAML 跑 `audit-evals`，确认 `runnable=true` 且 findings
   为空再 merge 进正式 `evals.yaml`。
5. **入库**：与正式 `evals.yaml` 一起 commit；`review_status` / `review_notes` /
   `source` 字段允许保留作为审核痕迹。

详细字段约定与排查指引见 [docs/ARTIFACTS.md](docs/ARTIFACTS.md)；schema_version /
run_metadata 解析契约也在同一文件。

## 如何理解报告

`report.md` 现在包含以下结构：

- **Signal Quality**：本次 run 的信号质量等级与中文警告 banner。
- **Methodology Caveats**：RuleJudge 是启发式 / MockReplayAdapter 是 deterministic
  replay / Tool Design Audit 仅 structural 检查的明确边界声明。
- **Tool Design Audit / Eval Quality Audit / Agent Tool-Use Eval**：摘要。
- **Per-Eval Details**：每个 eval 单独成段，展示 status (PASS/FAIL/SKIPPED/ERROR)、
  tool sequence、required tools 状态、forbidden first tool、max tool calls 违规、
  runtime/skipped 原因、可行动 next steps。
- **Transcript-derived Diagnosis** / **Improvement Suggestions**。
- **Artifacts**：列出 10 个文件并指向 [docs/ARTIFACTS.md](docs/ARTIFACTS.md)。

报告永远是派生视图。失败复盘必须回到 `transcript.jsonl` / `tool_calls.jsonl` /
`tool_responses.jsonl` 三件套；详细 schema 见 [docs/ARTIFACTS.md](docs/ARTIFACTS.md)。
