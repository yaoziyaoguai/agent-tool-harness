# Internal Trial Request Template — 内部小组试用申请模板

> **目的**：内部小组准备开始 / 已完成一次 agent-tool-harness 试用时，
> 复制本模板填好后发给 maintainer，用于对外登记。本模板**不**替代
> [INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md](../INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md)
> （那是反馈正文）；本模板是 trial **登记**单。
>
> **使用方式**：复制下面 markdown 片段到内部 issue tracker / 团队 doc
> 系统，**不要**直接修改本文件。
>
> **不会被计入 v3.0 触发门槛**：本登记单只负责"我打算试用 / 我已试用"
> 登记；v3.0 门槛仍由
> [INTERNAL_TRIAL_FEEDBACK_SUMMARY.md](../INTERNAL_TRIAL_FEEDBACK_SUMMARY.md)
> 中真实反馈数量决定。

---

```markdown
# Internal Trial Request — <YYYY-MM-DD> — <your-team>

## 基本信息

- **Tool name**：（你要测的 AI tool 名称）
- **Owner**：（tool / 项目负责人，便于 maintainer 联系）
- **Tool purpose**：（1-3 句说明 tool 解决什么真实业务问题）
- **预计试用周期**：（≤ 2 周建议；超过请说明原因）

## 试用目标

- **Offline / deterministic test goal**：（你想用 harness 验证什么？
  例如：tool 描述是否让 Agent 选对场景 / output_contract 是否够约束
  Agent 给 evidence / bad path 时 Agent 是否能避开）
- **Input fixture path**：（你准备用的 transcript / 录像带 / 测试用例
  存在哪？相对路径或脱敏说明，**不要**贴绝对内部路径）
- **Expected behavior**：（good path 应观察到什么 / bad path 应触发哪
  类 finding）
- **Known limitations**：（你已知的 tool / 测试不足，例如：tool 暂不
  支持某类输入 / 测试用例覆盖不全）

## Redaction confirmation（**必填，否则 maintainer 不接收**）

逐项确认 ✅ 才能提交：

- [ ] 我已**确认**输入 fixture 不含真实 secret / API key / SSH key /
      DB 密码 / 内部 token；
- [ ] 我已**确认**输入 fixture 不含真实生产请求体 / 响应体（含真实
      用户数据 / 真实订单 / 真实日志）；
- [ ] 我已**确认**输入 fixture 不含真实 `Authorization` header；
- [ ] 我已**确认**输入 fixture 不含敏感 `base_url`（含 token / cookie /
      内部网段地址）；
- [ ] 我已**确认**输入 fixture 不含用户隐私（手机号 / 身份证 / 邮箱 /
      支付信息 / 个人健康数据）；
- [ ] 我已**确认**输入 fixture 不含未脱敏日志（HTTP / SDK 原始异常
      长文本）；
- [ ] 我已**确认**不会启用 live LLM judge（默认 deterministic / offline
      就够；如果确实需要 live，必须单独走 maintainer review，**不在**
      本登记单范围）。

## 试用产物

- **Report path**：（试用完成后填，例如 `runs/<your-team>-bad/report.md`；
  注意 `runs/` 已 gitignore，不会被推到仓库）
- **关键 finding 摘要**：（试用后 1-3 条最有用的 deterministic finding，
  **不要**贴完整 artifact 文本，只贴 finding id + 1 句话说明）

## 反馈分类（试用完成后填）

- [ ] **A 类 v2.x patch**：可在当前 v2.0 范围内修复（如文档漂移 /
      启发式漏掉某类 tool 设计问题 / artifact 字段不直观）
- [ ] **B 类 v3.0 backlog 候选**：必须 MCP / Web UI / live LLM Judge /
      HTTP / Shell executor 才能解决（**必须**同时填写下面 v3.0 4 项
      硬约束，否则归为 C 类）
- [ ] **C 类 信息不完整**：暂不计入 v3.0 触发门槛，欢迎之后补充
- [ ] **D 类 安全 / 泄漏风险**：试用过程中发现可能泄漏 / 已经泄漏，
      需要 maintainer 立即介入

## 是否请求 maintainer review

- [ ] **是**，请求 maintainer 在反馈进入 dogfooding log 前先 review
      （推荐第一次试用的小组都勾选）；
- [ ] **否**，团队自行追加到
      [INTERNAL_TRIAL_DOGFOODING_LOG.md](../INTERNAL_TRIAL_DOGFOODING_LOG.md)
      "试用记录模板"段。

## v3.0 4 项硬约束（**仅当反馈分类 = B 类时填**）

> 任何 B 类反馈**必须同时**满足下面 4 项才进入 v3.0 候选；任意一项
> 缺失自动降级为 C 类。

1. 当前 deterministic / offline 能力**为什么不够**（**具体业务场景**）：
2. 我需要 v3.0 的具体能力（MCP / Web UI / live LLM Judge / HTTP /
   Shell executor / 其他）：
3. 如果有 v3.0 能力，**哪个真实问题**能立刻被解决：
4. 这个能力是否**应该独立开新仓库 / 新 milestone** 处理，而不是污染
   v2.0 主线？
```

---

## 维护说明（给改这份模板的人看）

- 本模板是**登记单**，不是反馈正文也不是 v3.0 触发门槛输入；
- 不允许在本模板中**默认勾选** redaction confirmation；试用者必须
  逐项手动确认；
- 不允许加入"自动转 B 类"路径；B 类必须填齐 v3.0 4 项硬约束；
- 测试 `tests/test_internal_team_self_serve_trial.py` 钉死本模板的
  4 大段（基本信息 / Redaction confirmation / 反馈分类 4 类 / v3.0
  硬约束）和"不计入 v3.0 触发门槛"声明。
