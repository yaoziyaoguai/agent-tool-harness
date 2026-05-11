# Product Architecture（产品架构）

> 本文档从产品视角描述 agent-tool-harness 的架构：用户如何完成一次完整的工具评估。
> 它不关注代码实现细节（那是 `TECHNICAL_ARCHITECTURE.md` 的职责），
> 而是关注概念模型、用户流程、系统边界、人机分工。

---

## 一、核心产品闭环

用户使用 agent-tool-harness 完成一次工具评估的完整闭环：

```
用户的 tools.yaml ──→ Audit（审计工具契约） ──→ Generate（生成 eval 候选）
                                                       │
                                              人工 Review（审核候选）
                                                       │
                                               Promote（转正）
                                                       │
用户的 evals.yaml ───→ Audit Evals（审计 eval 质量）
                                                       │
                                                       ▼
                                                   Run（执行评估）
                                                       │
                                                 ┌─────┴─────┐
                                                 ▼           ▼
                                            good path    bad path
                                                 │           │
                                                 └─────┬─────┘
                                                       ▼
                                              10 个 Artifact（产物文件）
                                                       │
                                              人工复盘（读 report.md + JSONL）
                                                       │
                                                       ▼
                                              修复决策（改 tools.yaml / 改 evals.yaml / 改 Agent prompt）
```

**关键设计决策**：
- Audit 在 Run 之前——先检查工具契约，再跑评估。避免"Agent 跑通了但工具设计有硬伤"的假信号。
- Generate → 人工 Review → Promote 的"两阶段"流程——生成的是候选，不是正式 eval。框架**不能**自动把候选变成正式 eval。
- good path + bad path 必须都跑——只跑 good 看不出 judge 是否退化为同义复读。

---

## 二、核心概念模型

### 2.1 Scenario（评测场景）

一个 Scenario 是"用户给 Agent 的一个任务 + 对 Agent 工具使用行为的期望"。

组成：
- **用户输入**（`user_prompt`）：模拟真实用户对 Agent 说的一句话。**不泄露工具名**。
- **初始上下文**（`initial_context`）：Agent 在接到任务时已经知道的信息（如已有工单内容）。
- **期望工具行为**（`expected_tool_behavior`）：Agent 应该调用哪些工具（`required_tools`）、可以调用哪些（`allowed_tools`）、不能第一步调哪些（`forbidden_first_tool`）。
- **可验证结果**（`verifiable_outcome`）：最终回答应该包含什么、不应该包含什么。

Scenario 在系统中以 `evals.yaml` 中的一条 `eval` 条目存在。

### 2.2 Tool Adapter（工具适配）

Tool Adapter 是"Agent 如何调用工具"的抽象。当前有两种：

| Adapter | 行为 | 信号质量 |
|---------|------|---------|
| `MockReplayAdapter` | 按 eval 声明的 `expected_tool_behavior` 反向回放工具调用 | `tautological_replay`（PASS 在结构上必然） |
| `TranscriptReplayAdapter` | 从已有 run 的 `tool_calls.jsonl` / `tool_responses.jsonl` deterministic 重放 | `recorded_trajectory`（来自历史录制，不代表当前模型行为） |

未来可能增加 `RealAgentAdapter`（连接真实 OpenAI/Anthropic Agent），信号质量为 `real_agent`。

### 2.3 Runner（执行器）

Runner 是评估执行的编排器。它不直接调用工具，而是协调各子系统：

```
EvalRunner 主循环（对每条 eval）：
  1. 从 Audit 结果检查 eval 是否 runnable
  2. 通过 Adapter 模拟 Agent 行为
  3. 通过 ToolRegistry 执行工具（mock 模式下不真执行）
  4. 通过 Recorder 记录所有事件
  5. 通过 Judge 评判结果
  6. 通过 Diagnose 分析失败
  7. 通过 Reporter 生成报告
```

### 2.4 Evaluator（评测器 / Judge）

Judge 回答"这次 Agent 工具调用是否正确"。

当前实现：`RuleJudge`（deterministic rule-based），支持 8 类规则：
- `must_call_tool`：必须调用指定工具
- `must_call_one_of`：必须调用列表中的至少一个
- `forbidden_first_tool`：第一步不能调用某工具
- `max_tool_calls`：工具调用次数上限
- `expected_root_cause_contains`：结论必须包含指定关键词
- `must_use_evidence`：结论必须引用工具返回的 evidence
- `must_not_modify_before_evidence`：不能在没有 evidence 的情况下修改
- `evidence_from_required_tools`（anti-decoy）：evidence 必须来自 required_tools

Judge 的结果写入 `judge_results.json` + `report.md`。

### 2.5 Reporter（报告器）

Reporter 把 Audit + Judge + Diagnose 的结果聚合为人类可读的 `report.md`。

`report.md` 包含（来自 `docs/ARTIFACTS.md`）：
- Signal Quality banner（信号质量等级 + 中文警告）
- Methodology Caveats（方法论边界声明）
- Tool Design Audit / Eval Quality Audit / Agent Tool-Use Eval 摘要
- Per-Eval Details（每条 eval 的详细结果）
- Failure Attribution（按 category 聚合）
- Transcript-derived Diagnosis / Improvement Suggestions
- Cost Summary（v1.6+，advisory-only）

### 2.6 Human Review（人工复核）

系统中**必须人类介入**的关键节点：

| 节点 | 人类做什么 | 不做的风险 |
|------|-----------|-----------|
| **候选 eval 审核** | 补 `initial_context` / `expected_root_cause` / `judge.rules`，确认 `user_prompt` 真实性 | 生成一堆 `runnable: false` 的不可用 eval |
| **review_status 改 accepted** | 确认候选可以转正 | promoter 不会搬运未 accepted 的候选 |
| **good/bad 双路径验证** | 确认 good 全 PASS / bad 全 FAIL | judge 可能退化为同义复读（只看 `must_call_tool` 就 PASS） |
| **audit semantic_risk_detected** | 人工判断是否为真实语义风险 | deterministic 启发式可能漏掉"词汇不同、职责相同"的隐蔽诱饵 |
| **失败复盘** | 回到 raw JSONL 验证 diagnosis 的 `root_cause_hypothesis` | diagnosis hypothesis 可能错误归因 |
| **反馈分流** | maintainer 判断反馈属于 v2.x patch / v3.0 backlog / closed-as-design / needs-more-evidence / security-blocker | 所有反馈无差别进入 backlog |

---

## 三、数据流全景

```
project.yaml ──┐
tools.yaml ────┼──→ ConfigLoader ──→ ProjectSpec / ToolSpec[] / EvalSpec[]
evals.yaml ────┘                           │
                                            ▼
                                ┌──→ ToolDesignAuditor ──→ audit_tools.json
                                │
                                ├──→ EvalGenerator ──→ eval_candidates.yaml
                                │         │
                                │    (人工 Review + promote)
                                │         ▼
                                │    evals.yaml
                                │         │
                                ├──→ EvalQualityAuditor ──→ audit_evals.json
                                │
                                └──→ EvalRunner
                                         │
                           ┌─────────────┼─────────────┐
                           ▼             ▼             ▼
                     Adapter        ToolRegistry    Recorder
                     (Agent模拟)     (工具执行)      (事件记录)
                           │             │             │
                           └─────────────┼─────────────┘
                                         ▼
                                   transcript.jsonl
                                   tool_calls.jsonl
                                   tool_responses.jsonl
                                         │
                           ┌─────────────┼─────────────┐
                           ▼             ▼             ▼
                       RuleJudge    TranscriptAnalyzer  CostTracker
                           │             │                │
                           ▼             ▼                ▼
                   judge_results.json  diagnosis.json  llm_cost.json
                           │             │                │
                           └─────────────┼────────────────┘
                                         ▼
                                   MarkdownReport
                                         │
                                         ▼
                                    report.md
```

**关键数据流规则**：
- `transcript.jsonl` / `tool_calls.jsonl` / `tool_responses.jsonl` 是一手证据，不可被下游修改
- `metrics.json` / `judge_results.json` / `diagnosis.json` / `report.md` 是派生证据，必须能追溯回一手证据
- 所有 JSON artifact 顶层都带 `schema_version` + `run_metadata`（含 `run_id`），用于关联同一次 run 的产物

---

## 四、自动判断 vs 人类复核

| 环节 | 自动判断 | 人类复核 |
|------|---------|---------|
| 工具设计审计 | `ToolDesignAuditor` — 五维 deterministic 评分 + findings | `semantic_risk_detected` warning 必须人工 review |
| eval 候选生成 | `EvalGenerator` — 从 tools/tests 自动生成候选模板 | 所有 `TODO(reviewer):` 必须人工补完；`review_status` 必须人工改为 `accepted` |
| eval 候选转正 | `CandidatePromoter` — 机械搬运 accepted + runnable 的候选 | promoter 不做质量判断，只做字段完整性检查 |
| eval 质量审计 | `EvalQualityAuditor` — 五维评分 + runnable 判断 | 被拒 eval 的修复方向需要人工判断 |
| 运行评估 | `EvalRunner` + `RuleJudge` — 自动执行 + deterministic 评判 | 失败复盘必须回到 raw artifact 验证 |
| 失败诊断 | `TranscriptAnalyzer` — 11 类 deterministic finding | `root_cause_hypothesis` 是假设，需要人工验证 |
| 报告生成 | `MarkdownReport` — 自动聚合 | report 是派生视图，发现不一致以 raw artifact 为准 |
| 反馈分流 | `FeedbackIntakeValidator` — 字段/secret 扫描 | 5 类决策桶必须人工判断 |

---

## 五、系统边界

```
┌────────────────────────── agent-tool-harness ──────────────────────────┐
│                                                                         │
│  ┌─────────┐  ┌──────────┐  ┌────────┐  ┌────────┐  ┌─────────────┐  │
│  │ config  │  │  audit   │  │ runner │  │ judges │  │   reports    │  │
│  │ (加载)  │  │ (审计)   │  │ (编排) │  │ (评判) │  │  (报告)      │  │
│  └─────────┘  └──────────┘  └────────┘  └────────┘  └─────────────┘  │
│                                  │                                      │
│  ┌──────────┐  ┌──────────┐  ┌──┴───┐  ┌──────────┐  ┌───────────┐  │
│  │ scaffold │  │  agents  │  │tools │  │ diagnose │  │ recorder  │  │
│  │ (引导)   │  │ (适配器) │  │(执行)│  │ (诊断)   │  │  (记录)   │  │
│  └──────────┘  └──────────┘  └──────┘  └──────────┘  └───────────┘  │
│                                                                         │
│  ┌──────────┐  ┌──────────────────────────────┐                       │
│  │ feedback │  │ 10 artifact 文件（每次 run）    │                       │
│  │ (反馈验证)│  │ transcript/tool_calls/...      │                       │
│  └──────────┘  └──────────────────────────────┘                       │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
        │                    │
        ▼                    ▼
   用户的项目文件        用户的编辑器/查看器
   (project.yaml,        (读 report.md,
   tools.yaml,           复盘 JSONL,
   evals.yaml,           提交反馈)
   工具源码 .py)
```

**不在系统边界内的**（由用户侧负责）：
- 用户的 Python 工具源码的实现逻辑
- 用户的 Agent 框架（LangChain / 自研 Agent loop）
- CI 系统的配置（harness 只提供 CLI 接口，CI 模板未来可能提供但不属于核心）
- 报告的可视化消费（用户用自己习惯的工具打开 JSON/Markdown）
