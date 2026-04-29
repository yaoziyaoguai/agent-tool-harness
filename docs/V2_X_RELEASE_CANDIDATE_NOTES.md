# v2.x Release Candidate Notes — 维护者封板判断

> 这是给 **maintainer** 看的 1 页封板判断包。**不**是给试用者用的 release
> announcement，**不**是给市场看的 product brief。
>
> 关联文档：
> - 完整阶段进度 → [`ROADMAP.md`](ROADMAP.md)
> - 第一次真实试用执行包 → [`FIRST_REAL_TRIAL_EXECUTION_PLAN.md`](FIRST_REAL_TRIAL_EXECUTION_PLAN.md)
> - 反馈分流 → [`FEEDBACK_TRIAGE_WORKFLOW.md`](FEEDBACK_TRIAGE_WORKFLOW.md)
> - push 自检 + IM + 失败处置 → [`PUSH_PREFLIGHT_CHECKLIST.md`](PUSH_PREFLIGHT_CHECKLIST.md)

---

## 1. v2.x 已完成能力（截至当前 commit）

| 节点 | 内容 | canonical 文档 / 测试 |
|---|---|---|
| user-friendly bootstrap flow | 一条 `bootstrap` 命令出 5 件草稿 | `cli.py::bootstrap` / `test_user_friendly_bootstrap.py` |
| validate-generated + strict-reviewed | 草稿 → 可用 config 之间的硬门 | `cli.py::validate_gen` / `test_validate_generated.py` |
| realistic offline tool trial sample | 完整可跑样例 | `examples/realistic_offline_tool_trial/` |
| controlled live preflight | 离线 ready_for_live 自检（**不**联网） | `judges/preflight.py` / `test_judge_provider_preflight.py` |
| no-leak / safety release gate | 多处 `_scan_no_leak()` 钉死 artifact-级不变量 | `test_env_example_namespace_safety.py` / `test_run_artifact_doc_drift.py` |
| First Internal Trial Handoff Pack | 文档+测试齐全 | `FIRST_INTERNAL_TRIAL_HANDOFF.md` / 14 测试 |
| Push Preflight + Operator Pack | 4 节运营手册 | `PUSH_PREFLIGHT_CHECKLIST.md` / 10 测试 |
| Feedback Triage Workflow | 5 桶决策表 + 9 输入字段 + synthetic simulation | `FEEDBACK_TRIAGE_WORKFLOW.md` / 14 测试 |
| First Real Trial Execution Plan | 1 页 maintainer 自检包 | `FIRST_REAL_TRIAL_EXECUTION_PLAN.md` / 11 测试 |
| Documentation INDEX | 4 角色路由 | `INDEX.md` |
| Feedback Intake Validator | Python module guard | `agent_tool_harness/feedback/validator.py` / tests |

## 2. 当前状态

| 项 | 值 |
|---|---|
| Working tree | clean |
| Tag | **未 tag**（最新 tag 仍是 `v2.0`） |
| 真实非维护者反馈数 | **0 / 3** |
| v3.0 | **still backlog / not started** |
| Live judge real-network smoke | 3 模型全 `bad_response`（**非** v2.x blocker；详见 ROADMAP 第 11 项） |

## 3. 当前未 tag 的原因（必看）

tag 的语义应是**"被真实非维护者试用过的版本"**。当前：

- maintainer 自测 + dry-run 都已通过；
- 0 份真实非维护者反馈；
- 如果现在 tag，tag 就退化成"我自己跑过觉得 OK"——失去外部信号意义。

→ **结论**：等第一份真实反馈追加进
[`INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`](INTERNAL_TRIAL_FEEDBACK_SUMMARY.md)
后再 tag。

## 4. Tag 触发条件（满足全部 4 条才 tag）

1. ≥1 份真实非维护者反馈已追加 `INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`；
2. **无** security blocker 待修；
3. 第 1 份反馈已经按 [`FEEDBACK_TRIAGE_WORKFLOW.md`](FEEDBACK_TRIAGE_WORKFLOW.md) §4 跑完 11 步分流；
4. 如果反馈分到 v2.x patch，**先把 patch 修完再 tag**；如果分到
   closed-as-design / needs-more-evidence，可以直接 tag 当前 HEAD。

满足后 tag 名建议 `v2.1`，commit message 必须引用反馈记录的 commit hash
让 tag 真正含"被试用过"的语义。

## 5. v3.0 未启动的原因 + 启动 gate

未启动原因：

- 真实反馈数 = 0，没有真实业务证据指向 deterministic / offline 不够；
- 现有 bad_response（live smoke 3/3）属 multi-format provider 兼容问题，
  按 [`FEEDBACK_TRIAGE_WORKFLOW.md`](FEEDBACK_TRIAGE_WORKFLOW.md) §1 默认
  归 v3.0 backlog，**不**因单次 bad_response 立刻动 transport；
- maintainer rehearsal 不计入 v3.0 ≥3 门槛。

v3.0 启动 gate（必须**同时**满足）：

1. ≥3 份真实非维护者反馈累积；
2. 反馈指向**同一类根因**；
3. 至少 1 份反馈含**具体业务场景**（不是"看起来更厉害"）；
4. 满足 [`FEEDBACK_TRIAGE_WORKFLOW.md`](FEEDBACK_TRIAGE_WORKFLOW.md) §3
   "v3.0 backlog candidate" 5 条全部要求。

→ 满足后再写 v3.0 设计文档；**不允许**绕过 gate 提前实现 MCP / Web UI /
live judge / HTTP-Shell executor / multi-format provider / 企业平台能力。

## 6. 不在 v2.x 范围（仍 backlog）

| 能力 | 仍 backlog 原因 |
|---|---|
| MCP / `tools/list` discovery | 需真实网络 + 协议复杂度，超 v2.x 离线优先 |
| Web UI / 企业平台 | v2.x 定位是内部小团队 CLI 试用 |
| HTTP / Shell executor | 需真实命令执行边界，超 v2.x 安全边界 |
| 真实 LLM Judge 自动评估服务 | v2.x 只支持本地强 opt-in live smoke |
| Multi-format live judge transport | bad_response 当前默认 backlog，等 ≥3 同根因反馈 |
| 自动 patch 用户工具 | 违反"不自动改用户代码"硬约束 |
