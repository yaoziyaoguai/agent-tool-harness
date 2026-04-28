# Internal Trial Quickstart — 10-15 分钟最小闭环

> 一页版。**复制下面 5 条命令即可跑通**最小试用闭环。
> 完整版（含接入自己的工具 / pricing / budget / 全部 9+ artifact 解释）
> 见 [INTERNAL_TRIAL.md](INTERNAL_TRIAL.md)。

> 全程**离线 / 不调真实 LLM / 不联网 / 不需要密钥**。

## 0. 前提：3 行装好

```bash
git clone https://github.com/yaoziyaoguai/agent-tool-harness.git
cd agent-tool-harness && python -m venv .venv && source .venv/bin/activate
pip install -e . && python -m pytest -q   # 预期：>= 400 passed, 1 xfailed
```

## 1. 五条命令跑完最小闭环

下面 5 条按顺序复制粘贴。每条独立可重跑（输出在 `runs/quickstart-*`，
已被 `.gitignore` 忽略）。

```bash
# (1) audit 工具设计 → 看哪些工具字段缺 / 启发式语义重叠
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out runs/quickstart-audit

# (2) 跑 bad path → 必须故意失败，才能看到 diagnosis 信号
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/quickstart-run-bad \
  --mock-path bad

# (3) 把 run 当"录像带"deterministic 重放
python -m agent_tool_harness.cli replay-run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --run runs/quickstart-run-bad \
  --out runs/quickstart-replay

# (4) 离线复盘 trace 信号
python -m agent_tool_harness.cli analyze-artifacts \
  --run runs/quickstart-replay \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/quickstart-analysis

# (5) 看人类可读 report
cat runs/quickstart-run-bad/report.md
```

## 2. 跑通后看哪 3 个文件

按这个顺序读，**90% 失败 5 分钟内能定位**：

| 顺序 | 文件 | 看什么 |
|------|------|--------|
| 1 | `runs/quickstart-run-bad/report.md` | 顶部 `signal_quality` + `Failure attribution` 段 |
| 2 | `runs/quickstart-run-bad/diagnosis.json` | `findings[]` 含 grounding / decoy / when_not_to_use 信号 |
| 3 | `runs/quickstart-analysis/tool_use_signals.md` | trace 复盘信号（同义词改写场景仍会漏，详见 ARCHITECTURE Diagnose 段） |

## 3. 症状 → 先看哪个 artifact（速查）

| 症状 | 先看 | 再看 |
|------|------|------|
| 命令报错退出码非 0 | stderr | `--out` 目录是否被创建 |
| 跑完了但 PASS/FAIL 都不可信 | `metrics.json::signal_quality` | `report.md` 顶部 |
| FAIL 不知原因 | `report.md::Failure attribution` | `diagnosis.json` |
| PASS 但感觉"不对" | `metrics.json::signal_quality`（看是否 `tautological_replay`） | `transcript.jsonl` 真实输出 |
| 工具被 Agent 选错 | `audit_tools.json` finding | `tool_calls.jsonl` |
| eval 设计有问题 | `audit_evals.json` finding | `evals.yaml` 字段对照 |
| judge 判定怪 | `judge_results.json` rationale | `report.md::Per-Eval Details` |
| 想看成本 | `report.md::Cost Summary` | `llm_cost.json::totals`（顶层永远 null） |
| advisory / live 没就绪 | `runs/<dir>/preflight.json::summary.ready_for_live` | actionable_hints |

## 4. 接下来

- ✅ 跑通了 → 进 [INTERNAL_TRIAL.md §3 接入你自己的工具和 eval](INTERNAL_TRIAL.md#3-接入你自己的工具和-eval)；
- ✅ 想配 pricing / budget cap → [INTERNAL_TRIAL.md §4](INTERNAL_TRIAL.md#4-设置-pricing-与-per-eval-budget-cap)；
- ✅ 想提反馈 → 5 分钟极简版见 [INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md "5 分钟极简版"段](INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md#0-5-分钟极简版可选)；
- ❌ 跑不通 → 在反馈中精确到文件名 + 命令 + 行号，**不要**贴真实 key /
  Authorization / 完整请求/响应体。

## 5. 边界提醒（30 秒读完）

- `MockReplayAdapter` 的 PASS/FAIL 是**结构性的**，不代表 Agent 真实能力；
- `RuleJudge` 不是 LLM Judge，仍是 deterministic substring 校验；
- `ToolDesignAuditor` 是启发式，**字段写齐 ≠ 工具真好用**；
- `llm_cost.json` 是 advisory，**永远不是真实账单**，以 provider 官方
  console 为准；
- 真实 live LLM Judge / MCP / HTTP / Shell / Web UI **当前不做**，
  v2.0 不包含，详见 `docs/ROADMAP.md` "v2.0 不包含" 段。
