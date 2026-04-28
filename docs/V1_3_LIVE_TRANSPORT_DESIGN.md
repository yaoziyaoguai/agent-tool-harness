# v1.3 LiveAnthropicTransport 设计文档（仅设计，不实现）

本文档负责什么
==============

为未来真实接入 **Anthropic Messages API 兼容**端点（典型如阿里云
Coding Plan 的 Anthropic-compatible 协议资源）**提前钉死契约 / 配置 /
错误分类 / 脱敏 / artifact schema / 测试边界**——但 **本轮（v1.3）不实现**
任何真实 HTTP 调用、不读取真实 API key、不联网、不引入新依赖。

本文档**不**负责什么
====================

- 不引入 `anthropic` / `httpx` / `requests` / `urllib3` 等第三方依赖；
  未来 `LiveAnthropicTransport` 优先用 Python 标准库 `http.client` / `ssl` /
  `json` 实现，保持"零依赖"硬约束；
- 不规定具体重试 / 退避 / 限流策略——这些属于 v1.4+ 工程治理范畴；
- 不规定 prompt 模板 / rubric 内容；这些由 `AnthropicCompatibleJudgeProvider`
  在 v1.4 配套迭代时定义；
- 不替代 deterministic baseline——任何未来真实 LLM judge 的输出仍然只能
  作为 advisory 写入 `judge_results.json`，**不能**覆盖 `results[].passed`。

为什么需要这份设计文档
======================

v1.x 第二轮已经把 `AnthropicCompatibleJudgeProvider` 的契约 / 错误分类 /
fake transport / 8 条 contract test 全部就位（见 `agent_tool_harness/judges/provider.py`
里 `JudgeTransport` Protocol 部分）。**唯一缺的是真实 transport 实现**。

但真实 HTTP 实现一旦写下去，就会触发：
1. 密钥从哪里读、能否泄漏到 artifact / 日志 / git；
2. 默认是否会调用网络（哪怕跑 CI 也不应触发）；
3. 出现 `auth_error / rate_limited / network_error / timeout / invalid_response`
   时如何脱敏并归类；
4. 阿里云 Coding Plan 的具体 endpoint / model id / 协议差异如何隔离在
   配置层而不是代码里；
5. CI / 用户本地 / 用户真实付费场景之间的 **三道防线**（环境变量 / CLI
   双重 opt-in / 默认禁用）如何串起来。

这些问题任何一条没想清楚就动手，未来都要付出回滚成本。**先写文档钉契约，
再分批实现**——这是 v1.x 一贯的演进节奏。

未来 LiveAnthropicTransport 的核心契约
======================================

配置入口（环境变量，绝不入 git）
-------------------------------

| 环境变量                                    | 用途                                              | 示例                                  |
| ------------------------------------------- | ------------------------------------------------- | ------------------------------------- |
| `AGENT_TOOL_HARNESS_LLM_BASE_URL`           | Anthropic-compatible endpoint 根 URL              | `https://dashscope.aliyuncs.com/...`  |
| `AGENT_TOOL_HARNESS_LLM_API_KEY`            | API key（密钥，绝不写入 artifact 或 git）         | `sk-...`                              |
| `AGENT_TOOL_HARNESS_LLM_MODEL`              | 模型 id（按 provider 文档填写）                    | `claude-3-5-sonnet-20241022` 或厂商映射 |
| `AGENT_TOOL_HARNESS_LLM_REQUEST_TIMEOUT_S`  | 单次请求超时（秒），默认 30，硬上限 120           | `60`                                  |

**强约束**：

- API key **永远只通过环境变量传入**；CLI 不接受 `--api-key` 直接参数，避免
  在 shell history 留痕；
- 任何 artifact / 日志 / 报错 message **必须**先经过 `_safe_message()`
  脱敏（已在 v1.x 第二轮就位）；
- API key **绝不**进入 prompt 拼接、不写入 `judge_results.json` /
  `report.md` / `transcript_analysis.json` / 任何 run 目录文件；
- 仓库 `.env.example` 只放占位符（`your-api-key-here`），CI/dev 人手动复制成
  `.env` 后填真值；`.env` 已被 `.gitignore` 排除。

双重 opt-in：默认完全禁用
-------------------------

未来在 `judge-provider-preflight` 与 `run --judge-provider anthropic_compatible`
路径上，必须同时满足 **以下三道闸门** 才会真正打开网络：

1. **环境变量齐备**：上表 4 个变量都已设置且 base_url / model 不是占位符；
2. **CLI 双标志**：必须同时显式传 `--live` **且** `--confirm-i-have-real-key`；
   缺任一 → 不发任何网络请求，artifact 写入 `disabled_live_provider` error_code；
3. **provider 注入 transport**：`AnthropicCompatibleJudgeProvider`
   构造时显式传入 `transport=LiveAnthropicTransport(...)`；CLI 默认仍走
   `FakeJudgeTransport`，即便环境变量齐备也**不**自动切换。

任何一道闸门未通过，都必须返回结构化 `error_code=disabled_live_provider`
而非抛 traceback；这是为了让"用户跑了一条带 `--live` 的命令但忘了
`--confirm`"在 artifact 里**显眼**地报错，而不是默默走 fake。

**v1.3 第一轮已经在 `judge-provider-preflight` 里把双标志契约落地了**
（见 `agent_tool_harness/judges/preflight.py` 的 `--live` /
`--confirm-i-have-real-key` 处理逻辑）；真正的网络分支留给 v1.4。

错误分类与脱敏
--------------

`LiveAnthropicTransport` 必须把 HTTP 状态 + 异常映射到 v1.x 第二轮已
钉死的 8 条 `error_code`（与 `FakeJudgeTransport` 完全对齐）：

| HTTP / 异常                          | error_code            | 含义                                       |
| ------------------------------------ | --------------------- | ------------------------------------------ |
| 401 / 403                            | `auth_error`          | API key 无效 / 过期 / 权限不足             |
| 429                                  | `rate_limited`        | 触发限流，需用户排查配额                   |
| 5xx                                  | `server_error`        | 上游服务异常                               |
| `socket.timeout` / `TimeoutError`    | `timeout`             | 请求超时                                   |
| `socket.gaierror` / `ConnectionError`| `network_error`       | DNS / TCP / 无法建连                       |
| 200 但 JSON 解析失败                 | `invalid_response`    | 上游返回结构不符合契约                     |
| 200 但缺关键字段                     | `invalid_response`    | 同上                                       |
| transport 未注入 / 关闭              | `disabled_live_provider`| 三道闸门未全通过 → 不发网络               |

**脱敏规则**（已在 `_safe_message` 实现，未来 transport 复用）：

- 任何 message / 异常 repr 中包含的 `sk-***` / `Bearer ***` / 完整 URL query
  必须脱敏成 `sk-***REDACTED***` / `Bearer ***REDACTED***`；
- 不写入 raw response body 到 artifact；只写经过截断 + 脱敏的 `error_message`
  字段；
- error_message 长度上限 **512 字符**，超出截断并加 `...[truncated]` 后缀。

contract test 策略（v1.4 真实落地时必须先过）
---------------------------------------------

未来真正实现 `LiveAnthropicTransport` 时必须先写以下契约测试，**再**写代码：

1. `test_live_transport_default_disabled`：默认构造 provider + 默认 CLI
   命令，**任何环境变量都不读** → 不允许 import socket / http.client；
2. `test_live_transport_requires_double_optin`：只传 `--live` 不传
   `--confirm-i-have-real-key` → artifact 必出现 `disabled_live_provider`；
3. `test_live_transport_sanitizes_api_key_in_error`：用 monkeypatch 让
   transport 抛带 `sk-fakekey-xxx` 的异常 → artifact 文本扫描必不含原始
   key 字符串；
4. `test_live_transport_maps_http_status_to_error_code`：mock `HTTPResponse`
   返回 401 / 429 / 500 / timeout → 必须命中对应 error_code；
5. `test_live_transport_does_not_leak_to_judge_results_json`：完整跑
   `run --judge-provider anthropic_compatible --live --confirm-i-have-real-key`
   （用 mock transport），扫描所有 artifact 文件 → 不含 base_url / api_key
   / `Bearer` 子串；
6. `test_live_transport_zero_dep`：grep `agent_tool_harness/judges/`
   下不允许出现 `import requests` / `import httpx` / `import anthropic`。

artifacts 排查路径
==================

未来 `--live` 真实路径上线后，用户排查问题的入口：

- `runs/<run_dir>/judge_results.json`：每条 entry 的 `dry_run_provider.results[i]`
  会有 `error_code` / `error_message`（已脱敏）/ `model` 字段；
- `runs/<run_dir>/report.md`：在 "Dry-run JudgeProvider (advisory only)"
  段会列出 advisory 的 `error_code` 摘要；
- `runs/<preflight_dir>/preflight.md` + `preflight.json`：preflight 命令
  会专门告诉用户**当前**配置能否打开 live，以及缺什么环境变量 / 缺哪个标志。

MVP / mock / demo 边界（请用户**务必**理解）
============================================

- 本设计文档**不**代表 v1.3 已经支持真实调用 LLM。v1.3 只完成：
  - 多 advisory majority-vote 聚合（`CompositeJudgeProvider` 已支持 list）；
  - 本设计文档；
  - `judge-provider-preflight --live` **双标志契约**（不发网络，仅 contract）。
- 真实 `LiveAnthropicTransport` 实现在 **v1.4** 落地，按上述 contract test
  顺序逐条实现；
- 即便 v1.4 实现完成，**deterministic RuleJudge 仍然是 baseline**——LLM judge
  永远只是 advisory，不能改写 `results[].passed`。

未来扩展点（仅备忘）
====================

- `LiveOpenAITransport`：复用同一个 `JudgeTransport` Protocol，OpenAI
  Chat Completions 协议适配；
- 多 endpoint 故障转移：`CompositeJudgeProvider` 已支持 advisory 列表，
  未来可让 list 里包含 `LiveAnthropicTransport(provider_a)` +
  `LiveAnthropicTransport(provider_b)`，自然实现"多模型 majority
  vote"——本轮已经验证聚合契约；
- 成本上报：每次真实调用记录 token usage 到 `runs/<run_dir>/llm_cost.json`，
  与 artifact 一起 review；本设计本轮**不**展开。
