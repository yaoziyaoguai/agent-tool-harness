# Start Here — 30 秒判断

## 这个项目适合你吗？

**适合你如果：**
- 你在设计 AI Agent 使用的工具，想审计工具契约质量
- 你想理解"Agent 工具评测"的流程（audit → run → judge → report → review）
- 你想在 mock replay 模式下跑通工具评测的端到端闭环
- 你在为未来真实 LLM Agent 评测做技术准备

**不适合你如果：**
- 你想现在就接真实 OpenAI / Anthropic / DeepSeek API Key 做 Agent 评测（需 opt-in）
- 你需要 LLM Judge 做自动语义评分（当前 fake-testable rubric only，真实 LLM judge 需 opt-in）
- 你需要 Web UI / MCP / 多租户 / Benchmark 平台

## 当前成熟度

**v1 tool-use inspection platform。** 核心能力是 deterministic tool-use inspection
（D1/D2/D4/D5/D6 + Phase 2 LLM judge rubric framework）。接入路径是 external runner
→ trace/log import → inspect/evaluate/report。agent-tool-harness 不运行 Agent。

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

- LLM judge rubric framework 已实现（fake-testable），但真实 LLM live execution 不是默认路径，需显式 opt-in
- 不能作为 benchmark 平台使用
- deterministic rule checks 决定 pass/fail；JudgeFinding 为 advisory only
- 不运行真实 Agent runtime（primary path 是 external runner → trace/log import）
- 不做自动 optimizer / auto repair
