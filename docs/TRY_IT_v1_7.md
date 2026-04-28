# Try the v1.6 + v1.7 product flow — 完整试用指引

> 这份文档面向"我刚 clone 仓库，想把 agent-tool-harness v1.6 / v1.7 的
> live readiness 治理三件套（retry/backoff、llm_cost、judge prompt audit）
> 端到端跑一遍"的用户。**全程离线 / 不调真实 LLM / 不联网 / 不需要密钥**。
>
> 第一次跑通预计 5-8 分钟。如果你是 v0.2 第一次接入，请先看
> [TRY_IT.md](TRY_IT.md)。

## 这条 v1.7 试用路径覆盖什么

| 步骤 | 命令 | 目的 | 怎么判断成功 | 失败时看哪里 |
|------|------|------|-------------|-------------|
| 1 | `judge-provider-preflight` | 检查 live readiness 配置 + 安全闸门 | `preflight.json` + `preflight.md`；`ready_for_live=false`（默认无 key） | `preflight.json::actionable_hints` |
| 2 | `audit-judge-prompts` | 启发式扫描 judge prompt 安全 | `audit_judge_prompts.json` + `.md`；critical/high finding 必须修 | `audit_judge_prompts.md` 按 severity 列表 |
| 3 | `run --mock-path bad` | 跑一次 unhappy path（必跑） | 10 个 artifact 全在；含新 `llm_cost.json` | `report.md::Cost Summary` + `diagnosis.json` |
| 4 | `replay-run --run RUN` | 把第 3 步当录像带 deterministic 重放 | 新 `--out` 目录 9 个 artifact 全在 | 源目录缺 `tool_calls.jsonl` 时 stderr 给 hint |
| 5 | `analyze-artifacts` | 离线复盘 trace 信号 | `tool_use_signals.json` + `.md` | stderr `--run` / `--evals` 提示 |
| 6 | 看 `llm_cost.json` + `report.md::Cost Summary` | 验证 v1.6 成本聚合 | `totals.advisory_count` 与配置匹配；`cost_unknown_reasons` 解释为什么没数 | 直接 `cat runs/.../llm_cost.json` |

## 一键跑全流程（runtime_debug example）

```bash
# 1) live readiness 自检（永远不联网，不读真实 key）
python -m agent_tool_harness.cli judge-provider-preflight \
  --out runs/v17-preflight-check

# 2) judge prompt 启发式安全审计（用仓库自带示例 fixture）
python -m agent_tool_harness.cli audit-judge-prompts \
  --prompts examples/judge_prompts.yaml \
  --out runs/v17-prompt-audit

# 3) 跑一次 bad path（会自动产出 llm_cost.json）
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/v17-run-bad \
  --mock-path bad

# 4) 把上一步当"录像带"deterministic 重放
python -m agent_tool_harness.cli replay-run \
  --run runs/v17-run-bad \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/v17-replay

# 5) 离线复盘 trace 信号
python -m agent_tool_harness.cli analyze-artifacts \
  --run runs/v17-run-bad \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/v17-analysis

# 6) 看成本与诊断
cat runs/v17-run-bad/llm_cost.json
grep -A 8 "Cost Summary" runs/v17-run-bad/report.md
```

## 关键 artifact 解读速查

### `runs/<dir>/llm_cost.json`（v1.6 新增）

- `totals`：跨所有 advisory 的 token / retry / error 累加；
- `cost_unknown_reasons`：解释为什么某些 advisory 没 token 数（如
  `"recorded mode does not report token usage"`）；
- `estimated_cost_usd`：v1.6 永远 `null`——**这不是真实账单**，价格表
  注入留给 v1.7+。

### `runs/<dir>/audit_judge_prompts.json`（v1.6 新增）

- `summary.by_severity`：critical/high 必须修；
- `findings[]`：每条 finding 含 `prompt_id` / `rule_id` / `severity` /
  `description` / `evidence`（key 字面**自动脱敏**）。

### `report.md::Cost Summary` 段

- 只在有 advisory 数据时渲染；显式声明 `(advisory-only, deterministic)`；
- 不要把这一段当报账依据。

## 常见反模式提醒

- **不要**把 `estimated_cost_usd` 当真实账单——v1.6 永远是 `null`；
- **不要**把 `audit-judge-prompts` 通过当成 prompt 安全终判——它只是
  启发式 baseline；
- **不要**因为 retry_count > 0 就以为 LiveAnthropicTransport 接通了真
  实 LLM——CI / smoke 路径全程是 fake transport / disabled，retry 也
  只是 fake clock 注入；
- **不要**把 raw key / Authorization header / base_url 写进 prompt 文
  本——`audit-judge-prompts` 会 critical 报警，且任何 audit/preflight/
  cost artifact 都会自动脱敏。

## 下一步

- 想了解每个 artifact 完整字段：[ARTIFACTS.md](ARTIFACTS.md)；
- 想了解架构边界与未来路线：[ARCHITECTURE.md](ARCHITECTURE.md) +
  [ROADMAP.md](ROADMAP.md)；
- v1.6 release notes：[../RELEASE_NOTES_v1.6.md](../RELEASE_NOTES_v1.6.md)；
- v0.2 / v1.0 旧版本 try-it 路径：[TRY_IT.md](TRY_IT.md)。
