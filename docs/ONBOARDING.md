# Onboarding Guide

agent-tool-harness 的最小上手路径。

## 30 秒定位

agent-tool-harness **不运行**你的 Agent。它导入你的 Agent 产生的 tool-use trace，然后做确定性评测。

## 推荐接入路径

### 路径 A：Trace Import（主要路径）

你的外部 runner 产生 trace JSON → harness 导入并评测。

详见 [External Runner Workflow](EXTERNAL_RUNNER_WORKFLOW.md) 和 [Trace Import Adapter Spec](TRACE_IMPORT_ADAPTER_SPEC.md)。

### 路径 B：Mock Replay（demo / 了解工具）

不需要真实 Agent runtime。从 bootstrap 开始生成 draft 配置，跑 mock replay。

```bash
# 1. 从源码 scaffold
python -m agent_tool_harness.cli bootstrap --source my_tools_dir --out bootstrap_out

# 2. 审核 draft 后跑 mock replay
python -m agent_tool_harness.cli run \
  --project my_project.yaml --tools my_tools.yaml --evals my_evals.yaml \
  --out runs/trial --mock-path good
```

详见 [Project Integration](PROJECT_INTEGRATION.md)。

## 命令行速查

| 命令 | 用途 |
|------|------|
| `bootstrap` | 从 Python 源码 AST 扫描自动生成 draft tools.yaml + evals.yaml |
| `scaffold-tools` | 从 AST 生成 tools.draft.yaml |
| `scaffold-evals` | 从 AST 生成 evals.draft.yaml |
| `audit-tools` | 工具契约确定性审计 |
| `audit-evals` | eval 质量确定性审计 |
| `audit-judge-prompts` | judge prompt 启发式安全审计 |
| `run` | 跑 mock replay（--mock-path good/bad） |
| `run --core-flow --judge-provider llm` | 真实 LLM judge 路径（需 triple opt-in） |
| `judge-provider-preflight` | 静态配置校验（不调网络、不读 env 文件内容） |
| `generate-evals` | 从 tools + tests 自动生成候选 eval |
| `promote-evals` | 把 review 通过的候选搬运成正式 evals.yaml |
| `analyze-artifacts` | 离线 trace-derived 信号复盘 |
| `replay-run` | 从已有 artifacts 回放 mock trace |
| `scaffold-fixtures` | 从 AST 生成 mock fixtures |
| `validate-generated` | 校验候选 eval 的质量和一致性 |

完整 CLI 参考见 [CLI Usage](CLI_USAGE.md)。

## 常见问题

### 我需要真实 LLM 来评测吗？

不需要。RuleFinding（决定 pass/fail）是完全确定性的，零网络依赖。

JudgeFinding（advisory）可选使用真实 LLM，需要 triple opt-in（`--live --confirm-i-have-real-key --env-file`）。默认不走真实 LLM。

### 我如何接入自己的 Agent？

把你的 Agent 的 tool-use trace 导出为 JSON，通过 TraceImportAdapter (`native` 或 `simple_mapping` 模式) 导入。详见 [External Runner Workflow](EXTERNAL_RUNNER_WORKFLOW.md)。

### 我不确定场景是否合适

看 [START_HERE.md](START_HERE.md) 做 fit check。
