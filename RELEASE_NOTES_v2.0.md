# RELEASE_NOTES v2.0 — Internal Trial Ready

> 主线终点。本 release 把 agent-tool-harness 收敛成**内部小团队可以
> 本地 clone / 安装 / 按 [docs/INTERNAL_TRIAL.md](docs/INTERNAL_TRIAL.md)
> 端到端跑通**的离线优先 Agent Tool Evaluation Harness。
>
> v2.0 **不是**企业级 SaaS、不是托管 LLM Judge 自动评估服务、不是
> Web UI、不是真实生产平台。任何这些方向都属 v3.0+ backlog，已在
> `docs/ROADMAP.md` "v2.0 不包含" 段显式列出。

## 1. 定位（v2.0 = Internal Trial Ready）

v2.0 的成功标准不是"功能多 / 接了多少模型"，而是：**公司内部一个 5–10
人的团队可以**

- 本地 `git clone` + `pip install -e .`；
- 按 `docs/INTERNAL_TRIAL.md` 跑通 9 个核心 CLI（audit-tools /
  generate-evals / promote-evals / audit-evals / run / replay-run /
  analyze-artifacts / judge-provider-preflight / audit-judge-prompts）；
- 用自己的 `project.yaml` / `tools.yaml` / `evals.yaml` 接入；
- 看懂 9+ 个 artifact 与 `report.md`；
- 用 `docs/INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md` 提结构化反馈。

参见 `docs/ROADMAP.md` 的 16 条 release standards。

## 2. 内部团队第一次试用入口

按以下顺序读：

1. `README.md` 顶部 "⚠️ 当前阶段能力边界" + "快速开始"；
2. `docs/INTERNAL_TRIAL.md`（端到端 7 步路径 + pricing/budget setup）；
3. `docs/INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md`（反馈结构化模板，含
   key no-leak 提醒）；
4. `docs/ARTIFACTS.md`（9+ artifact 字段含义）；
5. `docs/ARCHITECTURE.md`（每段管线的边界 + 不负责什么）。

## 3. v2.0 已完成能力（v1.0 → v2.0 累积）

按管线顺序：

- **Tool Design Audit (v0.2)** — deterministic 启发式，识别字段缺失 +
  shallow_wrapper / semantic_overlap / usage_boundary_duplicated /
  missing_response_format 等信号；标注 `signal_quality:
  deterministic_heuristic`，命中高严重度信号 → `semantic_risk_detected`
  warning；**不**做语义级 LLM 判定。
- **Eval Generator (v0.1)** — `from_tools` 给可读模板；候选默认 not
  runnable，需人工补 fixture/expected_root_cause + 把 `review_status`
  改成 `accepted` 才能 promote；**不**自动造可执行 eval。
- **promote-evals (v0.1)** — 机械搬运 `accepted + runnable` 候选到
  正式 evals；**不**修改语义。
- **EvalRunner + MockReplayAdapter (v0.1)** — 9 个 artifact；
  `signal_quality: tautological_replay`，**PASS/FAIL 不代表 Agent
  能力**。
- **TranscriptReplayAdapter + replay-run CLI (v0.3)** — 把已有 run 当
  录像带 deterministic 重放；`signal_quality: recorded_trajectory`。
- **TraceSignalAnalyzer + analyze-artifacts CLI (v0.2)** — 从已有
  trace deterministic 复盘 5 类信号写入 `diagnosis.json`；**不**调
  LLM、不重新执行工具。
- **RuleJudge anti-decoy (v1.0)** — `evidence_from_required_tools` +
  `evidence_grounded_in_decoy_tool` deterministic 反诱饵规则；**不是**
  LLM Judge。
- **CompositeJudgeProvider + multi-advisory (v1.1–v1.5)** — majority-vote
  聚合 + `judge_disagreement` metrics + report 多 advisory 渲染 +
  `--judge-advisory NAME:PATH` 可重复 flag；**仅** offline / recorded /
  fake_transport / anthropic_compatible_offline，**绝不**接受 live
  transport NAME。
- **AnthropicCompatibleJudgeProvider offline + LiveAnthropicTransport
  骨架 (v1.2–v1.4)** — fake transport fully covered；live transport 默认
  disabled，必须 `live_enabled=True` + `live_confirmed=True` + 4 个 env
  var 完整且**绝不**传 fake fixture 才会触发；CI 0 联网。
- **judge-provider-preflight CLI (v1.2–v1.3)** — 默认
  `summary.ready_for_live=false`，actionable hints；`--live` +
  `--confirm-i-have-real-key` 双标志契约下也不发任何网络请求。
- **retry/backoff (v1.6)** — 默认 `max_attempts=1` 字节兼容；只对
  rate_limited / network_error / timeout 退避；非 retryable 永不重试；
  `sleep_fn` 注入 fake clock。
- **llm_cost.json + Cost Summary (v1.6)** — advisory-only，**永远不
  fabricate token**，缺失自动写 `cost_unknown_reason`；顶层
  `estimated_cost_usd` 永远 `null`；明细在 `totals.estimated_cost_usd`。
- **audit-judge-prompts CLI (v1.6)** — 7 类 prompt 启发式（含 sk- key
  字面、引导泄漏 secret、把 advisory 当 ground truth）；输出
  `audit_judge_prompts.json` + `.md`。
- **product hardening (v1.7)** — `docs/TRY_IT_v1_7.md` 端到端串联；
  `tests/test_docs_cli_snippets.py` + `test_artifact_consistency.py`
  钉死 docs ↔ CLI ↔ artifact schema 漂移。
- **pricing + budget cap (v1.8)** — `project.yaml` 支持 advisory
  `pricing.models[].input_per_1k / output_per_1k`（仅 USD，**拒绝**
  非 USD 自动换算）+ `budget_cap.per_eval.max_tokens_total /
  max_cost_usd`；budget exceeded **advisory，不中断 run**；模型无价
  → `cost_unknown_reason`，**不写 0**。
- **schema-driven docs drift (v1.8)** — `tests/test_docs_cli_schema_drift.py`
  从 argparse 反射 75 条 CLI 片段断言（含 alias 归一、`--flag=value`
  语法、`\` 续行），README/TRY_IT/INTERNAL_TRIAL 任何 CLI snippet 漂移
  即测试失败。
- **internal trial governance (v1.9)** — `docs/INTERNAL_TRIAL.md` +
  `docs/INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md` + `tests/
  test_internal_trial_readiness.py` 7 条防回归（v2.0 边界 + 文档诚实性 +
  no-overpromise 词汇必须出现在否定上下文）。

## 4. 已知限制（v2.0 仍然是 MVP，请把"通过"读成"结构化通过"）

- `MockReplayAdapter` 直接读 `eval.expected_tool_behavior.required_tools`
  回放，**PASS/FAIL 是结构性的，不能解读为"工具对真实 Agent 好用"**；
  每个 run 的 `metrics.json` + `report.md` 顶部都有 `signal_quality:
  tautological_replay` 声明。
- `RuleJudge.must_use_evidence` 仍是"包含 evidence id 子串"的轻量校验，
  非语义级判定；提升路径见 ROADMAP v3.0 backlog。
- `ToolDesignAuditor` 仍是 deterministic 启发式，**字段写齐 ≠ 工具真的
  好用**；`tests/test_tool_design_audit_subtle_decoy_xfail.py` strict
  xfail 钉死该根因，转正需 transcript-based 样本或 LLM judge。
- `LiveAnthropicTransport` 是骨架。本仓库 CI 0 联网；**任何真实 live**
  必须由用户在自己机器上显式 `live_enabled=True` +
  `live_confirmed=True` + 4 个 env var 完整 + 不传 fake fixture 才会
  触发；harness 本身**不托管 live 调用、不存 key、不上报使用量**。
- `llm_cost.json` 是 **advisory**。即使你配了 `pricing`，
  `totals.estimated_cost_usd` **不能用作账单或发票来源**；以 provider
  官方 console 为准。
- `Eval Generator` 不是生产级自动造题；候选默认 not runnable，必须
  人工 review。

## 5. v2.0 不包含（属 v3.0+ backlog）

| 不包含能力 | 原因 |
|-----------|------|
| 企业级 / 生产级 SaaS / 多租户 / 计费 | v2.0 定位是内部试用，不是产品化服务 |
| 真实托管 LLM Judge 自动评估服务 | 需要独立账号 / 计费 / 审计体系 |
| Web UI | 范围外；harness 是 CLI + artifact 优先 |
| MCP / HTTP / Shell executor | 真实执行器需要独立安全模型 + 长期维护 |
| 自动 patch 用户工具 | 范围外；harness 只读不改 |
| 大规模 benchmark / leaderboard | 留给独立 surface |
| 企业 RBAC / SSO | 范围外 |

详见 `docs/ROADMAP.md` "v2.0 不包含" 段。

## 6. 后续 backlog（**仅记录，本 release 不实现**）

- `RuleJudge.must_use_evidence` 升级为非 substring 语义匹配；
- decoy tool 真实样本库（让 strict xfail 能基于真实 transcript 转正）；
- 真实 LLM Judge live 路径（必须独立 review，不属 v2.x）；
- MCP / HTTP / Shell executor（属 v3.0+，需要独立安全模型设计）；
- Web UI（独立 surface，不在主线）。

详见 `docs/ROADMAP.md` 底部 "v3.0+ backlog" 段。

## 7. 验证

- `ruff check .`：clean；
- `pytest -q`：424 passed + 1 xfailed（v0.2 backlog 唯一 xfail，已记录
  根因 + 转正条件）；
- v2.0 internal trial smoke：preflight `ready_for_live=false` ✅；
  run --mock-path bad → 1 failed（结构化）✅；replay-run signal_quality
  `recorded_trajectory` ✅；analyze-artifacts 1 signal ✅；
  audit-judge-prompts 输出 json + md ✅。

## 8. 反馈

请按 [docs/INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md](docs/INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md)
提交结构化反馈。**不要**在反馈里粘贴真实 API key / Authorization
header / 完整请求/响应体 / 含敏感 query 的 base_url / SDK 原始异常长
文本。
