# knowledge_search example

第二个 demo 项目，配合 `runtime_debug` 一起证明 `agent_tool_harness` **不是只能跑某一个
业务领域**。本 example 选 KB 检索域是为了与 runtime_debug（trace / checkpoint / TUI）形成
最大对比：完全不同的工具语义、完全不同的 evidence 类型，但**复用同一份核心代码**——
`MockReplayAdapter`、`RuleJudge`、`TranscriptAnalyzer`、`MarkdownReport` 都不需要改一行。

## 范围声明（v0.1 边界）

- 3 个 demo 工具（`kb.search.search_articles` / `kb.article.fetch_article` /
  `kb.assistant.suggest_canned_response`），写死在 `demo_tools.py`，纯字典 mock，
  没有真实检索后端、没有 LLM、没有网络/磁盘 IO。
- 1 条 eval（`kb_sso_session_loss_regression`），覆盖 good path 与 bad path。
- 不引入任何新依赖，不修改 `agent_tool_harness/` 任何核心代码。

## 一键 smoke

```bash
.venv/bin/python -m agent_tool_harness.cli audit-tools \
  --tools examples/knowledge_search/tools.yaml \
  --out runs/kb-audit-tools

.venv/bin/python -m agent_tool_harness.cli audit-evals \
  --evals examples/knowledge_search/evals.yaml \
  --out runs/kb-audit-evals

.venv/bin/python -m agent_tool_harness.cli generate-evals \
  --project examples/knowledge_search/project.yaml \
  --tools examples/knowledge_search/tools.yaml \
  --source tools \
  --out runs/kb-generated/eval_candidates.from_tools.yaml

.venv/bin/python -m agent_tool_harness.cli run \
  --project examples/knowledge_search/project.yaml \
  --tools examples/knowledge_search/tools.yaml \
  --evals examples/knowledge_search/evals.yaml \
  --out runs/kb-good --mock-path good

.venv/bin/python -m agent_tool_harness.cli run \
  --project examples/knowledge_search/project.yaml \
  --tools examples/knowledge_search/tools.yaml \
  --evals examples/knowledge_search/evals.yaml \
  --out runs/kb-bad --mock-path bad
```

## 信号质量提醒

跑 `run` 命令时会在 `metrics.json` / `report.md` 顶部看到 `signal_quality =
tautological_replay`。这是 `MockReplayAdapter` 的固有限制：good path 的 PASS 是**结构性
必然**，不能解读成"工具对真实 Agent 好用"。两个 example 在这一点上完全一致——这正是我们
要证明"harness 在不同业务上行为一致"的关键。

如何深入排查请看 `docs/ARTIFACTS.md`，命令对照表见 `docs/ONBOARDING.md`。
