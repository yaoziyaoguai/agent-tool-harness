# Dogfood Record: Real LLM Infrastructure & Safety Gate Verification #001

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
| **Semantic judge verdict** | **Not produced** — provider response parsing returned `bad_response` |
| ReviewDecision auto-generated | **No** — confirmed by `REVIEW_DECISION_NOT_GENERATED.txt` |

**Key takeaway:** The real LLM transport, opt-in safety gates (--live, --confirm-i-have-real-key, --env-file), and factory wiring were all verified successfully. However, the actual semantic JudgeFinding (passed/rationale/confidence from LLM) was NOT produced because the provider response format did not match the expected parser. This is a provider response parsing/debugging follow-up, not a transport or safety gate failure.

## 6. Issues Found

### 6.1 CLI log `model=` displayed empty (FIXED)

**Root cause:** `cli.py:1432` used `result.config.model` (static `LLMProviderConfig.model`, which is `""` when `model_env` is used).

**Fix:** Added `LLMJudgeProvider.model` property, changed CLI to use `result.provider.model`.

### 6.2 Provider response parsing: bad_response (NOT FIXED)

**Status:** The real LLM judge transport successfully sent the request and received a response, but the response could not be parsed as a valid JudgeFinding. The finding recorded is `[openai-compatible] transport error: bad_response`.

**Impact:** The semantic JudgeFinding (passed/rationale/confidence from LLM) was NOT produced. RuleFindings (deterministic) were unaffected and passed normally. `EvaluationResult.passed` remained determined by RuleJudge, which is the correct behavior.

**Root cause:** To be investigated. Likely a mismatch between the provider's actual response format and the expected OpenAI chat completions response schema.

**Next follow-up:** Debug provider response parsing / response format compatibility. This does NOT block TraceImportAdapter or CLIAgentAdapter implementation.

## 7. What Was Verified

**Successfully verified:**
- Real LLM transport infrastructure (HTTPS call, factory wiring, safety gates)
- Opt-in safety gates: --live / --confirm-i-have-real-key / --env-file
- SecretSource resolution: api_key / base_url / model all correctly resolved from .env
- RuleFinding + JudgeFinding coexistence in EvaluationResult
- ReviewDecision NOT auto-generated
- EvaluationResult.passed stays RuleJudge-determined

**NOT yet verified:**
- Semantic judge verdict (passed/rationale/confidence from LLM) — blocked by bad_response

## 8. Safety Gates Verified

| Gate | Status |
|------|--------|
| `--live` required | Passed |
| `--confirm-i-have-real-key` required | Passed |
| `--env-file` or `--allow-os-env` required | Passed |
| Real key not logged | Passed (repr hides `api_key=****`) |
| `.env` gitignored | Passed |
| ReviewDecision not auto-generated | Passed |
| `EvaluationResult.passed` from RuleJudge only | Passed |

## 9. Next Steps

1. **Provider response parsing debug** — 排查 bad_response 根因（API 响应格式与预期 schema 不匹配）
2. **Prompt engineering** — 设计 JudgeFinding 的 system prompt + rubric
3. **TraceImportAdapter / CLIAgentAdapter implementation** — 不依赖 semantic judge 修复
4. **Re-dogfood after response parsing fix** — 再次尝试验证完整 semantic judge 链路
5. **Multi-provider comparison** — 用多个 provider 跑同一场景，分析分歧率（后续）

## 10. References

- [LLM_PROVIDER_CONFIG.md](./LLM_PROVIDER_CONFIG.md) — Provider 配置完整文档
- [AGENT2HARNESS_MAIN_FLOW.md](./AGENT2HARNESS_MAIN_FLOW.md) — Core Flow 架构
- [examples/llm_providers.example.yaml](../examples/llm_providers.example.yaml) — 配置模板
