# Configuration — project / tools / evals

所有配置为 YAML 文件，通过 `config/loader.py` 解析。

## project.yaml

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

# 可选
pricing:
  input_cost_per_1k_tokens: 0.003
  output_cost_per_1k_tokens: 0.015
budget:
  max_tokens_total: 100000
  max_cost_usd: 5.0
```

## tools.yaml

```yaml
tools:
  - name: search_code
    namespace: my_team
    qualified_name: my_team.search_code
    version: "1.0.0"
    description: |
      搜索代码库中的符号定义。返回匹配文件路径和行号。
    when_to_use:
      - 需要定位函数/类的定义位置
      - 确认符号是否存在
    when_not_to_use:
      - 不要用于自然语言语义搜索
      - 不要用于读取文件内容
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
```

### 关键字段

- `namespace` — 工具命名空间，防止与其他工具冲突
- `when_to_use` / `when_not_to_use` — 告诉 Agent 何时用/不用此工具
- `input_schema` — JSON Schema 风格的参数定义
- `output_contract` — 输出中必须包含的字段
- `token_policy` — Token 预算策略
- `side_effects` — 副作用声明（read_only / destructive）
- `executor` — 执行器类型和入口

## evals.yaml

```yaml
evals:
  - id: search_exact_symbol
    name: 精确符号搜索
    category: tool_selection
    split: test
    realism_level: realistic
    complexity: single_step
    source: manual
    user_prompt: 找到 parse_config 函数定义在哪个文件
    initial_context:
      project: my_project
    verifiable_outcome:
      expected_root_cause: "parse_config 定义在 src/config.py:42"
    success_criteria:
      - 必须调用 search_code 工具
      - 返回结果必须包含 config.py
    expected_tool_behavior:
      required_tools:
        - my_team.search_code
      forbidden_first_tool:
        - my_team.read_file
    judge:
      rules:
        - must_use_evidence
        - must_call_required_tools
    runnable: true
```

### candidate vs accepted

`generate-evals` 生成的是候选（`review_status: candidate`），不是正式 eval。
必须经过人工审核将 `review_status` 改为 `accepted`，再由 `promote-evals` 转正。
**不允许用脚本批量改 status 跳过 review。**

## 格式约定

- `tools.yaml` 和 `evals.yaml` 支持 `tools: [...]` / `evals: [...]` 包裹，也支持 list root
- `id` 必须唯一
- `input_schema` / `output_contract` / `side_effects` / `executor` 必须是 mapping
- `initial_context` / `verifiable_outcome` / `expected_tool_behavior` / `judge` 必须是 mapping
- `success_criteria` / `missing_context` 必须是 list
