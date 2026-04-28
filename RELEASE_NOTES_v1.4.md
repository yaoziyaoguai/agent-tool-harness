# agent-tool-harness v1.4 Release Notes

**发布定位**：v1.4 是 v1.x "live-ready fake transport MVP" 收口版本。它把
v1.3 的"未来 transport 设计 + 双标志契约"具象成可注入、可断言、可脱敏的
真实代码骨架，并补齐 CLI 入口与 fake transport 注入面，让真实用户能在自己
环境里以**双重 opt-in + 完整 env 配置**的方式触发真实 LLM judge——而 CI 与
官方 smoke 仍然 **0 联网、0 真实 key 读取、0 费用**。

**v1.4 不是**：默认真实 LLM Judge、retry/backoff/限流治理、成本上报、流式
响应、prompt/rubric 工程、多 advisory CLI、真实 live smoke 在 CI 跑——这些
属 v1.5+ 显式 opt-in milestone。

---

## 相对 v1.2 / v1.3 新增能力

本次 release 包含 3 个 commit（`4b8e866..0b8f2e1`）：

| commit | 摘要 |
|---|---|
| `db69f59` | feat(judges): add multi-advisory aggregation and live opt-in contract |
| `48f11ea` | feat(judges): add live-ready Anthropic-compatible transport skeleton |
| `0b8f2e1` | feat(judges,cli): wire live-ready fake transport path |

### 1. CompositeJudgeProvider 多 advisory majority-vote 聚合（v1.3）
- Python API 支持传 `advisory=[adv1, adv2, ...]`，输出新增 `advisory_results[]`
  / `majority_passed` / `vote_distribution`；
- 错误 advisory 单独算入 `vote_distribution.error`，不当成 fail 投票；
- 单 advisory 形态零字段变更（向后兼容 v1.x 第二轮）。

### 2. `judge-provider-preflight` 双标志契约 + v1.4 `live_ready` 终态
- `--live` + `--confirm-i-have-real-key` 双标志（任一缺即不视为完整 opt-in）；
- v1.4 起：双标志齐 + 4 项 safety 全绿（config_complete / gitignore_safe /
  env_example_safe / error_taxonomy_safe）→ `summary.live_optin_status="live_ready"`、
  `ready_for_live=True`；preflight 本身**仍**完全不联网。

### 3. LiveAnthropicTransport 实现骨架（v1.4 第一项）
- 基于标准库 `http.client` + `ssl` + `urllib.parse`，**零新增依赖**；
- 默认完全 disabled：`live_enabled=False or live_confirmed=False` →
  `send()` 立即抛 `_FakeTransportError(disabled_live_provider)`，**不**触碰
  任何 socket；
- `http_factory` 注入点：CI / contract test 用 fake connection 覆盖全部
  错误路径，**绝不**调真实 `HTTPSConnection`；
- HTTP 状态/异常映射到 v1.x 第二轮 8 类 error taxonomy：
  - `401/403 → auth_error`
  - `429 → rate_limited`
  - `5xx → provider_error`
  - `TimeoutError → timeout`
  - `OSError / HTTPException / ConnectionError → network_error`
  - `200 + 坏 JSON / 缺字段 → bad_response`
- 脱敏硬约束：异常 message **只**含 error_code slug；`raise ... from None`
  截断 `__cause__` 链；200 响应只回传 4 个公开字段（`passed / rationale /
  confidence / rubric`），raw response 永不入 artifact。

### 4. CLI `--judge-provider anthropic_compatible_live` + fake transport（v1.4 第二轮）
- `run` 子命令新增 3 组旗标：`--live`、`--confirm-i-have-real-key`、
  `--judge-fake-transport-fixture PATH`；
- 装配优先级：fake fixture > LiveAnthropicTransport(双标志) > 永远先过
  `missing_config` 硬检查；
- 示例 fake fixture：`examples/fake_transport_fixtures/runtime_debug.yaml`
  （`responses` / `raise_error` 二选一）。

### 5. 测试覆盖（无 leak / 无联网 / 无吞异常）
v1.4 新增 26 条契约测试（v1.3 合并基线 246 → v1.4 总 272）：
- `tests/test_live_anthropic_transport.py`（19 条）：默认 disabled / 单 `--live`
  不够 / 缺 config / 200 OK / 6 类 status / timeout / network / 坏 JSON / 缺
  字段 / 不合法 base_url / **泄漏扫描全错误路径** / 端到端 provider+disabled
  / multi-advisory composition / RuleJudge 默认路径不退化；
- `tests/test_cli_anthropic_compatible_live.py`（6 条）：CLI 端到端覆盖 5 类
  装配契约 + 旧 `recorded` 路径回归；每条都 monkeypatch `socket.socket = banned`，
  并扫描整个 run 目录确保 `FAKE_KEY` / `FAKE_BASE_URL` 永不泄漏；
- `tests/test_judge_provider_preflight.py`（v1.4 新增 1 条）：v1.4 `live_ready`
  终态正向案例，含 socket 禁用 + key/url 字面值泄漏扫描。

---

## 核心命令路径（v1.4）

```bash
# 1. 本地 preflight（永远不联网）：
python -m agent_tool_harness.cli judge-provider-preflight --out runs/preflight

# 2. fake transport smoke（CI 推荐；绝不联网）：
AGENT_TOOL_HARNESS_LLM_PROVIDER=anthropic_compatible \
AGENT_TOOL_HARNESS_LLM_BASE_URL=https://fake.local \
AGENT_TOOL_HARNESS_LLM_API_KEY=sk-fake \
AGENT_TOOL_HARNESS_LLM_MODEL=claude-fake \
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/v14-fake-bad --mock-path bad \
  --judge-provider anthropic_compatible_live \
  --judge-fake-transport-fixture examples/fake_transport_fixtures/runtime_debug.yaml

# 3. 真实 live（用户自己环境，不在 CI 跑）：
#    a) 配 .env 里 4 个 AGENT_TOOL_HARNESS_LLM_* 真实值
#    b) python -m agent_tool_harness.cli judge-provider-preflight --live --confirm-i-have-real-key --out runs/preflight
#    c) 确认 summary.ready_for_live=True
#    d) 运行 run --judge-provider anthropic_compatible_live --live --confirm-i-have-real-key
#       （**不**传 --judge-fake-transport-fixture 才会触发真实 HTTPSConnection）
```

---

## 已知限制 / v1.4 不做的能力

- **真实 live smoke 永远不在 CI / 官方 smoke 跑**：任何真实 ping 必须由
  用户在自己环境主动触发，自负成本与隐私责任。
- **没有 retry / backoff / 限流治理 / 成本上报 / 流式响应**：v1.5+ backlog。
- **没有多 advisory CLI 入口**：`CompositeJudgeProvider` 多 advisory 仅
  Python API；CLI 仍是单 advisory。
- **没有 prompt / rubric 工程 / pre-call sanitization**：transport 层只做
  HTTP / 错误分类 / 脱敏；prompt 内容由后续 milestone 补齐。
- **没有 transcript-aware judge prompt**：要等真实 LLM 路径稳定后才有意义。
- **`MockReplayAdapter` 仍是 tautological replay**：`signal_quality_note`
  显眼提示这是 MVP mock，PASS / FAIL 不代表 Agent 真实能力。
- **`RuleJudge` 仍是 deterministic baseline**：v1.4 `anthropic_compatible_live`
  只是 advisory，**绝不**覆盖 `results[].passed`。
- **`ToolDesignAuditor` 仍以启发式信号为主**：v0.2 候选 A 已合入 1 条
  semantic decoy detection；更深的语义信号留给后续 milestone。

---

## 后续路线（仅备忘，不在 v1.4 范围）

- **v1.5 真实 live 收口**：retry / backoff / 成本上报 / 流式 / 隐私脱敏实战；
- **v1.6 prompt & rubric 工程**：判定 prompt 模板化 / rubric 校验 / 多模型对比；
- **v1.7 多 advisory CLI**：`--judge-advisory` 列表入口 + 投票 schema 稳定化；
- **v1.8 真实 LLM judge baseline**：替换 `RuleJudge` 作为 ground truth 的
  设计探讨与 contract 钉住。

---

## 安全契约（继续生效）

- 任何真实 key、Authorization header、完整请求体 / 响应体、base_url 敏感
  query、HTTP / SDK 原始异常长文本 **不得**写入代码、文档、测试、`runs/`、
  `artifacts`、report、metrics、`judge_results`、`diagnosis`、git commit。
- `.env` 已被 `.gitignore` 忽略；`.env.example` 仅含占位符，由 preflight
  扫描钉死。
- 所有 transport 错误路径 **只**抛 `_FakeTransportError(error_code)`；
  上层 provider 读 `error_code` 后用 `_safe_message()` 模板生成脱敏文本。

详见 `docs/V1_4_LIVE_TRANSPORT_IMPLEMENTATION.md`、
`docs/V1_3_LIVE_TRANSPORT_DESIGN.md`、`docs/ROADMAP.md`。
