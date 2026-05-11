# Self-Serve Trial — 接入你自己的工具和 eval

> 适用对象：已跑通 [INTERNAL_TRIAL_QUICKSTART.md](INTERNAL_TRIAL_QUICKSTART.md) 的用户。
> 这一页帮你用**自己的项目**跑通第一个 self-serve trial。

> 全程**离线 / 不调真实 LLM / 不联网 / 不需要密钥**。

## 前置条件

- 已完成 INTERNAL_TRIAL_QUICKSTART.md 的 5 条命令
- 有自己团队的 AI Agent 工具（Python 函数）
- 知道这些工具的名称、参数和预期行为

## 最小接入流程（4 步）

### 1. 准备 `tools.yaml`

在你自己项目的目录下创建 `tools.yaml`。每个工具至少需要以下字段：

```yaml
tools:
  - name: my_search
    namespace: my_team
    qualified_name: my_team.my_search
    description: |
      在你的代码库中搜索符号定义。返回匹配的文件路径和行号。
      当 Agent 需要定位某个函数或类的定义时调用此工具。
    when_to_use:
      - Agent 需要找到函数/类的定义位置
      - 需要确认某个符号是否存在于代码库中
    when_not_to_use:
      - 不要用于语义搜索（这不是自然语言搜索引擎）
      - 不要用于读取文件内容（这是搜索工具不是文件读取工具）
    input_schema:
      type: object
      properties:
        query:
          type: string
          description: 要搜索的符号名或关键词
      required: [query]
    output_contract:
      required_fields: [evidence]
      evidence: matches
    token_policy:
      max_output_tokens: 2000
    side_effects:
      read_only: true
      destructive: false
    executor:
      module: my_team.tools
      function: my_search

  # 至少定义 2-3 个工具，覆盖不同职责
  - name: my_read_file
    namespace: my_team
    qualified_name: my_team.my_read_file
    # ... （同上结构）
```

> 完整字段说明见 [ARTIFACTS.md](ARTIFACTS.md) §tool_spec。

**写法要点**：
- `description` 面向 Agent（不是面向人类 reviewer）——用 Agent 能理解的动词和场景
- `when_to_use` / `when_not_to_use` 比 description 更重要，直接决定 Agent 是否选对工具
- `output_contract.required_fields` 必须包含 `evidence`

### 2. 准备 `project.yaml`

```yaml
project:
  name: my-team-trial
  domain: 你的业务领域（一句话）
  description: |
    你的项目描述，会出现在 report.md 中。

# pricing 和 budget 是可选的，跳过不影响跑通
# pricing:
#   anthropic_claude_sonnet_4:
#     input_per_1k: 0.003
#     output_per_1k: 0.015
#   currency: usd
#
# budget:
#   per_eval:
#     max_input_tokens: 4000
#     max_output_tokens: 2000
#     max_estimated_cost_usd: 0.05
```

### 3. 准备 `evals.yaml`

手工写 1 条 eval 即可开始（后续可用 `generate-evals` 从 tools 自动生成候选）：

```yaml
evals:
  - id: my_first_eval
    user_prompt: |
      在代码库中找到 authenticate 函数的定义。
      （这是真实用户会问的问题，不要包含工具名）
    expected_tool_behavior:
      required_tools:
        - my_team.my_search      # 必须用 qualified_name
        - my_team.my_read_file
      tool_sequence:             # 可选，不写则只检查 required_tools
        - my_team.my_search
        - my_team.my_read_file
      forbidden_first_tool:      # 可选
        - my_team.inappropriate_entry_tool
    expected_root_cause: "缺少关键搜索步骤"
    verifiable_outcome: "在 final_answer 中找到文件路径和 authenticate 定义"
    initial_context:
      runnable: true
    judge:
      rules:
        - must_call_tool
        - must_use_evidence
```

### 4. 运行

```bash
# 审计你的工具设计
python -m agent_tool_harness.cli audit-tools \
  --tools path/to/your/tools.yaml \
  --out runs/my-trial-audit

# 跑 good path（预期 PASS）
python -m agent_tool_harness.cli run \
  --project path/to/your/project.yaml \
  --tools path/to/your/tools.yaml \
  --evals path/to/your/evals.yaml \
  --out runs/my-trial-good \
  --mock-path good

# 跑 bad path（预期 FAIL）
python -m agent_tool_harness.cli run \
  --project path/to/your/project.yaml \
  --tools path/to/your/tools.yaml \
  --evals path/to/your/evals.yaml \
  --out runs/my-trial-bad \
  --mock-path bad
```

## 看结果

```bash
cat runs/my-trial-bad/report.md
```

重点关注：
1. **顶部 Signal Quality** — 确认是 `tautological_replay`（理解当前信号边界）
2. **Tool Design Audit** — 看哪些工具字段缺失或描述重叠
3. **Failure Attribution** — 按 category 看失败归因

## 排查

| 症状 | 先看 |
|------|------|
| 命令报错 | stderr |
| audit_tools 评分低 | `runs/my-trial-audit/audit_tools.json` findings |
| run 全是 SKIPPED | `audit_evals.json` — eval 可能被判定为 not_runnable |
| PASS/FAIL 不对 | `metrics.json::signal_quality`（tautological_replay 时 PASS 是结构性的） |
| 不知道怎么改进工具 | `diagnosis.json` → 每条 finding 的 suggested_fix |

## 提交反馈

完成 self-serve trial 后，请用 [INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md](INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md) 提交反馈。
哪怕是 "5 分钟极简版"（5 行）也能帮我们判断下一步方向。

## 边界提醒

- `MockReplayAdapter` 按 `expected_tool_behavior` 回放，PASS/FAIL 是结构性的——不代表真实 Agent 行为
- `ToolDesignAuditor` 是 deterministic 启发式，不读工具源码
- `RuleJudge` 不做 LLM 语义判定
- **真实 LLM judge / MCP / HTTP / Shell executor / Web UI 当前不做**
- **不接真实密钥、不调真实外部 API、不联网**
- 这是 **local-first / fake-first / review-first** 的 self-serve trial

## 下一步

- 配 pricing / budget → 见 [INTERNAL_TRIAL.md §4](INTERNAL_TRIAL.md#4-设置-pricing-与-per-eval-budget-cap)（HISTORICAL，仅供参考）
- 了解完整 artifact schema → [ARTIFACTS.md](ARTIFACTS.md)
- 了解架构 → [architecture/TECHNICAL_ARCHITECTURE.md](architecture/TECHNICAL_ARCHITECTURE.md)
