# Milestones（里程碑）

> 本文档从 `ROADMAP.md`（85KB 工程日志）中提炼各阶段的里程碑概览，用于快速扫描和决策。
> 每个里程碑的详细内容（毕业标准、停止规则、非目标）见 `ROADMAP.md` 对应章节。

---

## 一、里程碑总览

| 里程碑 | 状态 | 一句话目标 | Release Tag | 关键产出 |
|--------|------|-----------|-------------|---------|
| **v0.1** | ✅ 已完成 | 最小 harness 跑起来 | `v0.1` | 9 artifact + audit/run/judge/report 闭环 |
| **v0.2** | ✅ 已完成 | 更强的 deterministic audit/judge/transcript | `v0.2` | semantic signals + trace analyzer + analyze-artifacts CLI |
| **v0.3** | ✅ 已完成 | 自动化回归 / 场景库 | `v0.3` | TranscriptReplayAdapter + replay-run CLI |
| **v1.0** | ✅ 已完成 | 稳定可扩展的 Agent Harness 平台 | `v1.0` | anti-decoy evidence grounding + grounding/decoy report |
| **v1.1** | ✅ 已完成 | JudgeProvider abstraction | `v1.1` | JudgeProvider Protocol + RecordedJudgeProvider |
| **v1.2** | ✅ 已完成 | CompositeJudge + AnthropicCompatible skeleton | `v1.2` | CompositeJudgeProvider + error taxonomy (8 类) + preflight |
| **v1.4** | ✅ 已完成 | LiveAnthropicTransport 骨架 | `v1.4` | HTTPS transport + CLI live-ready 入口 + fake fixture 注入 |
| **v1.5** | ✅ 已完成 | Multi-advisory CLI + report readability | `v1.5` | `--judge-advisory` CLI + MarkdownReport multi-advisory |
| **v1.6** | ✅ 已完成 | Retry/backoff + cost + judge prompt audit | `v1.6` | retry/backoff + llm_cost.json + audit-judge-prompts CLI |
| **v1.7** | ✅ 已完成 | Product hardening + release-readiness | `v1.7` | artifact consistency + doc/CLI drift 防回归 + TRY_IT_v1.7 |
| **v2.0** | ✅ 已完成 | Internal Trial Ready | `v2.0` | bootstrap + internal trial 文档 + feedback loop |
| **Doc Consolidation** | ✅ 已完成 | 文档收口里程碑 | `cf9831c` | 补齐产品/架构/约束/Roadmap/Milestone/模块文档 |
| **v2.x patch** | ⏳ 候选 | 内部试用反馈驱动的小版本 | 未来 | 取决于真实反馈内容 |
| **v3.0** | ⏳ 候选 | 真实 LLM judge + MCP executor + Web UI | 未来 | 触发条件：≥3 份真实非维护者反馈 |

---

## 二、当前里程碑：Documentation Consolidation（文档收口）

**里程碑目标**：补齐 agent-tool-harness 的产品意图、用户场景、架构、约束、Roadmap、Milestone、模块设计文档体系，让后续开发有文档可循。

**开始日期**：2026-05-11

### 完成定义（Definition of Done）

- [x] `docs/product/PRODUCT_INTENT.md` 创建并通过人工 Review
- [x] `docs/product/USER_SCENARIOS.md` 创建并通过人工 Review
- [x] `docs/product/PROJECT_CONSTRAINTS.md` 创建并通过人工 Review
- [x] `docs/architecture/PRODUCT_ARCHITECTURE.md` 创建并通过人工 Review
- [x] `docs/architecture/TECHNICAL_ARCHITECTURE.md` 迁移并增强（+ 接口稳定性分级）
- [x] `docs/architecture/MODULE_BOUNDARIES.md` 创建并通过人工 Review
- [x] `docs/roadmap/ROADMAP.md` 迁移（保留全部内容）
- [x] `docs/roadmap/MILESTONES.md` 创建（从 ROADMAP 提炼）
- [x] `docs/roadmap/NEXT_STEPS.md` 创建
- [x] `docs/modules/` 下 5 份模块设计文档创建
- [x] `docs/review/ENGINEERING_REVIEW_CHECKLIST.md` 创建
- [x] `docs/review/STALE_DOCS_AUDIT.md` 创建
- [x] `docs/INDEX.md` 更新新目录结构导航
- [x] `README.md` 更新文档链接
- [x] 10 份历史层文档标记 `[HISTORICAL]`
- [x] `git diff --check` 干净
- [x] 无遗留 `TODO` / `TBD` / `待补充`（除非明确标注为未来工作）

**验证方式**：DoD 达成情况由独立 Coding Agent 于 2026-05-11 完成只读审计（审计报告见 plan `ai-agent-robust-tiger.md`），审计确认所有 17 项全部完成。审计发现 5 个 P0/P1 收口问题（版本号不一致、INDEX.md 路由至 HISTORICAL 文档、finding type 计数不一致、旧路径引用），于 `docs: fix consolidation audit findings` commit 修复。

**完成日期**：2026-05-11

### 验收标准

1. 新读者能通过 `docs/INDEX.md` 在 1 分钟内找到自己需要的文档
2. 每份新文档都能独立阅读，不依赖读者预先知道项目历史
3. 文档之间无矛盾（以 `PRODUCT_INTENT.md` → `PROJECT_CONSTRAINTS.md` → `TECHNICAL_ARCHITECTURE.md` 的优先级解决冲突）
4. 后续 Coding Agent 能根据模块设计文档理解每个模块的职责和边界

### 是否允许写代码

**不允许**。本轮只创建和修改文档。禁止修改任何 `.py` 源码或测试文件。

### 是否允许改文档

**允许**。可以创建新文档、修改已有文档、调整目录结构、标记 deprecated。

### 是否允许 tag / push

**不允许**。完成后创建本地 commit（`docs: consolidate product architecture and roadmap docs`），但**不 tag、不 push**。

---

## 三、下一候选里程碑

### v2.x Internal Trial Patch

**触发条件**：
- 收到 ≥1 份真实非维护者反馈
- 反馈经 `FEEDBACK_TRIAGE_WORKFLOW.md` 分流为 `v2.x patch`
- 反馈涉及 bug / 文档断点 / CLI 体验问题（不是 v3.0 能力请求）

**目标**：修复内部试用中发现的具体问题，不新增 v3.0 能力。

**完成定义**：根据具体反馈内容确定。

**是否允许写代码**：允许（仅限修复 v2.x patch 范围内的问题）。

### v3.0 Planning

**触发条件**（来自 `ROADMAP.md` v3.0 gate）：
- **≥3 份真实非维护者反馈**（maintainer rehearsal 和 synthetic 不计入）
- 至少 1 份反馈来自真实内部团队的端到端试用
- 反馈中不包含 security-blocker（如有，先处置安全风险再谈 v3.0）

**目标**：规划 v3.0 的真实 LLM judge / MCP executor / Web UI 等大特性的架构和范围。

**完成定义**：v3.0 PRD + 技术设计文档通过 Review。

**是否允许写代码**：仅允许 prototype 级别的验证代码，不允许合入 main 的功能代码。

---

## 四、里程碑管理规则

1. **每个里程碑必须有明确的完成定义（DoD）**。"差不多好了"不是完成。
2. **每个里程碑必须有明确的停止条件**。超出范围的工作必须停止或被推迟到下一里程碑。
3. **里程碑之间的切换必须显式决策**：当前里程碑完成后，由 maintainer 根据触发条件决定进入哪个候选里程碑。
4. **不允许同时进行两个里程碑**。如果 v2.x patch 正在进行，v3.0 planning 不能同时启动（反之亦然）。
5. **tag 只在确认所有 DoD 达成 + 测试全绿 + 文档一致性检查通过后创建。**
