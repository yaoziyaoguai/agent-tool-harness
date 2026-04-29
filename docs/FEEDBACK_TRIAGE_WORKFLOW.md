# Feedback Triage Workflow — 反馈分流工作流

> **这是给 maintainer 的一页操作手册**：每收到 1 份内部试用反馈，
> 严格按本流程跑一次，把反馈分流到 v2.x patch / v3.0 backlog /
> closed-as-design / needs-more-evidence / **security blocker**
> 五类之一。
>
> **本流程不是发明 v3.0 的入口**。当前 v3.0 **still not started**，
> 任何"我们要做 v3.0"的提案在跑完本流程前**一律**留 backlog。
>
> 配套：
> - 反馈模板 → `INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md`
> - 反馈汇总 → `INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`
> - dogfooding log → `INTERNAL_TRIAL_DOGFOODING_LOG.md`
> - 第一次试用流程 → `FIRST_INTERNAL_TRIAL_HANDOFF.md`
> - Push / 操作 / 失败处置 → `PUSH_PREFLIGHT_CHECKLIST.md`

---

## 1. 反馈来源类型（先分类，再分流）

| 来源 | 是否计入"真实反馈" | 处理 |
|---|---|---|
| **maintainer rehearsal / dry-run** | ❌ 不计入 | 只记录到 `INTERNAL_TRIAL_DOGFOODING_LOG.md` 的 maintainer dry-run 段；**不能**用来凑 v3.0 ≥3 门槛 |
| **real internal teammate trial**（非维护者，跑完 7 步并出 artifact）| ✅ 计入 | 进入 §2 triage |
| **user idea without trial**（"我希望有 X 功能"，没真跑） | ❌ 不计入 | 礼貌记录、要求先跑 7 步、暂留 needs-more-evidence |
| **live provider compatibility issue**（bad_response / 网关格式错） | 默认**不阻塞**主线 | 进入 §2，但默认归 v3.0 backlog（multi-format live judge），**不**因单次 bad_response 启动 v3.0 |
| **security / no-leak issue**（发现 key / Authorization / 完整请求响应落盘） | ✅ **最高优先级** | **立即**走 security blocker 路径，先停试用、净化、修复，再继续其它 triage |

> 唯一例外：security blocker **跨过** v2.x/v3.0 的所有分类讨论，
> 直接进入修复队列。

---

## 2. Triage 五分类决策表

输入字段（来自反馈模板 §11 + maintainer 校核）：

| 字段 | 取值 |
|---|---|
| `real_feedback` | yes / no |
| `trial_completed`（跑完 7 步、出了 artifact）| yes / no |
| `report_artifacts_generated` | yes / no |
| `blocker_type` | docs / cli / artifact / live / security / feature / unknown |
| `needs_secret_network_database` | yes / no |
| `asks_for_v3_feature`（MCP / Web UI / live judge / HTTP-Shell executor / multi-format provider / 企业平台） | yes / no |
| `explains_offline_gap`（明确说明 deterministic / replay-first 为什么不够） | yes / no |
| `has_reproduction_steps`（命令 + artifact 行号） | yes / no |
| `security_risk` | yes / no |

输出决策：

| 优先级 | 条件 | 决策 |
|---|---|---|
| **0**（最高） | `security_risk == yes` | **security-blocker** |
| 1 | `real_feedback == yes` AND `trial_completed == yes` AND `asks_for_v3_feature == no` AND 修复方案不需要 secret/network/database | **v2.x patch** |
| 2 | `real_feedback == yes` AND `trial_completed == yes` AND `asks_for_v3_feature == yes` AND `explains_offline_gap == yes` AND `has_reproduction_steps == yes` | **v3.0 backlog candidate** |
| 3 | `real_feedback == yes` AND（"期望默认 live" / "期望自动读 secret" / "期望自动执行任意工具" / "期望跳过 review" / "期望 generated draft 当生产配置" / "期望 maintainer rehearsal 当真实反馈"） | **closed-as-design** |
| 4 | 其它 | **needs-more-evidence**（要求补 reproduction / artifact / offline-gap 说明） |

> **v3.0 启动门槛（不是单条反馈门槛）**：在"v3.0 backlog candidate"
> 桶里**累计 ≥3 份真实团队反馈**且**指向同一类根因**且**至少 1 份**
> 含具体业务场景（不是"看起来更厉害"），才召开 v3.0 启动 review。
> 当前 = **0 / 3**。

---

## 3. 各分类的"判定提示"

### v2.x patch（典型样例）
- bootstrap 命令不清楚 / `--source` 不会写
- `REVIEW_CHECKLIST.md` 看不懂 / TODO 修复路径不明
- `validate-generated` 错误信息不可行动
- `--strict-reviewed` 太严或漏字段
- `report.md` / 10 件 artifact 找不到对应 finding
- 反馈模板字段不够 / 文档中文 typo
- no-leak 文案缺一句

→ 一律可在 v2.x 内做小 patch，不涉及 v3.0 能力。

### v3.0 backlog candidate（必须**同时**满足）
1. 来自真实非维护者试用；
2. 不只是文档/UX；
3. 反馈写清 deterministic / offline / replay-first 为什么不够；
4. 反馈写清需要 v3.0 哪个子能力（MCP / Web UI / live judge / HTTP-Shell
   executor / multi-format provider / 企业权限 / 大规模 benchmark）；
5. 至少 1 份反馈给出**具体业务场景**。

→ 先入 backlog，**不**立刻启动开发，等 ≥3 份累积。

### closed-as-design（典型样例）
- "默认就该开 --live" → 设计上 opt-in；
- "应该自动读 .env" → 设计上 namespace 隔离；
- "应该自动执行用户任意工具" → 设计上禁止；
- "应该跳过 review 直接 promote" → 设计上必须 review；
- "generated draft 应能直接当生产" → 设计上 strict-reviewed 必过；
- "maintainer rehearsal 也算反馈" → 设计上不算。

→ 礼貌记录原因 + 引用对应 ROADMAP / docs 段落，**不**进入 patch
也**不**进入 v3.0 backlog。

### needs-more-evidence（典型样例）
- 反馈无 artifact / 无 reproduction
- 反馈是想法但没真跑
- 反馈含真实泄漏 → 走 security-blocker，**净化后**重新提

→ 回到反馈人请补；不进入任何修复队列。

### security-blocker（必须立刻动作）
1. **暂停**对外试用招募；
2. **净化** repo / artifact / log / 截图 / IM 历史；
3. 在 `INTERNAL_TRIAL_FEEDBACK_SUMMARY.md` D 段登记（**不**透露泄漏内容本身）；
4. 修复 redaction / no-leak 测试 / 文档措辞；
5. 跑全套 release gate；
6. 让试用者**重新**提交脱敏反馈，重新进入 §2 triage。

→ **绝不**因为一次 security-blocker 启动 v3.0；security 是 v2.x patch
的最高优先级，不是 v3.0 触发器。

---

## 4. Maintainer 收到反馈后的执行步骤

1. 把反馈复制到 `INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`（保留原文，只删敏感字段）；
2. 在反馈头部标注 `real_feedback: yes/no` + `trial_completed: yes/no`；
3. 列出试用者的 artifact 路径（如 `runs/trial-1/report.md`）；
4. 跑 §2 决策表，给出 5 类之一；
5. 按 §3 决定：
   - v2.x patch → 开 1 个小 patch + 补回归测试 + 不引入新依赖；
   - v3.0 backlog candidate → 入 `docs/ROADMAP.md` v3.0 backlog 区，**不**启动；
   - closed-as-design → 在反馈条目加 1 句"为什么不做 + 设计依据链接"；
   - needs-more-evidence → 回反馈人；
   - security-blocker → 走 §3 security-blocker 6 步。
6. 更新 `INTERNAL_TRIAL_FEEDBACK_SUMMARY.md` 当前默认结论的"真实反馈数量"；
7. 如果是第 1 份真实反馈 → 收齐后才考虑是否 `git tag v2.1`；
8. **不**自动 push、**不**自动 tag、**不**因单份反馈启动 v3.0。

---

## 5. 不可逆纪律（写死在本流程里）

- 任何分类**不允许**绕过反馈模板的 reproduction + artifact 字段；
- maintainer rehearsal **永远**不计入 v3.0 触发；
- v3.0 触发是 ≥3 份**真实**反馈累计 + 指向同根因，不是 1 份特别响亮的反馈；
- security blocker **不是** v3.0 的支持论据；
- bad_response 一次 / 网关格式不兼容一次 → 默认 v3.0 backlog，不立刻动 transport 层；
- 任何 closed-as-design 决策必须留下"设计依据链接"，不能空口拒绝。

---

## 6. Synthetic Feedback Triage Simulation —— 决策表演练（**非真实反馈**）

> **强约束**：本节 5 个 case 全部是 synthetic / simulated / **演练用例**。
> 它们**不计入**真实反馈数（仍 0 / 3）、**不**触发 v3.0 启动 gate、
> **不**追加到 [`INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`](INTERNAL_TRIAL_FEEDBACK_SUMMARY.md)
> 的 A/B/C/D 分类。
> 唯一作用：让维护者跑一遍 §2 决策表，确认手感正确。

### Case A — v2.x onboarding patch
- 反馈：试用者能 `bootstrap`，但 `REVIEW_CHECKLIST.md` 看不懂某段；
- 输入：`real_feedback=yes` / `trial_completed=yes` / `asks_for_v3_feature=no` / 修复方案不需 secret/network；
- **决策**：v2.x patch（改 REVIEW_CHECKLIST 措辞 + 补回归测试）。

### Case B — v2.x validation UX patch
- 反馈：`validate-generated --strict-reviewed` 失败，但 stderr 错误信息不可行动；
- 输入：`real_feedback=yes` / `trial_completed=yes` / `blocker_type=cli` / `asks_for_v3_feature=no`；
- **决策**：v2.x patch（改 stderr hint + 补 stderr drift 测试）。

### Case C — closed-as-design
- 反馈：试用者希望 generated draft 不 review 直接 `run`；
- 输入：`real_feedback=yes` / 落入 §3 closed-as-design 反例"跳过 review";
- **决策**：closed-as-design（记录设计依据链接：`FEEDBACK_TRIAGE_WORKFLOW.md` §3 closed-as-design 段；不修代码、不入 v3.0 backlog）。

### Case D — security blocker
- 反馈：试用者把 `Authorization: Bearer ...` 真实头粘进了反馈正文；
- 输入：`security_risk=yes`；
- **决策**：security-blocker（**优先级 0**，立即走 §3 security-blocker 6 步：
  暂停招募 → 净化 → 登记不透露内容 → 修复 → 跑 release gate → 让试用者
  脱敏后重提）。**不**因此启动 v3.0、**不**因此立即 tag。

### Case E — v3.0 backlog candidate, 但 NOT trigger
- 反馈：试用者明确写"我们需要 Web UI / MCP / live judge"且解释了 deterministic
  为什么不够 + 给出了具体业务场景；
- 输入：`real_feedback=yes` / `asks_for_v3_feature=yes` / `explains_offline_gap=yes` / `has_reproduction_steps=yes`；
- **决策**：v3.0 backlog candidate（追加到 ROADMAP v3.0 backlog 区）。
  **但**：当前桶内累计 = 1（含本条），距 ≥3 同根因门槛仍差 ≥2 份；
  **不**启动 v3.0、**不**写 v3.0 设计文档、**不**实现任何 v3.0 能力。

### 演练验证清单
跑完 5 个 case 后，确认：
- 真实反馈数依然 = 0 / 3（synthetic 不计入）；
- v3.0 状态依然 = still backlog / not started；
- 没有任何 case 因为"看起来很重要"被错升级到 v3.0 立即启动；
- security blocker 没有被吞成普通 patch；
- closed-as-design 留下了设计依据链接；
- 所有 v2.x patch 都附带回归测试规划。
