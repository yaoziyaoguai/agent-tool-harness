# agent-tool-harness v1.2 — Anthropic-compatible preflight readiness MVP

> Tag: `v1.2` · Base: `v1.1` (`983de16`) · Head: `326213d`
>
> 中文学习型说明：v1.2 的目标是把"未来真实 LLM judge 在阿里云 Coding Plan
> Anthropic-compatible endpoint 上 live"前**必须先做的本地侧安全闸**全部
> 落地：分歧率聚合（Composite + disagreement metrics）、provider skeleton
> 与脱敏错误分类（AnthropicCompatible offline / fake-transport）、live 之
> 前的本地自检 CLI（`judge-provider-preflight`）。**v1.2 仍然完全不接真
> 实 OpenAI / Anthropic API、不调网络、不需要密钥、不替代 RuleJudge。**

## 定位

- v1.0：deterministic anti-decoy / evidence grounding 收口，`RuleJudge` +
  `MockReplayAdapter` 是 MVP 判定底座。
- v1.1：`JudgeProvider` Protocol 抽象 + RuleJudgeProvider / RecordedJudge
  Provider；EvalRunner 接受可选 `dry_run_provider`；deterministic baseline
  仍是 ground truth。
- **v1.2**：在 v1.1 基础上落地"未来真实 LLM judge 上线**前**所需的全部
  脚手架"——Composite 分歧率聚合、Anthropic-compatible offline provider
  skeleton 与 8 类错误 taxonomy 脱敏、`judge-provider-preflight` 本地侧
  自检 CLI。任何一步失误都可能把真实 key 推进 git 或 artifact，本版本提
  前用契约测试钉死。

## 相对 v1.1 的新增能力

### 1. CompositeJudgeProvider + judge_disagreement metrics（commit `f31ceeb`）

- 新增 `CompositeJudgeProvider`（位于
  `agent_tool_harness/judges/provider.py`）：把 `RuleJudgeProvider`
  （deterministic ground truth）与一个 advisory provider 并列调用；返回的
  `ProviderJudgeResult.passed` **透传 deterministic**，advisory 信息放进
  `extra={agreement, deterministic_result, advisory_result}`。
- `EvalRunner._invoke_dry_run_provider` 在 entry 中追加 `agreement /
  advisory_result / deterministic_result`；`_metrics` 新增可选顶层
  `judge_disagreement = {schema_version, total, agree, disagree, error,
  disagreement_rate}`，**优先**按 `entry.agreement` 计数（advisory vs
  deterministic 真实分歧），仅当字段缺失时回落到 `agrees_with_deterministic`。
- `MarkdownReport._render_dry_run_provider` 在段首打印 `Disagreement
  summary`；逐条 entry 多渲染 `advisory=<provider>/<mode>=<passed>` 字段。
- CLI `run` 新增 `--judge-provider composite`，与 `recorded` 共用
  `--judge-recording PATH`，缺路径走可行动错误路径（exit 2）。
- 4 条新集成测试 `tests/test_eval_runner_judge_provider.py::
  test_composite_*`：advisory 不改写 deterministic baseline；缺 recording
  必走 entry.error；默认 run 字节兼容；socket-ban monkeypatch 下仍跑通。
- 新增 `.env.example` 占位符模板 + 中文学习型说明。

### 2. AnthropicCompatibleJudgeProvider offline / fake-transport skeleton（commit `1ecaa91`）

- 新增 `AnthropicCompatibleJudgeProvider`（同文件）+
  `AnthropicCompatibleConfig`（4 个 `AGENT_TOOL_HARNESS_LLM_*` env：
  `PROVIDER` / `BASE_URL` / `API_KEY` / `MODEL`；`__repr__` 屏蔽 api_key
  与 base_url，仅暴露 `*_set` 布尔）。
- 新增 `JudgeTransport` Protocol 注入 seam + `FakeJudgeTransport`
  in-process 假 transport。**本轮无 live HTTP 实现**——provider 只能走
  `offline_fixture`（`--judge-recording PATH`）或注入 fake transport。
- 稳定 **error taxonomy 8 类**（模块级常量导出）：
  `missing_config / disabled_live_provider / auth_error / rate_limited /
  network_error / timeout / bad_response / provider_error`。
- `_safe_message(error_code)` 模板化错误消息：固定字符串，**绝不**
  echo raw exception / Authorization header / response body /
  api_key / base_url。
- Provider **返回**带 `error_code` 的 `ProviderJudgeResult`（不抛异常）→
  `EvalRunner._invoke_dry_run_provider` 转 `entry.error={type, message}`
  + 不写 `entry.passed`，metrics 计入 `judge_disagreement.error` 桶而非
  `disagree`，杜绝吞异常假成功。
- `CompositeJudgeProvider.judge` 透传 advisory 的 `error_code /
  error_message / model` 到 extra（修复 v1.x 第一轮里 advisory error 被
  Composite 摘掉、误算成 disagree 的 root cause）。
- CLI `run` 新增 `--judge-provider anthropic_compatible_offline`，
  从 env 读 config，由 `CompositeJudgeProvider` 包裹。缺 key/model 时
  CLI **不崩溃**，artifact 中 `entry.error.type=missing_config`。
- 8 条新契约测试 `tests/test_anthropic_compatible_provider.py`：默认
  `disabled_live_provider`；缺 key/model → `missing_config` 且
  `repr(config)` 不泄漏；6 类 transport 错误全部脱敏；fake transport 成
  功透传；CLI 完整闭环 + disagreement + **artifact 不泄漏 fake key/
  base_url**；缺 key 时 CLI 不崩溃；CLI monkeypatch 禁 socket 后仍跑通。

### 3. judge-provider-preflight 本地侧自检 CLI（commit `326213d`）

- 新增 `agent_tool_harness/judges/preflight.py` + CLI
  `judge-provider-preflight --out PATH` —— 真实 LLM judge live **之前**
  的"本地侧最后一道闸"。**纯本地、不联网、不读取真实 key 值**。
- `run_preflight(config, repo_root)` 检查 4 项：
  1. **配置面**：`AnthropicCompatibleConfig.from_env()` 字段齐全度
     （只回 `*_set` 布尔与 `missing_fields` KEY 名，**不**回值）；
  2. **Git 面**：`.gitignore` 是否忽略 `.env`（按行匹配
     `.env / *.env / .env*`）；
  3. **文件面**：`.env.example` 是否仅含占位符（每行 `KEY=` 后值非空即
     视为可疑，但报告**只**回 KEY 名，**不**回 value——防止 preflight
     artifact 二次泄漏）；
  4. **Provider 面**：8 类 error taxonomy message 模板用 fake transport
     触发一遍，并用真实 `config.api_key` / `config.base_url` 做"泄漏扫描"，
     确认 message 不含字面值。
- 输出 `preflight.json`（schema `1.0.0-preflight`）+ `preflight.md`，
  字段全部为脱敏 / 布尔。`summary.ready_for_live` **永远** `False`——
  本轮不开 live；要 live 必须等未来 `LiveAnthropicTransport` milestone
  显式开关。
- 7 条新契约测试 `tests/test_judge_provider_preflight.py`：missing_fields
  全 4；`.gitignore` 缺 `.env`；`.env.example` 含真实 value（KEY 报但
  value 不进 artifact）；8 类 message 脱敏扫描；`preflight.json` /
  `preflight.md` 任何路径下不含 fake key/base_url/model 字面值；CLI
  monkeypatch 禁 socket 后仍跑通；fake-env 端到端。

## 核心命令路径（v1.2）

```bash
# 1. 默认 deterministic 路径（v1.0 字节兼容）
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/v12-good --mock-path good

# 2. Composite + recorded advisory（看 advisory vs deterministic 分歧率）
python -m agent_tool_harness.cli run ... \
  --judge-provider composite --judge-recording PATH/to/judgments.yaml

# 3. Composite + Anthropic-compatible offline（fixture / fake transport）
AGENT_TOOL_HARNESS_LLM_PROVIDER=anthropic_compatible \
AGENT_TOOL_HARNESS_LLM_API_KEY=fake-key \
AGENT_TOOL_HARNESS_LLM_MODEL=fake-model \
python -m agent_tool_harness.cli run ... \
  --judge-provider anthropic_compatible_offline \
  --judge-recording PATH/to/judgments.yaml

# 4. live 之前的本地自检（任何时候都可以跑，0 网络 0 key 读取）
python -m agent_tool_harness.cli judge-provider-preflight \
  --out runs/preflight
```

## 已知限制（明确不在 v1.2 范围）

- **没有真实 LLM judge**：所有 advisory 路径要么是 in-process 字典
  fixture，要么是 in-process fake transport。**绝不**联网、**绝不**读
  取真实 API key 值（即使 env 已设置）。
- **没有真实 HTTP transport**：`AnthropicCompatibleJudgeProvider` 只接受
  `FakeJudgeTransport`；真实 `LiveAnthropicTransport`（基于 stdlib
  `http.client` 或经用户明确同意后引入轻量依赖）属未来单独 milestone。
- **没有 endpoint 可达性 / api_key 合法性 / model 服务端校验**：preflight
  只做本地文件结构与字段齐全度检查；服务端验证仍属未来 live readiness。
- **MockReplayAdapter 仍是 MVP**：`signal_quality=tautological_replay`
  说明 PASS/FAIL 是结构性必然，**不**等于真实 Agent 能力评估。
- **PROVIDER_SCHEMA_VERSION 仍 `1.1.0-skeleton`**：等真实 LLM provider 落
  地后才 bump 到 `1.1.0` 正式版。

## 后续真实 live provider 路线（仅 ROADMAP 备忘，**不**在 v1.2）

- 设计 `LiveAnthropicTransport`：基于 stdlib `http.client` 或经用户明确
  同意后引入轻量依赖；覆盖 auth/retry/timeout 治理；request/response 全
  部走脱敏路径，不写 raw header / body 进 artifact。
- 给 `judge-provider-preflight` 加 `--live` 显式开关：在用户明确同意后做
  一次最小 ping（仍需脱敏、限定 request 体积、限定调用次数）。
- 阿里云 Coding Plan Anthropic-compatible endpoint 的 live smoke：在
  preflight + `--live` ping 通过后，跑一次真实 evals 闭环。
- prompt / rubric 真实组装；多 advisory majority-vote 聚合；成本控制
  与隐私脱敏的 prompt 模板审计。
- 接入更多 provider（OpenAI / Gemini）后提取通用 `ProviderPreflight`
  协议。

## 兼容性与升级

- v1.0 / v1.1 `judge_results.json` / `metrics.json` 在**未配 dry-run
  provider** 时仍**字节兼容**——无 `dry_run_provider` 顶层字段、无
  `judge_disagreement` 顶层字段。
- 任何已有调用方升级到 v1.2 后，不传 `--judge-provider` 即可保持原行为。
- `.env.example` 已就绪；`.env` 已在 `.gitignore`；任何真实 key 应只在
  本地 `.env` 出现，**绝不** commit。

## 验证

- ruff: All checks passed
- pytest: **234 passed, 1 xfailed**（v0.2 候选 A subtle decoy 已知 xfail）
- smoke: `run --mock-path good/bad` ✅；`analyze-artifacts` ✅；
  `judge-provider-preflight` no-key ✅；`judge-provider-preflight`
  fake-env ✅，artifact 中无 fake key/base_url/model 字面值。
