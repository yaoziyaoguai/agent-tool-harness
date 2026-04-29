# Internal Trial Feedback Summary — 内部反馈汇总

> 这份文档**汇总**当前所有内部试用反馈的关键结论，并给出**当前默认结论**：
> v3.0 是否应被讨论 / 是否应被启动。
>
> 它不是单次记录（单次记录见
> [INTERNAL_TRIAL_DOGFOODING_LOG.md](INTERNAL_TRIAL_DOGFOODING_LOG.md)），
> 也不是反馈模板（模板见
> [INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md](INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md)）。
>
> 它是**给 maintainer / reviewer**看的：当有人提出"我们要做 v3.0"时，
> 第一步打开本页，看是否真的满足触发条件。

---

## 当前默认结论

| 项 | 当前值 |
|---|---|
| **真实**内部团队反馈数量 | **0** |
| 维护者 dry-run 记录数（**不计入** 3 份门槛） | 1（见 [DOGFOODING_LOG "Maintainer dry-run record" 段](INTERNAL_TRIAL_DOGFOODING_LOG.md#maintainer-dry-run-record)） |
| 是否满足 v3.0 讨论门槛（≥3 份**真实团队**反馈 + 全部满足 4 项硬约束） | **否** |
| **v3.0 状态** | **not started**（严格保持 backlog） |

> **维护者 dry-run 不计入 3 份门槛**：dry-run 仅用于验证 launch pack
> 命令是否真能复制粘贴跑通、artifact 是否齐、文档与 CLI 是否一致；
> 它**不能**代替来自不同试用团队的真实业务反馈。当前**真实团队反馈
> 数量 = 0**，因此目前能且只能继续做 v2.x onboarding / docs / smoke /
> safety patch；任何 v3.0 能力请求**一律**继续转入 backlog。

> v3.0 不会因为某一个人 / 某一次 review / 某一次"看起来更厉害"的提案
> 就被启动。详见
> [INTERNAL_TRIAL_LAUNCH_PACK.md §8 v3.0 触发条件](INTERNAL_TRIAL_LAUNCH_PACK.md#8-v30-触发条件严格保持-backlog)。

---

## 当前已发现的问题清单

> 本节按 **可作为 v2.x patch 修复** vs **必须留在 v3.0 backlog** 分类。
> 反馈数 = 0 时，本节自然为空。每收录一次反馈都需要在这里登记新发现。

### A. 可作为 v2.x patch 修复（不出 v2.x 范围）

> 标准：修复方案不需要 MCP / Web UI / live judge / HTTP / Shell executor /
> 多租户 / 真实托管 LLM Judge 自动评估服务即可解决。
>
> 当前空。第一份反馈进入后请在此追加。

### B. 必须留在 v3.0 backlog（明确超出 v2.x 范围）

> 标准：**同时**满足下面 3 项才能进入 v3.0 backlog：
> 1. 反馈中明确说明 deterministic / offline 能力为什么不够；
> 2. 反馈中明确说出需要的 v3.0 能力（MCP / Web UI / live judge /
>    HTTP / Shell executor 等）；
> 3. 反馈中明确说出**具体业务场景**（不是"看起来更厉害"）。
>
> 当前空。第一份满足 3 项的反馈进入后请在此追加。

### C. 反馈不完整 / 暂不计入 v3.0 触发条件

> 标准：欢迎收录，但缺少 v3.0 4 项硬约束中的任何一项时，
> 不计入 v3.0 触发门槛。

> 当前空。

### D. 安全 / 泄漏风险（**最高优先级，先于 A/B/C**）

> 标准：试用过程中发现可能泄漏 / 已经泄漏（真实 key / Authorization /
> 完整请求体响应体 / 敏感 base_url / 用户隐私 / 未脱敏日志）。
> 处理顺序：阻断 → 净化 → 登记（**不**透露泄漏内容） → 试用者重提
> 脱敏后的反馈 → 重新进入 A/B/C 分类。

> 当前空。**任何 D 类登记都不能透露泄漏内容本身**，仅用于改进未来
> redaction confirmation 流程。

---

## 维护说明

- 当
  [INTERNAL_TRIAL_DOGFOODING_LOG.md](INTERNAL_TRIAL_DOGFOODING_LOG.md)
  中"已收录试用记录数"变化时，**请同步更新**本文件"当前反馈数量"；
- 任何"我们要做 v3.0"的提案被提出前，**必须**先在本文件登记理由
  与对照硬约束，否则不进入 ROADMAP review；
- 测试 `tests/test_internal_trial_dogfooding_log.py` 钉死本文件
  "v3.0 not started" 默认结论 + A/B/C 分类骨架 + 维护者 dry-run 不计入
  3 份触发门槛，防止有人在反馈数仍为 0 时偷偷把状态改成"in
  discussion"或"started"。

---

## Maintainer release checklist（发给同事试用前必过一遍）

> 这是 maintainer 自己用的清单。**新同事不需要看**。
> 每次准备把试用包发给一个新内部团队前，按下面 8 项逐项确认；任何一项
> 不绿色都**不要**邀请新团队，先修。

### A. 文档/导航完整性
- [ ] `README.md` 顶部"v2.0 Internal Trial Ready"段已链接
  `docs/INTERNAL_TRIAL_LAUNCH_PACK.md`；
- [ ] `docs/INTERNAL_TRIAL.md` TL;DR 已链接 launch pack；
- [ ] launch pack §1 五条命令、§5 全部命令与
  `docs/INTERNAL_TRIAL_QUICKSTART.md`、`docs/INTERNAL_TRIAL.md` 命令
  **逐字一致**（drift 测试见
  `tests/test_docs_cli_snippets.py` / `tests/test_docs_cli_schema_drift.py`）。

### B. 命令真能跑
- [ ] Quickstart 五条命令本地复制粘贴跑通，10 个 artifact 全在；
- [ ] `judge-provider-preflight --out runs/<x>` 默认 `ready_for_live=false`
  且不联网；
- [ ] `audit-judge-prompts --prompts examples/judge_prompts.yaml --out runs/<y>`
  正常输出 markdown audit。

### C. 测试全绿
- [ ] `.venv/bin/python -m ruff check .` All checks passed；
- [ ] `.venv/bin/python -m pytest -q` ≥ 470 passed, 1 xfailed
  （xfailed 是 v0.2 候选 A subtle decoy strict xfail，已记录在 ROADMAP）；
- [ ] docs CLI snippet drift + schema drift + internal trial readiness +
  launch pack + dogfooding log 五组测试全绿。

### D. 安全 / no-leak
- [ ] grep 全 docs / tests / examples 无真实 key / Authorization /
  完整请求体 / 完整响应体 / base_url 敏感 query / SDK 异常长文本；
- [ ] 没有读取真实 `.env`；没有任何命令真的发起远端 HTTP；
- [ ] `.gitignore` 仍忽略 `runs/`、`.env`、`.venv/`。

### E. 反馈状态准确
- [ ] 本文件"真实内部团队反馈数量"= dogfooding log 中**真实团队记录数**
  （**不**包含 maintainer dry-run record）；
- [ ] 本文件"v3.0 状态"= **not started**；
- [ ] dogfooding log 中 maintainer dry-run record 段明确标
  `Template only — not real team feedback` 且 v3.0 4 项硬约束全填 N/A。

---

## 收到反馈后的分类（maintainer 操作手册）

收到一份新反馈时，**按下面顺序**判定它落到 §A / §B / §C / §D 哪一类：

1. **先做 no-leak 净化**：如果反馈中粘了真实 key / Authorization /
   完整请求体响应体，**立即按 §D 处理**（先阻断、再净化、再讨论），
   不允许进入分类。
2. **判定可否在 v2.x patch 内解决**（→ §A）：
   - 修复方案不需要 MCP / Web UI / live judge / HTTP / Shell executor /
     多租户 / 真实托管 LLM Judge 即可解决；
   - 例如：文档命令漂移、artifact 字段不直观、CLI 错误提示不可行动、
     启发式 finding 漏掉某类常见 tool 设计问题、Quickstart 前置条件
     缺失等。
3. **判定是否 v3.0 候选**（→ §B）：**必须同时**满足下面 3 项：
   - 反馈中**明确**说明 deterministic / offline 能力为什么不够；
   - 反馈中**明确**说出需要的 v3.0 能力（MCP / Web UI / live judge /
     HTTP / Shell executor 等）；
   - 反馈中**明确**说出**具体业务场景**——不是"看起来更厉害"、
     不是"我们以后可能需要"、不是"对标某竞品"。
4. **任何一项不满足**（→ §C）：欢迎收录，但**不**计入 v3.0 触发门槛
   的 3 份反馈。
5. **§D 安全 / 泄漏风险**（**最高优先级，先于 A/B/C**）：试用过程中
   发现可能泄漏 / 已经泄漏 → 立即按下面 4 步处理：
   1. **阻断**：要求试用者立即停止使用受污染的 fixture / runs 目录；
   2. **净化**：删除受污染 artifact、`git reset --hard` 撤销未推送
      commit；如已 push，走 secret rotation + git history 清洗流程；
   3. **不进入 A/B/C 分类**：只有净化完成、试用者重提脱敏后的反馈
      才允许重新进入分类；
   4. **登记**：在 dogfooding log 中以 D 类标记登记一次（**不**透露
      泄漏内容本身），用于改进未来 redaction confirmation 流程。

> v3.0 候选问题最终是否启动 v3.0，**必须**满足"§B 累计达到 3 份不同
> 团队 + 评估是否独立开新仓库 / 新 milestone"，并由 ROADMAP review
> 决定，不能由 maintainer 单方决定。
