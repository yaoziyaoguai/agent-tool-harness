# Testing

本项目测试的目标是查出架构边界问题，不是追求表面通过率。

## 测试纪律

不允许：

- 通过放宽断言来追求通过；
- 删除关键断言；
- 把失败测试改成空测试；
- 忽略 bad path；
- 只看 Agent 最终回答，不看 tool calls 和 tool responses。
- 为了让测试通过而降低 artifact 完整性要求；
- 把框架核心写死到 `examples/runtime_debug` 的业务逻辑上。

允许 xfail，但必须满足：

- reason 写清楚为什么现在不能过；
- 写清楚未来转正条件；
- 不能覆盖当前 MVP 必须可运行的能力。

当前没有 xfail 测试。

## 改测试前的判断顺序

当实现和测试冲突时，先判断：

1. 实现是否违反架构边界；
2. 测试是否表达了真实需求；
3. 需求是否缺少清晰边界；
4. 是否需要更新 Roadmap 或 ARCHITECTURE。

只有确认测试本身错误时，才修改测试语义。不能把失败测试改成“永远能过”的占位。

## xfail 模板

未来新增 xfail 时，reason 应包含：

- 当前为什么不能通过；
- 依赖的未来能力；
- 转正条件；
- 为什么不影响当前 MVP 质量门槛。

示例：

```python
@pytest.mark.xfail(
    reason=(
        "需要 TranscriptReplayAdapter 读取真实历史 transcript；"
        "转正条件：replay adapter 进入 P0 当前范围，并有 fixture 覆盖 bad path。"
    )
)
```

## 如何运行

```bash
python -m pytest -q
```

如果安装了 ruff：

```bash
python -m ruff check .
```

如果当前 Python 没有安装 ruff，但项目虚拟环境存在：

```bash
.venv/bin/python -m ruff check .
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
- 文档保留证据契约、非目标范围和 xfail 转正规则；
- 当前阶段没有实现真实模型 adapter、MCP/HTTP/Shell executor 或 Web UI。
- adapter 抛错时 runner 仍生成复盘 artifacts；
- audit 判定不可运行时 runner 不执行 adapter；
- MockReplayAdapter 可使用自定义工具名，不依赖 runtime_debug demo；
- ToolRegistry 对歧义短名不静默覆盖；
- PythonToolExecutor 校验 required/type 并正确绑定单参数函数；
- RuleJudge 拒绝空 root cause 和未引用具体 evidence 的答案。

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

## Artifact 完整性门槛

一次 `run` 只有同时满足以下条件，才算可复盘：

- 9 个必需 artifacts 全部存在；
- `transcript.jsonl` 非空；
- `tool_calls.jsonl` 非空；
- `tool_responses.jsonl` 非空；
- `judge_results.json` 至少有一条 result；
- `diagnosis.json` 至少有一条 result；
- `report.md` 包含 Tool Design Audit、Eval Quality Audit、Agent Tool-Use Eval、Transcript-derived Diagnosis、Improvement Suggestions。

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
