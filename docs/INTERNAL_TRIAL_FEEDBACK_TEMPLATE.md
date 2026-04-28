# Internal Trial 反馈模板

> 内部小团队试用 agent-tool-harness 后请用本模板提交反馈。
> 把整个文件复制一份到 `feedback/<your-team>-<YYYY-MM-DD>.md`
> 或贴到内部 issue tracker。
>
> **不要**在反馈里粘贴真实 API key、Authorization header、完整请求/
> 响应体、base_url 含敏感 query 的字符串、HTTP/SDK 原始异常长文本。
> 只贴脱敏后的关键片段（reviewer 能定位 artifact 行号即可）。

## 0. 5 分钟极简版（可选）

**没时间填完整版？只填这 5 行也能给我们最关键反馈：**

- (a) `INTERNAL_TRIAL_QUICKSTART.md` 5 条命令是否能直接复制粘贴跑通？（是 / 否，否的话第几条卡住）：
- (b) 跑完后能不能 5 分钟内看懂 `report.md` + `diagnosis.json`？（是 / 否 / 部分）：
- (c) 你试用过程中最大的 1 个痛点（一句话）：
- (d) 整体推荐意愿 1-5 分（5=会推荐给其它团队）：
- (e) 是否会继续用 agent-tool-harness？（会 / 不会 / 看情况，原因一句话）：

填完上面 5 行就可以直接提交。下面是完整版（可选）。

---

## 1. 项目背景

- 团队名：
- 团队规模（人数）：
- Agent 用途（一句话）：
- 你想用 agent-tool-harness 验证什么问题：

## 2. 接入规模

- `tools.yaml` 工具数量：
- `evals.yaml` eval 数量：
- 是否使用了 `examples/` 下的现成例子作为模板（runtime_debug /
  knowledge_search / 都没用 / 其它）：

## 3. 跑了哪些命令

请勾选你实际跑过的（也可以补充）：

- [ ] `audit-tools`
- [ ] `generate-evals --source tools`
- [ ] `promote-evals`
- [ ] `audit-evals`
- [ ] `run --mock-path good`
- [ ] `run --mock-path bad`
- [ ] `replay-run`
- [ ] `analyze-artifacts`
- [ ] `judge-provider-preflight`
- [ ] `audit-judge-prompts`
- [ ] 其它（请列出）：

## 4. 失败 / 不可信结果

请精确到 eval id / artifact 文件名 / 行号：

| eval_id | 期望 | 实际 | 你看的 artifact | 你的判断（真实 bug / advisory / 不确定） |
|---------|------|------|----------------|----------------------------------|
|         |      |      |                |                                  |

## 5. 文档 / 命令是否可复制粘贴

- [ ] README 快速开始能直接复制粘贴跑通
- [ ] `docs/TRY_IT.md` v0.2 路径能直接跑通
- [ ] `docs/TRY_IT_v1_7.md` v1.6/v1.7 路径能直接跑通
- [ ] `docs/INTERNAL_TRIAL.md` 本指南能直接跑通

如果有命令复制粘贴失败，请贴出失败命令 + 实际报错（脱敏）：

```
$ <command>
<error message>
```

## 6. report / artifact 是否可行动

- [ ] `report.md` 总览能让我快速判断 PASS / FAIL；
- [ ] `report.md::Failure attribution` 能定位失败原因；
- [ ] `report.md::Cost Summary` 能让我看到 advisory token / cost；
- [ ] `report.md::Per-Eval Details` 能解释每条 eval 的判定；
- [ ] `diagnosis.json` 的 finding 是可行动的（有 suggested_fix /
  rule_id / severity）；
- [ ] `audit_tools.json` 的 finding 能告诉我具体哪个工具哪个字段需要改；
- [ ] `audit_evals.json` 的 finding 能告诉我具体哪条 eval 不 runnable；
- [ ] `llm_cost.json` 的 advisory cost / budget 状态可信；

不可行动的具体例子（artifact 路径 + 你期望的样子）：

## 7. key / no-leak / budget / doc drift 检查

- [ ] 没在任何 artifact / 文档 / git diff / 控制台输出看到 `sk-` 字面、
  `Authorization: Bearer ...`、完整请求/响应体；
- [ ] `llm_cost.json` 的 `estimated_cost_usd` 顶层是 `null`；
- [ ] `llm_cost.json` 的 `estimated_cost_note` 含 advisory-only 措辞；
- [ ] `judge-provider-preflight` 默认 `summary.ready_for_live=false`；
- [ ] 没有遇到"README 命令在我机器跑不通"的 doc drift；

如果发现疑似泄漏 / advisory 被宣传成真实账单 / preflight 默认值不对 /
doc drift，请精确记录（**不要**贴真实泄漏内容，只贴文件名 + 行号）：

## 8. 希望改进点

按优先级（P0 阻塞 / P1 高价值 / P2 后续可做）排序：

- P0:
- P1:
- P2:

## 9. 整体满意度（1-5 分）

- 安装易用度：
- 文档清晰度：
- artifact 可行动性：
- 整体推荐意愿：

## 10. 其它

- 你认为 v2.0 Internal Trial Ready 还缺什么？
- 你愿意把这个 harness 推荐给其它团队吗？为什么 / 为什么不？
