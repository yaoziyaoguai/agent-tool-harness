# Roadmap

> 外部接入指南见 [ONBOARDING.md](./ONBOARDING.md)；
> 常见坏配置对照表见 [`examples/bad_configs/README.md`](../examples/bad_configs/README.md)。

## 最近一次实现状态

当前 MVP 已完成可运行闭环：

- YAML loader
- Tool Design Audit
- Eval Quality Audit
- Eval Generator from_tools
- Eval Generator from_tests
- PythonToolExecutor
- ToolRegistry
- MockReplayAdapter
- EvalRunner
- RunRecorder
- RuleJudge
- TranscriptAnalyzer
- MarkdownReport
- `examples/runtime_debug` demo
- pytest 测试
- README / ARCHITECTURE / ROADMAP / TESTING

第二阶段强化已加入当前工作范围：

- 补强关键模块中文学习型注释，强调证据流和架构边界；
- 补强架构文档中的证据契约、失败归因流程和变更守卫；
- 补强测试纪律文档，明确不允许改弱测试、空测试和无理由 xfail；
- 增加治理纪律测试，防止文档/范围约束被无意削弱。

第三阶段基础修复已加入当前工作范围：

- EvalRunner 在 adapter/registry 失败时尽量写完整 artifacts；
- EvalRunner 使用 EvalQualityAuditor 的 runnable 结果作为执行闸门；
- MockReplayAdapter 从 eval/tool spec 推导 good/bad path，不再硬编码 runtime_debug 工具名；
- ToolRegistry 不再静默覆盖歧义短名；
- PythonToolExecutor 增加最小 input_schema 校验和单参数绑定修正；
- RuleJudge 修复空 root cause 和弱 evidence 引用的明显误判。
- 配置 loader 支持 tools/evals list root，并拒绝重复 eval id 和明显错误字段类型。

第六阶段 Failure Attribution 强化已加入当前工作范围（本轮）：

- TranscriptAnalyzer 重写：从 raw artifacts + audit findings 派生 11 类 finding，
  每条带 `type / severity / category / evidence_refs / why_it_matters /
  suggested_fix / related_tool_or_eval`；新增 `category_summary` /
  `root_cause_hypothesis` / `suggested_fixes` / `what_to_check_next` / 
  `diagnosis_kind="deterministic_heuristic"`，旧字段保留向后兼容。
- MarkdownReport 在 Per-Eval Details 渲染 finding 列表 + root cause hypothesis +
  what to check next，新增顶层 **Failure Attribution** 段按 category 聚合，
  并在 Methodology Caveats 显式声明诊断为 deterministic heuristic。
- 借鉴方法论：LangSmith / LangGraph trace tags、OpenTelemetry span attributes、
  Anthropic *Writing effective tools for agents* 失败分类、G-Eval rubric 风格、
  MCP tool annotations。**本轮明确不引入这些 SDK / LLM Judge / 新依赖。**
- 新增 `tests/test_failure_attribution.py` 覆盖至少 5 类 finding。

第七阶段 P0 治理硬化已加入当前工作范围（本轮）：

- **EvalQualityAuditor.judge.tautological_must_call_tool** 收口到根因层：原版只钉
  "恰好 1 条 must_call_tool 且指向 required_tools[0]"，多条 must_call_tool 全覆盖
  required_tools 的等价绕过仍能通过 audit；本轮判定改成"全部规则都是 must_call_tool /
  must_call_one_of 且没有任何一条行为语义规则（must_use_evidence /
  expected_root_cause_contains / must_not_modify_before_evidence /
  forbidden_first_tool / max_tool_calls）"，避免同根因换写法绕过。
- **RuleJudge.must_use_evidence 短串假阳修复**：evidence id 长度 < 3 时直接忽略，
  避免 ``id="1" / "id" / "a"`` 这类短串让 substring 匹配把任何 final_answer 都
  误判 PASS。``ev-17`` / ``ckpt-input-17`` / ``snap-03`` 等真实标识不受影响。
- **audit_tools.json / audit_evals.json 增加 `summary.warnings` 字段**：空输入
  时显式写 ``empty_input: ...`` 警告，避免 CI / 远程消费者只看 JSON 时把"零输入"
  当成"通过"。原 stderr 警告保留。
- **EvalQualityAuditor.realism.cheating_prompt 启发式扩展**：覆盖 `please use /
  call the X / use the X / invoke the X / 请使用 / 使用工具 / (call|use|invoke,
  tool) 词共现`，避免审核者用同义词绕过工具名泄露检测。仍是 deterministic 启发式。
- 新增 `tests/test_p0_governance_hardening.py` 8 条治理测试，每条都同时写正向
  与反向用例（避免新规则误伤合理 eval）。

第八阶段 P1B 接入体验三件套已加入当前工作范围（本轮）：

- **CLI `promote-evals` 子命令**：把 `eval_candidates.yaml` 中
  `review_status="accepted"` 且 `runnable=true` 且字段齐全（initial_context /
  verifiable_outcome.expected_root_cause / judge.rules）的候选机械搬运到指定
  正式 evals.yaml 片段。**默认禁止覆盖已有文件**，需 `--force`；保留
  review_status / review_notes / source 等审核痕迹；不做 audit、不改 prompt、
  不自动 LLM 评审。Skip reason 显式可读，告诉审核者下一步要补什么。
- **CandidateWriter 顶层 `warnings` 字段**：generate-evals 输出文件直接带
  empty_input / all_unrunnable / missing_review_notes / high_missing_context /
  cheating_prompt_suspect 等可行动质量提示，审核者关掉终端也不会丢失；CLI 同时
  把 warning 镜像到 stderr。warnings 不是失败，CLI 退出码仍为 0。
- **artifact `schema_version` + `run_metadata`**：新模块
  `agent_tool_harness/artifact_schema.py` 定义 `ARTIFACT_SCHEMA_VERSION="1.0.0"`
  与 `make_run_metadata`，给 metrics.json / audit_tools.json / audit_evals.json /
  judge_results.json / diagnosis.json 以及 generate-evals / promote-evals 输出
  YAML 都打戳。同一次 run 的 5 份 artifact 共享同一个 `run_id`，下游可由它串
  起来复盘。**不是 OpenTelemetry**，只是最小解析契约；raw JSONL 不打戳（事件流
  逐行独立，由 docs/ARTIFACTS.md 与 schema_version 共同表达字段约定）。
- 新增 `tests/test_p1b_promote_warnings_schema.py` 19 条治理测试：覆盖 promote
  accepted/needs_review/rejected/runnable=false/缺字段 + 拒覆盖 + 强制覆盖 +
  promoted 文件可被 load_evals/audit-evals 读 + 各 artifact schema_version 一致
  + 失败路径 artifact 也带 schema_version + CLI 退出码语义。

每次 run 会生成：

- `transcript.jsonl`
- `tool_calls.jsonl`
- `tool_responses.jsonl`
- `metrics.json`
- `audit_tools.json`
- `audit_evals.json`
- `judge_results.json`
- `diagnosis.json`
- `report.md`

## 当前 MVP 范围

MVP 目标是“可运行闭环”，不是大而全 benchmark。

当前重点：

- 用 deterministic rules 审计工具和 eval；
- 用 replay adapter 固定 good/bad 路径；
- 用 artifacts 证明 Agent 是否真的正确使用工具；
- 用测试保证 bad path 会失败、good path 会成功。

## 暂不做范围

本轮和第二阶段均不实现：

- 真实 OpenAI API adapter
- 真实 Anthropic API adapter
- MCP executor
- HTTP executor
- Shell executor
- Web UI
- 自动修改用户工具代码
- 复杂 LLM Judge
- 并发执行
- 大规模 benchmark
- `generate-evals --source transcripts/docs/logs`（当前只支持 `from_tools` / `from_tests`）
- held-out eval split 自动迁移
- CI 集成（GitHub Actions / pre-commit）

任何新增文件如果实现上述能力，都应先进入 Roadmap review，而不是直接进入代码。

## 已知设计债

- Audit 规则是启发式 deterministic rules，后续需要用真实项目反馈调权重。
- **`ToolDesignAuditor` 当前只是 structural / completeness 检查**：它只读 `tools.yaml` 字段，不读 Python 源码、不调用工具、不做语义级判断。语义诱饵（与已有工具职责重叠的浅封装）会被判高分，已在 `tests/test_tool_design_audit_decoy_xfail.py` 用 strict xfail 钉住。
- **`MockReplayAdapter` 直接读 `eval.expected_tool_behavior.required_tools` 反向回放**，导致 RuleJudge 在 good path 上结构性 PASS。这是当前最大的 evaluation 信号缺陷，靠 `signal_quality=tautological_replay` 标签向使用者诚实披露；真正修复要等真实 LLM adapter。
- `from_tools` 只能生成候选题，缺少真实 fixture 时不可运行。**默认 judge 已升级为
  `must_call_tool` + `must_use_evidence` + `must_not_modify_before_evidence`（destructive
  工具自动加），并在 hint 提供 `expected_root_cause` 时再加 `expected_root_cause_contains`**；
  这关掉了"调用即通过"的根因，使新候选不再被 `EvalQualityAuditor.judge.tautological_must_call_tool`
  报告。同时：
  - 工具契约缺关键字段（`when_to_use` / `when_not_to_use` / `output_contract` /
    `output_contract.required_fields` 含 `evidence` / `input_schema.properties` 含
    `response_format`）时，候选自动落到 `review_status="needs_review"` + `runnable=false`，
    审核者必须先回 `tools.yaml` 修工具契约，不能改 eval 绕过。
  - 默认 `success_criteria` 含 4 条反 tautology 文案；`EvalQualityAuditor` 新增
    `verifiability.success_criteria_only_required_tools` finding，识别"只把 required_tools
    复述成准则"的伪装。
  - `user_prompt` 在去工具名后再做一次"动词+工具/tool"共现兜底替换（`_scrub_cheating_signals`），
    避免 cheating prompt 回潮。
  详见 `tests/test_from_tools_judge_quality.py`、`tests/test_anti_patch.py`。
  仍未做：从 transcripts / 真实工单 / docs 自动生成更真实的 user_prompt——这要等
  `from_transcripts` / `from_docs` 与 LLM 辅助改写，已记 P2。
- `EvalQualityAuditor.runnable` 现已穿透字段层只看实际值（`_has_substantive_value`），
  能识别 `initial_context: {trace_id: ""}` 这种"看似配齐"的伪 fixture，并要求
  `verifiable_outcome` 至少含一条非空 `expected_root_cause` 或 `evidence_ids`；
  但**它仍是启发式 deterministic check**，不会判断 fixture 是否真实/语义合理。
  语义级 fixture 校验需要后续 LLM-assisted reviewer，已记 P2。
- `RuleJudge.must_use_evidence` 现要求 (a) final answer 含 `evidence`/`证据` 关键词、
  (b) 至少一次成功 tool_response 返回非空 evidence id/label、(c) 答案文本引用其中
  至少一个 id——避免"模板化提到 evidence 一词就通过"的 false positive。**仍不是 LLM
  Judge 的语义 grounding**：它无法判断引用的 id 是否真的支撑结论，也无法识别
  paraphrased evidence。完整 evidence grounding（连接证据 → 推理链 → 结论）需要
  LLM Judge 或更强 evidence matcher，已记 P2。
- `from_tests` 只做静态扫描，不能自动恢复测试 fixture 和用户上下文。
- `MockReplayAdapter` 仍只是 deterministic mock，不代表真实模型能力；后续需要 replay transcript adapter 和真实 LLM adapter。
- `RuleJudge.must_use_evidence` 已支持基础 evidence id/label 引用，后续仍需要更完整的 evidence matcher。
- metrics 只统计基础数量，后续需要 latency、token、tool error、retry 等指标。
- 当前文档测试只能检查关键短语和范围守卫，不能替代人工架构 review。
- loader 仍不是完整 schema validator；它只做接入期结构校验，深层质量判断仍依赖 audit。
- `PythonToolExecutor` 只做 `required` / `type` / `enum` 三类 minimal schema validation，远不及完整 JSON Schema。

## 信号质量（与 Anthropic 文章方法论的差距披露）

Anthropic *Writing effective tools for agents* 主张评估必须由真实 LLM agentic loop
驱动并观察 trajectory。当前 harness 没有真实 LLM adapter，因此引入 `signal_quality`
标签作为框架级能力披露：

- 等级在 `agent_tool_harness/signal_quality.py` 里集中定义；
- `AgentAdapter` 协议要求每个实现必须显式声明 `SIGNAL_QUALITY`；
- EvalRunner 把它写到 `metrics.json`，MarkdownReport 在报告顶部渲染 banner；
- `MockReplayAdapter` 永远是 `tautological_replay`——任何看到这个等级的 PASS 都不能
  被解读为“工具对真实 Agent 好用”。

升级路径（每一步都要伴随 `SIGNAL_QUALITY` 的诚实变更）：

1. `recorded_trajectory`：实现 TranscriptReplayAdapter，从已有 JSONL 重放；
2. `real_agent`：接入真实 OpenAI/Anthropic adapter；
3. 任何介于两者之间的规则型 adapter 必须使用 `rule_deterministic` 而非默认值。

不允许的反向修改：把 `MockReplayAdapter.SIGNAL_QUALITY` 改成更高等级以让 banner 消失。

## P0 后续

- 增加 transcript replay adapter，从已有 JSONL 重放真实事件链路（同时把 `SIGNAL_QUALITY` 升到 `recorded_trajectory`）。
- 扩展 `RuleJudge` 支持 evidence id 精确匹配。
- 给 eval candidate 增加 review 状态和转正命令。
- 增加 artifact schema 校验测试。
- 将治理纪律测试扩展为文档章节/schema 的更细粒度检查。
- **让 `ToolDesignAuditor` 做语义级重叠检测**（例如基于 token Jaccard / description embedding），让 `tests/test_tool_design_audit_decoy_xfail.py` 的语义诱饵能被识别——届时该 xfail 会变 XPASS 强制 CI fail，触发转正。

## P1 后续

- 实现 OpenAI adapter。
- 实现 Anthropic adapter。
- 实现 MCP executor。
- 增加 tool latency、token estimate、error rate metrics。
- 支持多 eval 文件合并和 split 过滤。
- 给候选 eval 增加更细的 review 状态机（`needs_review` / `approved` /
  `rejected`），并提供非交互式 promote 命令，把已审核条目合入正式 `evals.yaml`。
  **本轮（第八阶段）已落地最小版本**：`promote-evals` 子命令支持把
  `review_status="accepted"` + `runnable=true` + 字段齐全的候选机械搬运到指定
  evals.yaml 片段；默认禁止覆盖；保留 review_notes。仍未做的：完整状态机（
  needs_review/approved/rejected 多态流转）、PR/issue tracker 双向同步。
- 在 `report.md` 的 Per-Eval Details 中加入 trajectory 节选块（带行号）和 token
  估算；本轮已渲染 failure attribution finding 列表 / category breakdown /
  root cause hypothesis / what to check next，但仍是字段聚合，**没有原始
  transcript 片段**。trajectory 节选属于 P1 后续（需要先稳定 transcript schema
  版本号）。
- 给 artifact schema 加版本号字段（`schema_version`）：**本轮（第八阶段）已落地
  最小版本**——`agent_tool_harness/artifact_schema.py` 定义
  `ARTIFACT_SCHEMA_VERSION="1.0.0"`，所有派生 JSON / generate-evals / promote-evals
  输出 YAML 均带戳；同一 run 共享 `run_metadata.run_id`。仍未做的：raw JSONL
  自描述（事件流逐行独立）、SemVer 升级流程自动化、跨版本兼容性测试。

## P2 后续

- HTTP executor。
- Shell executor。
- LLM Judge 作为辅助 reviewer（与 deterministic findings 并列输出，不替换）。
- Web UI 查看 transcript、tool calls、diagnosis。
- 自动 patch 建议，但默认不直接修改用户工具代码。
- 大规模 benchmark 和并发执行。

## xfail 测试

当前存在 1 个 strict xfail 测试：

- `tests/test_tool_design_audit_decoy_xfail.py::test_audit_should_flag_semantic_decoy_tool`
  钉住 `ToolDesignAuditor` 当前不做语义级重叠检测的能力 gap。它构造一个语义
  诱饵工具（`runtime_quick_root_cause`，与主工具 `runtime_trace_event_chain` 职责
  重叠、声称一步到位），断言 audit 应该给出 finding——当前 audit 过不了这条断言，
  所以保持 xfail (strict=True)。
  - **转正条件**：`ToolDesignAuditor` 实现语义级重叠/职责冗余检测后，断言会通过，
    xfail 变 XPASS 触发 CI fail，此时把 `@pytest.mark.xfail` 移除即可。
  - **绝不允许的反向修改**：把测试改弱以让它 PASS、或把诱饵工具改得不像诱饵。

未来允许 xfail 的条件：

- 测试覆盖的是明确的未来能力，例如真实 adapter、MCP executor 或 evidence id 精确引用；
- 必须写清楚 reason；
- 必须写清楚转正条件；
- 不能用 xfail 掩盖当前 MVP 应该满足的需求。

xfail 转正条件必须满足：

- 对应能力进入当前阶段范围；
- 有真实 fixture 或 replay 证据；
- bad path 仍能被判失败；
- 相关文档和 Roadmap 已同步更新。

## Mock/Replay 替换计划

当前 `MockReplayAdapter` 是 MVP 的可复现 adapter。

后续替换方向：

- `TranscriptReplayAdapter`：读取历史 transcript/tool_calls/tool_responses；
- `OpenAIAdapter`：直接调用 OpenAI API；
- `AnthropicAdapter`：直接调用 Anthropic API；
- `MCPExecutor`：连接用户 MCP server 执行工具。
