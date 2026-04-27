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
- **Tool Design Audit 当前主要是 structural / completeness checks**：检查 `namespace`、`output_contract`、`token_policy`、`side_effects` 等字段是否齐全、值是否合理。它**不读 Python 工具源码、不调用工具看真实输出、不做语义级质量判断**。字段写得齐 ≠ 工具真的好用。语义诱饵（与已有工具职责重叠、声称一步到位的浅封装）当前仍会被判高分，详见 `tests/test_tool_design_audit_decoy_xfail.py`。
- **RuleJudge 不是 LLM Judge**：只做 deterministic rule 匹配；`must_use_evidence` 仍是“包含 evidence id 子串”的轻量校验，不做语义级判定。
- **PythonToolExecutor 的 minimal schema validation 不是完整 JSON Schema**：只覆盖 `required` / `type` / `enum` 三类最容易导致误调用的契约。
- **Eval Generator 不是生产级自动生成器**：`from_tools` 给出可读模板，`from_tests` 仅做静态扫描；候选默认不可运行，需要人工补 fixture/expected_root_cause 才能转正。
- **真实 OpenAI/Anthropic adapter、MCP executor、HTTP/Shell executor、LLM Judge、from_transcripts/from_docs eval 生成、held-out 比较、Web UI 都属未来路线**。

进度与能力边界以 `docs/ROADMAP.md` 为准；架构与失败归因以 `docs/ARCHITECTURE.md` 为准。

## 快速开始

> 第一次接入的团队请先看 [docs/ONBOARDING.md](docs/ONBOARDING.md)（10 分钟接入路径）；
> 常见坏配置对照表见 [examples/bad_configs/README.md](examples/bad_configs/README.md)。

```bash
python -m pytest -q

python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out runs/audit-tools

python -m agent_tool_harness.cli audit-evals \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/audit-evals

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

运行 good/bad replay：

```bash
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo \
  --mock-path good
```

## Artifacts

每次 `run` 都会生成：

- `transcript.jsonl`
- `tool_calls.jsonl`
- `tool_responses.jsonl`
- `metrics.json`
- `audit_tools.json`
- `audit_evals.json`
- `judge_results.json`
- `diagnosis.json`
- `report.md`

这些文件用于复盘 Agent 的真实事件链路。失败时先看 `tool_calls.jsonl` 和 `tool_responses.jsonl`，再看 `judge_results.json` 与 `diagnosis.json`。

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

- `review_status`：当前固定为 `candidate`，需要人工 review 才能转正。
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
     --candidates runs/generate-evals/eval_candidates.from_tools.yaml \
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
- **Artifacts**：列出 9 个文件并指向 [docs/ARTIFACTS.md](docs/ARTIFACTS.md)。

报告永远是派生视图。失败复盘必须回到 `transcript.jsonl` / `tool_calls.jsonl` /
`tool_responses.jsonl` 三件套；详细 schema 见 [docs/ARTIFACTS.md](docs/ARTIFACTS.md)。
