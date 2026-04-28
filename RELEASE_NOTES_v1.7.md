# agent-tool-harness v1.7 — product hardening + artifact consistency MVP

> v1.7 是一个 **release-readiness / product-hardening** 小步迭代。
> 不引入新依赖、不接真实 LLM、不联网、不读真实 API key、不接 MCP/HTTP/
> Shell/Web UI。它把 v1.6 已经加进来的三件套（retry/backoff、llm_cost、
> audit-judge-prompts）串成一条用户可复制粘贴的产品试用路径，并补上
> 跨 artifact / 文档 ↔ CLI 漂移的真实防回归契约。

## 定位（一句话）

**"v1.6 加了真实接入面，v1.7 把这个接入面钉成可发布的契约"** —— 不增加
能力，但把现有能力的安全闸门、文档真实性、跨 artifact 一致性变成 CI
强制断言，从此 v1.7+ 任何漂移都会立刻失败。

## 相对 v1.6 新增了什么

### 1. `docs/TRY_IT_v1_7.md` —— v1.6 三件套端到端产品试用路径

- 端到端串联 6 步：`judge-provider-preflight` →
  `audit-judge-prompts` → `run --mock-path bad` →
  `replay-run` → `analyze-artifacts` → 看 `llm_cost.json` +
  `report.md::Cost Summary`；
- 全程**离线 / 不调真实 LLM / 不联网 / 不需要密钥**；
- 含反模式提醒（不要把 `estimated_cost_usd` 当真实账单 / 不要把
  audit 通过当 prompt 安全终判 / 不要把 retry_count > 0 当成真实接通
  LLM / 不要把 raw key 写进 prompt 文本）。

### 2. `tests/test_docs_cli_snippets.py` —— docs ↔ CLI 漂移防回归（4 条）

钉死的真实 bug：
- README/TRY_IT/TRY_IT_v1_7/ONBOARDING 中任何
  `python -m agent_tool_harness.cli <sub>` 片段，subcommand 必须是当前
  argparse 真正注册的子命令；
- v1.6 新增的 `audit-judge-prompts` 必须在 README/ARTIFACTS/
  TRY_IT_v1_7 至少各出现一次（防"加了 CLI 但没用户接入文档"）；
- `llm_cost.json` 必须在 `EvalRunner.REQUIRED_ARTIFACTS` 中且
  ARTIFACTS.md 必须保留 "advisory-only" 与 "不是真实账单" 措辞（防
  "把 advisory cost 当真实账单宣传"）；
- `audit_judge_prompts.json` 在 ARTIFACTS.md 必须保留 "启发式" 与
  "通过 audit 不代表" 边界声明（防"把启发式 audit 当 prompt 安全终判"）。

### 3. `tests/test_artifact_consistency.py` —— 跨 artifact 一致性 + 反泄漏（4 条）

钉死的真实 bug：
- 同一次 run 产出的所有 `.json` artifact 必须有顶层 `schema_version`
  字段（下游消费者升级时唯一信号）；
- 没有任何 artifact（JSON/MD/JSONL）允许出现 sk- key 形态、
  `Authorization: Bearer ...` header 字面、`Bearer <token>` 字面
  （v1.6 prompt 维度脱敏后，本测试在 artifact 维度横向钉死）；
- `llm_cost.estimated_cost_usd` 必须为 `null`，
  `estimated_cost_note` 必须包含 "advisory-only" —— 防止有人偷偷
  接价格表把 advisory cost 当真实账单宣传；
- `preflight.json::summary.ready_for_live` 在没真实 key 的默认 CI
  场景必须为 `false` —— 防止有人误把默认值翻成 true 让用户以为接通
  真实 LLM。

## 工程指标

| 指标 | v1.6 | v1.7 |
|------|------|------|
| 单元 + 契约测试 | 309 passed + 1 xfailed | **317 passed + 1 xfailed** |
| ruff | 0 issue | 0 issue |
| 新增依赖 | 0 | **0** |
| 新增 CLI 子命令 | +1 (`audit-judge-prompts`) | 0 |
| 新增文档 | RELEASE_NOTES_v1.6.md | TRY_IT_v1_7.md + RELEASE_NOTES_v1.7.md |
| 跨 artifact 反泄漏 | per-prompt（v1.6 audit）| **跨所有 artifact 横向**（v1.7） |

## 已知限制（v1.7 不解决）

- **`audit-judge-prompts` 仍是启发式**：不替代真实 LLM judge 的语义级
  评估，且当前规则集偏保守，可能漏报；
- **`llm_cost.estimated_cost_usd` 永远 null**：价格表注入留 v1.7+ 后续；
  v1.7 只增强"反 advisory-cost 被当真实账单"防御，不增加价格能力；
- **retry/backoff 未在真实联网验证**：CI 永远不联网；线上如要观察真实
  retry 行为需自行打开 live opt-in（README 已写）；
- **docs CLI snippet 测试只覆盖 subcommand 名，不覆盖 `--flag`**：v1.7+
  可考虑加 schema-driven snippet 检查，但会增加维护成本；
- **artifact consistency 测试只覆盖 v1.6 三件套核心 artifact**：
  v1.7+ 加新 artifact 时需要在该测试中扩展。

## v1.7 仍**不**做（刻意保留的边界）

| 能力 | 原因 |
|------|------|
| 真实 LLM judge | 需要真实 key + 真实 provider 评估，永远不在 CI 默认路径 |
| 真实 LLM provider 集成验证 | 同上 |
| MCP / HTTP / Shell 集成 | 范围外 |
| Web UI | 范围外 |
| 跨多 run cost dashboard | v1.8+ |
| per-eval-budget 强制 cap | v1.8+ |
| jitter / 跨 process 限流 | v1.8+ |

## 后续路线（v1.8+ 候选）

- **真实 live readiness 试跑**：在 opt-in 的本地 fixture provider 上
  跑一次端到端 retry → cost → audit 链路，但仍 CI 默认禁用；
- **价格表注入 + per-eval-budget cap**：把 `estimated_cost_usd` 从
  null 升级为 advisory 估算（保留 advisory-only 措辞），并允许在
  `project.yaml` 设硬性 budget cap；
- **schema-driven CLI snippet drift 检查**：把 `--flag` 也纳入 docs ↔
  CLI 漂移防回归，需先稳定 argparse 演进策略。

## 升级兼容性

- v1.7 完全兼容 v1.6 的 artifact schema_version；
- 没有移除任何 CLI 子命令或 `--flag`；
- 没有删除/弱化任何 v1.6 测试；
- v1.7 强化的契约（schema_version、no key leak、cost advisory-only、
  preflight default not ready）都是**已经在 v1.6 实现中存在但未被 CI
  钉死**的不变量，v1.7 只是把这些不变量变成 CI 强制断言。

## 涉及 commit

- `cc4f246` `feat(tests): add v1.7 docs CLI drift and artifact consistency audits`
