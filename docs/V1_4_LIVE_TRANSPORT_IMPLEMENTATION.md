# v1.4 LiveAnthropicTransport 实现说明

本文档负责什么
==============

记录 v1.4 第一项（已落地）：基于 `docs/V1_3_LIVE_TRANSPORT_DESIGN.md` 的
设计，在核心包中实现最小可用的 `LiveAnthropicTransport`——一个**默认完全
disabled、不引入新依赖、不在 CI / smoke 中真实联网**的 HTTPS transport
骨架。**为未来用户在自己环境中 opt-in 真实阿里云 Coding Plan
Anthropic-compatible endpoint 准备**好可注入、可断言、可脱敏的代码路径，
但本身**不**代表默认开启了真实 LLM Judge。

本文档**不**负责什么
====================

- **不**记录任何真实 endpoint / model / 计费策略；这些只能通过本地
  `.env`（`AGENT_TOOL_HARNESS_LLM_*` 4 个环境变量）配置；
- **不**承诺已经做过真实 live smoke——v1.4 的所有测试与 smoke 均通过
  fake `http_factory` 注入完成，未真实建联；
- **不**实现 retry / backoff / 限流治理 / 成本上报 / 流式响应；这些仍
  属于 v1.5+ 工程治理 milestone；
- **不**实现 prompt / rubric 工程；transport 只把上层给的 `request` dict
  序列化成 JSON body 发出去。

核心契约
========

类位置
------

`agent_tool_harness/judges/provider.py::LiveAnthropicTransport`

构造签名
--------

```python
LiveAnthropicTransport(
    config: AnthropicCompatibleConfig,
    *,
    live_enabled: bool = False,      # 对应 CLI --live
    live_confirmed: bool = False,    # 对应 CLI --confirm-i-have-real-key
    http_factory: Callable[[host, port, timeout], conn] | None = None,
    timeout_s: float | None = None,
)
```

- 双标志同时为 True 才视为完整 opt-in；任一为 False → `send()` 立即抛
  `_FakeTransportError(ERROR_DISABLED_LIVE)`，**不**触碰任何 socket / http.client；
- `http_factory` 用于注入 fake connection（contract test）。签名约定：
  `http_factory(host, port, timeout) -> conn`，conn 必须有
  `request(method, path, body, headers)` 与 `getresponse() -> resp`，
  resp 必须有 `status` 与 `read()`；
- 默认 `http_factory=None` 时回落到 `http.client.HTTPSConnection`——但
  CI / smoke **不**会触发这条分支（因为完整 opt-in 在 CI 中永远 False）；
- `timeout_s` 优先级：显式参数 > `AGENT_TOOL_HARNESS_LLM_REQUEST_TIMEOUT_S`
  env > 默认 30s；硬上限 120s。

错误分类映射（v1.x 第二轮 8 类 taxonomy 完全对齐）
--------------------------------------------------

| 触发条件                                              | error_code              |
| ----------------------------------------------------- | ----------------------- |
| 双标志未完整 opt-in                                   | `disabled_live_provider`|
| 完整 opt-in 但 `base_url` / `api_key` / `model` 缺失  | `missing_config`        |
| HTTP 401 / 403                                        | `auth_error`            |
| HTTP 429                                              | `rate_limited`          |
| HTTP 5xx                                              | `provider_error`        |
| `TimeoutError` / "timed out" OSError                  | `timeout`               |
| `OSError` / `http.client.HTTPException` / 无法解析 URL | `network_error`         |
| 200 但 JSON 解析失败 / 缺 `passed` 字段 / 其它非 2xx | `bad_response`          |

脱敏硬约束
----------

- 异常 message **只**含 error_code slug；从不含 `base_url` / `api_key` /
  完整 URL / Authorization header；
- 用 `raise ... from None` 截断异常 chain，防止 `__cause__` 携带原始
  exception repr；
- 200 响应**只**回传 4 个公开字段（`passed / rationale / confidence / rubric`），
  raw response body 永远不进入 artifact；
- `AnthropicCompatibleJudgeProvider` 复用 v1.x 第二轮已落地的脱敏路径
  捕获 `_FakeTransportError`，写入 `extra.error_code` + `extra.error_message`
  （来自固定 `_safe_message()` 模板）。

测试覆盖（19 条契约）
=====================

文件：`tests/test_live_anthropic_transport.py`。覆盖矩阵：

1. 默认 disabled + socket banned 不会触发 socket；
2. 单 `--live` 不够 → DISABLED；
3. 完整 opt-in + 缺 config → MISSING_CONFIG，不构造 connection；
4. fake 200 OK → 返回 4 字段 dict；
5. HTTP 401 / 403 / 429 / 500 / 503 / 302（其它非 2xx）→ 各自 error_code；
6. TimeoutError → TIMEOUT；
7. OSError → NETWORK；
8. 200 但坏 JSON → BAD_RESPONSE；
9. 200 缺 `passed` 字段 → BAD_RESPONSE；
10. 不合法 base_url → NETWORK，不泄漏原始 URL；
11. **泄漏扫描**：所有错误路径下异常 str/repr/`__cause__` 都不含
    FAKE_KEY / FAKE_BASE_URL；
12. 端到端 provider + disabled transport → 写入脱敏 artifact extra；
13. multi-advisory composition：disabled transport-backed provider 进入
    advisory list 后 `vote_distribution.error += 1`，不计入 pass/fail；
14. RuleJudge 默认路径不被 v1.4 影响。

与 v1.3 双标志契约的对应关系
============================

| CLI 标志 / 状态                          | LiveAnthropicTransport 行为             |
| ---------------------------------------- | --------------------------------------- |
| 不传任何标志                             | `live_enabled=False` → DISABLED         |
| 传 `--live`                              | `live_enabled=True, live_confirmed=False` → DISABLED |
| 传 `--live` + `--confirm-i-have-real-key`| `live_enabled=True, live_confirmed=True` → 走 transport（CI 用 fake_factory；用户自己环境用 stdlib） |

`judge-provider-preflight` 的 `summary.live_optin_status` 三态值
（`disabled / opt_in_incomplete / opted_in_no_transport`）覆盖了
LiveAnthropicTransport 的前两条状态。第三条 `opted_in_no_transport` 在
v1.3 是"无 transport 类"，v1.4 起 user 在自己环境中可以构造
`LiveAnthropicTransport(config, live_enabled=True, live_confirmed=True)`
让它真正生效——但**仍不会被 CLI 自动启用**：v1.4 不引入新的
`--judge-provider anthropic_compatible_live` CLI 入口（避免一次性引入太多
变更面），只暴露 Python API；CLI wiring 留 v1.4 第二轮。

V1.5+ 待做（仅备忘）
====================

- 真实 live smoke 工具：在用户明确允许 + 限定 budget 下做一次最小 ping；
- 成本上报：每次成功调用记录 token usage 到 `runs/<run_dir>/llm_cost.json`；
- retry / backoff / 限流；
- prompt / rubric 工程；
- 多 advisory CLI 入口（如 `--judge-provider composite_multi
  --judge-recording PATH1 --judge-recording PATH2`）；
- 流式响应（Anthropic Messages SSE）。

阿里云 Coding Plan Anthropic-compatible 提示
============================================

如果你的真实 endpoint 是阿里云 Coding Plan Anthropic-compatible
资源：

- **绝不**把 API key 粘进任何 prompt / 代码 / 文档 / git；
- 仅通过 `.env`（已在 `.gitignore` 中被忽略）配置 4 个 env var；
- 配置完成后建议先跑 `judge-provider-preflight --live --confirm-i-have-real-key`
  确认 preflight 报告 `summary.live_optin_status == "opted_in_no_transport"`
  + 4 个 env 字段齐全；
- 真正打开 live 必须由用户主动构造 `LiveAnthropicTransport(...,
  live_enabled=True, live_confirmed=True)` 并注入到
  `AnthropicCompatibleJudgeProvider`——v1.4 不为你做这一步。

---

## v1.4 第二轮补充：CLI 入口 + fake transport smoke fixture

v1.4 第二轮在 `agent_tool_harness/cli.py::run` 子命令上把第一项的 transport
骨架接上 CLI：

- `--judge-provider anthropic_compatible_live`：选择 live 路由；
- `--live` + `--confirm-i-have-real-key`：与 preflight 同语义的双标志；
- `--judge-fake-transport-fixture PATH`：注入 `FakeJudgeTransport`，
  CI / smoke 走这条路径**绝不**真实联网。

装配优先级：

1. 给了 `--judge-fake-transport-fixture` → 用 `FakeJudgeTransport`
   （读 fixture 中的 `responses` 或 `raise_error`）；
2. 否则用 `LiveAnthropicTransport(live_enabled=args.live,
   live_confirmed=args.confirm_i_have_real_key)`；
3. AnthropicCompatibleJudgeProvider 在调 transport **之前**还会做硬性
   config 检查：`api_key` 或 `model` 缺一即 `missing_config`，**所有路径都先过这关**。

示例 fixture：`examples/fake_transport_fixtures/runtime_debug.yaml`。
契约测试：`tests/test_cli_anthropic_compatible_live.py`（6 条，含
socket 禁用 + 全文件 key/url 字面值泄漏扫描）。

CLI smoke 输出位置：`runs/v14-cli-preflight-check`、
`runs/v14-cli-live-disabled`、`runs/v14-cli-fake-bad`、`runs/v14-cli-bad`、
`runs/v14-cli-analysis`。
