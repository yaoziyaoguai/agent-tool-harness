# Documentation Index — 按你的角色直接进入

> agent-tool-harness 的文档已经积累得不少。**99% 的人不需要看完所有
> 文档**。请按下面 4 个角色之一**只看那一条 row 里的 1-2 份文档**。

---

## 你的角色 → 你只需要看的文档

| 角色 | 看 1 份 canonical | 然后看 1 份 fallback | 其它一律先不看 |
|---|---|---|---|
| **第一次跑 harness 的内部团队同事**（试用者） | [`INTERNAL_TRIAL_QUICKSTART.md`](INTERNAL_TRIAL_QUICKSTART.md) — 5 行命令跑通 | [`INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md`](INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md) — 跑完填反馈 | 别的 INTERNAL_TRIAL_*.md 都是历史层 |
| **第一次给非维护者发邀请的 maintainer** | [`FIRST_REAL_TRIAL_EXECUTION_PLAN.md`](FIRST_REAL_TRIAL_EXECUTION_PLAN.md) — 1 页执行包 | [`PUSH_PREFLIGHT_CHECKLIST.md`](PUSH_PREFLIGHT_CHECKLIST.md) §② 复制中文 IM 直接发 | FIRST_INTERNAL_TRIAL_HANDOFF 是详细背景，可选 |
| **收到反馈、要做分流的 maintainer** | [`FEEDBACK_TRIAGE_WORKFLOW.md`](FEEDBACK_TRIAGE_WORKFLOW.md) — 5 桶决策表 | [`INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`](INTERNAL_TRIAL_FEEDBACK_SUMMARY.md) — 真实反馈数与 v3.0 gate | DOGFOODING_LOG 是历史/dry-run 记录，仅追加 |
| **决定要不要 tag / release 的 maintainer** | [`V2_X_RELEASE_CANDIDATE_NOTES.md`](V2_X_RELEASE_CANDIDATE_NOTES.md) — 封板判断 | [`ROADMAP.md`](ROADMAP.md) — 完整阶段表 | 历史 RELEASE_NOTES_v*.md 仅 archive |

---

## 开发者 / 想读架构的人

| 想了解什么 | 看这一份 |
|---|---|
| 整个 harness 的架构与边界 | [`ARCHITECTURE.md`](ARCHITECTURE.md) |
| 9-10 件 artifact 各表示什么 | [`ARTIFACTS.md`](ARTIFACTS.md) |
| 测试纪律与 strict xfail 制度 | [`TESTING.md`](TESTING.md) |
| 接入 / 10 分钟路径 | [`ONBOARDING.md`](ONBOARDING.md) |
| 进度与能力边界 | [`ROADMAP.md`](ROADMAP.md) |

---

## 文档分层（仅供 maintainer 维护时参考）

- **canonical 入口**（trial 试用者 + maintainer 各 4 份）：见上表第 1-2 列。
- **历史层**：INTERNAL_TRIAL.md / INTERNAL_TRIAL_LAUNCH_PACK.md /
  INTERNAL_TEAM_SELF_SERVE_TRIAL.md / FIRST_INTERNAL_TRIAL_INVITE_TEMPLATE.md /
  PUSH_READINESS_SUMMARY.md / TRY_IT.md / TRY_IT_v1_7.md /
  V1_3_LIVE_TRANSPORT_DESIGN.md / V1_4_LIVE_TRANSPORT_IMPLEMENTATION.md
  / REAL_TRIAL_CANDIDATE.md —— **保留**做 historical reference，被 ≥1
  测试 pin 防 drift；**新读者请走 canonical 入口**。
- **运行/append-only 层**：INTERNAL_TRIAL_DOGFOODING_LOG.md（dry-run 记录，
  不计入真实反馈）/ RELEASE_NOTES_v*.md。

---

## 这一页本身的角色

- 它**不是**新增使用手册，**只**是"按你的角色路由到 1-2 份 canonical 文档"。
- 它被 `tests/test_docs_index.py` 钉死：4 个角色路由必须存在、所有
  canonical 文档必须真实存在、不能有断链。任何修改都要确保测试仍绿。
