# Internal Trial Launch Pack — 内部小团队试用启动包

> **入口页（umbrella / 导航页）**。本文不重复 Quickstart 与完整版内容，
> 而是把"启动一个内部小团队试用"所需的全部素材按 9 个固定区块串好，
> 每一区块都直链到现有权威文档。如果你只想**立刻**跑通最小闭环，请
> 直接读 [INTERNAL_TRIAL_QUICKSTART.md](INTERNAL_TRIAL_QUICKSTART.md)。

---

## 0. 一句话定位

agent-tool-harness 是一个 **offline-first / deterministic / replay-first
的 Agent 工具调用评估框架**：用来检查 tool 设计契约、生成 / 审核 eval、
重放 transcript 并复盘 Agent 是否按真实证据链调用工具。

它**不是**：

- ❌ 自动修复用户工具的 patch 工具；
- ❌ 企业级 / 多租户 / 生产级 SaaS（详见 [ROADMAP v2.0 不包含段](ROADMAP.md#v20-不包含的能力一律进-v30--future-backlog不在主线排期)）；
- ❌ 默认启用真实托管 LLM Judge 评估服务（仅本地强 opt-in smoke）；
- ❌ Web UI / MCP / HTTP executor / Shell executor。

主线终点 = **v2.0 Internal Trial Ready**（详见
[ROADMAP v2.0 终点定义](ROADMAP.md#v20-终点定义主线唯一终点避免无限滚版本)）。

---

## 0.5 新同事关键词速懂（每词 1-2 句，看完再读下面）

下面这几个词在后面段落里反复出现；不需要先读 ARCHITECTURE/TESTING，
看完这一节就能继续往下走。

- **replay-first**：默认不调真实 LLM；把"transcript（对话录像带）"
  + `tools.yaml` / `evals.yaml` 离线重放一遍，验证工具调用是否符合
  契约。所以全程**不需要密钥、不联网**。
- **deterministic evidence**：所有 PASS/FAIL/finding 都来自可重复的
  规则（启发式 + transcript 字符串 + JSON schema 校验），相同输入永远
  得到相同输出；**不依赖 LLM 主观判断**。
- **trace-derived signals**：从 transcript（`tool_calls.jsonl` /
  `tool_responses.jsonl`）派生的"工具用得对不对"信号，例如 grounding
  缺失、when_not_to_use 触发、decoy 工具被选中等；写入
  `runs/<dir>/diagnosis.json::tool_use_signals`。
- **failure attribution**：**启发式**地把一次 FAIL 归类到 tool 设计 /
  eval 设计 / Agent 行为 / mock-replay 结构性失败之一；它是**方向性
  结论**，不是真实根因，必须回看 raw artifacts 确认。
- **MockReplayAdapter**：MVP 唯一内置 adapter；把 eval 自己声明的
  `expected_tool_behavior` 当作 Agent 输出**结构性回放**。所以
  `signal_quality = tautological_replay`，PASS 不代表工具好用、FAIL
  不代表工具差。**不是真实 Agent 接入**。
- **judge-provider-preflight**：本地**强 opt-in** live judge readiness
  检查；默认 `ready_for_live = false`，不调任何远端服务。仅用来确认
  `.env` 是否齐、`.gitignore` 是否安全。
- **audit-judge-prompts**：deterministic 启发式审计 judge prompt 文件
  （`examples/judge_prompts.yaml` 风格），**不**调 LLM；只查 prompt
  本身的安全/重叠/缺 rubric 等问题。
- **pricing / budget cap**：在 `project.yaml` 写 `pricing:` 与
  `budget:` 段后，框架会输出 advisory 成本估算到 `llm_cost.json`；
  顶层 `estimated_cost_usd` 永远 null，**不是真实账单**，以 provider
  官方 console 为准。

---

## 1. 10-15 分钟 Quickstart

**试用前 10 项自检（30 秒勾完）**：

- [ ] 我只选了**一个小场景**（不是一上来接整个项目）；
- [ ] 我准备好了 `project.yaml`（可先复制 `examples/runtime_debug/project.yaml`）；
- [ ] 我准备好了 `tools.yaml`（**1 个**真实 tool 起步即可，含 `output_contract` / `when_to_use` / `when_not_to_use`）；
- [ ] 我准备好了 `evals.yaml`（**2-3 个** eval 起步即可）；
- [ ] 我知道输出目录 = `--out runs/<my-name>`，artifact 都落在这里；
- [ ] 我知道人类可读 report 在 `runs/<my-name>/report.md`；
- [ ] 失败时**先看 `report.md` + `diagnosis.json` + `tool_calls.jsonl`**，不是先猜；
- [ ] 我**不会**把真实 API key / Authorization header 粘进 issue / docs / prompt / commit / `runs/` 任何文件；
- [ ] 我**没有**启用 live LLM judge（默认就是 deterministic / offline，不需要做任何事）；
- [ ] 我知道这次反馈**不等于**启动 v3.0（v3.0 触发条件见 §8）。

→ [INTERNAL_TRIAL_QUICKSTART.md](INTERNAL_TRIAL_QUICKSTART.md)

复制 5 条命令、跑通最小闭环、看 3 个 artifact 即结束。全程**离线 /
不调真实 LLM / 不联网 / 不需要密钥**。

---

## 2. 接入你自己项目的最小路径

→ [INTERNAL_TEAM_SELF_SERVE_TRIAL.md](INTERNAL_TEAM_SELF_SERVE_TRIAL.md)
（**内部小组自助试用入口**，10 个问题 Q&A，不依赖 maintainer）
→ [INTERNAL_TRIAL.md §3 接入你自己的工具和 eval](INTERNAL_TRIAL.md#3-接入你自己的工具和-eval)
（更详细的字段说明）
→ [docs/templates/INTERNAL_TRIAL_REQUEST_TEMPLATE.md](templates/INTERNAL_TRIAL_REQUEST_TEMPLATE.md)
（**正式 trial 登记单**，含必填 redaction 自查）

推荐顺序（**不要**一上来接整个项目）：

1. 1 个真实 tool（写 `tools.yaml`，含 `output_contract` / `when_to_use` /
   `when_not_to_use`）；
2. 2-3 个 eval（写 `evals.yaml`，含 `expected_tool_behavior.required_tools`
   与 `must_use_evidence`）；
3. 1 个 `project.yaml` 串起前两个；
4. 跑 `audit-tools` / `audit-evals` 看 deterministic 启发式发现什么；
5. 再用 MockReplayAdapter 跑一次 `run`，**清楚理解 PASS/FAIL 是结构性的**
   （由 [TRY_IT_v1_7.md 反模式提醒](TRY_IT_v1_7.md) 解释根因）。

---

## 3. 如何看结果（report / artifact / failure attribution）

| 看什么 | 在哪 |
|--------|------|
| 顶层结论 + signal_quality 边界声明 | `runs/<dir>/report.md` 顶部 |
| Failure attribution（失败归因到 tool / eval / agent） | `report.md::Failure attribution` 段 |
| 9+ artifact 速查表 | [INTERNAL_TRIAL.md §5.1](INTERNAL_TRIAL.md#51-9-artifact-速查) |
| trace-derived signals（grounding / decoy / when_not_to_use 等） | `runs/<dir>/diagnosis.json::tool_use_signals` |
| RuleJudge / composite judge 判定细节 | `runs/<dir>/judge_results.json` |
| advisory cost + budget cap 状态 | `runs/<dir>/llm_cost.json`（顶层永远 null，**非真实账单**） |
| 完整 artifact schema 与字段含义 | [docs/ARTIFACTS.md](ARTIFACTS.md) |
| trace 信号离线复盘 | `replay-run` + `analyze-artifacts` 两步，详见 [INTERNAL_TRIAL.md §5.2](INTERNAL_TRIAL.md#52-复盘replay-run--analyze-artifacts) |

---

## 4. 失败排查顺序（**不要先猜，按证据链看**）

发现 PASS/FAIL 不可信、命令报错、judge 判定怪时，请按下面顺序逐项排查；
症状 → 先看哪个 artifact 的速查表见
[INTERNAL_TRIAL_QUICKSTART.md §3](INTERNAL_TRIAL_QUICKSTART.md#3-症状--先看哪个-artifact速查)。

1. **CLI stderr / 退出码** — 命令本身是否退出非 0；
2. **`runs/<dir>/report.md`** — 顶层 `signal_quality` 与 `Failure attribution` 段；
3. **`runs/<dir>/diagnosis.json`** — `findings[]` + `tool_use_signals`；
4. **`runs/<dir>/judge_results.json`** — 每条 judge 的 `rationale`；
5. **`runs/<dir>/llm_cost.json`** — advisory cost + budget cap 触发情况；
6. **`runs/<dir>/preflight.json`**（live opt-in 才有） — `summary.ready_for_live` + `actionable_hints`；
7. **`runs/<dir>/transcript.jsonl` / `tool_calls.jsonl` / `tool_responses.jsonl`** —
   真实事件流，**这是最权威的证据**；
8. **回到 `tools.yaml` / `evals.yaml`** — 是不是契约本身写得不对。

---

## 5. 关键命令入口（可复制）

下面所有命令均**不需要真实 key**，全部走 deterministic / advisory 路径。
完整可复制片段见 [INTERNAL_TRIAL.md](INTERNAL_TRIAL.md) 与
[INTERNAL_TRIAL_QUICKSTART.md](INTERNAL_TRIAL_QUICKSTART.md)。

```bash
# 工具设计 deterministic 启发式审计（输出 audit_tools.json）
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out runs/launch-audit-tools

# Eval 设计 deterministic 启发式审计
python -m agent_tool_harness.cli audit-evals \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/launch-audit-evals

# 跑 bad path（必须故意失败才能看到 diagnosis 信号）
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/launch-run-bad --mock-path bad

# 把 run 当"录像带"deterministic 重放
python -m agent_tool_harness.cli replay-run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --run runs/launch-run-bad \
  --out runs/launch-replay

# 离线 trace 信号复盘
python -m agent_tool_harness.cli analyze-artifacts \
  --run runs/launch-replay \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/launch-analysis

# Live judge **强 opt-in** 前置 readiness 检查（默认 not ready，advisory-only）
python -m agent_tool_harness.cli judge-provider-preflight \
  --out runs/launch-preflight

# Judge prompt 安全 / 启发式审计（默认 7 类 finding）
python -m agent_tool_harness.cli audit-judge-prompts \
  --prompts examples/judge_prompts.yaml \
  --out runs/launch-judge-audit
```

> **pricing / budget cap** 的写法（`project.yaml` 中的 `pricing:` / `budget:`
> 段）见 [INTERNAL_TRIAL.md §4 设置 pricing 与 per-eval budget cap](INTERNAL_TRIAL.md#4-设置-pricing-与-per-eval-budget-cap)。
> `llm_cost.json` 是 advisory，**永远不是真实账单**，以 provider 官方
> console 为准。

---

## 6. 反馈闭环

→ [INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md](INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md)
（单次反馈模板）
→ [INTERNAL_TRIAL_DOGFOODING_LOG.md](INTERNAL_TRIAL_DOGFOODING_LOG.md)
（每次试用追加一段，作为 v3.0 触发条件的真实证据库）
→ [INTERNAL_TRIAL_FEEDBACK_SUMMARY.md](INTERNAL_TRIAL_FEEDBACK_SUMMARY.md)
（汇总当前反馈数量与 v3.0 是否达讨论门槛）

提交方式：复制反馈模板到 `feedback/<your-team>-<YYYY-MM-DD>.md` 或
贴到内部 issue tracker。**没有时间填完整版？** 只填顶部
[5 分钟极简版段](INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md#0-5-分钟极简版可选)
也行。

反馈必须至少覆盖：

- 试用场景（你自己的项目类型 / 你自己的 tool 类型）；
- 接入规模（tool / eval 数量）；
- 是否在 10-15 分钟内跑通 Quickstart；
- 哪一步卡住、卡住时看的是哪个 artifact；
- 哪个 artifact 最有用、哪个 report 字段最难懂；
- 是否需要 v3.0 能力（**必须** 同时说明 deterministic / offline 为什么不够 +
  具体需要什么，详见 §8 v3.0 触发条件）。

**安全硬约束：反馈中绝对不要粘**真实 key、Authorization header、完整
请求体、完整响应体、`base_url` 敏感 query、HTTP/SDK 原始异常长文本。
模板里已有 [§7 key / no-leak / budget / doc drift 检查清单](INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md#7-key--no-leak--budget--doc-drift-检查)。

---

## 7. 明确**不**包含的能力（与 v2.0 边界对齐）

下面能力**当前不做**、**v2.0 不做**、且**不会**因为某个用户单方面要求
就被加进 v2.0：

- ❌ Web UI / SaaS / 多租户；
- ❌ MCP executor；
- ❌ HTTP / Shell executor；
- ❌ 自动修复用户工具（auto-patch）；
- ❌ 大规模 benchmark / leaderboard；
- ❌ 企业 RBAC / SSO / 企业权限系统；
- ❌ 真实托管 LLM Judge 自动评估服务（**只能在你自己机器**强 opt-in 跑 smoke）；
- ❌ "MockReplayAdapter PASS / FAIL = Agent 真实能力"（这是结构性
  tautological replay，详见 [TRY_IT_v1_7.md 反模式提醒](TRY_IT_v1_7.md)）。

完整否定列表与原因见 [ROADMAP §v2.0 不包含的能力](ROADMAP.md#v20-不包含的能力一律进-v30--future-backlog不在主线排期)。

---

## 8. v3.0 触发条件（**严格保持 backlog**）

v3.0 严格保持在 backlog，**不会**因为某一个人觉得需要就启动。**必须
同时**满足下面所有条件，才考虑开 v3.0 milestone：

1. **至少收集 3 份**来自不同试用团队的内部反馈（用 §6 的反馈模板）；
2. 每份反馈**明确**说明 deterministic / offline 能力为什么不够；
3. 每份反馈**能指出**需要哪类 v3.0 能力（MCP / Web UI / live judge /
   HTTP executor / Shell executor 等）的**具体业务原因**，不是单纯
   "看起来更厉害"；
4. 评估这些能力是否应**独立开新仓库**或新 milestone 处理，而不是污染
   v2.0 主线（详见 [ROADMAP §v2.0 终点定义](ROADMAP.md#v20-终点定义主线唯一终点避免无限滚版本)）。

未达成上述条件前，所有 v3.0 能力请求一律转入 backlog；不得在 v2.x
patch 中偷偷夹带。

---

## 9. 安全 / no-leak 硬约束（试用全程必须遵守）

- ❌ 不要把真实 key（OpenAI / Anthropic / 阿里云 Coding Plan / 任意
  HTTP `Authorization` header）粘进任何代码、文档、测试、`runs/` 目录
  下任意 artifact、`report.md`、`metrics.json`、`judge_results.json`、
  `diagnosis.json`、git commit message、PR description；
- ❌ 不要把完整请求体 / 完整响应体 / `base_url` 敏感 query / HTTP
  / SDK 原始异常长文本贴出来（这些通常含 token / cookie / 内部地址）；
- ✅ 真实 live judge **唯一**入口是**本地环境变量** + **强 opt-in
  CLI flag**：

  ```bash
  export AGENT_TOOL_HARNESS_LLM_PROVIDER=anthropic_compatible
  export AGENT_TOOL_HARNESS_LLM_BASE_URL=...        # 本地配置，不入 git
  export AGENT_TOOL_HARNESS_LLM_API_KEY=...         # 本地配置，不入 git
  export AGENT_TOOL_HARNESS_LLM_MODEL=...
  python -m agent_tool_harness.cli judge-provider-preflight ...   # 默认 advisory，必须 ready 才能 live
  ```

  详细 readiness gate 与 no-leak 测试见 [TESTING.md](TESTING.md) 与
  `tests/test_cli_anthropic_compatible_live.py`。

---

## 维护说明（给改这份文档的人看）

- 本文是**导航页**，不重复 QUICKSTART / 完整版内容；如果发现内容重复，
  请删除重复段落、保留链接；
- 任何对"v2.0 不包含 / v3.0 触发 / 安全约束"的修改都会被
  `tests/test_internal_trial_readiness.py` +
  `tests/test_internal_trial_launch_pack.py` 钉住，**不要**为了"看起来
  更厉害"修改这些段；
- 命令片段必须与 [INTERNAL_TRIAL.md](INTERNAL_TRIAL.md) /
  [INTERNAL_TRIAL_QUICKSTART.md](INTERNAL_TRIAL_QUICKSTART.md) 中的命令
  逐字一致（drift 测试见 `tests/test_docs_cli_snippets.py`）。
