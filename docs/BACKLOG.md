# Backlog

## Current stage

**Headless CLI Agent Tool Harness Prototype**

当前不是：
- Real LLM evaluation platform
- Full real-agent runtime harness
- Web UI product
- Benchmark platform

---

## P0: restore product intent and avoid misleading users

### P0.1 Anthropic lineage restored in docs
- **Status**: in progress
- **Why**: 文档瘦身时 Anthropic 文章引用被静默删除，项目失去了设计来源
- **Acceptance**: `docs/ANTHROPIC_LINEAGE.md` 存在；README 引用 lineage 但保持简短
- **Not doing**: 不在 README 写论文解读；不夸大当前能力

### P0.2 README distinguishes demo, prototype, and future
- **Status**: in progress
- **Why**: 用户可能看到 9 个 ✅ 而忽视 10 个 ❌，误以为支持真实 LLM eval
- **Acceptance**: README 声明"当前不是真实 LLM Agent evaluation platform"
- **Not doing**: 不在 README 加冗长的能力边界列表

### P0.3 Mock replay not described as real eval
- **Status**: in progress
- **Why**: "mock replay — 预期 PASS/FAIL" 容易被理解为真实评测
- **Acceptance**: 所有 docs 明确区分 tool design audit（已实现）和 tool use evaluation（未实现）
- **Not doing**: 不修改 mock replay 行为

---

## P1: strengthen current demo value

### P1.1 Stronger tool design audit signals
- **Status**: not started
- **Why**: 当前 5 类原则审计是项目与 Anthropic 文章最直接的对齐点，应做得更深
- **Acceptance**: ToolDesignAuditor 覆盖更多边界 case；decoy 检测更精确
- **Not doing**: 不引入 LLM judge 做语义诱饵检测（那是 P2）

### P1.2 Clearer failure attribution from mock transcripts
- **Status**: not started
- **Why**: TranscriptAnalyzer 四分类已对齐文章，但基于 mock 数据的归因仍需验证
- **Acceptance**: 每条 finding 的 category 映射正确；report 中归因可读
- **Not doing**: 不在没有真实 Agent 数据的情况下调整归因逻辑

### P1.3 Bootstrap / scaffold UX hardening
- **Status**: not started
- **Why**: bootstrap 是新用户入口，从 AST 扫描生成 draft 的体验决定 first impression
- **Acceptance**: `bootstrap` 端到端时间 < 5s；生成的 REVIEW_CHECKLIST 覆盖关键检查点
- **Not doing**: 不让 scaffold 执行用户代码或联网

---

## P2: prepare future real evaluation architecture

### P2.1 RealAgentAdapter spec
- **Status**: not started
- **Why**: 真实 Agent 评估是文章的核心主张，必须先有清晰的接口定义
- **Acceptance**: `AgentAdapter` Protocol 扩展为支持真实 LLM agentic loop
- **Not doing**: 不实现 RealAgentAdapter；只定义接口

### P2.2 JudgeProvider spec
- **Status**: not started
- **Why**: LLM judge 是替代 RuleJudge 的路径，但必须独立接口
- **Acceptance**: JudgeProvider Protocol 定义完整的语义评分接口
- **Not doing**: 不实现 LLM judge；不往 RuleJudge 塞 LLM 逻辑

### P2.3 ProviderConfig spec
- **Status**: not started
- **Why**: 模型选择 / cost / latency 可观测需要标准化配置
- **Acceptance**: ProviderConfig 定义 model / API key / base URL / budget 的配置格式
- **Not doing**: 不实现真实 API 调用

### P2.4 EvidenceStore spec
- **Status**: not started
- **Why**: 10 个 artifact 的写入契约需要升级为结构化证据存储
- **Acceptance**: EvidenceStore Protocol 定义证据的存储 / 查询 / 追溯接口
- **Not doing**: 不替换当前 RunRecorder

### P2.5 Opt-in real provider safety model
- **Status**: not started
- **Why**: 真实 LLM 调用需要双标志 + env var 的安全模型
- **Acceptance**: `--live --confirm-i-have-real-key` 双标志设计文档
- **Not doing**: 不实现真实 API 调用

---

## P3: future implementation candidates

### P3.1 Fake JudgeProvider first
- **Status**: not started
- **Why**: 在接真实 LLM judge 之前，先用 fake provider 验证 JudgeProvider 接口
- **Acceptance**: FakeJudgeProvider 通过 JudgeProvider Protocol 的所有测试
- **Not doing**: 不接真实 LLM

### P3.2 Real provider opt-in later
- **Status**: blocked (needs P2.3 + P2.5)
- **Why**: 真实 LLM 评估是最终目标，但需要安全模型和配置标准化先行
- **Acceptance**: opt-in 真实 LLM trial 完成一次端到端闭环
- **Not doing**: 不作为默认行为

### P3.3 RealAgentAdapter skeleton
- **Status**: blocked (needs P2.1)
- **Why**: 在 ProviderConfig 和 JudgeProvider 就绪后，实现最小 RealAgentAdapter
- **Acceptance**: RealAgentAdapter 通过 AgentAdapter Protocol 的 contract tests
- **Not doing**: 不实现完整的 agentic loop

### P3.4 Cost / latency evidence capture
- **Status**: blocked (needs P2.3)
- **Why**: llm_cost.json 当前永远是 advisory-only，真实数据需要真实 provider
- **Acceptance**: llm_cost.json 的 estimated_cost_usd 不再永远为 null
- **Not doing**: 不假装有真实数据

### P3.5 Combining deterministic checks + LLM judge output
- **Status**: blocked (needs P2.2 + P3.2)
- **Why**: RuleJudge 和 LLM judge 应该是互补的，不是替代的
- **Acceptance**: CompositeJudgeProvider 同时展示 rule 结果和 LLM 评分
- **Not doing**: 不让 LLM judge 替代 rule checks

---

## Explicit non-goals for now

- No Web UI
- No MCP executor
- No HTTP / Shell executor
- No RAG / vector database
- No automatic production benchmark
- No default real API calls
- No hidden .env reading
- No automatic pass/fail for real-world Agent quality without human review
- No multi-tenant / enterprise RBAC
