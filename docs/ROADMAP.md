# Roadmap

> 外部接入指南见 [ONBOARDING.md](./ONBOARDING.md)；
> 常见坏配置对照表见 [`examples/bad_configs/README.md`](../examples/bad_configs/README.md)。
> 历史版本见 `docs/ROADMAP.md.bak`（保留原文供回溯）。

---

## 设计原则（高于一切阶段目标）

1. **小步、根因、可证伪**：每一步只做"让最小闭环更可信"的事。任何工作出现"扩展
   auditor / judge / generator 细节"的冲动时，先回头问："这件事是当前阶段毕业
   标准的一部分吗？" 不是就停。
2. **新增/修改代码必须写中文学习型注释或 docstring**：解释模块/类/函数负责什么、
   不负责什么、为什么这样设计、用户项目自定义入口在哪里、如何通过 artifacts 查
   问题、哪些只是 MVP/mock/demo、未来扩展点在哪里。
3. **测试为发现真实 bug 而存在**：不放宽断言、不删关键断言、不空测试、不无理由
   xfail；fake/mock/xfail 都要有中文注释说明模拟什么边界或失败场景。
4. **不允许 hack / 补丁 / demo-only 分支 / 硬编码 runtime_debug 业务符号**。
5. **所有问题必须先找根因再修**：不吞异常、不靠 substring 假阳掩盖、不让 mock
   等级偷偷升级、不在 RuleJudge / Auditor 里加"为了让本次 run PASS"的临时支路。
6. **阶段范围是硬约束**：跨阶段的能力进入工作区前必须先在 ROADMAP 升级阶段，
   不允许"既然已经在做，就顺手把 v0.2/v0.3 的能力也做了"。

---

## 阶段总览

| 阶段 | 一句话目标 | 当前状态 |
|------|-----------|---------|
| **v0.1** | **最小 harness 跑起来** —— 一次 Agent 运行能记录证据、用基础规则判断工具调用链路是否合理、跑最小 eval、输出可读报告 | **基本达成（剩 3 条 blocking）** |
| v0.2 | 更强的 deterministic audit / judge / transcript 能力 | 进行中（**建议暂停扩张直到 v0.1 毕业**）|
| v0.3 | 自动化回归 / 场景库 / 真实 Agent Runtime 集成 | 未启动 |
| v1.0 | 稳定可扩展的 Agent Harness 平台 | 未启动 |

---

## 当前状态自评（基于真实仓库快照）

### 已经完成的（远超 v0.1 最低线）

- 9 个 artifact 完整生成（`transcript.jsonl` / `tool_calls.jsonl` /
  `tool_responses.jsonl` / `metrics.json` / `audit_tools.json` / `audit_evals.json`
  / `judge_results.json` / `diagnosis.json` / `report.md`）；
- `ToolDesignAuditor` 五维 deterministic 打分 + warning 字段；
- `EvalQualityAuditor` 五维 + runnable 闸门 + tautological judge 检测 +
  `verifiability.success_criteria_only_required_tools`（**已超 v0.1**）；
- `from_tools` / `from_tests` 候选生成 + spec gating + 默认语义 judge
  （`commit d3b6b2a`，**这部分属于 v0.2 但已合入**）；
- `promote-evals` CLI + 5 类 candidate writer warnings；
- `RuleJudge` 7 类规则 + evidence id 长度过滤；
- `TranscriptAnalyzer` 11 类 finding + root_cause_hypothesis；
- `MarkdownReport` 含 Failure Attribution + Methodology Caveats；
- `signal_quality` 披露 + `MockReplayAdapter.SIGNAL_QUALITY=tautological_replay`；
- `schema_version=1.0.0` + `run_metadata` 跨 artifact 共享 run_id；
- 113 passed + 1 strict xfailed（v0.1 + 候选 B 已合入后的基线）。

### v0.2 已启动但**尚未合入**的工作（在工作区，未 commit）

- 候选 A：`ToolDesignAuditor` 语义信号（`shallow_wrapper` /
  `semantic_overlap` / `usage_boundary_duplicated` / `shallow_usage_boundary` /
  `missing_response_format` + 扩 generic name token + signal_quality 披露 +
  原 strict xfail 转正 + 新隐蔽诱饵 strict xfail）。
- 工作区状态：`agent_tool_harness/audit/tool_design_auditor.py` +
  `docs/ARCHITECTURE.md` / `docs/ROADMAP.md`（被本轮重写覆盖）/ `docs/TESTING.md`
  + `tests/test_tool_design_audit_decoy.py` + `tests/test_tool_design_audit_semantic.py` +
  `tests/test_tool_design_audit_subtle_decoy_xfail.py`。
- 测试结果：127 passed / 1 xfailed，ruff clean，demo 端到端正确。
- **结论**：质量本身没问题，但**它是 v0.2 内容**，不应该在 v0.1 毕业前合入。
  建议处理方式见下文"v0.1 当前 blocking issue"第 3 条。

### 当前最大风险

不是某个 audit 不够强，而是 **v0.2 已经开始扩张但 v0.1 闭环还没在新用户/新项目
上验证**。继续把 ToolDesignAuditor / RuleJudge / from_tools 等做强，**不会让一个
新接入的用户第一次跑 harness 时更顺利**——他可能根本卡在"我不知道怎么写最小
tools.yaml"。

---

## v0.1 — 最小 harness 跑起来

### 阶段目标（一句话）

让一个外部用户，拿到本仓库 + ONBOARDING.md，能在 30 分钟内：在他自己的项目里写
最小 tools.yaml + evals.yaml，跑通 `audit-tools / audit-evals / run`，拿到 9 个
artifact，看 report.md 判断"工具调用链路是否合理 + 哪条 eval pass/fail"。

**v0.1 不追求很牛**——不追求 audit 信号多丰富、judge 多语义、analyzer 多智能。
只追求**闭环成立**且**新人能跑通**。

### 毕业标准（必须全部达成）

1. ✅ `examples/runtime_debug` good path 全 PASS / bad path 全 FAIL；
2. ✅ 9 个 artifact 在 good / bad / runner_error 路径下都能完整生成；
3. ✅ `signal_quality` 在每份 metrics.json 顶部诚实披露；
4. ❌ **在一个全新的 example 项目上完成同样的闭环**（v0.1 blocking 1）；
5. ❌ **ONBOARDING.md 的 10 分钟接入路径在一个没看过本项目的同事身上验证**
   （v0.1 blocking 2）；
6. ❌ **v0.2 工作区改动妥善归档**，v0.1 基线干净，可作为对外 release 候选
   （v0.1 blocking 3）。

### 非目标（v0.1 期间**严禁**做）

- 真实 LLM API、MCP、HTTP、Shell executor、Web UI、并发、benchmark、自动 patch；
- 任何 LLM Judge / 语义级 audit / transcript replay adapter；
- 继续给 ToolDesignAuditor / EvalQualityAuditor / RuleJudge 加 finding；
- 给 from_tools / from_tests 加新 source（transcripts / docs）；
- 多 example 项目库（v0.1 只需要 1 个 runtime_debug + 1 个新项目证明通用性，
  不需要场景库）；
- 给 report.md 加 trajectory 节选 / token estimate；
- 任何"反正都在改了顺手"的扩展。

### 停止规则（任一触发必须立刻停手回 v0.1）

1. 工作了一天还在 ToolDesignAuditor / EvalQualityAuditor / RuleJudge /
   TranscriptAnalyzer 里加 finding；
2. 在加任何 LLM-related 路径（哪怕只是"准备工作"）；
3. 当前任务的终点不是"让闭环在新用户/新项目上跑通"；
4. 给 strict xfail 文件再添加新的 case；
5. 对 examples/runtime_debug 之外的真实业务符号做硬编码。

### v0.1 当前 blocking issue（**只允许这 3 个**）

#### 1. 第二个 example 项目尚未存在
**根因**：所有 demo 都跑在 `examples/runtime_debug` 上。这无法证明 harness 是
通用的——可能 audit/judge/runner 的某些假设悄悄绑死在 runtime_debug 的工具命名
风格上。需要新增 `examples/<minimal-second-project>/`，用一个完全不同的领域
（如 payments / search / docs lookup）跑 audit + run 的闭环。

**约束**：
- **零新代码逻辑**——只用现有 audit/judge/runner 能力；
- 工具数量 ≤ 3，eval 数量 ≤ 2；
- good path 必须 PASS，bad path 必须 FAIL；
- 不需要复杂业务，只要能证明"换一个领域 harness 仍然成立"。

#### 2. ONBOARDING 10 分钟路径未在新人身上验证
**根因**：当前 ONBOARDING.md 是作者写的，可能存在"作者觉得显然但用户实际卡壳"的
步骤。这是 v0.1 用户体验的核心。

**约束**：
- 找内部一个没看过本项目的同事，按 ONBOARDING 跑一遍；
- 记录他卡住的所有步骤（包括"看不懂哪句话"）；
- **不允许通过加 audit/judge 能力解决用户体验问题**——只能改文档与示例；
- 把高级能力章节（如 `signal_quality` / `verifiability.success_criteria_only_required_tools`）
  挪到独立"进阶"章节，避免新手第一次接触就被淹没。

#### 3. v0.2 工作区改动妥善归档
**根因**：当前工作区有候选 A 的 5 文件 + 3 新测试（ToolDesignAuditor 语义信号），
功能本身正确，但属于 v0.2。如果直接合入会模糊 v0.1 release 的边界，且让"v0.2
能力先于 v0.1 毕业"的反模式合法化。

**处理方案（任选其一）**：
- **A**：`git stash push -m "v0.2-candidate-A"` 暂存，等 v0.1 毕业后再 pop；
- **B**：建一个 `v0.2/candidate-a-tool-design-semantic-signals` 分支，把改动
  commit 进去，然后 `git checkout main` 把工作区清干净；
- **C**：保留工作区改动但**不 commit**，且 v0.1 期间不再扩展该方向。

**强约束**：v0.1 毕业前不允许把候选 A 合入 main。

### v0.1 期间下一步只允许做什么

按优先级（同时只允许 1 件）：
1. 处理 v0.2 工作区改动（blocking 3，最快）；
2. 写 `examples/<second-project>/`（blocking 1）；
3. 找同事跑 ONBOARDING 并修订（blocking 2）。

---

## v0.2 — 更强的 deterministic audit / judge / transcript

> ⚠️ **v0.1 毕业前严禁动**。本节只描述"v0.1 毕业后第一波要做什么"，作为方向锚。

### 阶段目标

deterministic 启发式做到合理上限，让 audit / judge / analyzer 信号能识别"字段层
伪装"和"语法 PASS 但语义不通"的常见反模式。

### 毕业标准

1. ToolDesignAuditor 能识别浅封装捷径话术 + 跨工具语义重叠（候选 A 已实现，
   v0.1 毕业后从工作区/分支合入即可）；
2. EvalQualityAuditor 含 `success_criteria_only_required_tools` finding（已合入）；
3. `from_tools` 默认 judge 含语义/防御性规则（已合入 commit `d3b6b2a`）；
4. `RuleJudge.must_use_evidence` 升级为不只 substring 启发式（**未做**）；
5. `TranscriptReplayAdapter` 上线，`signal_quality` 升到 `recorded_trajectory`
   （**未做**）；
6. `TranscriptAnalyzer` 在 report.md 中加 trajectory 节选（**未做**）。

### 非目标

- 真实 LLM API；
- LLM Judge；
- 大规模 benchmark；
- 多场景库（留给 v0.3）。

### 停止规则

任一超出"deterministic 启发式 + 已有 transcript JSONL"的能力都不做。

### 已合入的 v0.2 工作

- `commit d3b6b2a feat: harden from-tools generated eval judging`（候选 B）。

### 工作区 / 分支中的 v0.2 候选（v0.1 毕业后再合入）

- 候选 A：ToolDesignAuditor semantic signals（处理方案见 v0.1 blocking 3）。

### v0.2 backlog（不排序，毕业后再排）

- 候选 A 合入；
- `RuleJudge.must_use_evidence` 加更强的 evidence matcher（仍是 deterministic）；
- `TranscriptReplayAdapter` —— 从已有 JSONL 重放，把 signal_quality 升到
  `recorded_trajectory`；
- `TranscriptAnalyzer` 在 report.md 加 trajectory 节选块；
- `ToolDesignAuditor` 隐蔽诱饵（词汇不重合的语义重叠）—— 仍是 strict xfail，
  转正条件需 transcript 真实样本或 LLM judge（这条可能要拖到 v0.3）；
- `from_tools` `_difficulty` 启发式细化；
- `PythonToolExecutor` 完整 JSON Schema 校验（取代当前 `required/type/enum`
  最小子集）。

---

## v0.3 — 自动化回归 / 场景库 / 真实 Agent Runtime

### 阶段目标

让 harness 不只是"能跑"而是"能持续监控真实 Agent 在多场景下的行为退化"。

### 毕业标准

1. 多场景库（`examples/scenarios/{payments, search, docs, runtime, ...}`）每个场景
   有独立 tools/evals + baseline 报告；
2. 自动化回归：CI 跑所有场景，与 baseline diff（包括 metrics / artifact /
   report.md）；
3. 真实 Agent Runtime adapter 至少接入 1 个（OpenAI / Anthropic / MCP）；
4. LLM Judge 作为**辅助 reviewer**（与 deterministic findings 并列输出，不替换）；
5. 质量评分体系：每个工具 / eval 有跨 run 的 quality_score 趋势线。

### 非目标

- Web UI、并发执行、自动 patch（留给 v1.0）。

### 停止规则

不引入"平台化"特性（多用户 / Web UI / 复杂权限）。

---

## v1.0 — 稳定可扩展的 Agent Harness 平台

### 阶段目标

让多个团队 / 多个项目能共享同一套 harness，作为长期质量基础设施。

### 毕业标准

1. Web UI 查看 transcript / tool calls / diagnosis；
2. CI 集成模板（GitHub Actions / pre-commit）；
3. 完整 schema validator（取代 audit 的 deterministic 启发式作为入口校验）；
4. 自动 patch 建议（默认不直接修改用户工具代码，输出 diff 让用户审核）；
5. 大规模 benchmark + 并发执行；
6. 多用户 / 多项目支持（含权限、quota、隔离）。

### 非目标

- 替代真实 Agent Runtime（永远只是评估框架，不是 Agent 框架）。

---

## 暂不做范围（永久或长期）

- **替代真实 Agent Runtime / SDK**：本项目永远是评估框架，不会变成 LangChain /
  AutoGPT / Anthropic SDK 的替代；
- **自动改用户工具代码**：v1.0 之后才考虑，且永远默认 dry-run；
- **跨语言工具支持**：Python 工具是 MVP；其他语言通过 MCP / HTTP / Shell
  executor（v0.3+）覆盖。

---

## 信号质量（与 Anthropic 文章方法论的差距披露）

Anthropic *Writing effective tools for agents* 主张评估必须由真实 LLM agentic loop
驱动并观察 trajectory。当前 harness 没有真实 LLM adapter，因此引入 `signal_quality`
标签作为框架级能力披露：

- 等级在 `agent_tool_harness/signal_quality.py` 里集中定义；
- `AgentAdapter` 协议要求每个实现必须显式声明 `SIGNAL_QUALITY`；
- EvalRunner 把它写到 `metrics.json`，MarkdownReport 在报告顶部渲染 banner；
- `MockReplayAdapter` 永远是 `tautological_replay`——任何看到这个等级的 PASS 都不能
  被解读为"工具对真实 Agent 好用"。

升级路径（每一步都要伴随 `SIGNAL_QUALITY` 的诚实变更）：

1. v0.2：`recorded_trajectory` —— 实现 `TranscriptReplayAdapter`，从已有 JSONL 重放；
2. v0.3：`real_agent` —— 接入真实 OpenAI/Anthropic adapter；
3. 任何介于两者之间的规则型 adapter 必须使用 `rule_deterministic` 而非默认值。

**不允许的反向修改**：把 `MockReplayAdapter.SIGNAL_QUALITY` 改成更高等级以让 banner 消失。

---

## xfail 测试

当前存在 1 个 strict xfail（v0.1 基线）：

- `tests/test_tool_design_audit_subtle_decoy_xfail.py::test_audit_should_flag_subtle_semantic_decoy_with_disjoint_vocabulary`
  —— 仅当候选 A 合入后存在；当前 v0.1 基线（`HEAD=d3b6b2a`）无该 xfail。
- 历史 strict xfail `tests/test_tool_design_audit_decoy_xfail.py` 在候选 A 中
  被转正，文件改名为 `tests/test_tool_design_audit_decoy.py`（同样仅在候选 A
  合入后生效）。

未来允许 xfail 的条件：

- 测试覆盖的是明确的下一阶段能力（v0.1 期间不允许新增 xfail）；
- 必须写清楚 reason 与中文学习型注释；
- 必须写清楚转正条件（写明属于哪个阶段）；
- **不能用 xfail 掩盖当前阶段应该满足的需求**。

---

## 全局停止规则总结

任何 PR / commit 在以下情况必须停手回 ROADMAP review：

1. 它实现的能力不在当前阶段毕业标准里；
2. 它扩展了 deterministic auditor / judge 但当前阶段已经足够；
3. 它引入了新依赖；
4. 它引入了 LLM 调用 / 真实 API；
5. 它新增了 strict xfail 但当前阶段不允许；
6. 它修改了已有断言变弱或删除关键断言；
7. 它给 examples/runtime_debug 之外的真实业务符号做硬编码。
