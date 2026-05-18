# Changelog

## v3.6.1 (2026-05-18)

Patch release for post-v3.6 architecture quality work.

- **Changed** Routed Anthropic-compatible provider config through explicit `SecretSource` / explicit opt-in env paths.
- **Changed** Added `ReportSection` contract and unified report composition path for v3.1-v3.6 sections.
- **Changed** Slimmed Markdown report rendering responsibilities by moving Core Flow rendering into a focused renderer.
- **Changed** Clarified post-v3.6 version strategy and release documentation.
- **Changed** Polished report architecture after independent review: priority constants, render-once section composition, deprecated static wrapper path, explicit timeout configuration, and thinner `core_report_bridge.py`.
- **Added** Multi-section report integration tests.

## v3.6.0 (2026-05-17)

- **Added** ToolPortfolioReview — 5 structural checks across tool portfolios (namespacing consistency, overlapping tools, shallow wrappers, missing higher-level tools, resource grouping).
- **Added** ToolImprovementBrief + EvidenceRef — per-tool and cross-tool improvement briefs with evidence references from v3.1-v3.5 findings, metrics, task outcomes, and transcript signals.
- **Added** EvidenceCollector + ToolImprovementBriefGenerator — deterministic generation of improvement briefs from accumulated signals.
- **Added** Portfolio review Markdown/JSON report rendering, integrated into main report path.
- **Changed** 59 new tests (3 test files), total 1764 passed / 1 xfailed.

## v3.5.0 (2026-05-16)

- **Added** TranscriptPatternAnalyzer — 6 agent confusion pattern detectors (repeated retry loops, tool switching confusion, arg micro-tuning, no recovery, unsupported final answers, broad search escalation).
- **Added** ContextEfficiencyAnalyzer — 5 context waste signal detectors (response bloat, missing pagination, missing concise mode, low-value large fields, truncation without hint).
- **Added** transcript_primitives — 8 sequence analysis primitives (normalize_args, args_similarity, sliding_window, consecutive_groups, count_tool_switches, find_repeated_sequences, is_truncated, extract_fields_usage).
- **Added** Analysis report Markdown/JSON rendering with recommendation catalog.
- **Changed** 96 new tests, total 1705 passed / 1 xfailed.

## v3.4.0 (2026-05-16)

- **Added** RegressionComparison — baseline vs candidate comparison across metrics, findings, task outcomes, and suite results.
- **Added** 5 auto-detected regression warnings: new_task_failures, error_rate_spike, finding_explosion, new_tool_errors, task_success_drop.
- **Added** Configurable thresholds for all regression warnings. is_regression is advisory — does not auto-block CI.
- **Added** Regression report Markdown/JSON rendering.
- **Changed** 104 new tests, total 1609 passed / 1 xfailed.

## v3.3.1 (2026-05-15)

- **Fixed** Integrated TaskOutcome and SuiteResult sections into the standard report path.
- **Fixed** v3.2/v3.3 audit findings around report rendering, docs, examples, and compatibility.
- **Fixed** Preserved external-runner boundary — did not add an Agent runner or LLM dependency.

## v3.3.0 (2026-05-14)

- **Added** EvalSuite manifest — YAML-driven multi-case, multi-trace orchestration.
- **Added** SuiteEvaluator + SuiteResult — per-case evaluation aggregation with task_success_rate, deterministic_pass_rate.
- **Added** SuiteScorecard + SuiteMetrics — suite-level pass/fail, top failing categories/tools, cross-case metrics.
- **Added** Suite report Markdown/JSON rendering.
- **Added** EvalSuite schema + YAML loader + validation.
- **Added** CaseResult / SuiteMetrics / SuiteScorecard / SuiteResult data structures.

## v3.2.0 (2026-05-13)

- **Added** EvalCase / ExpectedOutcome — declarative task-level evaluation schema.
- **Added** 6 verifiers — fact, field, pattern, tool_call, no_tool_call, llm (advisory), plus CompositeVerifier.
- **Added** TaskOutcome / TaskEvaluator — success/failed/inconclusive task verdicts.
- **Added** Task outcome Markdown section + JSON serialization.

## v3.1.1 (2026-05-12)

- **Added** Report Insight layer — Scorecard, Metrics, Grouped Findings, Recommendations.
- **Added** MetricsCollector — 15 aggregated metrics from ExecutionTrace + EvaluationResult.
- **Added** FindingGrouper — 4-dimensional finding bucketing.
- **Added** RecommendationCatalog — deduplicated, ranked actionable fix suggestions.
- **Added** Markdown report with 6 insight sections, JSON report with 8 top-level keys.
- **Added** CLI bootstrap / scaffold / validate-generated commands.

## v3.1.0 (2026-04-30)

- **Added** ReportMetrics + MetricsCollector.
- **Added** FindingGrouper + GroupedFindings.
- **Added** ReportScorecard.
- **Added** Recommendation + RecommendationCatalog.
- **Added** ReportInsight aggregate root + from_eval() factory.

## v3.0.0 (2026-04-27)

- Initial platform release.
- **Added** Trace import (native + simple_mapping).
- **Added** CoreEvaluation with deterministic inspectors (37+ rules).
- **Added** CLI (14 subcommands).
- **Added** Mock replay execution pipeline.
- **Added** Tool design audit, eval quality audit.
- **Added** Markdown/JSON report output.
