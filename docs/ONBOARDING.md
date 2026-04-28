# 10 分钟接入路径（外部 Agent 团队）

本文给即将把 `agent-tool-harness` 接到自家 Agent 项目的人一份**最短可走通的步骤**。

> **在开始之前**：下面所有命令统一使用 `python -m`，**假设你已经激活了项目的虚拟
> 环境**（`source .venv/bin/activate` 之类）。如果没有，请把 `python` 替换为
> `.venv/bin/python` 或你自己的解释器路径——**不要混着用**，一会儿走不通会很难
> 排查到底是路径问题还是配置问题。

> **MVP 边界（必读，否则很容易高估输出）**
>
> 1. **`MockReplayAdapter` 不是真实 Agent。** 它按 fixture 在 good/bad 两条预设路径上回放工具调用。
>    所有 demo run 的"Agent 决策正确率"由你写的 fixture 决定，不代表 GPT/Claude 的实际表现。
>    真实 adapter（OpenAI / Anthropic / 自有 runtime）需要你自己实现 `AgentAdapter` 接口。
> 2. **`RuleJudge` 不是 LLM Judge。** 它只检查"工具是否被调用 / root cause 字符串是否包含"等
>    确定性规则。**它无法判断回答语义是否正确**，也不会给出连续分数。
> 3. **`ToolDesignAuditor` 不是语义级审计。** 它检查命名/描述/契约是否齐全，不会判断
>    "这套工具能不能完成业务"。强语义审计需要人工 review，框架只把候选 evals 标 `review_status="candidate"` 等你审。
>
> 不在 MVP 范围内的能力请见 [docs/ROADMAP.md](./ROADMAP.md)。

---

## 步骤总览

```
1) 准备三个 YAML
2) audit-tools         → tool design audit
3) generate-evals      → 候选 eval 草稿（顶层带 warnings）
4) 人工 review         → 把 review_status 改为 "accepted"
5) promote-evals       → 非交互机械搬运到 evals.promoted.yaml
6) audit-evals         → eval quality audit（验证 promoted）
7) run --mock-path good / bad
8) 看 artifacts + report.md（注意 schema_version / run_metadata）
9) 根据 report 改工具/eval/adapter
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
python -m agent_tool_harness.cli audit-tools \
  --tools your/tools.yaml \
  --out runs/onboarding-audit-tools
```

读 `audit_tools.json`：每个工具有 `findings`（rule_id / severity / suggestion）和分数。
**首次接入大概率会看到 `missing_when_to_use` / `missing_output_contract` / `missing_token_policy`**。
这些不是 loader 错误，是设计提示，按建议补全字段后重跑。

## 3) generate-evals

```bash
python -m agent_tool_harness.cli generate-evals \
  --project your/project.yaml \
  --tools your/tools.yaml \
  --source tools \
  --out runs/onboarding-generated/eval_candidates.from_tools.yaml
```

> ⚠️ `--project` 和 `--source` 都是必填项；省略会被 argparse 直接拒收。
> `--source tools` 表示从 `tools.yaml` 推导候选（生产路径）；如果想从 pytest
> 测试名/docstring 推导，改 `--source tests` 并加 `--tests <pytest 目录>`。

输出是**候选**：每条带 `review_status: "candidate"` / `review_notes` /
`difficulty` / `runnable: false`。文件顶层还会带 `warnings` 字段（empty_input /
all_unrunnable / missing_review_notes / high_missing_context /
cheating_prompt_suspect），同样的内容也会镜像到 stderr。
**不要直接拿候选去 run**，先人工 review。

## 4) 人工 review 候选

最低要求：

- 把 `user_prompt` 改成真实业务问题，**不要出现"请调用 X 工具"**（否则会触发 `realism.cheating_prompt` finding）；
- 补 `initial_context`（trace_id / session_id / fixture）；
- 补 `verifiable_outcome`（expected_root_cause、evidence_ids）；
- 补 `judge.rules`（至少一条非 tautological 规则，例如 `must_use_evidence` /
  `expected_root_cause_contains`）；
- 把 `runnable` 改为 `true`，把 `review_status` 改为 `"accepted"`。

### 如何把候选转成 accepted（具体怎么做）

候选是一个 YAML 文件，**review 是一条一条人手对着 review_notes 看完再改**：

1. 用编辑器打开 `runs/onboarding-generated/eval_candidates.from_tools.yaml`；
2. 找到那条候选，按上面"最低要求"逐项改写 `initial_context` / `verifiable_outcome` /
   `judge.rules`（不能空，不能只剩 `must_call_tool`）；
3. 改完之后再把这条的 `review_status: "candidate"` 改成 `review_status: "accepted"`，
   并把 `runnable: false` 改成 `runnable: true`（如果你确认 fixture 已就位）；
4. 没改完的候选**留 `review_status: "candidate"` 不动**，promote-evals 会自动跳过它们。

> ⚠️ **不要写脚本批量把所有候选 `review_status` 一刀切成 `accepted`**
> （例如 `sed -i 's/review_status: candidate/review_status: accepted/g'`）。
> 这等同于跳过 review，会把没补 fixture / 没补 root cause / 仍带 tautological judge
> 的候选全部转正——之后所有 run 的 PASS/FAIL 都失去意义，`EvalQualityAuditor` 也无法
> 帮你拦住，因为 audit 看的是字段是否齐全，不是字段是否真实。
> review 是**人**对每条候选业务真实性的判断，是这条流水线唯一的语义保障，**不允许
> 用工具捷径绕过**。

> **看到 `review_status: "needs_review"` 怎么办？**
> 这表示生成器认为对应工具的 `tools.yaml` 契约本身就不完整（缺
> `when_to_use` / `when_not_to_use` / `output_contract.required_fields` 含
> `evidence` / `input_schema.properties` 含 `response_format` 等关键字段）。
> **正确做法是回 `tools.yaml` 修工具契约，不是改这条 eval 绕过**——契约不齐
> 时候选 eval 没办法跑出有意义的信号。修完工具后重新 generate-evals 即可。
> 候选的 `missing_context` 字段会列出具体缺哪些项。

## 5) promote-evals（非交互转正）

不要再手 copy 候选到 evals.yaml，调 promoter：

```bash
python -m agent_tool_harness.cli promote-evals \
  --candidates runs/onboarding-generated/eval_candidates.from_tools.yaml \
  --out runs/onboarding-generated/evals.promoted.yaml
# 默认禁覆盖；要覆盖加 --force
```

promoter 只搬运 `review_status="accepted"` + `runnable=true` + 字段齐全
（`initial_context` / `verifiable_outcome.expected_root_cause` / `judge.rules`）
的候选；其它会被列在输出文件 `promote_summary.skipped[*].reason` 里告诉你下一步
要补什么。即使 0 条搬运也返回退出码 0——"质量不足"不等于"CLI 失败"。

## 6) audit-evals（验证 promoted）

```bash
python -m agent_tool_harness.cli audit-evals \
  --evals runs/onboarding-generated/evals.promoted.yaml \
  --out runs/onboarding-audit-evals
```

`EvalQualityAuditor` 会标 `not_runnable` 和 `low_score_evals`。低分项不修复就拿去 run，等于污染 eval harness。验证通过后再 merge 进正式 `evals.yaml`。

## 7) run good / bad（验证 harness 自身）

先用 demo `MockReplayAdapter` 跑一遍，确认 artifact 链路正常：

```bash
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/onboarding-good --mock-path good

python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/onboarding-bad --mock-path bad
```

`good` 的 judge 应通过、`bad` 的应失败；如果两者结果一样，说明 judge 退化成了同义复读，必须先修。

> ⚠️ **`--mock-path good|bad` 不会自动制造好/坏路径**——它只是选择 `MockReplayAdapter`
> 回放哪一条预设分支，**真正的 good/bad 差异是 eval 自带的 `expected_tool_behavior`
> 与 fixture 决定的**。在你自家项目上跑 `--mock-path bad` 看到 PASS，绝大多数情况
> 是你只写了 good fixture（或者只在 good 路径上对齐 required_tools）；这不是 CLI
> bug，是你的 eval 还没准备好 bad 路径。先回 evals.yaml 把 bad fixture / mock 分支
> 写好，再重跑这一步——这是 ONBOARDING 走查里最常见的隐性断点。

## 8) 看 artifacts + report.md

每次 run 落 9 个 artifact（见 [docs/ARTIFACTS.md](./ARTIFACTS.md)）。重点看:

- `report.md` 顶部 **Signal Quality** 段：当前用 mock + rule judge 的可信度边界；
- **Methodology Caveats**：哪些维度本框架**没**覆盖；
- **Per-Eval Details**：每条 eval 的 tool calls、judge 结论、diagnosis 根因。

## 9) 根据 report 改

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
