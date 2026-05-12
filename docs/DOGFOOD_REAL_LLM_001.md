# Dogfood Record: Real LLM Judge #001

## 1. Basic Info

| Field | Value |
|-------|-------|
| Date | 2026-05-12 |
| Provider family | openai |
| Provider compatibility | compatible |
| Provider name | `openai-compatible` |
| Base URL | user-provided OpenAI-compatible endpoint |
| Model | user-provided model via `model_env` |
| API key source | `--env-file ./.env` (gitignored) |
| Config file | `examples/llm_providers.example.yaml` |

**敏感信息处理：** 真实 api_key、base_url、model 名不记录在此文档中。全部从 `.env` 文件中读取，`.env` 已 gitignored。

## 2. Command Structure

```bash
python -m agent_tool_harness.cli run \
  --project examples/knowledge_search/project.yaml \
  --tools examples/knowledge_search/tools.yaml \
  --evals examples/knowledge_search/evals.yaml \
  --out /tmp/dogfood-out \
  --core-flow \
  --judge-provider llm \
  --live --confirm-i-have-real-key \
  --llm-config examples/llm_providers.example.yaml \
  --llm-provider openai-compatible \
  --env-file ./.env
```

## 3. Provider Config (no secrets)

```yaml
# examples/llm_providers.example.yaml
providers:
  openai-compatible:
    family: openai
    compatibility: compatible
    api_key_env: AGENT_TOOL_HARNESS_OPENAI_COMPAT_API_KEY
    base_url_env: AGENT_TOOL_HARNESS_OPENAI_COMPAT_BASE_URL
    model_env: AGENT_TOOL_HARNESS_OPENAI_COMPAT_MODEL
```

## 4. Output Path

```
/tmp/dogfood-out/
├── evaluation_result_kb_sso_session_loss_regression.json
├── evidence_kb_sso_session_loss_regression.json
├── execution_trace_kb_sso_session_loss_regression.json
├── metrics.json
├── report_summary.json
├── report.md
├── REVIEW_DECISION_NOT_GENERATED.txt
└── signal_quality.txt
```

## 5. Results

| Metric | Value |
|--------|-------|
| total_evals | 1 |
| passed | 1 |
| core_flow | true |
| RuleFinding count | 8 (all passed) |
| JudgeFinding generated | Yes (1 finding, `category: "judge"`, `severity: "info"`) |
| JudgeFinding provider | `openai-compatible` |
| ReviewDecision auto-generated | **No** — confirmed by `REVIEW_DECISION_NOT_GENERATED.txt` |

## 6. Issues Found

### 6.1 CLI log `model=` displayed empty

**Root cause:** `cli.py:1432` used `result.config.model` (static `LLMProviderConfig.model`, which is `""` when `model_env` is used). The resolved model existed in `result.provider._model` but was not publicly exposed.

**Fix:** Added `LLMJudgeProvider.model` property exposing `self._model`, changed CLI to use `result.provider.model`.

**Status:** Fixed in same commit as this doc.

### 6.2 LLM judge transport error

A `bad_response` finding was recorded (`[openai-compatible] transport error: bad_response`). This indicates the HTTP call reached the server but the response format was unexpected. Does NOT block the evaluation — RuleFindings still passed, and the JudgeFinding is advisory only.

## 7. Safety Gates Verified

| Gate | Status |
|------|--------|
| `--live` required | Passed |
| `--confirm-i-have-real-key` required | Passed |
| `--env-file` or `--allow-os-env` required | Passed |
| Real key not logged | Passed (repr hides `api_key=****`) |
| `.env` gitignored | Passed |
| ReviewDecision not auto-generated | Passed |
| `EvaluationResult.passed` from RuleJudge only | Passed |

## 8. Next Steps

1. **Independent audit** — 由非作者 review 完整 dogfood 输出
2. **Push decision** — 等用户确认后 push
3. **Transport error debugging** — 排查 `bad_response` 根因（可能是 API 响应格式不匹配）
4. **Prompt engineering** — 设计 JudgeFinding 的 system prompt + rubric
5. **Multi-provider comparison** — 用多个 provider 跑同一场景，分析分歧率

## 9. References

- [LLM_PROVIDER_CONFIG.md](./LLM_PROVIDER_CONFIG.md) — Provider 配置完整文档
- [AGENT2HARNESS_MAIN_FLOW.md](./AGENT2HARNESS_MAIN_FLOW.md) — Core Flow 架构
- [examples/llm_providers.example.yaml](../examples/llm_providers.example.yaml) — 配置模板
