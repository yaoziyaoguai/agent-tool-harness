# V3.2 Implementation Backlog

> **Status: Implemented** — 4 Phase 全部完成，实测 5 Phase (P1-P5)，98 测试通过。

## TLDR

4 个 Phase，顺序实现。P1 定义 EvalCase/ExpectedOutcome schema + Verifier interface。P2 实现所有确定性 verifier。P3 实现 TaskOutcome + TaskEvaluator。P4 整合 report + examples/docs。每个 Phase 独立可测。

---

## Phase 依赖关系

```
P1: EvalCase / ExpectedOutcome schema
  └── P2: Deterministic verifiers
        └── P3: TaskOutcome + TaskEvaluator
              └── P4: Report integration + examples/docs
```

---

## P1: EvalCase / ExpectedOutcome schema

### 目标

定义 EvalCase、ExpectedOutcome、Verifier Protocol、VerifierResult 的数据结构。实现 EvalCase 的 YAML 加载。

### 输入

- 无（纯 schema 定义）

### 输出

- `EvalCase` + `ExpectedOutcome` dataclass
- `Verifier` Protocol + `VerifierResult` dataclass
- `load_eval_case_from_yaml()` 函数

### 允许修改文件

| 文件 | 操作 |
|------|------|
| `agent_tool_harness/task_eval/__init__.py` | 新建 |
| `agent_tool_harness/task_eval/eval_case.py` | 新建 |
| `agent_tool_harness/task_eval/verifiers.py` | 新建（Verifier Protocol + VerifierResult） |
| `tests/test_eval_case.py` | 新建 |

### 测试要求

| # | 测试场景 | 断言 |
|---|---------|------|
| 1 | EvalCase 最小字段创建 | case_id, task 有值 |
| 2 | EvalCase 含 ExpectedOutcome | expected_outcome 非 None |
| 3 | ExpectedOutcome 空（无 verifier） | 所有 list 为空，exact_answer/notes 为 None |
| 4 | ExpectedOutcome 含 required_facts | list 正确存储 |
| 5 | YAML 加载 EvalCase（最小） | 所有字段正确解析 |
| 6 | YAML 加载 EvalCase（含 ExpectedOutcome） | required_facts/forbidden_facts 正确 |
| 7 | YAML 加载 EvalCase（含 regex_patterns） | regex 列表正确 |
| 8 | VerifierResult 创建 | 字段正确 |
| 9 | EvalCase 缺少必填字段 → ValueError | raise |

### 完成定义

- [x] EvalCase + ExpectedOutcome dataclass defined（frozen=True）
- [x] Verifier Protocol defined
- [x] VerifierResult dataclass defined
- [x] YAML 加载可用
- [x] ≥ 9 个单测通过
- [x] 现有 1300+ tests 无 regression

### 停止条件

- 不要在这个 Phase 实现 verifier 逻辑
- 不要修改 core_contract.py

---

## P2: Deterministic verifiers

### 目标

实现 6 种确定性 verifier：ContainsRequiredFacts、ForbiddenFactsAbsent、JsonFieldMatch、ExactMatch、RegexMatch、CompositeVerifier。

### 输入

- P1 的 Verifier Protocol + VerifierResult

### 输出

- 6 个 verifier 类
- `build_verifiers_from_outcome(expected_outcome) -> list[Verifier]` 工厂函数

### 允许修改文件

| 文件 | 操作 |
|------|------|
| `agent_tool_harness/task_eval/verifiers.py` | 追加 — 6 个 verifier 实现 |
| `tests/test_verifiers.py` | 新建 |

### 测试要求

| # | 测试场景 | 断言 |
|---|---------|------|
| 1 | ContainsRequiredFacts — 全部匹配 | passed=true, matched=2, missing=0 |
| 2 | ContainsRequiredFacts — 部分匹配 | passed=false, matched=1, missing=1 |
| 3 | ContainsRequiredFacts — 零匹配 | passed=false, matched=0, missing=2 |
| 4 | ContainsRequiredFacts — case-insensitive | "Root Cause" 匹配 "root cause" |
| 5 | ContainsRequiredFacts — 空 required_facts | passed=true（无要求即通过） |
| 6 | ForbiddenFactsAbsent — 无禁止事实 | passed=true, missing=0 |
| 7 | ForbiddenFactsAbsent — 发现禁止事实 | passed=false, missing=["fact"] |
| 8 | ExactMatch — 精确匹配 | passed=true |
| 9 | ExactMatch — 不匹配 | passed=false |
| 10 | ExactMatch — 空白差异 | "answer" vs "answer " → passed=true（strip） |
| 11 | RegexMatch — 全部匹配 | passed=true |
| 12 | RegexMatch — 部分匹配 | passed=false |
| 13 | RegexMatch — 空 patterns | passed=true |
| 14 | JsonFieldMatch — 字段子集匹配 | passed=true（expected 是 actual 子集） |
| 15 | JsonFieldMatch — 字段缺失 | passed=false |
| 16 | JsonFieldMatch — 嵌套比较 | 深度 > 1 的嵌套 dict 匹配 |
| 17 | CompositeVerifier(all) — 全部通过 | passed=true |
| 18 | CompositeVerifier(all) — 一个失败 | passed=false |
| 19 | CompositeVerifier(any) — 一个通过 | passed=true |
| 20 | build_verifiers_from_outcome — 正确数量 | 从 ExpectedOutcome 构造正确数量的 verifier |

### 完成定义

- [x] 6 个 verifier 全部实现
- [x] `build_verifiers_from_outcome()` 可用
- [x] ≥ 20 个单测通过
- [x] 现有 1300+ tests 无 regression

### 停止条件

- 不要在这个 Phase 实现 TaskOutcome / TaskEvaluator
- 不要引入 LLM 依赖

---

## P3: TaskOutcome + TaskEvaluator

### 目标

实现 TaskOutcome 数据结构和 TaskEvaluator，整合 final answer 提取 + verifier 执行 + 状态判定。

### 输入

- P1: EvalCase + ExpectedOutcome
- P2: verifiers
- ExecutionTrace（来自 trace_import）

### 输出

- TaskOutcome dataclass
- TaskEvaluator.evaluate() 方法

### 允许修改文件

| 文件 | 操作 |
|------|------|
| `agent_tool_harness/task_eval/task_outcome.py` | 新建 |
| `agent_tool_harness/task_eval/task_evaluator.py` | 新建 |
| `tests/test_task_outcome.py` | 新建 |
| `tests/test_task_evaluator.py` | 新建 |

### 测试要求

| # | 测试场景 | 断言 |
|---|---------|------|
| 1 | 所有 verifier 通过 → status=success | check status |
| 2 | 一个 verifier 失败 → status=failed | check status |
| 3 | 无 verifier → status=inconclusive | check status |
| 4 | required_facts 部分匹配 → missing_facts 正确 | check missing_facts list |
| 5 | matched_facts 正确聚合 | check matched_facts list |
| 6 | final answer 从 trace.final_answer 提取 | 提取正确 |
| 7 | final answer 从 last tool_result output["answer"] fallback | fallback 正确 |
| 8 | final answer 从 last tool_result output JSON string fallback | fallback 正确 |
| 9 | 无法提取 final answer → inconclusive | status check |
| 10 | evidence_refs 正确生成 | list 非空且内容正确 |

### 完成定义

- [x] TaskOutcome dataclass defined（frozen=True）
- [x] TaskEvaluator.evaluate() 可用
- [x] final answer 提取 3 种 fallback 正确
- [x] ≥ 10 个单测通过
- [x] 现有 1300+ tests 无 regression

### 停止条件

- 不要在这个 Phase 修改 report 文件
- 不要引入 CLI 子命令

---

## P4: Report integration + examples/docs

### 目标

Markdown report 和 JSON report 集成 task outcome。创建 example eval cases。

### 输入

- P3: TaskEvaluator → TaskOutcome
- ReportInsight（v3.1）

### 输出

- Markdown report 新增 task outcome section
- JSON report 新增 task_outcome key
- ≥ 3 个 example eval cases

### 允许修改文件

| 文件 | 操作 |
|------|------|
| `agent_tool_harness/reports/markdown_report.py` | 追加 — render_task_outcome_section() |
| `agent_tool_harness/core_report_bridge.py` | 追加 — task_outcome_to_json_dict() |
| `examples/eval_cases/` | 新建目录 + 3 个 YAML |
| `tests/test_task_report.py` | 新建 |

### 测试要求

| # | 测试场景 | 断言 |
|---|---------|------|
| 1 | Markdown 包含 "Task Outcome" section | substring |
| 2 | Markdown 包含 case_id | substring |
| 3 | Markdown 包含 status 标签 | "SUCCESS" 或 "FAILED" 或 "INCONCLUSIVE" |
| 4 | JSON 包含 task_outcome key | key 存在 |
| 5 | JSON task_outcome.status 正确 | 值匹配 |

### 完成定义

- [x] Markdown report 包含 task outcome section
- [x] JSON report 包含 task_outcome key
- [x] ≥ 3 个 example eval cases
- [x] ≥ 5 个单测通过
- [x] 现有 1300+ tests 无 regression

---

## 汇总

| Phase | 新文件 | 修改文件 | 预计新增测试 |
|-------|--------|---------|------------|
| P1 | `task_eval/__init__.py`, `task_eval/eval_case.py`, `task_eval/verifiers.py` (部分), `tests/test_eval_case.py` | — | ~10 |
| P2 | `tests/test_verifiers.py` | `task_eval/verifiers.py` (追加) | ~20 |
| P3 | `task_eval/task_outcome.py`, `task_eval/task_evaluator.py`, `tests/test_task_outcome.py`, `tests/test_task_evaluator.py` | — | ~11 |
| P4 | `examples/eval_cases/`, `tests/test_task_report.py` | `reports/markdown_report.py`, `core_report_bridge.py` | ~5 |
| **合计** | **7 个新文件 + 1 新目录** | **3 个已有文件修改** | **≥46 tests** |
