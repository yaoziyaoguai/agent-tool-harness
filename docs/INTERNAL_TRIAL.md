# Internal Trial 指南 — 给公司内部小团队第一次试用的人

> **TL;DR — 想立刻跑通最小闭环？请先读 [INTERNAL_TRIAL_QUICKSTART.md](INTERNAL_TRIAL_QUICKSTART.md)（一页 5 条命令，10-15 分钟）。**
> 本页是完整版（含接入自己的工具 / pricing / budget / 9+ artifact 解释）。
>
> 这份文档面向**公司内部 5-10 人小团队**第一次试用 agent-tool-harness。
> 它**不是**面向企业级 / 多租户 / 生产 SaaS 用户。读完这页你应该能：
>
> - 在本地把 harness 跑通（30 分钟内）；
> - 用自己团队的 `project.yaml` / `tools.yaml` / `evals.yaml` 接入；
> - 看懂 9+ artifact 与 `report.md`，分辨"哪些信号可信、哪些是
>   advisory / mock / dry-run"；
> - 设置 pricing 与 per-eval budget cap；
> - 提交结构化反馈（见 [INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md](INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md)）。
>
> 全程**离线 / 不调真实 LLM / 不联网 / 不需要密钥**。需要真实 live
> 试跑请走强 opt-in 路径（README live opt-in 节，**仅本地**）。

## 0. 内部试用范围说明（请先读完）

下面这些能力当前已就绪：

| 能力 | 状态 |
|------|------|
| `audit-tools` / `audit-evals` | ✅ deterministic 启发式 |
| `generate-evals` (`--source tools`) | ✅ |
| `promote-evals` | ✅ deterministic |
| `run` + 9+ artifact | ✅ MockReplayAdapter / 真实 adapter（用户可选） |
| `replay-run` | ✅ deterministic 重放 |
| `analyze-artifacts` | ✅ deterministic trace 信号复盘 |
| `judge-provider-preflight` | ✅ 默认 not ready，advisory-only |
| `audit-judge-prompts` | ✅ 7 类启发式 |
| pricing / budget cap | ✅ advisory-only，**永远不是真实账单** |
| RuleJudge baseline + recorded / composite judge | ✅ deterministic |
| 强 opt-in live judge smoke（仅本地） | ✅ CI 默认禁用 |

下面这些能力**当前未做**，请不要假设它们可用：

- ❌ Web UI / SaaS / 多租户；
- ❌ MCP / HTTP / Shell executor；
- ❌ 自动修复用户工具（auto-patch）；
- ❌ 大规模 benchmark / leaderboard；
- ❌ 企业 RBAC / SSO；
- ❌ 真实托管 LLM Judge 自动评估服务（**只能在你自己机器**强 opt-in
  跑 smoke）；
- ❌ "MockReplayAdapter PASS / FAIL" 直接代表"你的 Agent 能力强弱"
  （它只是 deterministic 复述 expected_tool_behavior，详见
  [TRY_IT_v1_7.md 反模式提醒](TRY_IT_v1_7.md)）。

---

## 1. 环境准备

```bash
# 1.1 Python 3.12
python --version  # 必须 3.12.x

# 1.2 clone 仓库
git clone https://github.com/yaoziyaoguai/agent-tool-harness.git
cd agent-tool-harness

# 1.3 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate   # macOS / Linux
# Windows: .venv\Scripts\activate

# 1.4 安装本仓库（editable）
pip install -e .

# 1.5 sanity check：跑测试
python -m pytest -q
# 预期：>= 400 passed, 1 xfailed
```

---

## 2. 跑已有 examples（验证安装）

仓库自带两个 example：`examples/runtime_debug/` 与
`examples/knowledge_search/`。先用前者验证安装：

```bash
# 2.1 audit 工具设计
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out runs/internal-audit-tools

# 2.2 跑 bad path（必跑，才能看到 diagnosis 信号）
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/internal-run-bad \
  --mock-path bad

# 2.3 看 9+ artifact
ls runs/internal-run-bad/
# transcript.jsonl tool_calls.jsonl tool_responses.jsonl
# metrics.json audit_tools.json audit_evals.json
# judge_results.json diagnosis.json llm_cost.json report.md

# 2.4 看人类可读 report
cat runs/internal-run-bad/report.md
```

完整端到端 6 步路径见 [TRY_IT_v1_7.md](TRY_IT_v1_7.md)（含
`replay-run` / `analyze-artifacts` / `judge-provider-preflight` /
`audit-judge-prompts`）。

---

## 3. 接入你自己的工具和 eval

### 3.1 写 `project.yaml`

最小骨架：

```yaml
project:
  name: my-team-agent
  domain: customer-support
  description: 我们团队的 customer-support Agent

evidence_sources:
  - id: kb
    name: Internal KB
    description: 内部知识库摘要
```

### 3.2 写 `tools.yaml`

参考 `examples/runtime_debug/tools.yaml` 与
`examples/knowledge_search/tools.yaml`。每个工具至少要有：

- `name`、`description`、`when_to_use`、`when_not_to_use`；
- `input_schema`（JSON schema 子集）；
- `output_contract`：声明 `evidence` / `next_action` 等字段；
- `response_format`：声明 schema 或样例。

### 3.3 写 `evals.yaml`

参考 `examples/runtime_debug/evals.yaml`。每条 eval 至少：

- `id`、`user_prompt`、`expected_tool_behavior`；
- `judge_rules`：列出 RuleJudge 规则（如 `must_use_evidence`、
  `evidence_from_required_tools`、`no_evidence_grounding`）。

### 3.4 跑你自己的接入

```bash
python -m agent_tool_harness.cli audit-tools \
  --tools my_team/tools.yaml \
  --out runs/my-team-audit-tools

python -m agent_tool_harness.cli audit-evals \
  --evals my_team/evals.yaml \
  --out runs/my-team-audit-evals

python -m agent_tool_harness.cli run \
  --project my_team/project.yaml \
  --tools my_team/tools.yaml \
  --evals my_team/evals.yaml \
  --out runs/my-team-run \
  --mock-path bad
```

**先跑 audit，再跑 run**：audit 把工具 / eval 设计问题挑出来，避免
后续 run 把 noise 当 Agent bug。

---

## 4. 设置 pricing 与 per-eval budget cap

v1.8 起支持在 `project.yaml` 显式声明 advisory pricing 与 per-eval
budget cap。**这是 advisory-only，永远不是真实账单**。

```yaml
project:
  name: my-team-agent
  # ... 其它字段 ...

pricing:
  models:
    claude-3-5-sonnet-20241022:
      input_per_1k: 0.003
      output_per_1k: 0.015
      currency: USD
      effective_date: '2024-10-22'

budget:
  per_eval:
    max_tokens_total: 50000
    max_cost_usd: 0.10
```

跑完一次 run 后看 `runs/<dir>/llm_cost.json`：

```json
{
  "totals": {
    "estimated_cost_usd": 0.0123,         // advisory-only
    "budget_exceeded_count": 0,
    "pricing_unknown_count": 0
  },
  "per_eval": [
    {
      "eval_id": "...",
      "estimated_cost_usd": 0.0123,
      "budget_status": "ok",               // ok / exceeded / not_applicable
      "cap_breached_by": []
    }
  ],
  "estimated_cost_usd": null,              // 顶层永远 null
  "estimated_cost_note": "v1.8 advisory-only ..."
}
```

**关键约束**：
- 顶层 `estimated_cost_usd` 永远 null（"框架不替你报账"承诺）；
- 真实数字看 `totals.estimated_cost_usd`；
- 未知 model / 非 USD currency 不会被偷偷换算，会写
  `cost_unknown_reason`；
- budget exceeded 是 advisory，**不会中断 run**。

---

## 5. 看 report 与 artifact

### 5.1 9+ artifact 速查

| 文件 | 看什么 | 失败时先看 |
|------|--------|-----------|
| `report.md` | 人类可读总览，含 Cost Summary / Failure attribution / Per-Eval Details | 总览 |
| `metrics.json` | passed / failed / signal_quality | 数字 |
| `transcript.jsonl` | Agent 完整对话流 | 真实输出 |
| `tool_calls.jsonl` | Agent 决定调哪些工具 | 工具选择 |
| `tool_responses.jsonl` | 工具返回了什么 | 数据 |
| `judge_results.json` | RuleJudge / dry-run advisory 判定 | 判定原因 |
| `diagnosis.json` | trace 信号（含 grounding / decoy / when_not_to_use） | 排查根因 |
| `audit_tools.json` | 工具设计审计 finding | 工具质量 |
| `audit_evals.json` | eval 设计审计 finding | eval 质量 |
| `llm_cost.json` | advisory cost + budget cap 状态 | 成本/预算 |

### 5.2 复盘：replay-run + analyze-artifacts

```bash
# 把 run 当"录像带"deterministic 重放
python -m agent_tool_harness.cli replay-run \
  --project my_team/project.yaml \
  --tools my_team/tools.yaml \
  --evals my_team/evals.yaml \
  --run runs/my-team-run \
  --out runs/my-team-replay

# 离线复盘 trace 信号
python -m agent_tool_harness.cli analyze-artifacts \
  --run runs/my-team-replay \
  --tools my_team/tools.yaml \
  --evals my_team/evals.yaml \
  --out runs/my-team-analysis

cat runs/my-team-analysis/tool_use_signals.md
```

### 5.3 判断结果可信 vs 不可信

- ✅ **可信**：
  - `audit-tools` 报的 deterministic finding（field 缺失 / 语义重叠 / 启发式 decoy）；
  - `RuleJudge` 的 deterministic 判定（must_use_evidence / evidence_from_required_tools / no_evidence_grounding）；
  - `analyze-artifacts` 的 trace 信号（tool_selected_in_when_not_to_use_context 等）；
  - `audit-judge-prompts` 的启发式 prompt finding（key 字面 / 引导泄漏 secret 等）；
- ⚠️ **advisory / 仅参考**：
  - `judge_results.json::dry_run_provider` 的 LLM advisory（recorded / fake_transport / offline_fixture）；
  - `llm_cost.json` 的 `estimated_cost_usd`（永远 advisory，不是账单）；
  - MockReplayAdapter 的 PASS / FAIL（结构性保证，不代表 Agent 能力）。

---

## 6. 提交反馈

请使用 [INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md](INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md)
模板。如果遇到失败，先按这个顺序看 artifact：

1. `report.md::Failure attribution` → 总览定位；
2. `diagnosis.json` → 看具体 finding；
3. `metrics.json` → 看 signal_quality；
4. `audit_tools.json` / `audit_evals.json` → 排除是不是工具/eval 设计问题；
5. `judge_results.json` → 看 judge 判定原因；
6. `transcript.jsonl` / `tool_calls.jsonl` / `tool_responses.jsonl` → 真实证据。

如果 artifact 缺字段、文档命令复制粘贴失败、错误提示不可行动 →
请在反馈中**精确到文件名 / 命令 / 行号**记录。
