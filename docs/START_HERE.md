# Start Here — 30 秒判断

## 这个项目适合你吗？

**适合你如果：**
- 你在设计 AI Agent 使用的工具，想通过 tool-use trace 检查工具质量
- 你已经有 Agent runner，想把 tool-use trace/log 导入进行结构化评测
- 你想理解 Agent 工具评测的流程（import → inspect → evaluate → report → review）
- 你在为工具设计质量建立 deterministic 检查基线

**不适合你如果：**
- 你想让 agent-tool-harness 帮你运行 Agent（harness 不运行 Agent）
- 你期望开箱即用的 LLM judge 自动语义评分（需显式 opt-in）
- 你需要 Web UI / MCP / 多租户 / Benchmark 平台

## 当前成熟度

**v3.0.0 tool-use inspection platform。** 核心能力是 deterministic tool-use inspection
（D1/D2/D4/D5/D6 + Phase 2 LLM judge rubric framework）。接入路径是 external runner
→ trace/log import → inspect/evaluate/report。agent-tool-harness 不运行 Agent。

## 最小上手路径

1. [`README.md`](../README.md) — install + pytest + trace import demo + CLI demo
2. [`CLI_USAGE.md`](CLI_USAGE.md) — 了解全部 CLI 命令
3. [`EXTERNAL_RUNNER_WORKFLOW.md`](EXTERNAL_RUNNER_WORKFLOW.md) — 理解外部 runner → trace import 工作流
4. [`PROJECT_INTEGRATION.md`](PROJECT_INTEGRATION.md) — 接入你自己的项目

## 文档阅读顺序

```
README.md                          ← 第一站：install + trace import + CLI demo
   ↓
START_HERE.md                      ← 你在这里：判断是否继续
   ↓
EXTERNAL_RUNNER_WORKFLOW.md        ← 推荐工作流：外部 runner → trace import
   ↓
TRACE_IMPORT_ADAPTER_SPEC.md       ← trace import spec（native + simple mapping）
   ↓
CURRENT_IMPLEMENTATION.md          ← 诚实了解当前实现边界
   ↓
AGENT2HARNESS_MAIN_FLOW.md         ← Core Flow 架构
   ↓
TOOL_USE_INSPECTION_SDD.md         ← Tool-use inspection 设计（D1-D8）
   ↓
HEADLESS_HARNESS_MODEL.md          ← Harness 执行模型
   ↓
DEMO_CORE_REAL_BOUNDARY.md         ← Demo / Core / Real 分层边界
   ↓
CLI_USAGE.md                       ← CLI 命令全集
   ↓
CONFIGURATION.md                   ← 配置文件格式
   ↓
PROJECT_INTEGRATION.md             ← 接入你的项目
   ↓
LLM_PROVIDER_CONFIG.md             ← Real LLM judge opt-in 配置
   ↓
ROADMAP.md                         ← 完整演进路线
   ↓
BACKLOG.md                         ← 详细 backlog
   ↓
REVIEW_CHECKLIST.md                ← Review 检查清单
```

## 当前不能做什么

- 不运行真实 Agent（primary path 是 external runner → trace/log import）
- Real LLM judge 不是默认路径——需通过 `--live --confirm-i-have-real-key --env-file` 显式 opt-in
- LLM judge rubric framework 已实现（fake-testable），但 real LLM live execution 需 opt-in
- deterministic rule checks 决定 pass/fail；JudgeFinding 为 advisory only
- 不做自动 optimizer / auto repair
- 不做 batch / multi-trace evaluation（deferred）
- 不做 Human Review UX（deferred）
- CLIAgentAdapter 已移除
