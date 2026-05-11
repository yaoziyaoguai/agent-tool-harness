# Headless CLI Agent Tool Harness Prototype

一个 **CLI-first、无 UI、文件配置驱动** 的 Agent 工具评测 Harness 原型。

它把工具配置、mock 执行、确定性规则检查、证据收集、报告生成、人工 Review 串成
一条可复现的评测链路，用于探索 Agent 工具设计质量评测流程。当前不是成熟平台。

## Current status

**Headless CLI Demo Prototype — 本地 mock replay + deterministic rule checks。**

- 所有功能纯本地、离线、不联网、不需要密钥。
- Agent 行为由 `MockReplayAdapter` 按 good/bad 分支回放，不是真实 LLM 决策。
- 判定由 `RuleJudge` 做确定性规则匹配，不是 LLM 语义评分。

## What works today

- [x] `audit-tools` — 工具契约确定性启发式审计（字段齐全性、命名规范、边界关键词）
- [x] `run --mock-path good|bad` — mock replay 执行 + 10 个 artifact 输出
- [x] `replay-run` — 历史 run 的 deterministic 轨迹重放
- [x] `analyze-artifacts` — 离线复盘 trace 信号（5 类 deterministic 启发式）
- [x] `generate-evals` + `promote-evals` — 候选 eval 生成 → 人工审核 → 转正
- [x] `bootstrap` — 从 Python 工具源码 AST 扫描生成 draft tools.yaml
- [x] `audit-judge-prompts` — judge prompt 安全/格式审计
- [x] `judge-provider-preflight` — 本地侧 live readiness 自检（不联网）
- [x] `report.md` 生成 — 含 signal_quality 声明和方法论边界警告

## What does not work yet

- [ ] 配置真实 OpenAI / Anthropic / DeepSeek API Key 后完成 Agent 评测
- [ ] 接入真实用户项目 runtime 做端到端 Agent 评估
- [ ] LLM Judge 语义评分
- [ ] 真实 Agent 行为评估（当前只有 mock replay）
- [ ] Web UI
- [ ] MCP executor
- [ ] HTTP / Shell executor
- [ ] RAG / 向量库
- [ ] 多租户 / 企业 RBAC
- [ ] Benchmark / Leaderboard 平台

## Quick start

```bash
git clone https://github.com/yaoziyaoguai/agent-tool-harness.git
cd agent-tool-harness
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q
```

## Minimal CLI demo

```bash
# 审计工具契约
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out runs/audit-tools

# mock replay — good 路径（预期 PASS）
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-good --mock-path good

# mock replay — bad 路径（预期 FAIL）
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-bad --mock-path bad
```

## How to read the output

1. `report.md` — 顶部 signal_quality + Failure attribution → 判断信号可信度
2. `diagnosis.json` — findings[] 含 grounding / decoy / when_not_to_use 信号
3. `judge_results.json` — 每条 eval 的 PASS/FAIL 理由
4. `tool_calls.jsonl` + `tool_responses.jsonl` — 实际调用链路证据

> MockReplayAdapter 的 PASS/FAIL 是结构性的（`signal_quality: tautological_replay`），
> 不代表真实 Agent 能力。RuleJudge 是确定性匹配，不是 LLM 语义判定。

## How to integrate your project (prototype level)

当前支持 prototype-level 集成：用配置文件描述你的项目和工具，在本 Harness 中
跑 mock replay + rule checks。**不支持真实 Agent runtime 接入。**

→ 详细指南：[`docs/PROJECT_INTEGRATION.md`](docs/PROJECT_INTEGRATION.md)

## Roadmap

| 阶段 | 内容 |
|------|------|
| Current | Headless CLI Demo Prototype |
| Next | 文档瘦身 + 入口收敛 |
| Then | RealAgentAdapter / JudgeProvider / ProviderConfig 设计 |
| Later | opt-in 真实 LLM trial |

明确不做（除非未来重新批准）：Web UI / MCP executor / RAG / Benchmark 平台。

→ 详细路线图：[`docs/ROADMAP.md`](docs/ROADMAP.md)

## Docs

| 想了解 | 看这份 |
|--------|--------|
| 30 秒判断是否适合你 | [`docs/START_HERE.md`](docs/START_HERE.md) |
| 当前实现诚实描述 | [`docs/CURRENT_IMPLEMENTATION.md`](docs/CURRENT_IMPLEMENTATION.md) |
| Harness 执行模型 | [`docs/HEADLESS_HARNESS_MODEL.md`](docs/HEADLESS_HARNESS_MODEL.md) |
| CLI 命令全集 | [`docs/CLI_USAGE.md`](docs/CLI_USAGE.md) |
| 配置文件格式 | [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) |
| 接入你的项目 | [`docs/PROJECT_INTEGRATION.md`](docs/PROJECT_INTEGRATION.md) |
| 路线图 | [`docs/ROADMAP.md`](docs/ROADMAP.md) |
| Review Checklist | [`docs/REVIEW_CHECKLIST.md`](docs/REVIEW_CHECKLIST.md) |
