# Dogfood Record: Real LLM Infrastructure & Safety Gate Verification #001

> **Historical dogfood note (2026-05-14):** This is a historical dogfood record from 2026-05-12.
> CLIAgentAdapter has since been removed. The primary integration path is
> external runner → trace/log import. Real LLM judge remains explicit opt-in / non-default.
> **Update (2026-05-14):** The response parsing `bad_response` in Section 6.2 has been **fixed** —
> a normalization layer now handles 7 compatible provider response shapes.
> Both openai-compatible and anthropic-compatible providers verified via real LLM smoke test.

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
| **Semantic judge verdict** | **FIXED (2026-05-14)** — normalization layer now handles 7 provider response shapes. See follow-up smoke tests. |
| ReviewDecision auto-generated | **No** — confirmed by `REVIEW_DECISION_NOT_GENERATED.txt` |

**Key takeaway:** The real LLM transport, opt-in safety gates (--live, --confirm-i-have-real-key, --env-file), and factory wiring were all verified successfully. The semantic JudgeFinding was initially blocked by a response parsing mismatch (see Section 6.2), which was subsequently **fixed** — the normalization layer in `openai_transport.py` now handles 7 compatible provider response shapes. Follow-up smoke tests (2026-05-14) confirmed both openai-compatible and anthropic-compatible providers produce valid JudgeFinding output.

## 6. Issues Found

### 6.1 CLI log `model=` displayed empty (FIXED)

**Root cause:** `cli.py:1432` used `result.config.model` (static `LLMProviderConfig.model`, which is `""` when `model_env` is used).

**Fix:** Added `LLMJudgeProvider.model` property, changed CLI to use `result.provider.model`.

### 6.2 Provider response parsing: bad_response (FIXED 2026-05-14)

**Status:** The response parsing normalization layer (`_extract_content_text()` + `_extract_json_from_text()` + `_try_parse_judge_dict()` in `openai_transport.py`, plus `_extract_text_from_content_blocks()` in `anthropic_transport.py`) now handles 7 compatible provider response shapes. Both openai-compatible (glm-5) and anthropic-compatible (kimi-k2.5) verified via real LLM smoke test.

**Resolution:** Added a normalization layer that handles 7 compatible provider response shapes: str content, dict content, list content parts, markdown fenced JSON, embedded JSON objects, thinking blocks + text blocks, non-JSON fallback heuristic.

**Original impact:** The semantic JudgeFinding (passed/rationale/confidence from LLM) was NOT produced. RuleFindings (deterministic) were unaffected and passed normally. `EvaluationResult.passed` remained determined by RuleJudge, which is the correct behavior.

**Root cause:** Compatible providers returned response shapes (dict content, markdown-fenced JSON, content parts arrays, thinking blocks) that the original parser did not handle. Fixed by adding a normalization layer. See commit `79d7f29 fix: align LLM transports with provider response shapes`.

## 7. What Was Verified

**Successfully verified:**
- Real LLM transport infrastructure (HTTPS call, factory wiring, safety gates)
- Opt-in safety gates: --live / --confirm-i-have-real-key / --env-file
- SecretSource resolution: api_key / base_url / model all correctly resolved from .env
- RuleFinding + JudgeFinding coexistence in EvaluationResult
- ReviewDecision NOT auto-generated
- EvaluationResult.passed stays RuleJudge-determined

**Subsequently verified (2026-05-14):**
- Semantic judge verdict (passed/rationale/confidence from LLM) — verified via normalization layer fix
- Both openai-compatible (glm-5) and anthropic-compatible (kimi-k2.5) smoke tested and passing

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

## 9. Next Steps (post-fix)

1. ~~**Provider response parsing debug**~~ → **DONE** (2026-05-14): normalization layer in `openai_transport.py` + `anthropic_transport.py`
2. ~~**Re-dogfood after response parsing fix**~~ → **DONE** (2026-05-14): both openai-compatible (glm-5) and anthropic-compatible (kimi-k2.5) verified
3. **Native OpenAI / native Anthropic live smoke** — not yet run (deferred, not blocking v3.0.0)
4. **Multi-provider comparison** — 用多个 provider 跑同一场景，分析分歧率（后续）

## 10. References

- [LLM_PROVIDER_CONFIG.md](../LLM_PROVIDER_CONFIG.md) — Provider 配置完整文档
- [AGENT2HARNESS_MAIN_FLOW.md](../architecture/AGENT2HARNESS_MAIN_FLOW.md) — Core Flow 架构
- [examples/llm_providers.example.yaml](../../examples/llm_providers.example.yaml) — 配置模板
