# Agent Tool Harness

[中文文档](README.md)

**An offline evaluation and reporting tool for Agent tool-use quality.**

It consumes existing traces, JSON logs, and eval results. It does not run your agent, does not call real LLMs by default, and does not auto-modify tools.

> Latest stable release: `v3.6.1`. This is a post-v3.6 architecture quality patch, not a new Agent runner, real LLM integration, or v3.7 feature release.

## What problems it solves

| Your question | Capability |
|---------------|------------|
| Is my agent using tools correctly? | v3.1 Deterministic checks + report insight |
| Did the task actually succeed? | v3.2 Task-level evaluation |
| How does the full eval suite look? | v3.3 Suite aggregation |
| Did my tool spec change cause regressions? | v3.4 Regression comparison |
| Why does my agent retry endlessly? Is tool output bloated? | v3.5 Transcript + context analysis |
| Are there structural issues in my tool portfolio? | v3.6 Portfolio review + improvement brief |

## Capability chain

```
trace / JSON log
  → v3.1 import + deterministic checks (37+ rules) + report insight
    → v3.2 task-level evaluation (TaskOutcome: success/failed/inconclusive)
      → v3.3 suite aggregation (task_success_rate + top issues)
        → v3.4 regression comparison (baseline vs candidate)
        → v3.5 transcript confusion + context efficiency (11 patterns)
        → v3.6 portfolio review + improvement brief (5 checks + evidence brief)
```

## Core flow

```
Your agent / script / CI
  → produces tool-use trace / JSON log
    → agent-tool-harness imports
      → deterministic checks + evaluation
        → Markdown / JSON report
```

## Capabilities

### v3.1 Report Insight

- **Scorecard** — pass/fail at a glance
- **Metrics** — tool calls, success/error rates, response sizes
- **Grouped Findings** — by severity, category, and tool
- **Recommendations** — deduplicated, ranked, actionable suggestions
- Markdown + JSON output

### v3.2 Task-Level Evaluation

- **EvalCase / ExpectedOutcome** — declarative expected task outcomes
- **6 verifiers** — fact, field, pattern, tool_call, no_tool_call, llm (advisory)
- **TaskOutcome** — success / failed / inconclusive verdict

### v3.3 Eval Suite Aggregation

- **EvalSuite manifest** — YAML-driven multi-case, multi-trace orchestration
- **SuiteScorecard** — suite-level pass/fail + task success rate
- **SuiteMetrics** — cross-case aggregated metrics

### v3.4 Regression Comparison

- baseline vs candidate comparison across metrics, findings, task outcomes, and suites
- 5 auto-detected regression warnings, configurable thresholds
- consumes existing eval results only, never re-runs agents

### v3.5 Transcript + Context Analysis

- **6 agent confusion patterns** — repeated retries, tool switching, arg micro-tuning, no recovery, unsupported answers, broad search escalation
- **5 context waste signals** — response bloat, missing pagination, low-value large fields, truncation without hint, etc.
- All analysis deterministic, no LLM required

### v3.6 Portfolio Review + Improvement Brief

- **5 structural checks** — namespacing consistency, overlapping tools, shallow wrappers, missing higher-level tools, resource grouping
- **Improvement Brief** — per-tool + cross-tool improvement cards with evidence from v3.1-v3.5
- Does not auto-modify ToolSpec

### Infrastructure

- **Trace import** — native JSON + simple_mapping field mapping + diagnostics
- **Deterministic checks** — 37+ rules, zero network dependency, decides pass/fail
- **CLI audit** — `audit-tools`, `audit-evals`, `audit-judge-prompts`
- **LLM judge (optional)** — 6 advisory dimensions, disabled by default, requires explicit triple opt-in

## What it does not do

- **Does not run your agent** — you run your agent; harness imports and evaluates traces
- **Does not call real LLMs by default** — deterministic rules decide pass/fail
- **Does not auto-fix tools** — recommendations and improvement briefs are suggestions, not automatic patches
- **Is not an LLM eval benchmark** — does not replace human judgment

## Safety boundaries

- Does not run target agents
- Does not call real LLMs by default
- Does not read .env (unless explicitly opted in)
- Does not auto-modify tool specs
- Signal quality is explicitly declared (mock replay = `tautological_replay`, not a real agent signal)

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

No .env, no API key, no network required:

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

### Mock replay demo

```bash
# 1) Audit tool contracts
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out /tmp/harness-demo/audit

# 2) Mock replay — good path
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out /tmp/harness-demo/good --mock-path good

# 3) View report
cat /tmp/harness-demo/good/report.md
```

## When to use the real LLM judge

Not required by default. Deterministic RuleFinding is sufficient to decide pass/fail. The real LLM judge is optional and advisory-only.

```bash
# Enable real LLM judge (requires explicit triple opt-in)
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out /tmp/harness-demo/llm-judge \
  --core-flow --judge-provider llm \
  --llm-config examples/llm_providers.example.yaml \
  --llm-provider openai-compatible \
  --env-file .env --live --confirm-i-have-real-key
```

## Documentation

| I want to... | Read |
|-------------|------|
| Get started in 5 minutes | [QUICKSTART](docs/QUICKSTART.md) |
| Full usage guide | [USER_GUIDE](docs/USER_GUIDE.md) |
| Understand reports | [REPORT_GUIDE](docs/REPORT_GUIDE.md) |
| Browse all examples | [examples/README.md](examples/README.md) |
| Configure LLM judge (optional) | [PROVIDER_CONFIG](docs/PROVIDER_CONFIG.md) |
| Architecture / contributing | [DEVELOPER_GUIDE](docs/DEVELOPER_GUIDE.md) |
| Current implementation status | [CURRENT_IMPLEMENTATION](docs/CURRENT_IMPLEMENTATION.md) |
| Complete doc index | [INDEX](docs/INDEX.md) |
| Chinese docs | [README.md](README.md) |

## Design lineage

This project aligns with Anthropic Engineering's [Writing effective tools for agents — with agents](https://www.anthropic.com/engineering/writing-tools-for-agents) methodology, focusing on tool-use inspection — checking, evaluating, and reporting on agent tool-use logs and tool design quality.
