# agent-tool-harness v1.1 — JudgeProvider dry-run / recorded contract MVP

> Tag: `v1.1` · Base: `v1.0` (`5268197`) · Head: `b2c8bcd`
>
> 中文学习型说明：v1.1 的目标是为"未来真实 LLM judge"先把**抽象契约**落地，
> 让 deterministic baseline 永远是 ground truth、未来换 provider 实现时不会
> 破坏 v1.0 的字节兼容性。**v1.1 不接真实 OpenAI / Anthropic API、不调网络、
> 不需要密钥、不替代 RuleJudge。**

## 定位

- v1.0：deterministic anti-decoy / evidence grounding 收口，`RuleJudge` +
  `MockReplayAdapter` 是 MVP 判定底座。
- v1.1：在 v1.0 基础上引入 `JudgeProvider` Protocol 抽象层，让 EvalRunner
  能可选挂一个 dry-run / recorded provider 写"建议性"判定到
  `judge_results.json::dry_run_provider` 与 `report.md`，但**绝不**改写
  deterministic baseline。

## 相对 v1.0 的新增能力

### JudgeProvider abstraction（commit `22c1ba9`）

新增 `agent_tool_harness/judges/provider.py`：

- `JudgeProvider` Protocol：统一签名 `judge(eval_def, transcript, tool_calls,
  tool_responses) -> ProviderJudgeResult`。
- `RuleJudgeProvider`：透传 v1.0 `RuleJudge`，`mode="deterministic"`，是
  EvalRunner 默认行为对应的 provider 形态（向后兼容 anchor）。
- `RecordedJudgeProvider`：从 in-process 字典读 dry-run judgment，
  `mode="dry_run"`；缺 recording 抛 `MissingRecordingError`。
- `ProviderJudgeResult` 多带 `provider / mode / schema_version / rationale /
  confidence / rubric` 元字段。
- `PROVIDER_SCHEMA_VERSION = "1.1.0-skeleton"` —— stub 契约版本，等真实 LLM
  provider 落地后再 bump 到 `1.1.0` 正式版。
- 6 条契约测试 `tests/test_judge_provider_skeleton.py` 钉死：
  RuleJudgeProvider 必须透传 RuleJudge 的 PASS/FAIL；RecordedJudgeProvider
  缺 recording 必须抛错；两个 provider 在 judge 期间**禁止**开任何网络
  socket（用 monkeypatch 把 `socket.socket` 替成抛错版本验证）。

### EvalRunner provider metadata 集成（commit `b2c8bcd`）

- `EvalRunner.__init__` 新增可选 `dry_run_provider: JudgeProvider | None`
  参数；默认 `None` 时**走 v1.0 纯路径**，`judge_results.json` 字节兼容。
- 4 个 judge_results.append 站点（`tool_registry_init_failed` /
  `eval_not_runnable` / `adapter_execution_failed` / 正常 success）后挂
  `_invoke_dry_run_provider`，无论 deterministic 路径走哪个分支都会收集到
  对齐的 advisory entry。
- 当 `dry_run_provider` 配置时，`judge_results.json` 多顶层字段
  `dry_run_provider`（含 `schema_version + results[]`）；每条 entry 含
  `provider / mode / schema_version / deterministic_passed / passed /
  agrees_with_deterministic / rationale / confidence / rubric` 或
  `error{type, message}`。
- `MarkdownReport` 新增 `## Dry-run JudgeProvider (advisory only)` 段，
  显式声明 `DO NOT change deterministic pass/fail`，逐条渲染 entry 与
  `agrees_with_deterministic` 标志位、缺 recording 的 `error.type` 路径。

### CLI 新增参数

- `agent-tool-harness run --judge-provider recorded --judge-recording PATH`
- `PATH` 接 yaml/json，顶层必须含 `judgments` 字段：

```yaml
judgments:
  <eval_id>:
    passed: true|false   # 必填
    rationale: "..."     # 可选
    confidence: 0.9      # 可选 [0,1]
    rubric: "..."        # 可选
```

- 缺 `--judge-recording` / fixture 文件不存在 / fixture 缺 `judgments` 顶层
  字段，CLI 立即 `exit 2` + 可行动 hint，**绝不**静默 PASS / 伪造数据。

### judge_results.json / report 相比 v1.0 多了什么

| 字段 | 何时存在 | 含义 |
|---|---|---|
| `dry_run_provider.schema_version` | 配置 provider 时 | 当前 `"1.1.0-skeleton"` |
| `dry_run_provider.results[].provider` | 同上 | `"recorded"`（未来 `"openai"` 等） |
| `dry_run_provider.results[].mode` | 同上 | `"dry_run"`（未来 `"live"`） |
| `dry_run_provider.results[].deterministic_passed` | 同上 | 与 `results[].passed` 对比 |
| `dry_run_provider.results[].agrees_with_deterministic` | 同上 | 分歧诊断信号 |
| `dry_run_provider.results[].rationale/confidence/rubric` | 同上 | provider 自带 metadata |
| `dry_run_provider.results[].error{type,message}` | 缺 recording / provider 异常 | 不写 `passed`，杜绝伪造 |
| `report.md → ## Dry-run JudgeProvider (advisory only)` | 同上 | 必带 `DO NOT change deterministic pass/fail` |

## 核心命令路径

```bash
# v1.0 纯路径（无任何变化）
.venv/bin/python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/v11-provider-bad --mock-path bad

# v1.1 新增：挂 recorded provider
.venv/bin/python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/v11-provider-recorded --mock-path bad \
  --judge-provider recorded \
  --judge-recording /tmp/v11_recording.yaml
```

期望结果：deterministic FAIL 保持不变；`judge_results.json::results[0].passed`
仍是 `false`；`dry_run_provider.results[0].passed` 可能是 `true`，
`agrees_with_deterministic` 是 `false`，整个 `report.md` 用 advisory 段
明示这条分歧，但 metrics 的 `passed/failed` 计数**不变**。

## 已知限制 / 本版本未做

- **未接真实 LLM API**：没有 OpenAI / Anthropic / 任何外部 HTTP / MCP /
  Shell / Web UI 调用；`RecordedJudgeProvider` 只读静态 fixture。
- **未做密钥 / 成本 / 隐私治理**：因为不联网，密钥相关基础设施留给真实
  provider 落地一并交付。
- **未做 `CompositeJudgeProvider`**：同时跑 deterministic + LLM advisory
  并在 metrics 中聚合分歧率统计，留给下一轮。
- **未做 prompt-rubric 自动评估**：rubric 字段当前只是 fixture 透传，没有
  真实评分逻辑。
- **`PROVIDER_SCHEMA_VERSION = "1.1.0-skeleton"`** 是 stub 标记，等真实
  provider 落地再 bump 到 `1.1.0` 正式版。

## 后续真实 LLM provider 路线（仅备忘 / ROADMAP 占位，**不属于 v1.1**）

1. `OpenAIJudgeProvider` / `AnthropicJudgeProvider`：实现 `JudgeProvider`
   Protocol，`mode="live"`，需要密钥环境变量与超时治理。
2. `CompositeJudgeProvider`：在 EvalRunner 之上聚合 deterministic + LLM
   advisory，写 `judge_results.json::dry_run_provider` 之外再加分歧率
   `metrics.json::judge_disagreement_rate`。
3. Cost / latency / privacy 治理：把 prompt / response 落到独立 artifact，
   PII 脱敏开关，按 eval 的 token 计数累加到 `metrics.json`。
4. Rubric 评估：让 `rubric` 字段不只是透传，而是 provider 真实参与的
   评分锚点。

## 验证

- `.venv/bin/python -m ruff check .` → All checks passed
- `.venv/bin/python -m pytest -q` → **215 passed, 1 xfailed**
  （v0.2 候选 A `subtle_decoy` strict xfail 维持，ROADMAP 已记录）
- v1.1 smoke：default `runs/v11-provider-bad` + analyze
  `runs/v11-provider-analysis` + recorded
  `runs/v11-provider-recorded` 全绿，`dry_run_provider` schema/disclaimer
  正确。
