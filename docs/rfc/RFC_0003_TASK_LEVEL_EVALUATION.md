# RFC 0003: Task-level Evaluation

## TLDR

v3.1 的 EvaluationResult.passed 回答"Agent 调工具是否健康"，但不回答"任务是否完成"。v3.2 新增 EvalCase、ExpectedOutcome、Verifier、TaskOutcome 四个对象，在 trace-level inspection 之上提供 task-level verification。确定性 verifier 是默认路径，LLM verifier 是 optional/advisory/explicit。TaskOutcome 与 EvaluationResult.passed 是不同层级的判定，互不影响。

---

## Decision 1: TaskOutcome Is Evaluated After Trace-Level Inspection

### 问题

trace-level passed（EvaluationResult.passed）来自 deterministic RuleFinding，关注工具调用行为。task-level outcome 关注 Agent 是否完成了用户任务。两者回答不同层级的问题，不能互相替代。

### 决策

**TaskOutcome 在 EvaluationResult 之后独立计算。** 流程：

```
External trace JSON
  → TraceImportAdapter → ExecutionTrace
    → CoreEvaluation → EvaluationResult（trace-level）
      → TaskVerifier → TaskOutcome（task-level）
        → Report（含两层结果）
```

TaskOutcome 消费 ExecutionTrace 和 EvaluationResult，但不修改它们。TaskOutcome.status 不影响 EvaluationResult.passed。

### 为什么不是改 EvaluationResult 加 task_passed

EvaluationResult 是 Core Contract 的一部分，被所有 report consumer 消费。改动其 schema 会影响整个评测链路。TaskOutcome 是纯派生对象——它消费已有数据，不修改已有 schema。

---

## Decision 2: ExpectedOutcome Declares Ground Truth in Structured Form

### 问题

当前 EvalSpec 有 `verifiable_outcome` 和 `success_criteria` 字段，但：
- `verifiable_outcome` 是 `dict[str, Any]`，无 schema 约束
- `success_criteria` 是 `list[str]`，只有列表没有结构
- 无法表达"必须包含事实 A 和 B 但禁止事实 C"这类组合约束

### 决策

`ExpectedOutcome` 是 EvalCase 的核心字段，支持 5 种确定性验证类型 + 可选 human_notes：

```python
@dataclass(frozen=True)
class ExpectedOutcome:
    required_facts: list[str] = field(default_factory=list)
    forbidden_facts: list[str] = field(default_factory=list)
    expected_json_fields: dict[str, Any] = field(default_factory=dict)
    exact_answer: str | None = None
    regex_patterns: list[str] = field(default_factory=list)
    human_notes: str | None = None
```

### 为什么 required_facts 是 list[str] 而非 list[Fact]

用简单字符串做子串匹配（case-insensitive），避免引入 NLP 依赖。Fact 匹配是确定性的：`fact.lower() in answer_text.lower()`。

### 为什么 regex_patterns 存在

某些验证目标更适合正则（如版本号、百分比、时间戳格式）。regex 仍然是确定性的。

---

## Decision 3: Verifier Is a Composable Interface

### 问题

不同 eval case 需要不同的验证组合。有的只需要 fact check，有的还需要 regex + JSON field match。不能一个 verifier 做所有事。

### 决策

Verifier 是 Protocol，支持 5 种具体实现 + 1 种组合器：

| Verifier | 输入 | 判定逻辑 |
|----------|------|---------|
| `ContainsRequiredFacts` | answer_text + required_facts | 所有 fact 都是 answer 的子串（case-insensitive） |
| `ForbiddenFactsAbsent` | answer_text + forbidden_facts | 所有 fact 都不出现在 answer 中 |
| `JsonFieldMatch` | tool_output dict + expected_json_fields | expected_json_fields 是 output 的子集（递归比较） |
| `ExactMatch` | answer_text + exact_answer | answer_text.strip() == exact_answer.strip() |
| `RegexMatch` | answer_text + regex_patterns | 所有 pattern 都在 answer 中匹配 |
| `CompositeVerifier` | verifiers[] | 所有子 verifier 通过才通过（AND 语义） |

### 为什么用 Protocol 而非 ABC

Verifier 是一个简单接口（`verify(answer_text, tool_outputs) -> VerifierResult`），不需要状态，不需要 lifecycle。Protocol 足够灵活，不需要继承约束。

### VerifierResult schema

```python
@dataclass(frozen=True)
class VerifierResult:
    verifier_name: str
    passed: bool
    matched: list[str]
    missing: list[str]
    details: str  # human-readable explanation
```

---

## Decision 4: TaskOutcome Has Three States (Not Two)

### 问题

binary pass/fail 不足以描述 task-level evaluation：
- 有时没有定义 required_facts（只有 human_notes），无法自动判断
- 有时部分 fact 匹配、部分缺失，不能简单算 pass 或 fail

### 决策

TaskOutcome.status 有三种状态：

| status | 含义 | 触发条件 |
|--------|------|---------|
| `success` | 任务完成，所有 verifier 通过 | 所有 verifier.passed == True |
| `failed` | 任务未完成，至少一个 verifier 失败 | 任一 verifier.passed == False |
| `inconclusive` | 无法自动判定 | 没有定义 verifier，或所有 verifier 都 skipped |

### 为什么需要 inconclusive

有些 eval case 的 ground truth 本质上是主观的（如"答案是否 helpful"）。对这些 case，verifier 返回 inconclusive 是诚实的——它不假装自己能判断，而是建议人工 review。

---

## Decision 5: LLM Verifier Is Advisory, Opt-in, Explicit

### 问题

某些验证目标不适合确定性方法（如"答案是否 natural language"、"是否包含 subtle error"）。

### 决策

LLM verifier 是可选组件：
- 默认不启用
- 需要显式 opt-in（`--llm-verifier`）
- 产出 `JudgeFinding`，不影响 `TaskOutcome.status`（status 由确定性 verifier 决定）
- LLM verifier 的结果出现在 report 的 advisory section

### LLM Verifier interface

```python
class LLMVerifier:
    def verify(self, answer_text: str, expected_outcome: ExpectedOutcome) -> JudgeFinding:
        """LLM 辅助验证，返回 JudgeFinding（advisory only）。"""
```

---

## Decision 6: Extract Final Answer from ExecutionTrace

### 问题

ExecutionTrace 包含的是 tool_calls 和 tool_results，没有明确的 "final answer" 字段。Verifier 需要知道从哪提取文本做 fact match。

### 决策

Final answer 提取策略（按优先级）：
1. `trace.final_answer` 字段（如果 trace schema 支持）
2. 最后一条 tool_result 的 output 的 `answer` 或 `content` 字段
3. 最后一条 tool_result 的 output 的完整 JSON string
4. 如果都无法提取 → TaskOutcome.status = inconclusive，reason 说明原因

---

## Compatibility

### 不破坏的

| 对象 | 兼容方式 |
|------|---------|
| `Finding` / `RuleFinding` / `JudgeFinding` | 不修改 |
| `EvaluationResult` | 不修改 |
| `ExecutionTrace` | 不修改（新增可选 final_answer 字段） |
| `ReportInsight` | 不修改（新增 TaskOutcome 作为独立对象） |
| 现有 1300+ tests | 全部保持通过 |

### 新增的

| 新增项 | 位置 |
|--------|------|
| `EvalCase` dataclass | 新模块 `task_eval/eval_case.py` |
| `ExpectedOutcome` dataclass | 同上 |
| `Verifier` Protocol + 6 实现 | 新模块 `task_eval/verifiers.py` |
| `TaskOutcome` dataclass | 新模块 `task_eval/task_outcome.py` |
| `TaskEvaluator` | 新模块 `task_eval/task_evaluator.py` |
| task report section | MarkdownReport 新增方法 |

---

## Acceptance Criteria

1. **EvalCase** — 可从 YAML/JSON 加载，包含 ExpectedOutcome
2. **Verifier** — 4 种确定性 verifier + CompositeVerifier 可用
3. **TaskOutcome** — status 正确反映 verifier 结果
4. **Final answer 提取** — 支持 3 种 fallback 策略
5. **Report** — Markdown/JSON 包含 task outcome section
6. **兼容** — 现有 1300+ tests 全部通过
7. **零网络依赖** — 确定性 verifier 不调 LLM、不联网
8. **LLM verifier** — opt-in only，产出 JudgeFinding，不影响 TaskOutcome.status
