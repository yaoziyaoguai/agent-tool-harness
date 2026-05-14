# CLI Usage

所有命令通过 `python -m agent_tool_harness.cli <subcommand>` 调用。

## 子命令一览

### 审计

```bash
# 工具契约审计（字段齐全性 + 命名 + 边界关键词启发式）
python -m agent_tool_harness.cli audit-tools \
  --tools <tools.yaml> --out <dir>

# eval 质量审计
python -m agent_tool_harness.cli audit-evals \
  --evals <evals.yaml> --out <dir>

# judge prompt 安全审计
python -m agent_tool_harness.cli audit-judge-prompts \
  --prompts <prompts.yaml> --out <dir>
```

### 生成与审核

```bash
# 从工具生成候选 eval
python -m agent_tool_harness.cli generate-evals \
  --project <project.yaml> --tools <tools.yaml> \
  --source tools --out <candidates.yaml>

# 候选审核后转正（只搬运 accepted + runnable 条目）
python -m agent_tool_harness.cli promote-evals \
  --candidates <candidates.yaml> --out <evals.promoted.yaml>
```

### 执行

```bash
# mock replay 全链路（当前唯一可用模式）
# mock-path 可选 good 或 bad
python -m agent_tool_harness.cli run \
  --project <project.yaml> --tools <tools.yaml> \
  --evals <evals.yaml> --out <dir> --mock-path good

# 历史 run 轨迹重放
python -m agent_tool_harness.cli replay-run \
  --project <project.yaml> --tools <tools.yaml> \
  --evals <evals.yaml> --run <source-run-dir> --out <dir>

# 离线复盘 trace 信号
python -m agent_tool_harness.cli analyze-artifacts \
  --run <run-dir> --tools <tools.yaml> \
  --evals <evals.yaml> --out <dir>
```

### Bootstrap / Scaffold

```bash
# 一条命令完成 scaffold-tools + scaffold-evals + scaffold-fixtures + validate-generated
python -m agent_tool_harness.cli bootstrap \
  --source <tool_modules_dir> --out <dir>

# 分步操作
python -m agent_tool_harness.cli scaffold-tools \
  --source <tool_modules_dir> --out <tools.draft.yaml>
python -m agent_tool_harness.cli scaffold-evals \
  --tools <tools.draft.yaml> --out <evals.draft.yaml>
python -m agent_tool_harness.cli scaffold-fixtures \
  --tools <tools.draft.yaml> --out-dir <fixtures.draft>
python -m agent_tool_harness.cli validate-generated \
  --tools <tools.draft.yaml> --evals <evals.draft.yaml> \
  --fixtures-dir <fixtures.draft>
```

### Preflight（本地自检，不联网）

```bash
python -m agent_tool_harness.cli judge-provider-preflight --out <dir>
```

## 重要约束

- `run` 命令硬编码 `MockReplayAdapter`，不支持注入自定义 adapter。
- `--judge-provider anthropic_compatible_live` 为 legacy 路径（superseded），不推荐新使用。
  当前推荐 `--judge-provider llm` 配合 `--live --confirm-i-have-real-key` + explicit secret source。
  openai-compatible / anthropic-compatible transport 已通过 real LLM smoke 验证。
- `bootstrap` / `scaffold-*` 不执行用户代码、不联网、不读 `.env`。
- 所有 `llm_cost.json` 为 advisory-only，不是真实账单。
