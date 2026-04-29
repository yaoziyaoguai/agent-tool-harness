# Real Trial Candidate Pack（v2.x Real Trial Readiness）

**目标读者**：内部第一次拿"自己项目里的小工具"接入 `agent-tool-harness`
做试用的同事。

**核心边界**：
- 这不是产品文档；
- 仍属 v2.x patch，**不**包含 MCP / Web UI / live LLM Judge / HTTP·Shell
  executor / 企业级平台能力（这些都是 **v3.0** backlog，且**未启动**）；
- v2.x 安全契约：**no secrets read / no network / no live LLM / no untrusted
  code execution**（不读 `.env` / 不联网 / 不调真实 LLM / 不执行不可信用户工具）。

---

## 1. 选第一个试用工具：推荐 vs 不推荐

> 选一个**最小**工具试用，比"上来接整个项目"少踩 90% 的坑。

### ✅ 推荐
- 单一工具（不是工具链）；
- 输入参数 ≤ 3 个，类型简单（str / int / dict）；
- 输出可以用一个 dict / json 表达；
- **不**需要真实 secret / API key / Authorization；
- **不**需要联网；
- 输出可以被 mock / fixture 表达（mockable / example only 即可）；
- 可以写出 2–3 条 deterministic eval（rule-based judge 能验证）；
- 不会执行危险副作用（删数据 / 发邮件 / 调外部支付等）；
- 不需要真实用户数据 / PII。

### ❌ 不推荐（第一轮）
- 上来接整个项目 / 多工具链路；
- 上来接真实外部 API（HTTP / 第三方 SDK）；
- 上来接数据库（读写 production DB）；
- 上来接需要真实 key 的工具（Stripe / OpenAI / 内部 token）；
- 上来做 live LLM judge；
- 依赖 MCP server（v3.0 backlog）；
- 依赖 Web UI / Shell executor；
- 工具有重要副作用（发钱 / 发邮件 / 删账户）；
- 工具结果依赖时间 / 随机种子 / 外部状态（不可 deterministic）。

---

## 2. 试用路径（Copy-paste 可跑）

```bash
# 1. 一条命令生成 draft 三件套 + REVIEW_CHECKLIST + validation_summary
python -m agent_tool_harness.cli bootstrap \
  --source path/to/your_tool_module \
  --out ./ath-bs

# 2. 打开 REVIEW_CHECKLIST.md，按里面的 §6 First Tool Suitability Checklist
#    确认目标工具适合做第一轮试用。
open ./ath-bs/REVIEW_CHECKLIST.md

# 3. 修 TODO（when_to_use / output_contract / token_policy / 业务期望等），
#    把 evals.generated.yaml 里某条 eval 改成 runnable: true。

# 4. doctor 复查
python -m agent_tool_harness.cli validate-generated --bootstrap-dir ./ath-bs

# 5. 改完后跑 strict 校验（reviewer 声称已 review）
python -m agent_tool_harness.cli validate-generated \
  --bootstrap-dir ./ath-bs --strict-reviewed

# 6. deterministic smoke run（mock 桩；不联网；不调真实 LLM）
python -m agent_tool_harness.cli run \
  --project your_project.yaml \
  --tools ./ath-bs/tools.generated.yaml \
  --evals ./ath-bs/evals.generated.yaml \
  --out runs/first-trial --mock-path good

# 7. 看 report / 9 件套 artifact
open runs/first-trial/report.md
ls runs/first-trial/
```

完整 reviewed 形态参考 `examples/bootstrap_to_run/`（含可直接 run 的
最小 sample，端到端写出 10 件套 artifact）。

---

## 3. 反馈与试用纪律

- **不要**把真实 API key / Authorization header / 完整请求体 / 完整响应体
  粘进 prompt / issue / artifact / 反馈渠道；
- 真实内部反馈不足 3 份之前**不**讨论 v3.0；先把 v2.x bootstrap UX +
  deterministic smoke 跑顺；
- 失败也是有价值的反馈：哪一步 README 没说清 / 哪个错误提示不可行动 /
  哪个 artifact 看不懂 → 都可以直接反馈给 maintainer。

---

## 4. 不会做的事（v2.x 硬约束）

- 不执行用户代码（仅 ast 静态扫描 + PythonToolExecutor 在 `run` 时
  按用户配置显式 spec_from_file_location，**不**自动 import）；
- 不读 `.env`；
- 不联网；
- 不调真实 LLM；
- 不自动 approve 任何配置；
- 不伪造业务正确答案；
- 不替你决定第一个工具是哪个 —— 由你按上面 checklist 自己判断。

---

_本文档由 v2.x Real Trial Readiness 引入，后续 v3.0（MCP / Web UI /
live LLM judge / HTTP·Shell executor）启动前不会再扩张范围。_
