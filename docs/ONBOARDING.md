# 10 分钟接入路径（外部 Agent 团队）

本文给即将把 `agent-tool-harness` 接到自家 Agent 项目的人一份**最短可走通的步骤**。

> **MVP 边界（必读，否则很容易高估输出）**
>
> 1. **`MockReplayAdapter` 不是真实 Agent。** 它按 fixture 在 good/bad 两条预设路径上回放工具调用。
>    所有 demo run 的“Agent 决策正确率”由你写的 fixture 决定，不代表 GPT/Claude 的实际表现。
>    真实 adapter（OpenAI / Anthropic / 自有 runtime）需要你自己实现 `AgentAdapter` 接口。
> 2. **`RuleJudge` 不是 LLM Judge。** 它只检查“工具是否被调用 / root cause 字符串是否包含”等
>    确定性规则。**它无法判断回答语义是否正确**，也不会给出连续分数。
> 3. **`ToolDesignAuditor` 不是语义级审计。** 它检查命名/描述/契约是否齐全，不会判断
>    “这套工具能不能完成业务”。强语义审计需要人工 review，框架只把候选 evals 标 `review_status="candidate"` 等你审。
>
> 不在 MVP 范围内的能力请见 [docs/ROADMAP.md](./ROADMAP.md)。

---

## 步骤总览

```
1) 准备三个 YAML
2) audit-tools         → tool design audit
3) generate-evals      → 候选 eval 草稿
4) 人工 review         → 转正候选 eval
5) audit-evals         → eval quality audit
6) run --mock-path good / bad
7) 看 artifacts + report.md
8) 根据 report 改工具/eval/adapter
```

每步都会落 artifact，详细字段见 [docs/ARTIFACTS.md](./ARTIFACTS.md)。

---

## 1) 准备三个 YAML

最小集：

- `project.yaml`：项目元数据（mapping root，必填）
- `tools.yaml`：工具清单（mapping `tools: [...]` 或 list root 都接受）
- `evals.yaml`：eval 清单（同上）

参考 `examples/runtime_debug/` 下三个文件。常见坏配置见 `examples/bad_configs/README.md`。

> **不要把 demo 工具名写进核心框架。** 任何形如 `if tool.name == "lookup_session_failure"` 的逻辑
> 都属于业务侧，留在你自己的 demo/adapter 里。

## 2) audit-tools

```bash
.venv/bin/python -m agent_tool_harness.cli audit-tools \
  --tools your/tools.yaml \
  --out runs/onboarding-audit-tools
```

读 `audit_tools.json`：每个工具有 `findings`（rule_id / severity / suggestion）和分数。
**首次接入大概率会看到 `missing_when_to_use` / `missing_output_contract` / `missing_token_policy`**。
这些不是 loader 错误，是设计提示，按建议补全字段后重跑。

## 3) generate-evals

```bash
.venv/bin/python -m agent_tool_harness.cli generate-evals \
  --tools your/tools.yaml \
  --out runs/onboarding-generated/eval_candidates.from_tools.yaml
```

输出是**候选**：每条带 `review_status: "candidate"` / `review_notes` / `difficulty` / `runnable: false`。
**不要直接拿候选去 run**，先人工 review。

## 4) 人工 review 候选

最低要求：

- 把 `user_prompt` 改成真实业务问题，**不要出现“请调用 X 工具”**（否则会触发 `realism.cheating_prompt` finding）；
- 补 `initial_context`（trace_id / session_id / fixture）；
- 补 `verifiable_outcome`（expected_root_cause、evidence_ids）；
- 把 `runnable` 改为 `true`，把 `review_status` 改为 `"approved"`；
- 拷贝到正式 `evals.yaml`。

## 5) audit-evals

```bash
.venv/bin/python -m agent_tool_harness.cli audit-evals \
  --evals your/evals.yaml \
  --out runs/onboarding-audit-evals
```

`EvalQualityAuditor` 会标 `not_runnable` 和 `low_score_evals`。低分项不修复就拿去 run，等于污染 eval harness。

## 6) run good / bad（验证 harness 自身）

先用 demo `MockReplayAdapter` 跑一遍，确认 artifact 链路正常：

```bash
.venv/bin/python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/onboarding-good --mock-path good

.venv/bin/python -m agent_tool_harness.cli run \
  ... --out runs/onboarding-bad --mock-path bad
```

`good` 的 judge 应通过、`bad` 的应失败；如果两者结果一样，说明 judge 退化成了同义复读，必须先修。

## 7) 看 artifacts + report.md

每次 run 落 9 个 artifact（见 [docs/ARTIFACTS.md](./ARTIFACTS.md)）。重点看：

- `report.md` 顶部 **Signal Quality** 段：当前用 mock + rule judge 的可信度边界；
- **Methodology Caveats**：哪些维度本框架**没**覆盖；
- **Per-Eval Details**：每条 eval 的 tool calls、judge 结论、diagnosis 根因。

## 8) 根据 report 改

常见动作：

- 工具描述/契约不清晰 → 改 `tools.yaml` 字段；
- Agent 调错工具 → 改 prompt / adapter 选择策略；
- judge 太严或太松 → 在 `evals.yaml` 调 `judge.rules`。

---

## 接下来

- 想接真实 LLM？写一个 `AgentAdapter` 子类挂上去。**不要修改核心框架去耦合某家 SDK。**
- 想看常见错误对照？读 `examples/bad_configs/README.md`。
- 想知道哪些路线尚未实现？读 [docs/ROADMAP.md](./ROADMAP.md)。
- 想知道每个 artifact 字段含义？读 [docs/ARTIFACTS.md](./ARTIFACTS.md)。
- 想了解测试纪律？读 [docs/TESTING.md](./TESTING.md)。
