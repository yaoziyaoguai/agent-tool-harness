# agent-tool-harness v0.1 Release Notes

> Release tag: `v0.1`
> Release commit: `0dcb8e7` (`docs: mark v0.1 release-ready (3/3 blocking complete)`)
> Status: **release-ready MVP**（minimum harness loop closed end-to-end）

---

## v0.1 是什么 / 不是什么

agent-tool-harness v0.1 是一个**最小可工作的 Agent 工具评估骨架**。它的唯一目标
是把"一次 Agent 运行 → 记录证据 → 用确定性规则判断工具调用链路是否合理 → 跑最
小 eval → 输出可读报告"这条闭环跑通，并在两个不同业务领域的 example 项目上证明
该闭环不与单一业务耦合。

> **v0.1 不是真实生产平台**。MockReplayAdapter 不是真实 Agent runtime，
> RuleJudge 不是 LLM Judge，ToolDesignAuditor 仍是结构性启发式，EvalGenerator
> 不是生产级自动造题。详见下文 "Known limitations / 能力边界"。

---

## 已完成能力（v0.1 范围内）

### 1. 核心 CLI 流程

完整 7 步闭环（详见 `README.md` `## 快速开始`）：

```bash
python -m agent_tool_harness.cli audit-tools     --tools  ... --out ...
python -m agent_tool_harness.cli generate-evals  --project ... --tools ... --source tools --out ...
python -m agent_tool_harness.cli promote-evals   --candidates ... --out ...
python -m agent_tool_harness.cli audit-evals     --evals ... --out ...
python -m agent_tool_harness.cli run             --project ... --tools ... --evals ... --out ... --mock-path good
python -m agent_tool_harness.cli run             --project ... --tools ... --evals ... --out ... --mock-path bad
```

每个 subcommand 在 stdout 自报实际产物路径（`wrote <path>`）。

### 2. 两个 examples 证明跨域可复用

- **`examples/runtime_debug/`** —— Agent runtime / checkpoint / TUI 调试域
  （3 工具 + 1 eval；good PASS / bad FAIL）；
- **`examples/knowledge_search/`** —— 客服知识库检索域
  （3 工具 + 1 eval；good PASS / bad FAIL）；
- **`examples/bad_configs/`** —— 6 份故意写坏的 config 用于测试 CLI 错误提示是否
  可行动。

回归测试 `tests/test_example_knowledge_search.py` 钉死核心包（`agent_tool_harness/`）
任何 .py 文件**不出现**两个 example 的业务符号——保证 harness 与业务领域解耦。

### 3. 9-artifact 证据链

`run` 子命令必然写入 9 个 artifact（即使 adapter 抛错、ToolRegistry 初始化失败、
eval 被 audit 判不可运行，runner 也兜底写完，详见 `docs/ARTIFACTS.md`）：

| 文件 | 作用 |
|---|---|
| `transcript.jsonl` | 面向人类复盘的事件流 |
| `tool_calls.jsonl` | Agent 发出的结构化工具调用（含错误参数） |
| `tool_responses.jsonl` | 工具返回的结构化证据 |
| `metrics.json` | 派生统计 + `signal_quality` 边界声明 |
| `audit_tools.json` | ToolDesignAuditor 输出 |
| `audit_evals.json` | EvalQualityAuditor 输出 |
| `judge_results.json` | RuleJudge 逐规则结果 |
| `diagnosis.json` | TranscriptAnalyzer 派生失败现场 |
| `report.md` | 给人看的汇总视图（不可替代上面 8 件） |

### 4. Failure attribution & 可读 report

`report.md` 在失败路径下输出按 finding 分类的 attribution 段，每条 finding 含
`evidence_refs`（指向具体 artifact 行号 / JSON 路径）+ 中文 `suggested_fix`。
`signal_quality`（默认 `tautological_replay`）在 `metrics.json` 与 `report.md`
顶部诚实披露。

### 5. Onboarding 走查闭环（v0.1 blocking 2）

按 README → `docs/ONBOARDING.md` 的 10 分钟接入路径完整走通；走查发现的文档断点
全部用根因型修复 + 防回归测试钉死：

- README 快速开始 promote-evals → audit-evals 流程一致性
  （`tests/test_doc_cli_snippets.py::test_readme_quickstart_audits_the_just_promoted_file`）；
- 接入文档 CLI 片段与真实 argparse 自动对齐
  （`tests/test_doc_cli_snippets.py`，根因修复：把 `cli.main` 的 parser 抽出来作
  `_build_parser()`）；
- subcommand artifact 契约钉死
  （`tests/test_subcommand_artifact_contract.py`，`set==` 而非 `>=`）；
- review_status 状态全集（`candidate / accepted / rejected / needs_review`）写入
  README 并指向 `docs/ONBOARDING.md §4` 根因修工具契约的指引。

### 6. Schema 与可演进性

所有派生 JSON artifact + `generate-evals` / `promote-evals` 输出 YAML 顶层带
`schema_version`（`"1.0.0"`，SemVer）+ `run_metadata`（`run_id` UUID4 / `generated_at` /
`project_name` / `eval_count` / `extra`）。`promote-evals` 输出额外带
`promote_summary`（`promoted_ids` / `skipped`）。

> 这是**最小解析契约**，不引入 OpenTelemetry / OpenInference / W3C trace context；
> 详见 `agent_tool_harness/artifact_schema.py` docstring。

---

## v0.1 完整闭环 commit 链（按 release-ready 顺序）

| commit | 含义 |
|---|---|
| `1aff4a6` | `feat: add knowledge search example for v0.1 coverage`（blocking 1） |
| `6d1eadf` | `docs: mark v0.1 second example complete` |
| `cbdfc69` | `docs: fix v0.1 graduation doc consistency` |
| `a432db9` | `fix(onboarding): align doc CLI snippets with real argparse + harden against drift` |
| `d955a28` | `docs: tighten onboarding walkthrough governance` |
| `93a97a3` | `docs(v0.1): close onboarding walkthrough gaps + pin quickstart consistency`（blocking 2 P1-A/B/C） |
| `b533c91` | `docs(v0.1): clarify subcommand artifact contract + pin via test`（blocking 2 artifact 契约） |
| `d3a62bb` | `docs: mark v0.1 onboarding blocking complete` |
| `493f677` | `docs: archive v0.2 semantic signal branch decision`（blocking 3） |
| `0dcb8e7` | `docs: mark v0.1 release-ready (3/3 blocking complete)` |

更早的奠基 commit（`67678e4` signal quality / `e09b333` tautological judge /
`2c33441` runnable detection / `7160461` P0 governance / `f5434e3` artifact schema /
`d3b6b2a` from-tools judge quality / `eac532e` ROADMAP 重写……）见
`git log --oneline`。

---

## Known limitations / 能力边界（不允许被读者误解为已实现的能力）

> **如果你计划把 v0.1 接入真实生产，请先阅读这一节。**

| 能力 | v0.1 现状 | 不要误以为 |
|---|---|---|
| Agent 运行 | `MockReplayAdapter` 按 eval 自带 fixture 回放工具响应 | **不是真实 Agent runtime**；不接 LLM、不接 MCP、不接 HTTP、不接 Shell |
| Judge | `RuleJudge` 基于 eval 声明的 `expected_tool_behavior` / `forbidden_*` / `success_criteria` 做确定性匹配 | **不是 LLM Judge**；不做语义比对、不做 chain-of-thought 评估 |
| Tool Design Audit | 结构 / 字段完备性启发式（namespace / output_contract / token_policy / spec_quality 等 5 维） | **不读工具源码、不读真实工具响应**；语义诱饵工具仍判 5.0 满分（gap 由 `tests/test_tool_design_audit_decoy_xfail.py` strict xfail 钉死） |
| Eval Generator | `from_tools` 根据工具契约生成 candidate；`from_tests` 静态扫 pytest | **不是生产级自动造题**；缺 fixture / expected_root_cause 时只能标 `runnable: false` 或 `review_status: needs_review`，必须人工 review |
| Signal quality | 每份 metrics.json 顶部默认标 `tautological_replay` | PASS/FAIL 信号边界为"工具规范是否被 Agent 按声明用到"；**不能**作为"工具对真实 Agent 好用"的证据 |
| Web UI / 并发 / benchmark | 无 | v0.1 范围严格排除 |
| `v0.2/tool-design-semantic-signal` 分支 | 仅本地存在的 v0.2 候选 A 草案分支（HEAD `7cac829`），未推 origin、未 merge 到 main | **不属于 v0.1 release**；v0.1 release 期间禁止 merge / push / cherry-pick / 在 main 上重写绕过（详见 `docs/ROADMAP.md` §3 归档决议） |

---

## 未做能力（明确 v0.1 不做）

- 真实 LLM API、MCP、HTTP / Shell executor、Web UI、并发、benchmark、自动 patch；
- 任何 LLM Judge / 语义级 audit / transcript replay adapter；
- 给 from_tools / from_tests 加新 source（transcripts / docs）；
- 多 example 项目库（v0.1 只需 1 个 + 1 个证明通用性，不需要场景库）；
- 给 report.md 加 trajectory 节选 / token estimate；
- audit-tools 派生 markdown 视图；
- 一键 `onboarding-smoke` 脚本 / CLI 子命令。

以上未做项分别归档在 `docs/ROADMAP.md` §"v0.2 候选" 与 §"v0.1 收口期间记录的
ONBOARDING P2 backlog"。

---

## 后续路线（v0.2 / v0.3 / v1.0 简述）

完整定义见 `docs/ROADMAP.md`。本节仅给指针，**不视作承诺**：

- **v0.2** —— 更强的 deterministic audit / judge / transcript 能力。候选 A
  "ToolDesignAuditor 语义信号"已在 `v0.2/tool-design-semantic-signal` 分支原型化，
  与 strict xfail `tests/test_tool_design_audit_decoy_xfail.py
  ::test_audit_should_flag_semantic_decoy_tool_overlapping_with_primary` 一一对应；
  v0.1 正式 release 后才允许进入评审 / 合入流程。
- **v0.3** —— 自动化回归 / 场景库 / 真实 Agent Runtime 集成。未启动。
- **v1.0** —— 稳定可扩展的 Agent Harness 平台。未启动。

---

## 升级 / 接入指引

- **新接入**：从 `README.md` `## 快速开始` 7 步开始；详见 `docs/ONBOARDING.md`
  10 分钟路径。
- **写自己的 tools.yaml / evals.yaml**：参考两个 examples，对照
  `docs/ARTIFACTS.md` 验证产物。
- **CI 集成**：`run_metadata.run_id` 默认 UUID4，可通过环境变量
  `AGENT_TOOL_HARNESS_RUN_ID` 透传 CI build id。

---

## 致谢

v0.1 设计原则致敬 Anthropic 的 *Writing effective tools for agents*；
v0.1 不实现的"语义级 audit / LLM Judge"等能力正是该文章揭示的、需要在 v0.2+
真实信号源接入后才能闭环的部分。
