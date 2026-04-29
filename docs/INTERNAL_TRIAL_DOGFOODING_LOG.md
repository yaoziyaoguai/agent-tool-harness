# Internal Trial Dogfooding Log — 内部试用记录

> 这份文档记录**每一次**内部小团队试用 agent-tool-harness 的真实经历。
> 它不是营销材料，不是路线图；它是 v3.0 触发条件的**真实证据库**：
> 没有这里的记录，v3.0 不会被启动。

> 提交方式：每次试用后**追加**一个 `## 试用记录 — <YYYY-MM-DD> — <团队/试用人>`
> 段落到本文件末尾（不要修改历史段落）。也可以另起 `feedback/<team>-<date>.md`
> 单文件，再在本 log 顶部"已收录反馈索引"区登记一行链接。

---

## 当前 dogfooding 状态汇总

| 指标 | 当前值 |
|---|---|
| **真实**内部团队试用记录数 | **0** |
| 维护者 dry-run 记录数（**不计入** v3.0 门槛） | **1**（[Maintainer dry-run record](#maintainer-dry-run-record)） |
| 距 v3.0 讨论门槛（≥3 份**真实团队**反馈）还差 | **3 份** |
| v3.0 状态 | **not started**（严格保持 backlog） |

> v3.0 触发条件硬约束（来自
> [INTERNAL_TRIAL_LAUNCH_PACK.md §8](INTERNAL_TRIAL_LAUNCH_PACK.md#8-v30-触发条件严格保持-backlog)
> 与 [ROADMAP §v2.0 终点定义](ROADMAP.md#v20-终点定义主线唯一终点避免无限滚版本)）：
>
> 1. 至少 **3 份**来自不同试用团队的内部反馈；
> 2. 每份反馈**明确**说明 deterministic / offline 能力为什么不够；
> 3. 每份反馈**能指出**需要哪类 v3.0 能力（MCP / Web UI / live judge /
>    HTTP / Shell executor）的**具体业务原因**；
> 4. 评估这些能力是否应**独立开新仓库 / 新 milestone** 处理，
>    而不是污染 v2.0 主线。
>
> 任一条件未满足时，所有 v3.0 能力请求**一律**继续转入 backlog，
> **不得**在 v2.x patch 中偷偷夹带。

### 已收录反馈索引

> 本区按时间倒序追加，便于一眼看到最近一次试用结果。
> 暂无收录。第一次试用人请在下方"试用记录模板"复制粘贴一段。

---

## 试用记录模板（复制下面整段，填好后**追加到文件末尾**）

```markdown
## 试用记录 — YYYY-MM-DD — <团队/试用人>

### 元数据
- 试用人 / 团队：
- 日期：
- 项目类型（你自己的项目是哪类？）：
- 你接入的 tool 类型（数据查询 / 代码 grep / runtime debug / knowledge search / 其他）：
- eval 数量：
- 是否 10-15 分钟内跑通 Quickstart？（是 / 否）

### 跑通过程
- 完整跑通了哪些命令（按 [LAUNCH_PACK §5 关键命令入口](INTERNAL_TRIAL_LAUNCH_PACK.md#5-关键命令入口可复制)
  顺序勾选）：
  - [ ] audit-tools
  - [ ] audit-evals
  - [ ] run --mock-path good
  - [ ] run --mock-path bad
  - [ ] replay-run
  - [ ] analyze-artifacts
  - [ ] judge-provider-preflight
  - [ ] audit-judge-prompts
- 卡住的步骤（哪一条命令 / 哪一个 artifact 让你停下来超过 5 分钟）：
- 卡住时你看的是哪个 artifact / 文档 / stderr？

### 发现 / 体验
- 最有用的 artifact（按
  [LAUNCH_PACK §3 如何看结果](INTERNAL_TRIAL_LAUNCH_PACK.md#3-如何看结果reportartifactfailure-attribution)
  9+ 类中选）：
- 最难懂的 report 字段（按
  [LAUNCH_PACK §4 失败排查顺序](INTERNAL_TRIAL_LAUNCH_PACK.md#4-失败排查顺序不要先猜按证据链看)
  对照）：
- 哪一条 deterministic 启发式 finding 帮你发现了真实工具问题？

### v3.0 能力诉求（**严格按下面 4 项填写，不能跳过**）
> 任何"我觉得需要 v3.0"的诉求**必须**同时满足下面 4 项才会被记入
> v3.0 讨论；只填 1-2 项的反馈仍然欢迎，但不计入 v3.0 触发门槛。

1. 我需要 v3.0 的具体能力（MCP / Web UI / live LLM Judge / HTTP / Shell / 其他）：
2. 当前 deterministic / offline 能力**为什么不够**（**具体业务场景**）：
3. 如果有 v3.0 能力，**哪个真实问题**能立刻被解决：
4. 这个能力是否**应该独立开新仓库 / 新 milestone** 处理，而不是污染 v2.0 主线？

### 安全 / no-leak 自查
> 提交前请自检；任何 ✅ 都意味着你**没有**在本记录里写过对应内容。
- ✅ 没有粘真实 API key / Authorization header；
- ✅ 没有粘完整请求体 / 完整响应体；
- ✅ 没有粘 base_url 中包含 token / cookie / 内部地址 query；
- ✅ 没有粘 HTTP / SDK 原始异常长文本（这些常含 token）；
- ✅ 反馈中提到的 path / fixture 都是公开示例 / 已脱敏。
```

---

## 维护说明（给改这份文档的人看）

- 本文是**追加型**文档；不要修改历史试用记录段，不要删除"当前 dogfooding
  状态汇总"上方的 v3.0 触发条件硬约束；
- 每次新增一份试用记录后，请把"已收录试用记录数"对应数字 +1，
  并把"距 v3.0 讨论门槛还差"对应数字 -1（不能为负）；
- 一旦"已收录试用记录数"达到 3 且每份都满足 v3.0 4 项硬约束，
  请在 [INTERNAL_TRIAL_FEEDBACK_SUMMARY.md](INTERNAL_TRIAL_FEEDBACK_SUMMARY.md)
  中触发"v3.0 讨论门槛已达"提案，**仍然不直接启动 v3.0**——需独立
  ROADMAP review 决定；
- 测试 `tests/test_internal_trial_dogfooding_log.py` 钉死本文件结构契约。

---

## Maintainer dry-run record

> **Template only — not real team feedback.**
> 这是维护者本地 dry-run，仅用来钉住 launch pack / Quickstart 命令是否
> 真能复制粘贴跑通、artifact 是否齐、文档与 CLI 是否漂移。
> **不计入** v3.0 触发门槛的 3 份团队反馈；**不**代表任何外部团队体验。
> 真实团队请按上面 "试用记录模板" 追加新段，**不要**修改本段。

### 元数据
- 试用人 / 团队：maintainer dry-run（本地）
- 日期：见对应 git commit 日期，**不**手填具体日期，避免造成"已有团队
  在某日反馈"的误解
- 项目类型：repo 自带 `examples/runtime_debug/` demo
- 接入的 tool 类型：runtime debug demo（非真实业务工具）
- eval 数量：1（demo eval，非真实业务 eval）
- 是否 10-15 分钟内跑通 Quickstart：是（按 `INTERNAL_TRIAL_QUICKSTART.md`
  §0 + §1 五条命令；前提是用 `pip install -e ".[dev]"` 而不是
  `pip install -e .`，否则 pytest 不会被装上）

### 跑通过程
- 完整跑通了哪些命令（按 [LAUNCH_PACK §5 关键命令入口](INTERNAL_TRIAL_LAUNCH_PACK.md#5-关键命令入口可复制) 顺序）：
  - [x] audit-tools
  - [x] audit-evals
  - [ ] run --mock-path good（Quickstart 默认只走 bad；good 在完整版
    `INTERNAL_TRIAL.md` 中演示）
  - [x] run --mock-path bad
  - [x] replay-run
  - [x] analyze-artifacts
  - [x] judge-provider-preflight（默认 advisory，`ready_for_live=false`）
  - [x] audit-judge-prompts（用 `examples/judge_prompts.yaml`）
- 卡住步骤：无（dry-run 已对齐 launch pack 命令；任何漂移都会被
  `tests/test_docs_cli_schema_drift.py` 抓到）。

### 发现 / 体验（仅 dry-run 视角）
- 最有用的 artifact：`runs/<dir>/report.md` 顶部 `Signal Quality` 段
  + `Failure Attribution` 段（明确告诉读者 PASS/FAIL 是结构性的）。
- 最难懂的字段：`metrics.json::signal_quality` 三态（`tautological_replay`
  / `recorded_trajectory` / `live_run`）的边界初看不直观；已被 launch pack
  §3 / §4 速查表覆盖。
- 真实团队接入前已修的真实接入断点（dry-run 抓到的）：
  - `INTERNAL_TRIAL_QUICKSTART.md §0` 漏 `[dev]` extras（已修）；
  - `INTERNAL_TRIAL_QUICKSTART.md §3` 把 `Cost Summary` 当无条件存在
    （实际只在配置 pricing/budget 时才渲染，已加条件说明）；
  - `INTERNAL_TRIAL_FEEDBACK_SUMMARY.md` 引用了不存在的测试文件路径
    （已改为真实文件 `tests/test_internal_trial_dogfooding_log.py`）。

### v3.0 能力诉求
1. 我需要 v3.0 的具体能力：**无**。dry-run 不能代表真实业务诉求。
2. 当前 deterministic / offline 能力为什么不够：**N/A**（dry-run 仅验证
   v2.x patch 完整性，未涉及任何真实业务场景）。
3. 如果有 v3.0 能力，哪个真实问题能立刻被解决：**N/A**。
4. 是否应独立开新仓库 / 新 milestone：**N/A**。

### 安全 / no-leak 自查
- ✅ 没有粘真实 API key / Authorization header；
- ✅ 没有粘完整请求体 / 完整响应体；
- ✅ 没有粘 base_url 中包含 token / cookie / 内部地址 query；
- ✅ 没有粘 HTTP / SDK 原始异常长文本；
- ✅ 反馈中提到的 path / fixture 都是 repo 内公开示例。

---

## 示例反馈格式（Example only — not real internal feedback）

> ⚠️ **Example only — not real internal feedback.**
> ⚠️ **Does not count toward the 3-feedback v3.0 gate.**
>
> 下面这一段是"示例反馈格式"，用来给真实试用者**演示一份合格反馈
> 长什么样**。它**不是**任何外部团队的真实反馈，**不计入** v3.0 触发
> 门槛的 3 份真实反馈。真实试用者请按上面"试用记录模板"复制一段新的，
> **不要**修改本段。

```markdown
## 试用记录 — 2099-01-01 — example-team / Demo User （示例，非真实）

### 元数据
- 试用人 / 团队：example-team / Demo User （**EXAMPLE ONLY，非真实**）
- 日期：2099-01-01（占位日期，避免被读成真实事件）
- 项目类型：内部数据查询服务（示例）
- 接入的 tool 类型：1 个 SQL 查询 tool + 1 个 grep tool（示例）
- eval 数量：3
- 是否 10-15 分钟内跑通 Quickstart：是

### 跑通过程
- 完整跑通了哪些命令：
  - [x] audit-tools
  - [x] audit-evals
  - [x] run --mock-path good
  - [x] run --mock-path bad
  - [x] replay-run
  - [x] analyze-artifacts
  - [ ] judge-provider-preflight（暂未需要 live judge）
  - [ ] audit-judge-prompts（暂无 judge prompt 文件）
- 卡住的步骤：第一次跑 `audit-tools` 没看懂 `weak_when_to_use` finding 的
  根因，看了 `runs/<dir>/diagnosis.json::tool_use_signals` 才理解。
- 卡住时看的：`report.md` 顶部 + `diagnosis.json::findings[]`。

### 发现 / 体验
- 最有用的 artifact：`report.md::Failure Attribution` 段，把 FAIL 直接
  归类到"agent_tool_choice"，省去自己翻 transcript。
- 最难懂的字段：`metrics.json::signal_quality` 三态边界初看不直观；
  看了 launch pack §0.5 关键词速懂段才理解。
- deterministic 启发式发现的真实工具问题：1 个 SQL 工具 `when_to_use`
  写得过宽，`audit-tools` 报 `weak_when_to_use`；按建议补窄后再跑，
  finding 消失。

### v3.0 能力诉求（**EXAMPLE ONLY，4 项硬约束按真实反馈格式写**）
1. 我需要 v3.0 的具体能力：暂无（示例反馈不引出 v3.0）。
2. 当前 deterministic / offline 能力为什么不够：N/A（示例反馈不引出
   v3.0；真实反馈中此项必须填具体业务场景）。
3. 如果有 v3.0 能力，哪个真实问题能立刻被解决：N/A。
4. 这个能力是否应独立开新仓库 / 新 milestone：N/A。

### 安全 / no-leak 自查
- ✅ 全部 ✅（示例反馈不含任何真实 key / Authorization / 请求体 / 响应体 / 内部地址）。
```
