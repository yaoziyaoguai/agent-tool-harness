# agent-tool-harness v1.6 Release Notes

> Release date: 2026 — see git tag `v1.6`.
> Predecessor: [`RELEASE_NOTES_v1.5.md`](RELEASE_NOTES_v1.5.md)（multi-advisory
> CLI + report readability MVP）。

## v1.6 定位

v1.6 是 **live readiness 治理三件套** MVP，在 v1.4 / v1.5 已落地的真实
live HTTPS skeleton + 多 advisory CLI 之上，补齐三处真实用户即将开 live
之前会踩的工程治理空缺：

1. **retry/backoff 治理**——`LiveAnthropicTransport` 之前一遇到 429 /
   网络抖动直接抛错，reviewer 看不出"是真不可用还是临时抖一下"；
2. **LLM 成本聚合 artifact**——之前每条 advisory 的 token / retry 散落
   在 `judge_results.json::dry_run_provider` 内，无法跨 eval 横向看；
3. **judge prompt 启发式安全审计**——真实 LLM judge 落地之前，prompt
   文本可能引导泄漏 secret / 把 advisory 当 ground truth 之类反模式，
   缺少自动化 baseline。

**仍完全不接真实 LLM、不联网、不读取真实 key、不需要密钥**。任何"真
实 live HTTP" 必须由用户在自己环境主动构造 `LiveAnthropicTransport(...,
live_enabled=True, live_confirmed=True)` 触发；CI / smoke 全程走 fake /
disabled / fixture。

---

## 相对 v1.5 新增能力

### 1. retry/backoff 治理（commit `6e8a35c`）

`agent_tool_harness/judges/provider.py::LiveAnthropicTransport`：

- 新增四个治理参数：`max_attempts`（默认 1，与 v1.5 字节兼容）、
  `base_delay_s` / `max_delay_s`、`retryable_error_codes`（默认仅
  `rate_limited` / `network_error` / `timeout`）、`sleep_fn`（默认
  `time.sleep`，CI 注入 fake clock）；
- `send()` 外层包裹 deterministic 重试循环；非 retryable error 永不重
  试（auth_error / missing_config / disabled_live_provider /
  bad_response / provider_error）——避免 401 反复打、避免 5xx 推高
  账单；
- 退避公式：`min(max_delay, base * 2 ** (attempt-1))`，无 jitter，CI
  完全 deterministic；
- `last_attempts_summary` 写到 transport 实例属性，由
  `AnthropicCompatibleJudgeProvider` 透传到 `ProviderJudgeResult.extra`
  的 `attempts_summary` / `retry_count` 字段，再由 EvalRunner 写入
  `judge_results.json::dry_run_provider.results[].extra`；
- 单 advisory 与多 advisory（CompositeJudgeProvider）合成路径都已覆盖
  字段透传；
- 任何 attempt 信息**绝不**包含 raw key / base_url / Authorization
  header / SDK 异常长文本。

新增 7 条契约测试 `tests/test_live_transport_retry.py`：默认无重试 /
retry 后成功 / 不可重试不重试 / max_attempts 用尽 / max_delay cap /
provider extras 透传 / secret 永不入 attempts_summary。

### 2. `runs/<dir>/llm_cost.json` artifact + Cost Summary 段（commit `f777dc2`）

新增 `agent_tool_harness/reports/cost_tracker.py`：

- 把 `judge_results.json::dry_run_provider.results[]` 中每条 entry 的
  `usage` / `attempts_summary` / `retry_count` 聚合成 `runs/<dir>/
  llm_cost.json`；
- 输出 schema_version=1 的 dict，含 `totals`（advisory_count /
  with_usage_count / tokens_in / tokens_out / retry_count_total /
  error_count）/ `per_eval` / `cost_unknown_reasons` /
  `estimated_cost_usd` / `estimated_cost_note`；
- **当 entry 没有 usage 时，永远不 fabricate 数字**，而是按 provider
  mode 显式记录原因（如 `"recorded mode does not report token usage"`
  / `"fake_transport response missing usage field"` / `"advisory errored
  (rate_limited); no usage available"`）；
- `estimated_cost_usd` v1.6 永远 None；price 表注入留给 v1.7+。

`EvalRunner.REQUIRED_ARTIFACTS` 加入 `llm_cost.json` 并在
`_write_artifacts` 阶段产出（即使没配 dry-run provider 也写 0 totals
版本，让"找不到 artifact" vs "找到但 totals 全 0"两种状态可区分）。

`MarkdownReport.render` 新增可选 `llm_cost` kwarg，渲染 `Cost Summary
(advisory-only, deterministic)` 段，**显式声明 advisory-only / 不是真实
账单**；不传该 kwarg 时不渲染（保持 v1.5 字节兼容）。

新增 7 条契约测试 `tests/test_llm_cost_tracker.py`：空输入 / 单 advisory
带 usage / recorded 无 usage / 多 advisory error 优先归类 / cost 永远
None / 报告可见性 + advisory-only 文案。

### 3. `audit-judge-prompts` CLI + 启发式 prompt 审计器（commit `7032ad2`）

新增 `agent_tool_harness/audit/judge_prompt_auditor.py`：

- 7 类 deterministic 启发式 rule：

| rule_id | severity | 触发条件 |
| --- | --- | --- |
| `prompt_too_short` | high | prompt 文本 <80 字符 |
| `missing_evidence_refs_placeholder` | high | 未引用 evidence_refs / transcript / artifact 占位 |
| `missing_pass_fail_rubric` | high | rubric 无 PASS/FAIL/通过/失败 关键词 |
| `missing_grounding_requirement` | medium | 未要求模型基于 evidence/事实判断 |
| `contains_key_like_string` | critical | 出现 sk- / Bearer / 长 hex 等 key 字面 |
| `instructs_secret_disclosure` | critical | 引导模型披露 key/secret/credential |
| `advisory_treated_as_truth` | high | 暗示 advisory 输出就是最终结果 |

- key 字面在 finding `evidence` 字段**自动脱敏**（仅保留前 4 字符 +
  长度 + `[redacted]` 标记），任何 audit artifact 都不会把 raw key 写
  回——本 audit 自身不会成为新的泄漏面；
- 永远不调 LLM、不联网、stdlib only，可在 CI 任意频次跑。

新增 CLI 子命令 `audit-judge-prompts --prompts PATH --out DIR`：写出
`audit_judge_prompts.json`（含 schema_version + summary + findings +
rules）+ `audit_judge_prompts.md`（reviewer 可读，按 severity 分组）。

新增 `examples/judge_prompts.yaml` 示例 fixture（含 dirty p1 + clean p2
对比）。新增 11 条契约测试 `tests/test_audit_judge_prompts.py`：每条规
则单独触发、CLI 子命令端到端、key 不回写、advisory-only 文案、干净
prompt 0 finding。

### 4. 文档同步（commit `258fa10`）

- `README.md` 顶部能力声明加入 v1.6 第一轮三项；
- `docs/ARTIFACTS.md` 新增 `llm_cost.json` + `audit_judge_prompts.json`
  字段说明（含 7 类 rule_id 表 + 反模式硬约束）；
- `docs/ROADMAP.md` 在 v1.5 第二轮之后加入 v1.6 第一轮"已落地"段，明
  确范围内 / 范围外。

---

## 工程指标

- 测试基线：v1.5 时 284 passed + 1 xfailed → v1.6 时 **309 passed +
  1 xfailed**（+25 新增契约测试，xfail 仍是 v0.2 backlog 的 subtle
  decoy，未删除 / 未弱化）；
- ruff：All checks passed；
- 新增依赖数：**0**（所有 retry / cost / audit 都用 stdlib + 已有 yaml）；
- CI 真实 sleep：**0**（retry 测试全部注入 fake clock）；
- CI 网络请求：**0**；
- CI 真实 key 读取：**0**；
- 4 个 commit 都带中文学习型注释 / docstring（负责什么 / 不负责什么 /
  为什么 / MVP 边界 / 未来扩展点）。

---

## 已知限制（请如实告诉团队）

1. **Cost Summary / `llm_cost.json` 不是真实账单**：`estimated_cost_usd`
   v1.6 永远是 None；token 数依赖 fake transport / offline fixture 是否
   提供 `usage` 字段；recorded mode 完全不报 usage。请把它当 deterministic
   复盘指标，**严禁**作为公司报账依据。
2. **retry/backoff 还没在真实联网中验证过**：v1.6 默认 `max_attempts=1`
   也是为此——CI 永远不连真实网络。真实 live 用户在自己环境调高
   `max_attempts` 时，请自行做小流量灰度。
3. **`audit-judge-prompts` 是启发式 ≠ 语义级安全验证**：通过 audit 不
   代表 prompt 在生产中安全；它是治理 baseline，不是终判。
4. **prompt audit 的"含 key 字面"规则只覆盖最常见模式**（sk- /
   Bearer / 长 hex）；专有云 / 自建 IAM 短 token 仍可能漏检——这是 v1.7+
   规则扩展的 backlog。
5. **真实 LLM Judge / 真实联网 / 真实成本计费在 v1.6 仍未实现**——任何
   描述"v1.6 接入真实 LLM judge / 真实联网 / 真实计费"的内容都是错误
   的，请回到本文档。

---

## v1.6 仍**未做**的事（明确范围外）

- 真实 LLM judge 调用（永远不在 CI；用户需自己扩展 transport 并显式
  双标志 opt-in）；
- 价格表注入 / `estimated_cost_usd` 真实数值；
- 跨 process / 跨 run 限流；
- jitter / 抖动退避；
- prompt 语义级评估（如"prompt 是否能让模型给出对的判断"）；
- Web UI / HTML 报告变体；
- 自动 patch 用户工具；
- MCP / HTTP / Shell tool executor。

---

## 后续路线（仅备忘，不在 v1.6 范围）

- v1.7+ candidate：price table 注入 + per-eval-budget 强制 cap；
- v1.7+ candidate：跨多 run cost dashboard；
- v1.7+ candidate：jitter / 跨 process 限流；
- v1.7+ candidate：扩展 prompt audit 的 key 模式覆盖（专有云 /
  IAM 短 token）；
- v2.0+ candidate：真实 LLM judge prompt 效果回归测试。

---

## 升级提醒

- v1.6 严格向后兼容 v1.5：默认 `max_attempts=1`，未传 `llm_cost` kwarg
  时 `MarkdownReport.render` 行为不变；`run` 子命令未传新 flag 时输出
  与 v1.5 一致 + 多一个 `llm_cost.json`（0 totals）。
- 任何 v1.5 时已有的 artifact 字段都未删除 / 未重命名（"只增不删"承诺
  仍然有效）。
