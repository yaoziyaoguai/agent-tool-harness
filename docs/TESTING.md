# Testing

本项目测试的目标是查出架构边界问题，不是追求表面通过率。

## 测试纪律

不允许：

- 通过放宽断言来追求通过；
- 删除关键断言；
- 把失败测试改成空测试；
- 忽略 bad path；
- 只看 Agent 最终回答，不看 tool calls 和 tool responses。

允许 xfail，但必须满足：

- reason 写清楚为什么现在不能过；
- 写清楚未来转正条件；
- 不能覆盖当前 MVP 必须可运行的能力。

当前没有 xfail 测试。

## 如何运行

```bash
python -m pytest -q
```

如果安装了 ruff：

```bash
python -m ruff check .
```

## 覆盖范围

当前测试覆盖：

- `tools.yaml` 加载；
- `evals.yaml` 加载；
- Tool Design Audit 能发现坏工具；
- Eval Quality Audit 能发现弱 eval；
- Eval Generator from_tools 能生成候选 eval，且不生成“请调用某工具”的作弊题；
- Eval Generator from_tests 能抽取 docstring/xfail reason，并标记不可运行候选；
- PythonToolExecutor 能调用 demo 工具；
- RuleJudge good path 成功；
- RuleJudge bad path 失败；
- run 后生成所有 artifacts；
- `report.md` 包含关键章节。

## 如何检查 artifacts

运行：

```bash
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-good \
  --mock-path good
```

然后检查：

- `runs/demo-good/transcript.jsonl`
- `runs/demo-good/tool_calls.jsonl`
- `runs/demo-good/tool_responses.jsonl`
- `runs/demo-good/judge_results.json`
- `runs/demo-good/diagnosis.json`
- `runs/demo-good/report.md`

失败时优先看：

1. `tool_calls.jsonl` 的第一步工具；
2. `tool_responses.jsonl` 的 evidence；
3. `judge_results.json` 的 failed checks；
4. `diagnosis.json` 的 first_tool、missing_required_tools、issues。

## good path / bad path

good path：

```bash
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-good \
  --mock-path good
```

预期：

- 第一工具调用 `runtime_trace_event_chain`；
- 再调用 `runtime_inspect_checkpoint`；
- 最终根因为 `input_boundary`；
- RuleJudge 判成功。

bad path：

```bash
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-bad \
  --mock-path bad
```

预期：

- 第一工具调用 `tui_inspect_snapshot`；
- 不调用 `runtime_trace_event_chain`；
- 最终误判为 UI rendering；
- RuleJudge 判失败；
- TranscriptAnalyzer 指出第一步工具错误、缺少关键工具和缺少 evidence。
