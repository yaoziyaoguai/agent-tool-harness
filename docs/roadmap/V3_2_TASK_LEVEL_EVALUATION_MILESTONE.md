# V3.2 Milestone: Task-level Evaluation

> **Status: Planned** — 设计文档已完成，实现未开始。

## TLDR

v3.1 能判断"Agent 调工具对不对"，但不能判断"任务有没有完成"。v3.2 引入 EvalCase、ExpectedOutcome、Verifier 和 TaskOutcome，让 harness 可以验证 Agent 的输出是否满足任务预期的 ground truth。确定性 verifier 是默认路径，LLM verifier 是 optional/advisory/explicit。

---

## 1. 背景

### 1.1 v3.1 已经解决什么

v3.1.1 的 trace-level evaluation 回答的是：**Agent 的工具调用行为是否健康？**

- call_id 是否配对？
- tool spec 是否完整？
- tool response 是否够用？
- 整体 scorecard 怎样？

但它无法回答一个更根本的问题：**Agent 最终完成任务了吗？**

### 1.2 为什么 v3.2 需要 task-level evaluation

一条 trace 可以所有 tool-use 检查都通过（passed=true），但 Agent 最终给了错误答案。反之，一条 trace 可以有 tool-use warning，但 Agent 最终正确完成了任务。

**task-level passed ≠ trace-level passed**。两者回答不同层级的问题。

v3.2 的目标：在 trace-level inspection 之上新增 task-level verification。

---

## 2. 用户问题

| # | 问题 | 当前状态 |
|---|------|---------|
| 1 | "我的 Agent 工具调用没报错，但给用户的答案对吗？" | 无法验证 |
| 2 | "我怎么定义'任务成功了'？" | 无结构化方式 |
| 3 | "这个 eval case 里 Agent 漏了哪些关键信息？" | 无法定位 |
| 4 | "能不能不调 LLM 就验证答案中的关键事实？" | 无确定性 verifier |

---

## 3. v3.2 目标

### 3.1 EvalCase schema

定义结构化的评测用例：

```
EvalCase
  ├── case_id
  ├── task (用户问题描述)
  ├── input (初始上下文/对话)
  ├── expected_outcome: ExpectedOutcome
  ├── trace_ref (可选，关联已有 trace)
  ├── tags
  ├── difficulty
  └── metadata
```

### 3.2 ExpectedOutcome schema

支持多种确定性验证方式：

| 验证类型 | 字段 | 示例 |
|---------|------|------|
| 必须包含的事实 | `required_facts` | ["root cause is network timeout", "fix: increase retry"] |
| 禁止出现的事实 | `forbidden_facts` | ["reboot the server"] |
| JSON 字段匹配 | `expected_json_fields` | {"severity": "critical", "action": "restart"} |
| 精确答案匹配 | `exact_answer` | "42" |
| 正则匹配 | `regex_patterns` | ["error rate: \\d+\\.\\d+%"] |
| 人工备注 | `human_notes` | "答案可能因上下文而异，需人工判断" |

### 3.3 Verifier interface

可组合的确定性验证器：

| Verifier | 检查内容 | 输入 |
|----------|---------|------|
| `ContainsRequiredFacts` | final answer 是否包含所有 required_facts | final_answer_text + required_facts |
| `ForbiddenFactsAbsent` | final answer 是否不含 forbidden_facts | final_answer_text + forbidden_facts |
| `JsonFieldMatch` | tool output JSON 是否匹配期望字段 | tool_output + expected_json_fields |
| `ExactMatch` | 精确字符串匹配 | final_answer_text + exact_answer |
| `RegexMatch` | 正则匹配 | final_answer_text + regex_patterns |
| `CompositeVerifier` | 组合多个 verifier，全部通过才通过 | verifiers[] |

### 3.4 TaskOutcome

```
TaskOutcome
  ├── case_id
  ├── status: "success" | "failed" | "inconclusive"
  ├── verifier_results: list[VerifierResult]
  ├── missing_facts: list[str]
  ├── matched_facts: list[str]
  ├── reason: str
  └── evidence_refs: list[str]
```

### 3.5 Report integration

- task-level summary section in Markdown report
- task outcome section in JSON report
- verifier results 可追溯

### 3.6 examples/eval_cases

- 至少规划 3 个 sample eval cases
- 不依赖真实 LLM
- 不运行真实 Agent

---

## 4. 典型用户场景

### 场景 A：定义 eval case

```yaml
# examples/eval_cases/knowledge_search_case.yaml
case_id: "ks-001"
task: "找到生产环境最近一次部署失败的根本原因并给出修复建议"
input:
  context: "生产环境 deploy-service 在 2026-05-15 14:30 部署失败"
expected_outcome:
  required_facts:
    - "root cause"
    - "fix recommendation"
  forbidden_facts:
    - "restart production without approval"
  regex_patterns:
    - "error: .+ at .+"
difficulty: "medium"
tags: ["knowledge_search", "production"]
```

### 场景 B：运行 task-level evaluation

```bash
python -m agent_tool_harness.cli run \
  --project examples/runtime_debug/project.yaml \
  --tools examples/runtime_debug/tools.yaml \
  --evals examples/eval_cases/knowledge_search_case.yaml \
  --out /tmp/harness-demo/task-eval
```

### 场景 C：CI 中消费 task outcome

```json
{
  "task_outcome": {
    "case_id": "ks-001",
    "status": "failed",
    "missing_facts": ["fix recommendation"],
    "matched_facts": ["root cause"],
    "reason": "Agent identified root cause but did not provide actionable fix"
  }
}
```

---

## 5. 完成定义

用户可以用 EvalCase 定义任务期望，用 Verifier 验证 Agent 产出：

- [ ] `EvalCase` + `ExpectedOutcome` schema defined
- [ ] 5 种确定性 verifier + CompositeVerifier 可用
- [ ] `CompositeVerifier` 可组合
- [ ] `TaskOutcome` 正确判定 success/failed/inconclusive
- [ ] Markdown report 包含 task-level section
- [ ] JSON report 包含 task_outcome key
- [ ] 可选 LLM verifier（opt-in, advisory only）
- [ ] ≥ 46 个新增单测
- [ ] 现有 1300+ tests 无 regression
- [ ] examples/eval_cases/ 含 ≥ 3 个 sample

### 可验证标准

| 标准 | 验证方式 |
|------|---------|
| required_facts 全部匹配则 status=success | 单测 |
| 任一 required_fact 缺失则 status=failed | 单测 |
| 无 required_facts 且无其他 verifier 则 status=inconclusive | 单测 |
| CompositeVerifier AND 语义正确 | 单测 |
| TaskOutcome 不影响 EvaluationResult.passed | 单测 |
| LLM verifier 默认不启用 | 单测（env check） |

---

## 6. 明确不在此 milestone

- 不内置 Agent runner（task 执行仍在外部）
- 不实现自动 eval case 生成
- 不实现 multi-trace aggregation（v3.3）
- 不实现 regression comparison（v3.4）
- 不修改 EvaluationResult / Finding 结构
- 不做 LLM-only verifier（确定性优先）
- 不做 Web UI
