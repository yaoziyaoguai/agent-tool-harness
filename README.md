# Agent Tool Harness

Agent Tool Harness 是一个 **Agent 工具检查、评估集生成与工具使用评估框架**。

它不是普通单测框架，也不是只验证函数能不能跑。它关注的是：工具作为确定性系统和非确定性 Agent 之间的契约，是否足够适合 Agent 使用；eval 是否真实、多步、可验证；Agent 在运行时是否真的按正确证据链调用工具。

本项目吸收 Anthropic Engineering 的工具设计方法论：[Writing effective tools for AI agents—using AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)。MVP 对应五类工具设计原则：

- Choosing the right tools for agents
- Namespacing your tools
- Returning meaningful context from tools
- Optimizing tool responses for token efficiency
- Prompt-engineering tool descriptions and specs

## 快速开始

```bash
python -m pytest -q

python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out runs/audit-tools

python -m agent_tool_harness.cli audit-evals \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/audit-evals

python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-good \
  --mock-path good

python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo-bad \
  --mock-path bad
```

## 为什么不是普通单测

普通单测通常验证“函数输入 X 是否输出 Y”。Agent tool-use eval 还必须回答：

- Agent 第一步是否选对工具；
- 参数是否来自真实上下文；
- 工具返回了什么 evidence；
- Agent 是否缺少关键工具调用；
- 最终结论是否引用证据；
- judge 规则失败在哪里；
- 失败应归因于工具设计、eval 设计、Agent 路径还是证据处理。

因此每次 run 都生成 raw artifacts，而不是只看最终回答。

## 当前阶段边界

当前代码库仍处于 MVP/治理强化阶段。它只提供可复现的 mock replay 闭环，不接真实模型。

当前不实现真实 OpenAI/Anthropic adapter、MCP/HTTP/Shell executor、Web UI、自动 patch、复杂 LLM Judge、并发执行或大规模 benchmark。这些方向记录在 Roadmap 中，进入实现前需要单独 review。

当前 mock replay 已从 `evals.yaml` 和 `tools.yaml` 推导工具路径，不要求用户项目复用
`examples/runtime_debug` 的工具名；但它仍然只是 deterministic replay，不代表真实模型能力。

## 配置文件

`project.yaml` 描述用户项目：

- `project.name`
- `project.domain`
- `project.description`
- `evidence_sources`
- `domain_taxonomy.issue_categories`
- `domain_taxonomy.evidence_types`

`tools.yaml` 描述工具契约和执行方式：

- `name`
- `namespace`
- `version`
- `description`
- `when_to_use`
- `when_not_to_use`
- `input_schema`
- `output_contract`
- `token_policy`
- `side_effects`
- `executor`

`evals.yaml` 描述 eval case：

- `id`
- `name`
- `category`
- `split`
- `realism_level`
- `complexity`
- `source`
- `user_prompt`
- `initial_context`
- `verifiable_outcome`
- `success_criteria`
- `expected_tool_behavior`
- `judge`

## CLI 用法

审计工具：

```bash
python -m agent_tool_harness.cli audit-tools \
  --tools examples/runtime_debug/tools.yaml \
  --out runs/audit-tools
```

从工具生成 eval 候选：

```bash
python -m agent_tool_harness.cli generate-evals \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --source tools \
  --out runs/generated/eval_candidates.from_tools.yaml
```

从测试生成 eval 候选：

```bash
python -m agent_tool_harness.cli generate-evals \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --source tests \
  --tests tests/ \
  --out runs/generated/eval_candidates.from_tests.yaml
```

审计 eval：

```bash
python -m agent_tool_harness.cli audit-evals \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/audit-evals
```

运行 good/bad replay：

```bash
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/runtime_debug/evals.yaml \
  --out runs/demo \
  --mock-path good
```

## Artifacts

每次 `run` 都会生成：

- `transcript.jsonl`
- `tool_calls.jsonl`
- `tool_responses.jsonl`
- `metrics.json`
- `audit_tools.json`
- `audit_evals.json`
- `judge_results.json`
- `diagnosis.json`
- `report.md`

这些文件用于复盘 Agent 的真实事件链路。失败时先看 `tool_calls.jsonl` 和 `tool_responses.jsonl`，再看 `judge_results.json` 与 `diagnosis.json`。

## 如何写自己的 tools.yaml

工具描述应该像教新同事，而不是像给另一个函数写 API 注释。一个合格工具应说明：

- 它适合解决什么真实工作流；
- 什么时候不要用；
- 输入参数的业务语义；
- 输出里的 summary、evidence、next_action、technical_id；
- token 策略，如 pagination/filter/range/max_output_tokens；
- 副作用，如 destructive/open_world_access；
- executor 类型和入口。

## 如何写自己的 evals.yaml

一个强 eval 应该：

- 像真实用户问题，不泄露工具名；
- 需要多步工具调用；
- 有 initial_context 或 fixture；
- 有 verifiable_outcome；
- 允许合理替代路径，避免过拟合唯一调用顺序；
- 用 judge 规则检查 transcript 和 tool calls。

## 生成 eval 候选

`from_tools` 会根据工具契约生成候选 eval，但不会覆盖正式 `evals.yaml`。缺少 fixture 或 expected_root_cause 时会标记 `runnable: false`。

`from_tests` 会扫描 pytest 测试函数名、docstring、xfail reason 和 regression 命名线索。静态扫描无法构造 initial_context 时，也会标记 `runnable: false`。

## 如何理解报告

`report.md` 包含五个核心部分：

- Tool Design Audit：工具契约是否适合 Agent；
- Eval Quality Audit：eval 是否真实、多步、可验证；
- Agent Tool-Use Eval：运行了多少 eval、通过多少；
- Transcript-derived Diagnosis：从调用链路解释失败；
- Improvement Suggestions：下一步改工具、eval 或 adapter 的建议。
