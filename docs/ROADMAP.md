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
| **v0.1** | **最小 harness 跑起来** —— 一次 Agent 运行能记录证据、用基础规则判断工具调用链路是否合理、跑最小 eval、输出可读报告 | **已 release（commit `2161193`，tag `v0.1`）** |
| **v0.2** | 更强的 deterministic audit / judge / transcript 能力 | **已 release（commit `9acd788`，tag `v0.2`）** —— 已合入 4 轮：第一轮 ToolDesignAuditor 语义信号（commit `5016660`）；第二轮 actionable principle metadata + report 渲染（commit `6a0c6ff`）；第三轮 trace-derived deterministic tool-use 信号（commit `6fc4e7c`）+ analyze-artifacts 离线复盘 CLI（commit `761e53e`）+ TRY_IT 完整试用闭环文档化（commit `cc70868`）。本阶段**仍是 deterministic 启发式**，不接真实 LLM judge / MCP / HTTP / Shell / Web UI / 真实 Agent runtime——这些属 v0.3+。详见 `RELEASE_NOTES_v0.2.md`。|
| v0.3 | 自动化回归 / 场景库 / 真实 Agent Runtime 集成 | **第一项受控启动** —— `TranscriptReplayAdapter` + `replay-run` CLI 已合入，把已有 run 当"录像带"deterministic 重放；signal_quality 升至 `recorded_trajectory`；不接真实 LLM/MCP/HTTP/Shell/Web UI。下一步：`RuleJudge.must_use_evidence` non-substring 升级 / decoy 真实样本库（待 owner 触发）。|
| v1.0 | 稳定可扩展的 Agent Harness 平台 | **第一项受控启动** —— `RuleJudge.evidence_from_required_tools` deterministic anti-decoy 规则 + `TranscriptAnalyzer.evidence_grounded_in_decoy_tool` finding 已合入；`examples/runtime_debug` 与 `examples/knowledge_search` evals.yaml 加挂新规则。仍**不是** LLM Judge / 真实 Agent runtime / MCP / HTTP / Shell / Web UI。 |

**为什么 v0.2 先做语义级 deterministic audit，而不是直接接真实 LLM / MCP / HTTP**：
- v0.1 已经把"框架能跑通 + 9 个 artifact + 文档自洽"闭环；下一步真正能放大用户
  价值的是**audit/judge 信号本身的质量**，不是更多 adapter；
- 真实 LLM judge / MCP / HTTP 会立刻引入网络依赖、API 配额、不确定性、调试难
  ——在 audit 信号还无法识别明显诱饵的情况下接它们，等于在沙堆上盖楼；
- deterministic 启发式可以让 CI / 离线场景仍然能用，并且为未来 LLM judge 准备
  好评估对照基线（同一个 decoy 工具，启发式说什么、LLM 说什么、人类说什么）；
- 严格按 Anthropic 工具设计 5 类原则把 audit 升级到"per-finding actionable"
  （rule_id + principle + severity + why_it_matters + suggestion）后，下游
  dashboard / CI bot 可以在不依赖任何真实模型的前提下消费这些信号——这是
  v0.3 真实 Agent runtime 集成的前置条件。

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
- 116 passed + 1 strict xfailed（v0.1 + 候选 B 已合入后的基线，HEAD `a432db9`；
  xfail 见下文 §xfail 测试）。

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
4. ✅ **在一个全新的 example 项目上完成同样的闭环**（v0.1 blocking 1 — 已完成，
   commit `1aff4a6`，详见下文 §1）；
5. ✅ **ONBOARDING.md 的 10 分钟接入路径在外部用户视角下完整走查并修订**
   （v0.1 blocking 2 — 已完成，详见下文 §2）；
6. ✅ **v0.2 工作区改动妥善归档**，v0.1 基线干净，可作为对外 release 候选
   （v0.1 blocking 3 — 已完成 commit `493f677`，详见下文 §3）。

**v0.1 release-ready 状态**：上述 6 条毕业标准已全部达成（最后闭环 commit
`493f677`）。下一步是 v0.1 release 决策（由项目所有者触发）；v0.2 路线在 v0.1
正式标 release 前不启动新功能开发，仅允许文档层面引用与回溯。

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

### v0.1 当前 blocking issue（**3/3 已闭环**）

#### 1. 第二个 example 项目（已完成 — commit `1aff4a6`）
**状态**：✅ 已完成。`examples/knowledge_search/` 在 commit `1aff4a6` 落地
（`feat: add knowledge search example for v0.1 coverage`）。

**实际交付**：
- `examples/knowledge_search/` 含 `project.yaml` + `tools.yaml`（3 工具：
  `kb.search.search_articles` / `kb.article.fetch_article` /
  `kb.assistant.suggest_canned_response`）+ `evals.yaml`（1 eval：
  `kb_sso_session_loss_regression`）+ `demo_tools.py` + `README.md`；
- **零核心代码改动**：`agent_tool_harness/` 任何 .py 文件均不出现 KB 业务符号
  （由 `tests/test_example_knowledge_search.py::test_core_package_does_not_hardcode_kb_example_symbols`
  作为根因型回归钉死）；
- good path PASS / bad path FAIL，9 个 artifact 全在，`signal_quality =
  tautological_replay` 在 metrics 顶部诚实披露——与 runtime_debug 行为完全一致，
  证明 harness 不与单一业务域耦合；
- 7 条新增测试覆盖：example 文件齐全、loader 可读、audit-tools / audit-evals 可跑、
  good/bad smoke 必 PASS / 必 FAIL、9 artifact 完整、核心包无业务硬编码。

**保留的范围约束**（未来添加第三 example 时仍适用）：
- **零新代码逻辑**——只用现有 audit/judge/runner 能力；
- 工具数量 ≤ 3，eval 数量 ≤ 2；
- good path 必须 PASS，bad path 必须 FAIL；
- 不需要复杂业务，只要能证明"换一个领域 harness 仍然成立"。

**未来扩展点（仅 backlog，非 v0.1 范围）**：
- 第三 example（如 payments / pricing）以参数化形式接入测试，把
  `CORE_FORBIDDEN_KB_SYMBOLS` 抽成 fixture；
- 把 mock 的 `_DEMO_ARTICLES` 换成真实 KB 检索后端 demo（v0.3+ 真实 adapter 后）。

#### 2. ONBOARDING 10 分钟路径外部用户视角走查（已完成 — commit `93a97a3` + `b533c91`）
**状态**：✅ 已完成。v0.1 收口决定：在缺少真实新人资源的现实约束下，由 agent
以"外部用户视角 + 不依赖内部记忆"严格按 README → ONBOARDING 跑完整接入闭环
（含 audit-tools / generate-evals / 候选 review / promote-evals / audit-evals /
run good / run bad / 看 9 件套 artifact 与 report.md），等价覆盖了"非作者第一次
照抄文档"的真实失败模式；外部新人反馈作为 v0.2+ 持续改进项跟踪，不再阻塞 v0.1。

**实际交付的根因型修复（按时间顺序）**：

- `cbdfc69` `docs: fix v0.1 graduation doc consistency` —— v0.1 graduation 阶段对
  ONBOARDING / README / ARTIFACTS / TESTING / ROADMAP 的交叉引用与版本号做一致性
  整理，消除"文档之间互相矛盾"的接入断点。
- `a432db9` `fix(onboarding): align doc CLI snippets with real argparse + harden against drift`
  —— ONBOARDING §3 等命令缺必填参数的根因修复：把 `cli.main` 的 parser 抽成
  `_build_parser()`，新增 `tests/test_doc_cli_snippets.py` 静态扫接入文档每条命令
  并真跑 argparse 校验，未来再有 doc/CLI drift 立即被 CI 钉住。
- `d955a28` `docs: tighten onboarding walkthrough governance` —— 把 ONBOARDING 走查
  本身的纪律（不允许"看了一眼觉得 OK"、必须真跑命令、必须看 artifact 而不是只看
  report）写进 ONBOARDING 顶部，作为对自审与未来真人走查的统一约束。
- `93a97a3` `docs(v0.1): close onboarding walkthrough gaps + pin quickstart consistency`
  —— knowledge_search example 走查发现的 P1-A/B/C 三个文档断点：README 快速开始
  step 5 audit-evals 现在审计刚 promote 出的文件（修流程闭环）；review_status
  状态全集（candidate / accepted / rejected / needs_review）写清楚并指向 ONBOARDING
  §4 根因修工具契约的指引；ONBOARDING §1 同时引用 runtime_debug 与 knowledge_search
  两个 example 互为对照。新增 `test_readme_quickstart_audits_the_just_promoted_file`
  钉死 promote→audit 流程不变量。
- `b533c91` `docs(v0.1): clarify subcommand artifact contract + pin via test` ——
  走查发现"audit-tools 产物疑似缺失"的根因不是 CLI bug 而是 README §Artifacts 的
  9 文件清单容易被跳读用户误推到 standalone subcommand。修复：明示其它 subcommand
  各只写 1 文件并列出文件名；新增 `tests/test_subcommand_artifact_contract.py`
  以真实 CLI + tmp_path 钉每个 subcommand 的 `set(listdir) == {expected}` 契约，
  防未来产物文件静默新增 / 改名 / 删除。

**配套依赖前序**（不计入 blocking 2 但是其前提）：
- `1aff4a6` `feat: add knowledge search example for v0.1 coverage`（blocking 1
  落地的 knowledge_search example，是 blocking 2 走查的对象）；
- `6d1eadf` `docs: mark v0.1 second example complete`（blocking 1 闭环 ROADMAP
  更新）。

**仍未做（非 v0.1 blocking，记入 v0.2+ 持续改进）**：
- 找一位真正没看过本项目的外部新人按修订后 ONBOARDING 跑一遍并记录卡点——
  agent 视角无法替代真实新人的"看不懂 / 不知道下一步"反馈，但这种反馈属于发布
  后持续打磨范畴，不再视为 v0.1 release blocker。

#### 3. v0.2 工作区改动妥善归档（v0.2/tool-design-semantic-signal 分支归档决议）
**根因**：v0.2 候选 A "ToolDesignAuditor 语义信号"已在本地分支
`v0.2/tool-design-semantic-signal`（HEAD `7cac829` `feat: prototype tool design
semantic signals`）原型化。功能方向正确（详见 §"v0.2 候选 A"），但**属于 v0.2 阶段**：
如果直接合入 main 会模糊 v0.1 release 的能力边界，且让"v0.2 能力先于 v0.1 毕业"
的反模式合法化。

**v0.1 期间归档决议（已固化）**：

- **载体**：`v0.2/tool-design-semantic-signal` 是**仅本地存在的草案分支**，未推
  origin、未对外可见，**不属于** v0.1 main。`git branch --no-merged main` 始终列
  出它作为可审计标记。
- **不允许的操作**（v0.1 release 前硬约束 — v0.1 已 release，本节保留作为历史决议）：
  - 不允许 `git merge v0.2/tool-design-semantic-signal` 到 main（仍然有效：分支
    base 早于 v0.1 graduation，merge 会回退 v0.1 收口）；
  - 不允许 `git push origin v0.2/tool-design-semantic-signal`；
  - 不允许从该分支 `git cherry-pick` 任何 commit（同样会拉入旧 base 的删除）；
  - 允许且**已经做**的操作：手工 port 增量代码 + 测试到 main 的 v0.1 之上
    （v0.2 候选 A 第一轮已落地，详见下方"v0.2 候选 A 第一轮"段）。
- **允许的操作**：纯文档层面在 main 引用该分支名 / 转正条件 / strict xfail 关系
  （即本节本身），用于 v0.1 release notes 与未来回溯。
- **strict xfail 锚点演进**：v0.1 期间钉
  `tests/test_tool_design_audit_decoy_xfail.py::test_audit_should_flag_semantic_decoy_tool_overlapping_with_primary`
  ——v0.2 候选 A 第一轮（`right_tools.shallow_wrapper` + `right_tools.semantic_overlap`）
  已让该 xfail 自然 XPASS，按归档承诺把它转正为
  `tests/test_tool_design_audit_decoy.py` 普通 passing 测试。剩余更深一层的诱饵 gap
  （字段齐全 + 无捷径话术 + 用完全不同词汇描述同一职责）转移到新的 strict xfail
  `tests/test_tool_design_audit_subtle_decoy_xfail.py::test_audit_should_flag_subtle_semantic_decoy_with_disjoint_vocabulary`
  钉根因——deterministic 启发式无法靠词袋识别"职责相同、词汇不同"。
- **未来转正条件**（v0.2 第二轮或 v0.3，任一满足且新 strict xfail 自然 XPASS）：
  - 在 main 引入 transcript-based 或真实 tool response 样本驱动的语义级 audit；
  - 或合入 LLM judge 对工具职责做语义 cluster 识别"职责相同但词汇不同"的对子；
  - 不允许通过"任何工具都报 needs_review"等放宽断言的方式假装解决。

### v0.2 候选 A 第一轮（已落地）

- **吸收范围（手工 port，不 merge / 不 cherry-pick）**：
  - `agent_tool_harness/audit/tool_design_auditor.py` 新增：`GENERIC_NAME_TOKENS`
    扩充（check / analyze / debug / read / quick / info / data / do / process / handle）；
    `_SHALLOW_WRAPPER_PHRASES` + `right_tools.shallow_wrapper` finding；
    `_OVERLAP_STOPWORDS` + `_OVERLAP_JACCARD_THRESHOLD = 0.4` + `_semantic_overlap_pairs`
    + `right_tools.semantic_overlap` finding（双向）；`prompt_spec.usage_boundary_duplicated`
    + `prompt_spec.shallow_usage_boundary` + `prompt_spec.missing_response_format`
    findings；顶层 `signal_quality: deterministic_heuristic` + `signal_quality_note`
    披露；`semantic_risk_detected` warning。
  - `agent_tool_harness/reports/markdown_report.py` 增强：`## Tool Design Audit`
    节渲染 signal_quality / signal_quality_note / warnings / 每个工具的高严重度 finding
    + suggested_fix，让用户在 `report.md` 里直接看到语义风险，不必去翻 audit_tools.json。
  - 测试：替换 `tests/test_tool_design_audit_decoy_xfail.py` 为
    `tests/test_tool_design_audit_decoy.py`（转正版）；新增
    `tests/test_tool_design_audit_semantic.py`（每个新 finding 含正向+反向断言 +
    `examples/runtime_debug` 端到端反误报保险）；新增
    `tests/test_tool_design_audit_subtle_decoy_xfail.py`（新 strict xfail 锚点）。
- **明确丢弃**：v0.2 分支对 `cli.py` / docs / examples / RELEASE_NOTES 的所有删除/重写
  ——分支 base 早于 v0.1 graduation，merge 任何 doc/CLI 改动都会回退已 release 的 v0.1。
- **能力边界声明（不允许夸大）**：本轮只新增 deterministic 启发式信号；不是 LLM Judge，
  不读工具源码，不调用工具，不做真实语义理解。`signal_quality` 仍是
  `deterministic_heuristic`。
- **后续 v0.2 / v0.3 路线**（写在这里，本轮**不实现**）：
  - 引入 transcript-based 工具调用样本观测 Agent 是否在错误场景被诱饵命中；
  - 接入 LLM judge 对工具职责做语义 cluster；
  - 真实 OpenAI / Anthropic adapter / MCP executor / HTTP / Shell executor / Web UI。

**v0.1 release 之后的处理路径**：v0.1 标 release 后，按 §"v0.2 候选 A"流程把
`v0.2/tool-design-semantic-signal` 作为 v0.2 milestone 的第一个 PR 评审入口；
评审通过后合入 main 并把本节标"已归档 / 已合入 v0.2"。在那之前本节作为唯一
v0.1 blocking 3 的归档凭证。

### v0.1 期间下一步只允许做什么

按优先级（同时只允许 1 件）：
1. ~~处理 v0.2 工作区改动（blocking 3）~~ — **已完成 commit `493f677`**；
2. ~~写 `examples/<second-project>/`（blocking 1）~~ — **已完成 commit `1aff4a6`**；
3. ~~外部用户视角走查 ONBOARDING（blocking 2）~~ — **已完成 commit `93a97a3` + `b533c91`**。

3 条 blocking 全部闭环，v0.1 release-ready；下一步由项目所有者触发 release 决策，
v0.2 milestone 在 release 之后才允许启动新功能（详见 §"v0.2"）。

---

## v0.2 — 更强的 deterministic audit / judge / transcript

> ⚠️ **v0.1 毕业前严禁动**。本节只描述"v0.1 毕业后第一波要做什么"，作为方向锚。

> v0.2 试用闭环（audit-tools → generate-evals → promote-evals → audit-evals →
> run good/bad → analyze-artifacts）见 [`docs/TRY_IT.md`](./TRY_IT.md)；
> 配套 `tests/test_doc_try_it.py` 钉死该文档涵盖完整命令链路且顺序正确。

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
- `commit 5016660 feat: add deterministic tool design semantic signals`
  （候选 A 第一轮：浅封装 / 语义重叠 / 边界重复 / 缺 response_format
  / signal_quality 披露 + strict xfail 转正 + 新 subtle decoy xfail）。
- `commit 6a0c6ff feat(audit): make tool design findings actionable with
  Anthropic principle metadata`（候选 A 第二轮：finding 增加
  `principle` + `principle_title` + `why_it_matters` + 在 report.md
  渲染 actionable 三元；附带修了 `_render_audit_high_severity_findings`
  历史里 `suggested_fix` 字段读不到的 bug）。
- **v0.2 第三轮（trace-derived deterministic tool-use 信号）已落地**：
  新模块 `agent_tool_harness/diagnose/trace_signal_analyzer.py`，
  从已有 raw `tool_calls.jsonl` / `tool_responses.jsonl` payload +
  `ToolSpec.output_contract` / `when_not_to_use` 复盘出 5 类 deterministic
  信号：`tool_result_no_evidence` / `tool_result_missing_next_action` /
  `large_or_truncated_tool_response_without_guidance` /
  `repeated_low_value_tool_call` /
  `tool_selected_in_when_not_to_use_context`。每条信号自带
  `evidence_refs` / `why_it_matters` / `suggested_fix`。EvalRunner 把
  signals 嵌入 `diagnosis.json` 每条记录的 `tool_use_signals` 字段；
  `report.md` 在 Per-Eval Details 段渲染 "Trace-derived signals" 小节。
  - **能力边界声明**：本轮全部信号都是 deterministic 启发式，能稳定指出
    "工具响应没满足自己的 contract" / "调用模式异常" / "Agent 进入了
    工具自报的禁用场景关键词"，但**无法**回答"语义上是否真的根因"——
    例如 when_not_to_use 用同义词改写的诱饵仍会漏（仍由 strict xfail
    `test_tool_design_audit_subtle_decoy_xfail.py` 钉住，等待 v0.3
    transcript-based 样本或 LLM judge）。
  - **可独立 replay 的入口**：`analyze_run_dir(run_dir, tools=...)` 提供
    "对历史 run 目录复盘"的纯函数入口。本轮**不**新增 CLI（避免扩范围）；
    `analyze-artifacts` CLI 列入 v0.2 backlog。

### 工作区 / 分支中的 v0.2 候选（v0.1 毕业后再合入）

- 候选 A：ToolDesignAuditor semantic signals（处理方案见 v0.1 blocking 3）。

### v0.2 backlog（不排序，毕业后再排）

- 候选 A 后续 round（已落地两轮，详见上方）；
- ✅ ~~`analyze-artifacts` CLI（基于 `analyze_run_dir` helper），让用户对
  历史 `runs/` 目录独立复盘 trace 信号，不必 re-run Agent~~ — **已落地**
  （v0.2 第三轮后续小步：`agent_tool_harness/cli.py::_analyze_artifacts`
  + `tests/test_cli_analyze_artifacts.py` 5 条 e2e）；
- `unused_high_signal_tool` trace 信号（when_to_use 命中 prompt 但工具
  未被调用）—— 本轮丢弃，v0.2 后续轮再看；
- `candidate_prompt_too_tautological` 信号（候选 eval 的 judge 规则与
  prompt 同义重复）—— 同上；
- `RuleJudge.must_use_evidence` 加更强的 evidence matcher（仍是 deterministic）；
- `TranscriptReplayAdapter` —— 从已有 JSONL 重放，把 signal_quality 升到
  `recorded_trajectory`；
- `TranscriptAnalyzer` 在 report.md 加 trajectory 节选块；
- `ToolDesignAuditor` 隐蔽诱饵（词汇不重合的语义重叠）—— 仍是 strict xfail，
  转正条件需 transcript 真实样本或 LLM judge（这条可能要拖到 v0.3）；
- `from_tools` `_difficulty` 启发式细化；
- `PythonToolExecutor` 完整 JSON Schema 校验（取代当前 `required/type/enum`
  最小子集）。

### v0.1 收口期间记录的 ONBOARDING P2 backlog（v0.2 处理）

来自 ONBOARDING 外部用户视角走查（v0.1 blocking 2）。本身不阻塞 v0.1 毕业，但
应在 v0.2 期间清理：

- **`audit-tools` 没有 markdown 派生视图**：当前只输出 `audit_tools.json`，新用户
  得手动 cat JSON 才能看 finding。建议加 `audit_tools.md`（与 `audit_evals.md`
  对齐），把 findings 按 severity 分组渲染。属于 derived view 工作，不增加新信号。
- **`examples/runtime_debug/tools.yaml` 全部 5.0 满分、零 finding**：导致新用户
  跑 audit-tools 看到的是"完美样本"，无法直观看到 finding 长什么样。应在 README
  快速开始或 ONBOARDING 加一个对照命令，跑一次 `examples/bad_configs/` 让用户看到
  非空 finding 列表（bad_configs 已存在，只是没有指引去跑）。
- **没有"1 个命令端到端走完 9 步"的便捷脚本**：新用户得逐条复制粘贴 6+ 个命令，
  容易在中间步骤忘改 `--out` 路径导致互相覆盖。可以加 `scripts/onboarding_smoke.sh`
  或一个 `agent-tool-harness onboarding-smoke` CLI 子命令把走查脚本化（用于
  CI/PR 验证 ONBOARDING 没坏，不替代真人走查）。

---

## v0.3 — 自动化回归 / 场景库 / 真实 Agent Runtime

### 阶段目标

让 harness 不只是"能跑"而是"能持续监控真实 Agent 在多场景下的行为退化"。

### 当前进度（受控启动，逐项推进）

- ✅ **第一项 `TranscriptReplayAdapter` + `replay-run` CLI**（v0.3 第一项）：
  把一份历史 run 当成"录像带"deterministic 重新播放，新 run 输出 9 个完整
  artifact，`signal_quality = recorded_trajectory`。**不调 LLM、不调
  `registry.execute`、不发起任何外部副作用**。这是为后续真实 Agent adapter
  打地基——recorder/judge/report/analyze-artifacts 接口先被 deterministic
  replay 反复验证过，再接真实模型。模块见
  `agent_tool_harness/agents/transcript_replay_adapter.py`，CLI 见
  `replay-run`，测试见 `tests/test_transcript_replay_adapter.py`（9 条
  防回归断言：fail-fast、不调 execute、signal_quality、good/bad replay
  等价、缺源记录走 FAIL warning、CLI actionable error）。
- ⏳ 后续候选（owner 触发）：`RuleJudge.must_use_evidence` non-substring
  升级；decoy 真实样本库 + subtle decoy strict xfail 转正路径；
  `unused_high_signal_tool` trace 信号；真实 LLM/MCP adapter。

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

### v1.0 第一项已落地：deterministic anti-decoy evidence grounding

**根因目标**：v0.x 的 `must_use_evidence` 只校验"final_answer 是否引用了任意 tool_response 里的 evidence id"，**不区分 evidence 来自哪个工具**。
若 Agent 走 decoy 工具收 evidence + 把 decoy id 写进结论，规则仍会通过，
trajectory 上的真实路径错误被掩盖。这是 trajectory 级 anti-decoy 的一个明确 gap。

**本轮（受控范围）**：
- `agent_tool_harness/judges/rule_judge.py` 新增 opt-in 规则
  `evidence_from_required_tools`：把"final_answer 引用的 evidence ≥1 条来自
  `expected_tool_behavior.required_tools`"升为硬约束。eval 未声明 required_tools
  时本规则视为不适用，自动 PASS（不破坏既有 eval）。
- `agent_tool_harness/diagnose/transcript_analyzer.py` 新增 finding
  `evidence_grounded_in_decoy_tool`（severity=high, category=agent_tool_choice）：
  即使用户没配新规则，只要 trajectory 里 final_answer 只引用了非 required 工具的
  evidence，也会自动 surface 到 `diagnosis.json` 与 `report.md`。
- `examples/runtime_debug/evals.yaml` 与 `examples/knowledge_search/evals.yaml`
  双 example 同步加挂 `evidence_from_required_tools`，作为新用户的可复制示例。
- `tests/test_evidence_grounding.py` 9 条边界 + decoy trajectory 内联样本库。

**仍不是 / 边界声明**：本规则与 finding 仍是 **deterministic 启发式**，不是 LLM
Judge，不验 evidence 内容语义；语义级 grounding 等真实 LLM judge（v1.0 后续条目）。

**v1.0 候选 A 增量（已落地）**：把 `evidence_grounded_in_decoy_tool` 与
`no_evidence_grounding` 在 finding payload 中**结构化**暴露 `cited_refs /
cited_tools / required_tools` 与 `tool_responses_had_evidence /
available_evidence_refs`；`report.md` Failure Attribution **与 Per-Eval Details
两段都直接读这些字段**渲染（用户在每条 eval 块内就能复盘 grounding 失败原因，
不必跳到聚合段也不必打开 raw JSONL）。`no_evidence_grounding` 进一步区分两种修复
方向完全不同的子场景。`tests/test_evidence_grounding.py` 覆盖 5 类 deterministic
grounding/decoy 场景作为 sample 基线（keyword-only / id-not-cited / decoy-grounded
/ forbidden-first-tool 上游链路 / 正向路径）。

**与 subtle decoy strict xfail 的关系**：
`tests/test_tool_design_audit_subtle_decoy_xfail.py` 仍保留 strict xfail，
因为它测的是**静态 ToolDesignAuditor 仅看 yaml 字段**就能识别 disjoint-vocabulary
decoy 的能力，与本轮的 trajectory 级 anti-decoy 是不同维度。两者互补，xfail
转正条件不变（真实 trajectory 聚合 / 真实 LLM judge）。

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

当前存在 1 个 strict xfail（v0.2 候选 A 第一轮已落地后的新基线）：

- `tests/test_tool_design_audit_subtle_decoy_xfail.py::test_audit_should_flag_subtle_semantic_decoy_with_disjoint_vocabulary`
  —— 钉住 deterministic 启发式根本限制：当诱饵工具**字段齐全 + 无捷径话术 + 用完全
  不同词汇描述同一职责**时（词袋 Jaccard 远低于 0.4 阈值），`right_tools.shallow_wrapper`
  / `right_tools.semantic_overlap` 都不会触发，auditor 仍判 5.0 满分。
  **历史**：v0.1 期间的 `tests/test_tool_design_audit_decoy_xfail.py` 已被 v0.2 候选 A
  第一轮（`right_tools.shallow_wrapper` + `right_tools.semantic_overlap`）解决，
  按归档承诺（§3）转正为 `tests/test_tool_design_audit_decoy.py` 普通 passing 测试；
  剩余更深一层 gap 转移到本新 strict xfail 钉根因。
  **转正条件**（任一满足且 strict xfail 自然 XPASS）：引入 transcript-based 工具
  调用样本观测 Agent 是否在错误场景被诱饵命中；或合入 LLM judge 对工具职责做语义
  cluster 识别"职责相同但词汇不同"的对子。
- 严禁通过"任何工具都报 needs_review"等放宽断言假装解决；严禁删除 / 弱化 / 改
  strict=False。

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
