# Headless CLI Agent Tool Harness Prototype

一个 **CLI-first、无 UI、文件配置驱动** 的 Agent 工具评测 Harness 原型。

它把工具配置、mock 执行、确定性规则检查、证据收集、报告生成、人工 Review 串成
一条可复现的评测链路，用于探索 Agent 工具设计质量评测流程。当前不是成熟平台。

## Design lineage

本项目对齐 Anthropic Engineering [Writing effective tools for agents — with agents](https://www.anthropic.com/engineering/writing-tools-for-agents) 工具设计方法论。当前项目是 headless CLI prototype，核心定位为 **tool-use inspection**——围绕 Agent tool-use logs 做工具检查、评测和质量报告。实现了 tool design audit、deterministic rule checks、trace import。当前不是完整真实 LLM Agent evaluation platform。后续方向见 [docs/TOOL_USE_INSPECTION_SDD.md](docs/TOOL_USE_INSPECTION_SDD.md)。

## Current status

**Headless CLI Demo Prototype — 本地 mock replay + deterministic rule checks。**

- 所有功能纯本地、离线、不联网、不需要密钥。
- Agent 行为由 `MockReplayAdapter` 按 good/bad 分支回放，不是真实 LLM 决策。
- 判定由 `RuleJudge` 做确定性规则匹配，不是 LLM 语义评分。

## What works today（v1 scope）

**接入路径：**
- [x] `TraceImportAdapter`（native + simple_mapping）— 从外部 trace/log 导入 ExecutionTrace（**唯一接入路径**）
- [x] Trace diagnostics（field coverage / type diagnostics / confidence / dry-run）

**Tool-use inspection（5 个模块，37+ deterministic rules）：**
- [x] D1 Trace Import — field coverage report, type diagnostics, trace confidence, mapping dry-run
- [x] D2 Tool-use Correctness — 9 rules（call_id / pairing / arguments / status / orphan / non-empty）
- [x] D4 Tool Ergonomics — 6 deterministic rules（name / namespace / overlap / similarity / wrapper / action-resource）
- [x] D5 Tool Response Quality — 6 rules（2 ERROR + 4 WARNING）（output presence / size / signal / error actionability / context）
- [x] D6 Tool Spec Quality — 10 rules（description / input_schema / parameters / output_contract / docs）

**LLM judge framework（Phase 2）：**
- [x] Rubric definitions（6 dimensions: 4 D4 + 2 D5, all advisory only）
- [x] ToolUseQualityJudge（fake, deterministic heuristics, no real LLM calls）
- [x] JudgeFinding advisory only — 不影响 `EvaluationResult.passed`
- [x] ReviewDecision human explicit only

**Supporting capabilities：**
- [x] `audit-tools` — 工具契约确定性启发式审计
- [x] `run --mock-path good|bad` — mock replay 执行 + artifact 输出
- [x] `replay-run` — 历史 run 的 deterministic 轨迹重放
- [x] `analyze-artifacts` — 离线复盘 trace 信号
- [x] `generate-evals` + `promote-evals` — 候选 eval 生成
- [x] `bootstrap` — AST 扫描生成 draft tools.yaml
- [x] `audit-judge-prompts` — judge prompt 安全/格式审计
- [x] `judge-provider-preflight` — 本地侧 live readiness 自检（不联网）
- [x] CoreEvaluation + ReportSummary + Evidence → Report 链路
- [x] CoreJudgeProvider Protocol + JudgeProvider factory（real LLM opt-in）

## What is deferred（明确不在 v1 scope）

- [ ] D3 Tool Metrics（error rate / redundancy / response size / latency）
- [ ] D7 Batch / multi-trace evaluation
- [ ] D8 Human Review UX
- [ ] D2 remaining rules（fallback / retry / grounding / order）
- [ ] D6 deferred rules（examples / auth / response_format — ToolSpec schema 不支持）
- [ ] JSONL importer / stdout parser
- [ ] Real LLM live rubric execution（infrastructure exists, rubric execution deferred）
- [ ] Optimizer / auto repair / LLM auto mapping
- [ ] CLIAgentAdapter（已移除）
- [ ] Web UI / Benchmark / Leaderboard 平台

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

## How to integrate your project

**推荐工作流（trace/log import，主路径）：**

1. 用自己的脚本/CI/外部 runner 运行 Agent
2. 保存 tool-use trace/log（JSON/JSONL/stdout）
3. 写 mapping config（如果格式非 native schema）
4. 用 `TraceImportAdapter` 导入 trace
5. 运行 `CoreEvaluation`
6. 生成 `Report`
7. Human Review

```bash
# 示例：导入 trace 并评测
python -c "
from agent_tool_harness.trace_import import TraceImportAdapter
from agent_tool_harness.core_evaluation import CoreEvaluation

adapter = TraceImportAdapter(mode='native')
trace = adapter.import_file('path/to/trace.json')
evidence = adapter.to_evidence(trace)
result = CoreEvaluation().evaluate(evidence)
print(f'passed: {result.passed}')
"
```

agent-tool-harness **不运行 Agent**。所有 Agent 启动由外部 runner/CI/用户脚本负责。

→ 详细指南：[`docs/PROJECT_INTEGRATION.md`](docs/PROJECT_INTEGRATION.md)
→ 外部 runner 工作流：[`docs/EXTERNAL_RUNNER_WORKFLOW.md`](docs/EXTERNAL_RUNNER_WORKFLOW.md)

## Roadmap

| 阶段 | 内容 |
|------|------|
| Current (v1) | TraceImportAdapter + D1/D2/D4/D5/D6 tool-use inspection + Phase 2 LLM judge rubric framework |
| Next | Tool metrics (D3) + batch evaluation (D7) + human review UX (D8) |
| Later | Real LLM rubric execution, D2 remaining rules, D6 deferred rules |

明确不做：Web UI / MCP executor / RAG / Benchmark / 把 Agent 启动逻辑塞进 Core /
为每个 Agent 写 wrapper / 自动 optimizer / 运行真实 Agent / CLIAgentAdapter。

→ 详细路线图：[`docs/ROADMAP.md`](docs/ROADMAP.md)
→ Tool-use inspection SDD：[`docs/TOOL_USE_INSPECTION_SDD.md`](docs/TOOL_USE_INSPECTION_SDD.md)

## Docs

| 想了解 | 看这份 |
|--------|--------|
| 30 秒判断是否适合你 | [`docs/START_HERE.md`](docs/START_HERE.md) |
| 当前实现诚实描述 | [`docs/CURRENT_IMPLEMENTATION.md`](docs/CURRENT_IMPLEMENTATION.md) |
| Harness 执行模型 | [`docs/HEADLESS_HARNESS_MODEL.md`](docs/HEADLESS_HARNESS_MODEL.md) |
| CLI 命令全集 | [`docs/CLI_USAGE.md`](docs/CLI_USAGE.md) |
| 配置文件格式 | [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) |
| 接入你的项目 | [`docs/PROJECT_INTEGRATION.md`](docs/PROJECT_INTEGRATION.md) |
| Tool-use inspection SDD | [`docs/TOOL_USE_INSPECTION_SDD.md`](docs/TOOL_USE_INSPECTION_SDD.md) |
| 路线图 | [`docs/ROADMAP.md`](docs/ROADMAP.md) |
| Review Checklist | [`docs/REVIEW_CHECKLIST.md`](docs/REVIEW_CHECKLIST.md) |
