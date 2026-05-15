# Agent Tool Harness

[中文文档](README.zh-CN.md)

A local harness for importing, inspecting, evaluating, and reporting Agent tool-use traces.

**agent-tool-harness does not run your agent.**
It evaluates tool-use traces produced by your own agent runner, script, CI, or logs.

## What it does

- **Import** native Agent2Harness trace JSON or custom JSON via simple field mapping
- **Diagnose** trace quality — field coverage, type checks, confidence assessment, mapping dry-run
- **Inspect** tool-use correctness — call_id uniqueness, call/result pairing, argument validity, orphan detection (9 rules)
- **Inspect** tool spec quality — description completeness, input_schema presence, parameter docs, output contract (10 rules)
- **Inspect** tool ergonomics — naming clarity, namespace overlap, wrapper detection, action-resource patterns (6 rules)
- **Inspect** tool response quality — output presence, error actionability, signal strength, context sufficiency (6 rules)
- **Evaluate** with deterministic RuleFinding that decides pass/fail — no LLM required
- **Advise** with fake-testable LLM judge rubric — 6 advisory dimensions, never affects pass/fail
- **Report** findings as structured JSON artifacts and Markdown summaries
- **Audit** tool design (`audit-tools`), eval quality (`audit-evals`), and judge prompts (`audit-judge-prompts`) with deterministic heuristics
- **Generate** candidate evals from tools and tests (`generate-evals`), then promote reviewed candidates to formal evals (`promote-evals`)
- **Scaffold** draft tools.yaml, evals.yaml, and fixtures from Python source via AST scan (`bootstrap`, `scaffold-tools`, `scaffold-evals`)

All features are local, offline, zero-network by default.

## What it does not do

- **Does not run target agents** — you run your agent; harness imports and evaluates traces
- **Does not manage your API keys** — no .env loading by default, no key storage, no secret management
- **Does not call real LLMs by default** — real LLM judge requires explicit triple opt-in
  (`--live --confirm-i-have-real-key --env-file`)
- **Does not auto-fix tools** — no optimizer, no prompt repair, no automatic tool modification
- **Does not auto-generate ReviewDecision** — human review is explicit and required
- **Does not provide batch / multi-trace evaluation**
- **Does not provide review UI**
- **Does not include CLIAgentAdapter** — built-in agent runner has been removed

## Quickstart

### Install

```bash
git clone https://github.com/yaoziyaoguai/agent-tool-harness.git
cd agent-tool-harness
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# verify installation
python -m pytest tests/ -q
```

### Import a trace and evaluate

The primary workflow: your external runner produces a trace → harness imports and evaluates.

```bash
python -c "
from agent_tool_harness.trace_import import import_trace_as_evidence
from agent_tool_harness.core_evaluation import CoreEvaluation, EvalSpec

# 1. Import a native-schema trace
evidence = import_trace_as_evidence('examples/trace_import/native_trace.json')
trace = evidence.trace
print(f'Imported: scenario={trace.scenario_id}')
print(f'  tool_calls={len(trace.tool_calls)} tool_results={len(trace.tool_results)}')
print(f'  signal_quality={evidence.signal_quality}')

# 2. Run deterministic tool-use inspection (no LLM required)
eval_spec = EvalSpec(
    id=trace.scenario_id, name=trace.scenario_id,
    category='knowledge_search', split='dev', realism_level='recorded',
    complexity='simple', source='external_runner',
    user_prompt='Find root cause and recommendation',
    initial_context={}, verifiable_outcome={},
    success_criteria=['identify root cause', 'provide recommendation'],
    expected_tool_behavior={}, judge={},
)
result = CoreEvaluation().evaluate(evidence, eval_spec)

# 3. Inspect deterministic findings
print(f'Evaluation passed: {result.passed}')
print(f'Findings: {len(result.findings)} (severity: high→ERROR, medium→WARNING, info→advisory)')
for f in result.findings:
    print(f'  [{f.severity}] {f.message[:140]}')
"
```

This minimal snippet runs 9 deterministic tool-use correctness checks (D2: call_id uniqueness,
call/result pairing, argument validity, orphan detection) plus RuleJudge — **zero network,
zero API key, zero .env**. `passed` is determined by deterministic RuleFinding only;
JudgeFinding and ReviewDecision are advisory/human only.

`passed` may be `False` when the eval_spec has no ``judge.rules`` configured, which is
expected for a bare import without custom rules. Full v3.1.0 evaluation also supports
D4 (tool ergonomics), D5 (response quality), and D6 (tool spec quality) inspectors,
which can be enabled by passing their instances to the ``CoreEvaluation`` constructor.

### Run a mock replay demo (CLI)

The CLI demo uses pre-scripted good/bad branches to show the audit → run → report loop.
It does not evaluate real agent behavior (`signal_quality: tautological_replay`).

```bash
# audit tool contracts
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out /tmp/harness-demo/audit

# mock replay — good path (expected PASS)
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out /tmp/harness-demo/good --mock-path good

# mock replay — bad path (expected FAIL)
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out /tmp/harness-demo/bad --mock-path bad

# read the report
cat /tmp/harness-demo/good/report.md
```

## Input model

```
Your agent runner / script / CI
  → produces tool-use trace/log (JSON)
    → TraceImportAdapter imports trace
      → CoreEvaluation evaluates tool use
        → Report (Markdown + JSON artifacts)
          → Human Review
```

Two import modes:

| Mode | When to use |
|------|-------------|
| `native` | Your trace already matches the [native Agent2Harness schema](docs/TRACE_IMPORT_ADAPTER_SPEC.md) |
| `simple_mapping` | Your trace uses different field names — map them with `SimpleMappingConfig` |

If your trace is JSONL, stdout, or CSV, write a small conversion script to produce native-schema JSON first.
See [External Runner Workflow](docs/EXTERNAL_RUNNER_WORKFLOW.md) for guidance.

## Example trace

A minimal native-schema trace ([`examples/trace_import/native_trace.json`](examples/trace_import/native_trace.json)):

```json
{
  "scenario_id": "knowledge_search_regression",
  "tool_calls": [
    {
      "call_id": "call-1",
      "tool_name": "kb.search.search_articles",
      "arguments": {"query": "SSO session loss after password reset", "limit": 5}
    }
  ],
  "tool_results": [
    {
      "call_id": "call-1",
      "tool_name": "kb.search.search_articles",
      "status": "success",
      "output": {"articles": [{"id": "kb-0042", "title": "SSO Session Loss: Root Cause Analysis"}]},
      "error": null
    }
  ],
  "final_answer": "Root cause: race condition in SSO session storage layer...",
  "messages": [],
  "observations": []
}
```

## Evaluation model

agent-tool-harness separates findings into three layers with clear boundaries:

| Layer | Decides `passed`? | Source | Description |
|-------|-------------------|--------|-------------|
| **RuleFinding** | **Yes** | Deterministic rules | call_id uniqueness, call/result pairing, argument presence, spec completeness — 37+ rules across 5 inspectors |
| **JudgeFinding** | **No** (advisory only) | LLM judge rubric (opt-in) | tool choice reasonableness, ergonomics, response quality — 6 advisory dimensions |
| **ReviewDecision** | **No** (human only) | Human reviewer | Final accept/reject after reviewing all evidence |

Key properties:
- `EvaluationResult.passed` comes from deterministic RuleFinding only.
- JudgeFinding is always advisory (`severity: "info"`) and never changes the pass/fail outcome.
- ReviewDecision is never auto-generated — a human must create it explicitly.

See [Agent2Harness Main Flow](docs/AGENT2HARNESS_MAIN_FLOW.md) for the full architecture.

## Report Insight in v3.1

v3.1 adds a **report-level insight layer** on top of v3.0's deterministic inspection. Instead of a flat list of findings, you get a structured, skimmable evaluation report:

| Component | What it tells you |
|-----------|-------------------|
| **Scorecard** | Pass/fail at a glance, plus error/warning/advisory breakdown |
| **Metrics** | Tool call counts, success/error rates, response sizes, orphan detection |
| **Grouped Findings** | Findings bucketed by severity, category, and affected tool — spot patterns instantly |
| **Recommendations** | Deduplicated, ranked, actionable fix suggestions with "what / why / how to fix" |

All components are **deterministic, zero-network, no LLM required**. They enrich both the
Markdown report (`report.md`) and the JSON artifact output automatically — no extra flags needed.

### Example: what the report looks like

```
## Scorecard
| Field | Value |
|-------|-------|
| Passed | FAIL |
| Errors | 2 |
| Warnings | 4 |

## Metrics
Tool calls: 5 | Success rate: 60% | Error rate: 40%

## Top Issues
1. [critical] 缺少 arguments — tool: search (2 occurrences)
2. [high] 输出信号过低 — tool: read (1 occurrence)

## Recommendations
1. search: 确保每次调用都传入必需的 arguments 参数
2. read: 检查工具返回的 output 是否包含足够上下文
```

See [`docs/sdd/SDD_EVALUATION_REPORT_INSIGHT_V3_1.md`](docs/sdd/SDD_EVALUATION_REPORT_INSIGHT_V3_1.md) for the full design.

## v3.1.0 scope

### Includes

- [x] External runner → trace/log import as the primary integration path
- [x] Native trace import + simple field mapping import
- [x] Trace diagnostics — field coverage, type checks, confidence assessment, mapping dry-run
- [x] Tool-use correctness checks — 9 deterministic rules
- [x] Tool spec quality checks — 10 deterministic rules
- [x] Tool ergonomics deterministic hints — 6 rules
- [x] Tool response quality deterministic hints — 6 rules
- [x] Fake-testable LLM judge rubric framework — 6 advisory dimensions
- [x] Markdown report + structured JSON artifacts
- [x] RuleFinding determines deterministic passed
- [x] JudgeFinding advisory only, ReviewDecision human explicit only
- [x] 14 CLI subcommands — audit, scaffold, replay, bootstrap, preflight, and more
- [x] **Report Insight** — Scorecard, Metrics, Grouped Findings, Recommendations (Markdown + JSON)
- [x] **MetricsCollector** — 15 aggregate metrics from ExecutionTrace + EvaluationResult
- [x] **FindingGrouper** — findings bucketed by severity, category, tool, rule prefix
- [x] **RecommendationCatalog** — deduplicated, ranked, actionable fix suggestions

v3.1.0 focuses on single-trace inspection and evaluation with structured insight reporting.
Additional capabilities (batch/multi-trace, richer review workflows, remaining D2 rules) may be
considered in future releases. See [`docs/ROADMAP.md`](docs/ROADMAP.md) for long-range planning.

## Documentation

| Category | Document | Covers |
|----------|----------|--------|
| **Getting started** | [`docs/START_HERE.md`](docs/START_HERE.md) | 30-second fit check |
| | [`docs/ONBOARDING.md`](docs/ONBOARDING.md) | Minimum onboarding path & command cheat-sheet |
| | [`examples/trace_import/README.md`](examples/trace_import/README.md) | Trace import examples |
| **User guides** | [`docs/EXTERNAL_RUNNER_WORKFLOW.md`](docs/EXTERNAL_RUNNER_WORKFLOW.md) | External runner → trace import workflow |
| | [`docs/TRACE_IMPORT_ADAPTER_SPEC.md`](docs/TRACE_IMPORT_ADAPTER_SPEC.md) | Trace import spec (native + simple mapping) |
| | [`docs/CLI_USAGE.md`](docs/CLI_USAGE.md) | Full CLI command reference |
| | [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) | YAML config file formats |
| | [`docs/PROJECT_INTEGRATION.md`](docs/PROJECT_INTEGRATION.md) | Integrating your project |
| | [`docs/LLM_PROVIDER_CONFIG.md`](docs/LLM_PROVIDER_CONFIG.md) | Real LLM judge opt-in config |
| **Reference** | [`docs/ARTIFACTS.md`](docs/ARTIFACTS.md) | Artifact schema reference & versioning policy |
| **Architecture** | [`docs/AGENT2HARNESS_MAIN_FLOW.md`](docs/AGENT2HARNESS_MAIN_FLOW.md) | Core flow: Trace → Evidence → Evaluation → Report |
| | [`docs/TOOL_USE_INSPECTION_SDD.md`](docs/TOOL_USE_INSPECTION_SDD.md) | Tool-use inspection design |
| | [`docs/CURRENT_IMPLEMENTATION.md`](docs/CURRENT_IMPLEMENTATION.md) | Honest capability matrix |
| | [`docs/HEADLESS_HARNESS_MODEL.md`](docs/HEADLESS_HARNESS_MODEL.md) | Harness execution model |
| | [`docs/DEMO_CORE_REAL_BOUNDARY.md`](docs/DEMO_CORE_REAL_BOUNDARY.md) | Demo / Core / Real layer boundaries |
| **Planning** | [`docs/ROADMAP.md`](docs/ROADMAP.md) | Full roadmap (Tracks A–D) |
| | [`docs/BACKLOG.md`](docs/BACKLOG.md) | Detailed backlog |
| **Historical** | [`docs/DOGFOOD_REAL_LLM_001.md`](docs/DOGFOOD_REAL_LLM_001.md) | Historical dogfood record (2026-05-12) |
| | [`docs/DOGFOODING.md`](docs/DOGFOODING.md) | Dogfooding policy |
| | [`docs/REAL_AGENT_INTEGRATION_SDD.md`](docs/REAL_AGENT_INTEGRATION_SDD.md) | Historical architecture note |

## Roadmap

| Phase | Content |
|-------|---------|
| **v3.1.0 (current)** | Report Insight — Scorecard, Metrics, Grouped Findings, Recommendations in Markdown + JSON |
| **v3.0.0** | TraceImportAdapter + D1/D2/D4/D5/D6 tool-use inspection + Phase 2 LLM judge rubric framework |
| **Future** | Real LLM rubric execution, remaining D2 rules, batch/multi-trace, review workflows |

For the full roadmap, see [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Design lineage

This project aligns with Anthropic Engineering's [Writing effective tools for agents — with agents](https://www.anthropic.com/engineering/writing-tools-for-agents) methodology. The core focus is **tool-use inspection** — checking, evaluating, and reporting on Agent tool-use logs and tool design quality.
