# First Internal Trial — Invite Message Template

> **维护者复制此模板，私聊或 IM 发给第一位非维护者内部同事**。请按
> ``<...>`` 占位替换；其余结构请勿改。本模板不可包含真实 key /
> Authorization header / 完整请求 / 完整响应 / 真实 endpoint URL。

---

```
Hi <colleague-handle>，

想请你帮忙做一次 agent-tool-harness 的「第一位内部试用者」走查（10–15 分钟）。

目标：从你自己工具仓库挑 1 个最简单的纯函数（不需要 secret / 网络 /
数据库 / 真实公司数据），按 7 步把"小工具评测"闭环跑通。这**不是**
需求收集会，**不是** v3.0 启动；只是想知道一个没参与开发的人能否独立
跑通 v2.x 离线评测。

请阅读：

  docs/FIRST_INTERNAL_TRIAL_HANDOFF.md

里面 §2 有"工具选择 10 秒决策表"，§3 是 7 步命令，§4 是反馈模板。

只要 3 件事：

1. 选一个最小工具（看 §2 决策表，不通过就换更小的）
2. 跑 §3 的 7 步命令（任何一步卡 ≥ 5 分钟请停下来记到反馈）
3. 把 §4 反馈模板填好后追加到 docs/INTERNAL_TRIAL_FEEDBACK_SUMMARY.md

⚠️ 安全边界：不要贴 API key / Authorization / 完整请求响应 /
真实 endpoint URL / 真实公司或用户数据到任何地方。详见 §6。

⚠️ Live judge：v2.x 第一轮试用**不要开** ``--live`` flag；按 mock-path
good 跑 deterministic smoke 即可。维护者已经验证了阿里云 gateway 3
个模型当前会返回 ``bad_response``（gateway envelope 不严格匹配
Anthropic Messages 格式），但**不阻塞** offline 主线。

如果你试用后觉得"必须 LLM judge / MCP / 真实 executor 才有用"，请在
反馈里 ``v3.0 candidate request`` 字段写一句**具体**理由（"我想要
LLM judge"不算理由，要写"我的工具语义判定无法用 RuleJudge 表达，因
为 ..."）。这是触发 v3.0 backlog 的唯一机制。

谢谢！
```

---

## 中文学习型说明（为什么单独抽出 invite 模板）

- **避免维护者每次都重写邀请话术**：直接复制粘贴即可，安全边界已内置
- **避免遗漏关键告警**：``no secret`` / ``live 不开`` / ``bad_response 不阻塞``
  / ``v3.0 触发条件``——4 条最容易被忽略的边界已经写在模板里
- **避免私聊里贴 key / endpoint**：模板顶部明确禁止；维护者复制前再次
  自检"我加的私人补充话术里有没有真实值"
- **不算文档膨胀**：本文件不进 README、不进 LAUNCH_PACK、不进 ROADMAP
  正文；只在 ``docs/FIRST_INTERNAL_TRIAL_HANDOFF.md`` 顶部链接一次
