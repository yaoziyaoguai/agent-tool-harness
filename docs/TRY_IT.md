# Try the v0.2 flow — 完整试用指引

> 这份文档面向"我刚 clone 仓库，想用 agent-tool-harness v0.2 把它真正跑一遍"
> 的用户。你不需要看完 ROADMAP / ARCHITECTURE，只需要按本页命令复制粘贴。
>
> 整个流程**离线 / 不调 LLM / 不联网**。第一次跑通预计 3-5 分钟。

## 这条 v0.2 试用路径覆盖什么

| 步骤 | 命令 | 目的 | 怎么判断成功 | 失败时看哪里 |
|------|------|------|-------------|-------------|
| 1 | `audit-tools` | 检查 `tools.yaml` 是否符合 deterministic 设计原则 | `audit_tools.json` 写出，`overall_score` ≥ 0 | stderr 错误信息 / `audit_tools.json` 中 `findings` |
| 2 | `generate-evals --source tools` | 从 tools 自动生成候选 eval | 写出 `eval_candidates.from_tools.yaml` | stderr / 候选文件中 `review_notes` |
| 3 | `promote-evals` | 把 review 通过的候选转成正式 eval | stdout JSON `promoted_count` ≥ 0 | stderr 中 `skip:` 行 / 候选 `review_status` |
| 4 | `audit-evals` | 验证正式 evals 是否 runnable | `audit_evals.json` 写出 | `audit_evals.json` 的 `findings` |
| 5 | `run --mock-path good` | 跑一次 happy path 回放 | 9 个 artifact 全在 `--out` 目录 | `report.md` + `metrics.json` |
| 6 | `run --mock-path bad` | 跑一次 unhappy path 回放（**必跑**） | 同上，但 `passed=false` | `diagnosis.json` 的 `findings` + `tool_use_signals` |
| 7 | `analyze-artifacts` | 离线复盘上一步 trace 信号 | `tool_use_signals.json` + `.md` 写出 | stderr `--run` / `--evals` 提示 |
| 8 | 看 `report.md` + `tool_use_signals.md` | 真人解读 | Per-Eval Details 段含 trace 信号 | 回 raw `tool_calls.jsonl` / `tool_responses.jsonl` |
| 9 *(可选, v0.3)* | `replay-run --run RUN`（亦接受 `--source-run`） | 把上面的 run 当"录像带"deterministic 重放 | 新 `--out` 目录 9 个 artifact 全在；`metrics.signal_quality=recorded_trajectory` | 源目录缺 `tool_calls.jsonl` 时 stderr 给可行动 hint |
| 10 *(v1.0)* | 看 `report.md` 里的 **Failure attribution** + **Per-Eval Details** 中的 grounding bullet | 验证 v1.0 deterministic anti-decoy + grounding 子场景区分 | bad path 的 `no_evidence_grounding` 必须额外打印 "Tool returned evidence ([...]) but final_answer did not cite any id/label"；decoy grounding 路径必须打印 "Cited evidence ... from non-required tool(s) ..." | 直接 `cat runs/.../report.md`；如缺 grounding bullet 检查 `diagnosis.json` 中 finding 的 `cited_refs`/`available_evidence_refs` 字段是否被 analyzer 写入 |

## 路径 A：runtime_debug example（推荐第一遍）

`examples/runtime_debug/` 是 9 工具 / 1 eval 的 demo，bad path 会自然触发
`tool_selected_in_when_not_to_use_context` 信号，是验证 v0.2 第三轮 trace
analyzer 最直接的路径。

```bash
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out runs/tryit-audit-tools

python -m agent_tool_harness.cli generate-evals \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --source tools \
  --out runs/tryit-generated/eval_candidates.from_tools.yaml

python -m agent_tool_harness.cli promote-evals \
  --candidates runs/tryit-generated/eval_candidates.from_tools.yaml \
  --out runs/tryit-promoted/evals.promoted.yaml

python -m agent_tool_harness.cli audit-evals \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/tryit-audit-evals

python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/tryit-good \
  --mock-path good

python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/tryit-bad \
  --mock-path bad

python -m agent_tool_harness.cli analyze-artifacts \
  --run runs/tryit-bad \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/tryit-analysis
```

跑完应看到：

- `runs/tryit-bad/report.md` 顶部 Signal Quality banner + Per-Eval Details
  里出现 `[high] tool_selected_in_when_not_to_use_context`；
- `runs/tryit-analysis/tool_use_signals.md` 同样列出该信号 + `evidence:` 行；
- `runs/tryit-good/diagnosis.json` 中 `tool_use_signals: []`（good path 没有
  trace 信号是预期，**不是 bug**）。

> step 3 的 `promote-evals` 在没有任何候选 review 通过时会输出
> `promoted_count: 0` + 一串 `skip: candidate ... — needs_review`——这是**预期**
> 行为：候选默认 `review_status="candidate"`，必须人工 review 改为 `accepted`
> 才会被 promote。详见 `docs/ONBOARDING.md` §4。

## 路径 B：knowledge_search example（验证"换一个业务域也能跑"）

```bash
python -m agent_tool_harness.cli audit-tools \
  --tools examples/knowledge_search/tools.yaml \
  --out runs/tryit-knowledge-audit

python -m agent_tool_harness.cli run \
  --project examples/knowledge_search/project.yaml \
  --tools examples/knowledge_search/tools.yaml \
  --evals examples/knowledge_search/evals.yaml \
  --out runs/tryit-knowledge-good \
  --mock-path good

python -m agent_tool_harness.cli run \
  --project examples/knowledge_search/project.yaml \
  --tools examples/knowledge_search/tools.yaml \
  --evals examples/knowledge_search/evals.yaml \
  --out runs/tryit-knowledge-bad \
  --mock-path bad
```

这条路径验证的是：核心 harness（`MockReplayAdapter` / `RuleJudge` /
`TranscriptAnalyzer` / `MarkdownReport`）**不绑死 runtime_debug**，把 tools/
evals 换成 KB 检索域同样跑得通。

## 边界声明（请先看清楚再做结论）

- 全部命令都是 deterministic：**不调 LLM、不联网、不调 MCP/HTTP/Shell、
  不重新执行真实工具**。
- `MockReplayAdapter` 直接读 `eval.expected_tool_behavior.required_tools`
  按顺序回放——`metrics.json` / `report.md` 顶部的
  `signal_quality: tautological_replay` 是显式披露，**PASS/FAIL 不能解读
  为"工具对真实 Agent 好用"**。
- `RuleJudge` 不是 LLM Judge；`ToolDesignAuditor` / `EvalQualityAuditor` /
  `TranscriptAnalyzer` / `TraceSignalAnalyzer` 全部是 deterministic 启发式。
- 接真实 LLM / MCP / HTTP/Shell executor / Web UI / LLM Judge 是 v0.3+
  的事，本试用路径**不**涉及。

## 如果哪一步崩了

- argparse 报参数缺失 → 对照本页命令逐字检查（`tests/test_doc_cli_snippets.py`
  会自动钉住 README/ONBOARDING/TRY_IT 的命令与 argparse 是否一致，所以
  本页发布时一定是和 CLI 对齐的；你看到 drift 请提 issue）；
- `ConfigError` → 按 stderr `hint:` 检查 YAML 字段类型；
- `tool registry` 错 → `tools.yaml` 中 `namespace.name` 必须唯一；
- `run` 写出的 9 个 artifact 不全 → 看 stderr 是否报 adapter 异常；
  即使 adapter 抛错框架仍会写出 `runtime_error` artifact（这是 v0.1 已经
  钉死的 invariant）。

## 接下来

- 想知道每个 artifact 字段含义 → [`docs/ARTIFACTS.md`](./ARTIFACTS.md)；
- 想接自己的项目 → [`docs/ONBOARDING.md`](./ONBOARDING.md) §1-9；
- 想知道哪些路线还没做 → [`docs/ROADMAP.md`](./ROADMAP.md) v0.2 / v0.3 / v1.0 段；
- 想了解测试纪律 → [`docs/TESTING.md`](./TESTING.md)。

## 三类目录关系（run / replay / analysis）

`agent-tool-harness` 当前对外有三种"输出目录"，承接关系如下；同一份 `report.md`
能通过这条管线被反复复盘：

```
run --out runs/A          (signal_quality=tautological_replay)
   │  9 个 artifact，含 transcript/tool_calls/tool_responses/diagnosis/report
   ▼
replay-run --run runs/A --out runs/B   (signal_quality=recorded_trajectory)
   │  从 A 重放出新一份完整 9 个 artifact，PASS/FAIL 由当前规则重新评判，
   │  但 Agent 行为严格来自 A 的 transcript（不调 LLM、不调真实工具）
   ▼
analyze-artifacts --run runs/{A|B} --out runs/C
   │  离线 trace 信号复盘：写出 tool_use_signals.json + tool_use_signals.md，
   │  与 run/replay 的 9 个 artifact 正交（不重新评判，只对 raw payload 做
   │  contract / 模式层信号挖掘）
```

任何一步**不**会修改前一步目录里的文件——前一步目录可作为不可变历史保留。
