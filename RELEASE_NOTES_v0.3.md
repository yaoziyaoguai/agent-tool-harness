# agent-tool-harness v0.3 Release Notes

> Release tag: `v0.3`
> Release commit (head at tag time): see `git log v0.3 -1` —— 由本轮 release commit 决定
> Status: **release-ready** —— v0.3 第一项受控落地：deterministic recorded-trajectory replay 闭环

---

## v0.3 是什么 / 不是什么

v0.3 在 v0.2 [`tag v0.2` / commit `9acd788`] 基础上启动 v0.3 milestone 的
**第一项受控任务**：把已有 run 目录当成"录像带"deterministic 重新播放给
EvalRunner，得到一份新的 9-artifact 输出，让 harness 第一次拥有"非 mock"
的 trajectory 来源——**但仍不调用任何真实 LLM、真实工具执行器或网络**。

这一轮的设计意图是 **先给真实 Agent adapter 打地基**：让
`recorder` / `RuleJudge` / `MarkdownReport` / `analyze-artifacts` /
`TraceSignalAnalyzer` 整条派生分析链先用 deterministic replay 反复验证一遍，
再接 OpenAI / Anthropic / MCP / HTTP / Shell —— 那些属于 v1.0 路线。

> **v0.3 仍不是真实生产平台**。`TranscriptReplayAdapter` 不调 LLM、
> 不调 `registry.execute`、不发起任何外部副作用；signal_quality 是
> `recorded_trajectory`，**不是** `real_agent`。历史 trajectory ≠ 当前
> 模型对当前工具集还会做出同样选择。详见下文 "Known limitations"。

---

## v0.3 相对 v0.2 的新增能力

### 1. TranscriptReplayAdapter（commit `16447f7`）

新增模块 `agent_tool_harness/agents/transcript_replay_adapter.py`：

- 构造时接受一份已有 run 目录（`source_run_dir`），读取
  `tool_calls.jsonl` / `tool_responses.jsonl` / `transcript.jsonl`，
  按 `eval_id` 分组建索引；
- `.run(case, registry, recorder)` 把源记录原样透传给新 recorder，
  保留原 `call_id` 让 call ↔ response 关联与源完全一致；
- 每条 replay 出来的 tool_call / tool_response 都带
  `replayed_from = {source_run, source_timestamp}`，方便对照；
- transcript 顶部第一条事件是 `runner.replay_summary`，写明源目录、
  命中的事件数、信号质量等级；
- 源 run 缺某条 eval 记录时写 `runner.replay_warning` + 返回空 final
  answer，让 RuleJudge deterministic FAIL —— **绝不伪造 PASS**；
- 源 transcript 缺 assistant 最终回答时同样写 warning + 空 answer；
- `SIGNAL_QUALITY = RECORDED_TRAJECTORY`（不会被静默升级到 `real_agent`）；
- 构造时 fail-fast：源目录不存在 / 不是目录 / 关键 JSONL 全缺 →
  `TranscriptReplaySourceError`（继承 `FileNotFoundError`，复用 CLI 已有
  的 except 通道直接打印可行动 hint）。

**关键边界（写在模块顶层 docstring，由测试钉死）**：

- **不**调用任何真实模型；
- **不**调用 `registry.execute` —— 工具响应直接来自源
  `tool_responses.jsonl`。原因：真实工具可能 stateful（数据库 / 文件 /
  外部 API），重新执行会让 trajectory 偏离原始证据，违背"录像带"语义。
  这条边界由 `tests/test_transcript_replay_adapter.py::
  test_replay_does_not_call_registry_execute` 用 monkeypatch 钉死。

### 2. `replay-run` CLI 子命令（同 commit `16447f7`）

新增 `python -m agent_tool_harness.cli replay-run --source-run RUN_DIR
--project ... --tools ... --evals ... --out OUT_DIR`：

- 装配 `TranscriptReplayAdapter` + `EvalRunner`，跑出一份完整的新
  9-artifact 目录（与 `run` 命令对齐）；
- `metrics.json` / `report.md` 顶部 banner 显示
  `signal_quality = recorded_trajectory`；
- stdout 打一行 JSON 摘要 `{out_dir, metrics, source_run}`，便于 CI grep；
- 错误处理：源目录不存在 / 缺关键 artifact → 退出码 2 + 可行动 hint，
  不抛 traceback。

### 3. 防回归测试（9 条）

新增 `tests/test_transcript_replay_adapter.py`，每条断言都钉死一个真实
风险，不是为了凑通过率：

| 测试 | 钉死的真实风险 |
|---|---|
| `test_replay_constructor_fails_fast_when_source_missing` | 源路径拼错时若静默继续会写空 run 污染 CI |
| `test_replay_constructor_fails_fast_when_source_has_no_artifacts` | 用户传错目录（指向 docs/ 或空 runs）不允许默认通过 |
| `test_replay_signal_quality_is_recorded_trajectory` | 防止未来重构把 replay 误标成 `REAL_AGENT` |
| `test_replay_does_not_call_registry_execute` | 核心边界：monkeypatch 让 `registry.execute` 一被调就抛 |
| `test_replay_reproduces_good_path_artifacts` | 9 artifact 完整 + judge passed + signal_quality 标签 |
| `test_replay_bad_path_preserves_failure_evidence` | replay 输出仍能被 TraceSignalAnalyzer 派生信号（写入协议兼容） |
| `test_replay_missing_eval_records_warning` | evals.yaml v2 多一条 eval 时新增 eval 必须 deterministic FAIL |
| `test_replay_cli_actionable_error_when_source_missing` | CLI 拼错路径退出码 2 + hint，不抛 traceback |
| `test_replay_cli_full_smoke` | replay-run 端到端 CLI 可用 |

### 4. 文档同步

- `docs/ROADMAP.md`：v0.3 表格行升级为 "第一项受控启动"，新增 v0.3
  进度小节列出已做 / 待做项；v0.2 表格行升级为 "已 release（commit
  `9acd788`，tag `v0.2`）"；
- `docs/ARCHITECTURE.md`：`recorded_trajectory` 等级说明从"未来"改为
  "已上线"；
- `docs/ARTIFACTS.md`：新增 "replay-run 产物" 段，解释 replay 输出与
  源 run 的 4 处关键标记差异（signal_quality / runner.replay_summary /
  replayed_from / runner.replay_warning），明确 replay 仍是 9 个
  artifact，可继续被 `analyze-artifacts` 消费；
- `docs/TRY_IT.md`：试用表新增可选第 9 步 `replay-run`；
- `docs/TESTING.md`：刷新一段过时的示例 xfail reason；
- `README.md`：新增 `replay-run` 命令片段 + 边界声明，加 v0.3 release
  notes 链接。

---

## Commit 链

| commit | 类别 | 说明 |
|---|---|---|
| `9acd788` | (v0.2 tag) | v0.2 release notes — 本轮基线 |
| `16447f7` | feat | TranscriptReplayAdapter + replay-run CLI + 9 防回归测试 + 文档 |
| (本 commit) | docs | RELEASE_NOTES_v0.3.md |

完整可用 `git log v0.2..v0.3 --oneline` 查看。

---

## 核心命令路径（v0.3 完整试用）

```bash
# 1) 跑一次 source run（仍是 mock，作为录像带）
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/source-bad \
  --mock-path bad

# 2) deterministic 重放上面的 run，得到 recorded_trajectory 的新 9 artifact
python -m agent_tool_harness.cli replay-run \
  --source-run runs/source-bad \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/replayed-bad

# 3) replay 输出仍可被 v0.2 离线 trace 分析消费
python -m agent_tool_harness.cli analyze-artifacts \
  --run runs/replayed-bad \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/replayed-analysis
```

更短的纯 v0.2 试用闭环（不含 replay）见 [`docs/TRY_IT.md`](docs/TRY_IT.md)。

---

## Artifacts 变化（vs v0.2）

- 新增 CLI `replay-run` 写出**与 `run` 完全相同的 9 个 artifact**，但带
  4 处关键标记区分（详见 [`docs/ARTIFACTS.md`](docs/ARTIFACTS.md) 的
  "replay-run 产物" 段）；
- 现有 `transcript.jsonl` 在 replay 场景下顶部多一条 `runner.replay_summary`
  事件 + 每条 `tool_call` / `tool_response` 带 `replayed_from` metadata；
- `metrics.json::signal_quality` 增加新值 `recorded_trajectory`（v0.2 时
  已在 `signal_quality.py` 定义但无 adapter 使用，本轮第一次真正出现在
  artifact 中）；
- v0.1 / v0.2 的所有 artifact schema **完全向后兼容**，没有字段重命名 /
  删除。

---

## Known limitations / 能力边界

- `TranscriptReplayAdapter` **不**调任何真实 LLM，**不**重新执行工具，
  **不**联网；它只是按源 JSONL 复读；
- `signal_quality = recorded_trajectory` 比 `tautological_replay` 高，
  但**不是** `real_agent` —— 历史 trajectory ≠ 当前模型对当前工具集还会
  做出同样选择；
- replay 不能 partial-eval slicing（一次 replay 整条 eval 的全部记录）；
- replay 不做 trajectory 字段级 schema 校验（只校验关键文件存在与否）；
- `RuleJudge` / `ToolDesignAuditor` / `EvalQualityAuditor` /
  `TranscriptAnalyzer` / `TraceSignalAnalyzer` 仍是 v0.2 的 deterministic
  启发式 —— v0.3 没有改它们的判断逻辑；
- 唯一的 strict xfail 仍是 v0.2 ROADMAP 已记录的
  `tests/test_tool_design_audit_subtle_decoy_xfail.py::
  test_audit_should_flag_subtle_semantic_decoy_with_disjoint_vocabulary`
  —— 转正条件是真实 transcript 样本或 LLM judge（v1.0 路线）。

---

## 未做能力（明确不在 v0.3 范围）

下面所有能力都属 **v1.0 / backlog**，本轮不实现，也不接纳临时 hack：

- 真实 OpenAI / Anthropic adapter；
- MCP / HTTP / Shell executor；
- LLM Judge（即使作为辅助 reviewer）；
- Web UI / 多用户 / 复杂权限；
- `replay-run --diff PREV_RUN` run-to-run 对比；
- 多场景库 + CI 自动 baseline diff；
- held-out eval 比较；
- `from_docs` / `from_transcripts` eval 自动生成；
- `unused_high_signal_tool` trace 信号；
- `RuleJudge.must_use_evidence` non-substring 升级；
- `TranscriptAnalyzer` 在 `report.md` 加 trajectory 节选块；
- 自动 patch 用户工具；
- `from_tools._difficulty` 启发式细化；
- 真实工具的 JSON Schema 完整校验；
- benchmark / 跨 run quality_score 趋势线。

---

## v1.0 路线提示

v1.0 的 stop rule 与 v0.2 / v0.3 一致：**不会平台化**（不做多用户 / Web
UI / 复杂权限）。v1.0 推荐入口候选（仅供未来 owner 触发，**本轮不开始**）：

1. **第一个真实 LLM adapter（OpenAI 或 Anthropic 二选一）**：把
   `TranscriptReplayAdapter` 验证过的 recorder / judge / report 接口先
   接一个真实模型，signal_quality 升到 `real_agent`；不接多个，避免范围扩散；
2. **`RuleJudge.must_use_evidence` non-substring 升级 + decoy 真实样本库**：
   作为 LLM Judge 的 deterministic 对照基线，让 v0.2 唯一 strict xfail
   能基于真实 trajectory 转正；
3. **多场景库 + CI baseline diff**：把 `examples/runtime_debug` /
   `examples/knowledge_search` 模式扩展到 ≥ 4 个场景，CI 跑全部场景与
   baseline diff metrics / artifact / report.md。

---

## 升级指引（v0.2 → v0.3）

- 不需要修改任何已有的 `project.yaml` / `tools.yaml` / `evals.yaml`；
- 不需要修改任何已有的 v0.1 / v0.2 artifact schema 解析代码；
- 仅当你想用 replay 能力时再调用 `replay-run`；
- v0.2 的所有 7 条试用命令（audit-tools → generate-evals → promote-evals
  → audit-evals → run good → run bad → analyze-artifacts）行为 **完全
  不变**；
- 测试基线从 v0.2 的 178 passed / 1 xfailed 升至 187 passed / 1 xfailed
  （+9 全部为 replay 相关防回归）。

---

## 测试基线

- ruff: All checks passed
- pytest: **187 passed, 1 xfailed**（唯一 strict xfail 见上文 "Known
  limitations"）
- 5 条 release smoke 全 exit 0：source run / replay-run / analyze-artifacts
  on replayed run / audit-tools runtime / audit-tools knowledge_search

---

## 致谢

v0.3 第一项 TranscriptReplayAdapter 的核心设计意图来自 v0.2 收尾时
ROADMAP 中已写好的 v0.3 推荐入口分析；它把 v0.2 已经做扎实的派生分析
基础设施第一次接到了"非 mock trajectory 来源"。

下一步（v1.0 启动条件）由 owner 决定。
