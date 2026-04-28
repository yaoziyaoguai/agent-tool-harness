# agent-tool-harness v1.5 Release Notes

> Release date: 2026 — see git tag `v1.5`.
> Predecessor: [`RELEASE_NOTES_v1.4.md`](RELEASE_NOTES_v1.4.md)（live-ready
> Anthropic-compatible transport skeleton + CLI live-ready 入口）。

## v1.5 定位

v1.5 是 **multi-advisory CLI 入口 + report readability** MVP。把 v1.3 已落地
的 `CompositeJudgeProvider` 多 advisory majority-vote Python API 暴露成 CLI
可重复 flag，并把 `report.md` 的多 advisory 渲染从"一行投票概览"扩展到
"每条 advisory 缩进 sub-bullet + error_code/suggested_fix"，让 reviewer
不用打开 `judge_results.json` 就能定位"哪条 advisory 与 deterministic
分歧 / 出错的 advisory 该怎么修"。

**仍完全不接真实 LLM、不联网、不需要密钥**。任何"真实 live HTTP" 必须
由用户在自己环境主动构造 `LiveAnthropicTransport(...,live_enabled=True,
live_confirmed=True)` 触发，CI / smoke 永远走 fake / disabled。

---

## 相对 v1.4 新增能力

### 1. Docs honesty pass（commit `feafbaf`）

更新 `docs/ARCHITECTURE.md` / `docs/ARTIFACTS.md` / `docs/ROADMAP.md` /
`docs/TESTING.md` / `docs/V1_4_LIVE_TRANSPORT_IMPLEMENTATION.md`：

- `judge-provider-preflight` 的 `summary.live_optin_status` 在 v1.4 已经
  从 v1.3 的"3 态 + ready_for_live 永远 False"扩展为**四态状态机**：
  `disabled / opt_in_incomplete / opted_in_no_transport / live_ready`，
  其中 `live_ready = 双标志齐 + 4 项 safety 全绿 → ready_for_live=True`；
- 删除 v1.x 第三轮残留的"`ready_for_live` 永远 False / `live_mode_enabled`
  永远 False"陈述，统一指向 v1.4 四态合同；
- preflight 本身**仍永远不联网**——`ready_for_live=True` 只是给真实用户
  的"前置条件全部通过"信号，真实 HTTP 必须由用户主动触发。

### 2. `--judge-advisory` 多 advisory CLI 入口（commit `8d63d23`）

`run` 子命令新增 `--judge-advisory NAME:PATH` **可重复** flag：

- NAME 仅支持 v1.x 已落地的三种**本地** advisory：
  - `recorded` → `RecordedJudgeProvider(judgments fixture)`；
  - `anthropic_compatible_offline` → `AnthropicCompatibleJudgeProvider
    (offline_fixture)`；
  - `anthropic_compatible_fake` → `AnthropicCompatibleJudgeProvider
    (transport=FakeJudgeTransport)`；
- **绝不**接受任何 live transport NAME；live HTTP 仍只能走 v1.4 的
  `--judge-provider anthropic_compatible_live` 单 advisory 路径；
- 与 `--judge-provider` **互斥**；同时给两者 → exit 2 + 提示；
- 未知 NAME / 缺 `:` 分隔 / 缺 PATH → exit 2 + 可行动 hint，**不**默认
  退化成 RuleJudge silent pass。

启用后 `judge_results.json::dry_run_provider` 中每条 entry 的 schema
切换为 v1.3 多 advisory 形态：

- `advisory_results[]`：每条 advisory 的脱敏结果（passed/rationale/
  confidence/rubric/recording_ref，错误时 error_code/error_message）；
- `vote_distribution`：`{pass, fail, error, total}`，**error advisory
  不计入 pass/fail 投票**；
- `majority_passed`：pass 多→True / fail 多→False / 平票或全 error→`None`
  （inconclusive）；
- `agreement = (majority_passed == deterministic_passed)`，平票时也是
  `None`；
- `metrics.json::judge_disagreement` 中 `agreement is None → error += 1`
  （反"吞异常假成功"延伸）。

**Deterministic baseline 不被任何 advisory 覆盖**：`results[].passed`
仍由 RuleJudge 决定，advisory 只写 `dry_run_provider` 段，
contract 由 6 条 `tests/test_cli_multi_advisory.py` 钉死，包括：
两条 recorded advisory 的字段齐全 + det 不被覆盖；互斥 / 未知 NAME / 缺 `:` 的
exit 2 + hint；`recorded` + `anthropic_compatible_fake` 混合 + `socket.socket`
banned + key/url 字面值泄漏扫描；默认无 flag → 不写 `dry_run_provider`
段（v1.0 字节兼容回归保护）。

### 3. MarkdownReport 多 advisory 可读性扩展（commit `be8226d`）

`agent_tool_harness/reports/markdown_report.py::_render_dry_run_provider`
在多 advisory 投票主行下，为每条 advisory 输出**缩进 sub-bullet**：

- 正常路径：`- advisory [provider/mode] passed=...; confidence=...;
  rationale=...; recording_ref=...`；
- 错误路径：`- advisory [provider/mode] error: <slug> — <脱敏 message>`
  + `  suggested_fix: <静态 deterministic 提示>`。

新增 `_ADVISORY_SUGGESTED_FIX` 静态映射覆盖 9 类 error_code：
`missing_recording` / `missing_config` / `disabled_live_provider` /
`auth_error` / `rate_limited` / `network_error` / `timeout` /
`bad_response` / `provider_error`；未识别 → 通用 fallback hint
"查看 judge_results.json...不要回填真实 key/url"。**绝不**调 LLM、
不拼真实 url/key。

contract 由 6 条 `tests/test_markdown_report_multi_advisory.py` 钉死：
consensus 渲染 / disagreement (majority=None) 渲染 /
error+suggested_fix 渲染 / 未识别 error_code fallback / fake key 不
被二次注入 / 默认路径返回 `[]`（v1.0 字节兼容回归）。

---

## 关键安全契约（v1.4 保留 + v1.5 强化）

- CI / smoke / pytest **零真实联网**；6 条新 CLI 测试 + 6 条新 report
  测试 + 19 条 v1.4 transport 契约测试 + 13 条 preflight 契约测试 全部
  在 `monkeypatch.setattr(socket, "socket", _BannedSocket)` 下跑通；
- 任何真实 key / Authorization header / 完整请求体响应体 / base_url
  敏感 query / HTTP/SDK 原始异常长文本，**绝不**进入代码、文档、测试、
  runs、artifacts、report、metrics、judge_results、diagnosis 或 git；
  6 条新 CLI 测试 + 6 条新 report 测试都包含字面量 leak 扫描；
- `_ADVISORY_SUGGESTED_FIX` 是 deterministic 静态表，**不**调 LLM、
  不拼真实 url/key、不读 env；未识别 error_code 走通用 fallback hint
  仍只引用 artifact 路径；
- multi-advisory 投票：error advisory **不计入** pass/fail 投票，单独
  算入 `error` 桶；平票或全 error → `majority_passed=None` (inconclusive)，
  避免"吞异常假成功"。

---

## 已知限制 / v1.5 不做的事

- **不**真实接入任何 LLM（OpenAI / Anthropic / Gemini / 本地模型）；
  v1.4 已落地 `LiveAnthropicTransport` 骨架 + CLI 入口，但 CI 永久不
  跑真实 live；要真实 live 必须由用户在自己环境主动构造；
- **不**做 retry / backoff / 限流治理 / 成本上报 / 流式响应；这些留
  v1.6+；
- **不**做 prompt / rubric / pre-call sanitization 工程；
- **不**做 transcript-aware judge prompt（需先有真实 LLM 路径才有意义）；
- **不**做投票算法权重 / 阈值可配置（先观察使用模式再迭代）；
- **不**做 per-advisory token / latency 指标（需先有真实 transport
  metrics）；
- **不**做 HTML / JSON 报告变体；
- **不**新增 MCP / HTTP / Shell executor；
- **不**新增 Web UI；
- **不**自动 patch 用户工具。

---

## 后续路线（仅 ROADMAP 备忘，**不**承诺时间）

详见 `docs/ROADMAP.md`：

- **v1.6 候选**：retry / backoff / 限流治理；cost tracking
  (`runs/<dir>/llm_cost.json`)；prompt 工程与 rubric 审计；
- **v1.7 候选**：流式响应（Anthropic Messages SSE）；transcript-aware
  judge prompt；
- **v2.x 候选**：第二个真实 provider（OpenAI / Gemini）抽象通用
  `ProviderPreflight` 协议；MCP / HTTP / Shell executor；Web UI；
- **永久不做**：CI 跑真实 live；自动改用户工具代码；硬编码 example
  业务逻辑到核心包。

---

## 升级指南（v1.4 → v1.5）

**纯加法**。所有 v1.4 路径字节兼容：

- 默认 `--judge-provider` 不传 + `--judge-advisory` 不传 → 与 v1.0
  字节相等（`judge_results.json` 不写 `dry_run_provider` 段）；
- 已有 `--judge-provider recorded/composite/anthropic_compatible_offline/
  anthropic_compatible_live` 路径全部不变；
- 已有 `--judge-fake-transport-fixture` / `--live` /
  `--confirm-i-have-real-key` 旗标全部不变；
- 已有 9 个 artifacts 字段全部不变。

**新启用建议**：

```bash
# 单 advisory（向后兼容；v1.x 第一/二/三轮形态）
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/single-advisory \
  --judge-provider recorded --judge-recording fixtures/r1.yaml

# 多 advisory（v1.5 第一轮新增；CompositeJudgeProvider 多 advisory 路径）
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/multi-advisory \
  --judge-advisory recorded:fixtures/r1.yaml \
  --judge-advisory anthropic_compatible_fake:examples/fake_transport_fixtures/runtime_debug.yaml
```

---

## 测试基线

- ruff: All checks passed!
- pytest: **284 passed, 1 xfailed**（v1.4 时 272 → v1.5 第一轮 +6 →
  v1.5 第二轮 +6）；
- 唯一 strict xfail：`tests/test_tool_design_audit_subtle_decoy_xfail.py`
  （v0.2 候选 A 已知 gap，已记录在 `docs/ROADMAP.md`，转正条件需
  transcript / real tool responses / LLM judge）。
