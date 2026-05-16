# Agent Tool Harness

[中文文档](README.md)

A local harness for importing, inspecting, evaluating, and reporting on Agent tool-use traces.

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
- **Advise** with optional LLM judge rubric — 6 advisory dimensions, never affects pass/fail
- **Report** with structured Markdown + JSON artifacts
- **Report Insight (v3.1)** — Scorecard, Metrics, Grouped Findings, Recommendations

All features are local, offline, zero-network by default.

## What it does not do

- **Does not run target agents** — you run your agent; harness imports and evaluates traces
- **Does not manage your API keys** — no .env loading by default
- **Does not call real LLMs by default** — real LLM judge requires explicit opt-in
- **Does not auto-fix tools** — no optimizer, no prompt repair
- **Does not auto-generate ReviewDecision** — human review is explicit and required

## Quickstart

```bash
git clone https://github.com/yaoziyaoguai/agent-tool-harness.git
cd agent-tool-harness
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# verify installation
python -m pytest tests/ -q
```

### Import a trace and evaluate

```bash
python -c "
from agent_tool_harness.trace_import import import_trace_as_evidence
from agent_tool_harness.core_evaluation import CoreEvaluation, EvalSpec

evidence = import_trace_as_evidence('examples/trace_import/native_trace.json')
trace = evidence.trace

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

print(f'Evaluation passed: {result.passed}')
for f in result.findings:
    print(f'  [{f.severity}] {f.message[:140]}')
"
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
| `native` | Your trace already matches the native Agent2Harness schema |
| `simple_mapping` | Your trace uses different field names — map them with `SimpleMappingConfig` |

## Evaluation model

| Layer | Decides `passed`? | Source | Description |
|-------|-------------------|--------|-------------|
| **RuleFinding** | **Yes** | Deterministic rules | 37+ rules across 5 inspectors |
| **JudgeFinding** | **No** (advisory) | LLM judge rubric (opt-in) | 6 advisory dimensions |
| **ReviewDecision** | **No** (human) | Human reviewer | Final accept/reject |

## Report Insight (v3.1)

v3.1 adds a report-level insight layer:

| Component | What it tells you |
|-----------|-------------------|
| **Scorecard** | Pass/fail at a glance, error/warning/advisory breakdown |
| **Metrics** | Tool call counts, success/error rates, response sizes |
| **Grouped Findings** | Findings bucketed by severity, category, and tool |
| **Recommendations** | Deduplicated, ranked, actionable fix suggestions |

All components are deterministic, zero-network, no LLM required.

## Task-Level Evaluation (v3.2)

v3.2 adds task-outcome evaluation on top of trace-level inspection:

| Component | What it tells you |
|-----------|-------------------|
| **EvalCase** | Declarative schema for expected task outcomes |
| **6 Verifiers** | fact, field, pattern, tool_call, no_tool_call, llm (advisory) |
| **TaskOutcome** | success / failed / inconclusive per-task verdict |
| **Report Integration** | Task Outcome section optionally rendered in main report |

All verifiers except `llm` are deterministic, zero-network.

## Eval Suite Aggregation (v3.3)

v3.3 adds multi-case, multi-trace suite-level aggregation:

| Component | What it tells you |
|-----------|-------------------|
| **EvalSuite manifest** | YAML-driven multi-case/multi-trace orchestration |
| **SuiteEvaluator** | Per-case evaluation orchestration |
| **SuiteResult** | task_success_rate, deterministic_pass_rate, aggregated metrics |
| **SuiteScorecard** | Suite-level pass/fail + top failing categories/tools |
| **SuiteMetrics** | Cross-case metrics (mean tool calls, error rate, findings/case) |
| **Suite Report** | Markdown + JSON dual-format aggregated output |

All components deterministic, zero-network.

## Regression Comparison (v3.4)

v3.4 adds baseline-vs-candidate regression detection:

| Component | What it tells you |
|-----------|-------------------|
| **MetricDiff** | Per-metric before/after comparison with direction (better/worse/neutral) |
| **FindingDiff** | Finding count changes by category, tracking new and resolved rule_ids |
| **TaskOutcomeDiff** | Per-case status transitions (new_failure, new_success, etc.) |
| **SuiteDiff** | Suite-level task success rate and deterministic pass rate deltas |
| **RegressionWarning** | 5 auto-detected warning types: new_task_failures, error_rate_spike, finding_explosion, new_tool_errors, task_success_drop |
| **RegressionReport** | Complete Markdown/JSON regression comparison output |

All thresholds configurable. `is_regression` is advisory — does not auto-block CI (RFC Decision 1).
All components deterministic, zero-network.

## Documentation

- [QUICKSTART](docs/QUICKSTART.md) — shortest path to first run
- [USER_GUIDE](docs/USER_GUIDE.md) — full usage guide
- [REPORT_GUIDE](docs/REPORT_GUIDE.md) — how to read v3.1 reports
- [PROVIDER_CONFIG](docs/PROVIDER_CONFIG.md) — real LLM judge opt-in config
- [DEVELOPER_GUIDE](docs/DEVELOPER_GUIDE.md) — architecture, RFCs, contributing
- [INDEX](docs/INDEX.md) — complete doc index

## Design lineage

This project aligns with Anthropic Engineering's [Writing effective tools for agents — with agents](https://www.anthropic.com/engineering/writing-tools-for-agents) methodology.
