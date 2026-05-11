# Project Integration — prototype level

当前支持 prototype-level 集成：用配置文件描述你的项目和工具，在本 Harness 中
跑 mock replay + rule checks。**不支持真实 Agent runtime 接入。**

## 最小集成步骤

### 1. 准备 project.yaml

```yaml
name: my_project
domain: code_search
description: 代码搜索与符号定位
evidence_sources:
  - tool_responses
  - transcript
domain_taxonomy:
  issue_categories:
    - wrong_tool
    - missing_tool
    - bad_params
  evidence_types:
    - tool_call
    - tool_response
    - final_answer
```

### 2. 准备 tools.yaml

为每个工具填写完整契约（见 [`CONFIGURATION.md`](CONFIGURATION.md) 的格式）。
重点字段：
- `when_to_use` / `when_not_to_use` — Agent 何时用/不用此工具
- `input_schema` — JSON Schema 风格参数定义
- `output_contract` — 输出必须包含的字段
- `side_effects` — read_only / destructive
- `executor` — 执行器类型和入口（当前仅 Python executor）

### 3. 准备 evals.yaml

为每个工具写至少一条 eval：

- `required_tools` — 预期工具调用顺序
- `forbidden_first_tool` — 第一步不应使用的工具
- `success_criteria` — 判定规则
- `verifiable_outcome.expected_root_cause` — 预期根因

### 4. 跑 mock replay

```bash
# 工具契约审计
python -m agent_tool_harness.cli audit-tools \
  --tools my_tools.yaml --out runs/audit

# mock replay — good 路径
python -m agent_tool_harness.cli run \
  --project my_project.yaml --tools my_tools.yaml \
  --evals my_evals.yaml --out runs/trial --mock-path good

# mock replay — bad 路径
python -m agent_tool_harness.cli run \
  --project my_project.yaml --tools my_tools.yaml \
  --evals my_evals.yaml --out runs/trial --mock-path bad
```

### 5. 读报告

`runs/trial/report.md` 包含 signal_quality 声明和方法论边界警告。

## 当前限制

- `run` 命令硬编码 `MockReplayAdapter`，不支持注入自定义 AgentAdapter。
- 仅支持 Python executor。MCP / HTTP / Shell executor 未实现。
- Judge 是 deterministic rule checks，不是 LLM 语义评分。
- PASS/FAIL 的 signal_quality = tautological_replay，不代表真实 Agent 能力。

## 从 bootstrap 开始（推荐新用户）

如果从零开始，用 `bootstrap` 扫描你的工具源码自动生成 draft：

```bash
python -m agent_tool_harness.cli bootstrap \
  --source my_tools_dir --out bootstrap_out
```

这会生成 `tools.draft.yaml` + `evals.draft.yaml` + fixtures + `REVIEW_CHECKLIST.md`。
人工审核后即可用于 mock replay。
