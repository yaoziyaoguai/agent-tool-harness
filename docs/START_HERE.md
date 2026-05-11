# Start Here — 30 秒判断

## 这个项目适合你吗？

**适合你如果：**
- 你在设计 AI Agent 使用的工具，想审计工具契约质量
- 你想理解"Agent 工具评测"的流程（audit → run → judge → report → review）
- 你想在 mock replay 模式下跑通工具评测的端到端闭环
- 你在为未来真实 LLM Agent 评测做技术准备

**不适合你如果：**
- 你想现在就接真实 OpenAI / Anthropic / DeepSeek API Key 做 Agent 评测
- 你想评估你的 AI Agent 在真实场景下的表现
- 你需要 LLM Judge 做语义评分
- 你需要 Web UI / MCP / 多租户 / Benchmark 平台

## 当前成熟度

**Headless CLI Demo Prototype。** 不是成熟平台。所有 Agent 行为是 mock replay，
所有 judge 是 deterministic rule checks。能跑通、能看懂流程，但不能替代真实评测。

## 最小上手路径

1. [`README.md`](../README.md) — 5 分钟跑通 demo（3 条命令）
2. [`CLI_USAGE.md`](CLI_USAGE.md) — 了解全部 CLI 命令
3. [`PROJECT_INTEGRATION.md`](PROJECT_INTEGRATION.md) — 接入你自己的项目（prototype level）

## 文档阅读顺序

```
README.md                     ← 第一站：了解项目 + 跑 demo
   ↓
START_HERE.md                 ← 你在这里：判断是否继续
   ↓
ANTHROPIC_LINEAGE.md          ← 设计来源：为什么这样设计
   ↓
DEMO_CORE_REAL_BOUNDARY.md    ← 架构边界：Demo / Core / Real 如何分层
   ↓
CURRENT_IMPLEMENTATION.md     ← 诚实了解当前实现边界
   ↓
HEADLESS_HARNESS_MODEL.md     ← 理解 Harness 执行模型
   ↓
CLI_USAGE.md                  ← CLI 命令全集
   ↓
CONFIGURATION.md              ← 配置文件格式
   ↓
PROJECT_INTEGRATION.md        ← 接入你的项目
   ↓
BACKLOG.md                    ← 当前 backlog（按三条 Track 组织）
   ↓
ROADMAP.md                    ← 完整演进路线
   ↓
REVIEW_CHECKLIST.md           ← Review 检查清单
```

## 当前不能做什么

- 不能接真实 LLM（OpenAI / Anthropic / DeepSeek）
- 不能用 LLM judge 做语义评分
- 不能接入真实 Agent runtime
- 不能作为 benchmark 平台使用
- deterministic rule checks 只能做 baseline，不能替代真实智能评测
