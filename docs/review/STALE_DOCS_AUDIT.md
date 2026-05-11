# Stale Docs Audit（旧文档清理审计）

> 审计日期：2026-05-11
> 审计范围：`docs/` 目录下全部 25 份现有文档
> 审计目的：为 Documentation Consolidation Milestone（文档收口里程碑）提供清理依据
> 原则：本轮不删除任何旧文档，仅分类标记，删除建议需人工确认

---

## 一、现有文档全景（25 份 + 1 个模板文件）

| # | 文件 | 大小 | 最后修改 | 分类 |
|---|------|------|---------|------|
| 1 | `ARCHITECTURE.md` | 22KB | 2026-05-03 | 核心架构 |
| 2 | `ARTIFACTS.md` | 36KB | 2026-04-29 | 核心参考 |
| 3 | `ROADMAP.md` | 85KB | 2026-05-03 | 核心路线 |
| 4 | `TESTING.md` | 23KB | 2026-04-28 | 核心规范 |
| 5 | `INDEX.md` | 3KB | 2026-05-03 | 导航索引 |
| 6 | `ONBOARDING.md` | 11KB | 2026-05-03 | 接入指南 |
| 7 | `TRY_IT.md` | 8KB | 2026-04-28 | 试用路径 |
| 8 | `TRY_IT_v1_7.md` | 5KB | 2026-04-28 | 试用路径(v1.7) |
| 9 | `INTERNAL_TRIAL.md` | 10KB | 2026-04-29 | 内部试用 |
| 10 | `INTERNAL_TRIAL_QUICKSTART.md` | 5KB | 2026-04-29 | 内部试用快速 |
| 11 | `INTERNAL_TRIAL_LAUNCH_PACK.md` | 15KB | 2026-04-29 | 试用启动包 |
| 12 | `INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md` | 6KB | 2026-04-29 | 反馈模板 |
| 13 | `INTERNAL_TRIAL_FEEDBACK_SUMMARY.md` | 9KB | 2026-04-29 | 反馈汇总 |
| 14 | `INTERNAL_TRIAL_DOGFOODING_LOG.md` | 16KB | 2026-04-29 | Dogfooding 日志 |
| 15 | `INTERNAL_TEAM_SELF_SERVE_TRIAL.md` | 12KB | 2026-04-29 | 自助试用 |
| 16 | `FIRST_REAL_TRIAL_EXECUTION_PLAN.md` | 7KB | 2026-04-29 | 首次真实试用 |
| 17 | `FIRST_INTERNAL_TRIAL_HANDOFF.md` | 8KB | 2026-04-29 | 试用交接 |
| 18 | `FIRST_INTERNAL_TRIAL_INVITE_TEMPLATE.md` | 3KB | 2026-04-29 | 邀请模板 |
| 19 | `FEEDBACK_TRIAGE_WORKFLOW.md` | 10KB | 2026-04-29 | 反馈分流 |
| 20 | `REAL_TRIAL_CANDIDATE.md` | 4KB | 2026-04-29 | 试用候选 |
| 21 | `PUSH_PREFLIGHT_CHECKLIST.md` | 9KB | 2026-04-29 | 推送检查表 |
| 22 | `PUSH_READINESS_SUMMARY.md` | 5KB | 2026-04-29 | 推送就绪摘要 |
| 23 | `V2_X_RELEASE_CANDIDATE_NOTES.md` | 5KB | 2026-04-29 | v2.x 封板 |
| 24 | `V1_3_LIVE_TRANSPORT_DESIGN.md` | 10KB | 2026-04-28 | v1.3 设计 |
| 25 | `V1_4_LIVE_TRANSPORT_IMPLEMENTATION.md` | 9KB | 2026-04-28 | v1.4 实现 |
| 26 | `templates/INTERNAL_TRIAL_REQUEST_TEMPLATE.md` | - | 2026-04-29 | 请求模板 |

---

## 二、分类判定

### 2.1 保持有效且应保留的文档（CANONICAL — 10 份）

这些文档是项目当前运行的核心，位于信息架构的顶层，内容未过期：

| 文档 | 理由 |
|------|------|
| `ARTIFACTS.md` | 10 个 artifact 的完整 schema 定义，是项目技术契约的核心。被 69 个测试引用。**不可替代**。 |
| `TESTING.md` | 测试纪律文档，定义了 strict xfail 制度、信号质量测试纪律、doc/CLI 一致性测试。被多个测试 pin 住。**不可替代**。 |
| `ONBOARDING.md` | 10 分钟接入路径。被 `test_doc_cli_snippets.py` 和 `test_onboarding_*` 测试 pin 住。内容有效。 |
| `INDEX.md` | 按角色路由的文档索引。被 `test_docs_index.py` 钉死 4 个角色路由。需要更新以反映新目录结构。 |
| `INTERNAL_TRIAL_QUICKSTART.md` | 5 条命令 10-15 分钟最小闭环。是当前新用户最常被引用的入口。 |
| `INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md` | 结构化反馈模板含 §11 triage 自评。仍在收反馈阶段使用。 |
| `INTERNAL_TRIAL_FEEDBACK_SUMMARY.md` | 反馈汇总，追踪 v3.0 gate 的真实反馈数。需持续更新。 |
| `FEEDBACK_TRIAGE_WORKFLOW.md` | 5 类决策表，maintainer 分流操作手册。被测试 pin 住。 |
| `V2_X_RELEASE_CANDIDATE_NOTES.md` | v2.0 封板判断，maintainer 决定 tag 时的参考。 |
| `templates/INTERNAL_TRIAL_REQUEST_TEMPLATE.md` | 自助试用请求模板，仍有使用价值。 |

### 2.2 内容有效但需迁移/重组的文档（MIGRATE — 3 份）

这些文档内容本身有效，但应迁移到新的子目录结构中，并在原位置保留重定向或说明：

| 文档 | 迁移目标 | 理由 |
|------|---------|------|
| `ARCHITECTURE.md` | → `docs/architecture/TECHNICAL_ARCHITECTURE.md` | 内容是技术架构，不是产品架构。新位置更准确。原位置保留简短重定向文件（指向新位置），避免断链。 |
| `ROADMAP.md` | → `docs/roadmap/ROADMAP.md` | 85KB 的 ROADMAP 是核心资产，应移入 `roadmap/` 子目录。原位置保留简短重定向文件。注意：现有 ROADMAP 本质是"工程日志 + 设计决策记录"，本轮迁移不重写内容，只在文件头加注说明。 |
| `TRY_IT.md` | → 保留在 `docs/` 根目录 | 被 `test_doc_try_it.py` 测试 pin 住，且是外部用户高频入口。移动风险大于收益。 |

### 2.3 历史层文档（HISTORICAL — 10 份）

这些文档记录了过去的设计决策或执行过程，对当前使用者不再必要，但保留作为历史参考。应在文件头部标记 `[HISTORICAL]` 标签，并从主索引（INDEX.md）中移除路由：

| 文档 | 历史价值 | 保留原因 |
|------|---------|---------|
| `V1_3_LIVE_TRANSPORT_DESIGN.md` | 记录 v1.3 的 LiveAnthropicTransport 设计决策 | 已实现并迭代到 v1.4/v1.6，但设计思路对理解当前实现有参考价值 |
| `V1_4_LIVE_TRANSPORT_IMPLEMENTATION.md` | 记录 v1.4 的实现细节和测试覆盖矩阵 | 理解 transport 安全模型的演变过程 |
| `TRY_IT_v1_7.md` | v1.7 版本的试用路径 | 被 `TRY_IT.md` 取代，但记录了 v1.7 特定功能（preflight + audit-judge-prompts）的试用方式 |
| `PUSH_PREFLIGHT_CHECKLIST.md` | maintainer 推送前的自检表 | 被 `V2_X_RELEASE_CANDIDATE_NOTES.md` 引用，仍有参考价值 |
| `PUSH_READINESS_SUMMARY.md` | 推送就绪摘要 | 已有 historical pointer 指向 RC notes，但本身内容过期 |
| `INTERNAL_TRIAL_LAUNCH_PACK.md` | v2.0 试用启动包的 umbrella 页 | INDEX.md 已将新读者路由到 QUICKSTART，但作为历史参考保留 |
| `INTERNAL_TRIAL.md` | 完整 internal trial 接入路径 | 被 QUICKSTART 取代作为主入口，但仍包含 QUICKSTART 没有的详细排查指引 |
| `INTERNAL_TEAM_SELF_SERVE_TRIAL.md` | 自助试用指南 | 对想自助跑的团队仍有参考价值，但非主入口 |
| `FIRST_REAL_TRIAL_EXECUTION_PLAN.md` | 首次真实试用的 9 节执行包 | 已被 `FEEDBACK_TRIAGE_WORKFLOW.md` 和 `V2_X_RELEASE_CANDIDATE_NOTES.md` 覆盖核心内容 |
| `FIRST_INTERNAL_TRIAL_HANDOFF.md` | maintainer 邀请第一位试用者的交接文档 | 首次试用已完成或即将完成，后续不再需要此文档 |
| `FIRST_INTERNAL_TRIAL_INVITE_TEMPLATE.md` | 试用邀请的 IM 模板 | 首次邀请已发出，后续可复用但非高频 |

### 2.4 运行日志/append-only 文档（LOG — 2 份）

这些文档记录运行过程，不参与信息架构路由，内容随时间增长：

| 文档 | 性质 | 处理建议 |
|------|------|---------|
| `INTERNAL_TRIAL_DOGFOODING_LOG.md` | maintainer rehearsal 的 dry-run 记录 | 保留，不计入真实反馈，仅追加。与 v3.0 gate 严格隔离。 |
| `REAL_TRIAL_CANDIDATE.md` | 第一个最小试用工具的候选指南 | 保留，与 REVIEW_CHECKLIST §6 联动，对选工具仍有参考价值 |

### 2.5 与本文档收口后新增文档潜在冲突的旧文档

以下旧文档的观点可能与本轮新增的产品/架构文档不完全一致（通常因为旧文档是工程日志视角，新文档是产品架构视角）：

| 旧文档 | 潜在冲突 | 处理方式 |
|--------|---------|---------|
| `ARCHITECTURE.md` | 模块职责描述偏工程实现，缺少产品视角的模块边界定义 | 迁移至 `architecture/TECHNICAL_ARCHITECTURE.md`，互补而非冲突。新增 `architecture/MODULE_BOUNDARIES.md` 补充产品级模块边界。 |
| `ROADMAP.md` | 85KB 的工程日志格式不利于快速扫描和决策 | 迁移至 `roadmap/ROADMAP.md`，新增 `roadmap/MILESTONES.md` 提供可扫描的里程碑表。原 ROADMAP 作为详细参考保留。 |
| `INDEX.md` | 4 角色路由模型仍然有效，但需纳入新文档的导航 | 更新 INDEX.md，新增"想了解产品定位/架构/模块设计的人"角色路由。 |

---

## 三、建议操作汇总

### 本轮执行（Documentation Consolidation Milestone 内）

| 操作 | 涉及文档 | 说明 |
|------|---------|------|
| **迁移** | `ARCHITECTURE.md` → `docs/architecture/TECHNICAL_ARCHITECTURE.md` | 内容迁移，原位置放简短重定向 |
| **迁移** | `ROADMAP.md` → `docs/roadmap/ROADMAP.md` | 内容迁移，原位置放简短重定向 |
| **标记 [HISTORICAL]** | 10 份历史层文档（见 2.3） | 在文件头部加 `> [HISTORICAL]` 标签 + 指向 canonical 文档的链接 |
| **更新** | `INDEX.md` | 新增文档目录结构导航，更新角色路由 |
| **更新** | `README.md` | 更新文档链接指向新路径 |

### 建议未来操作（需人工确认后执行）

| 操作 | 涉及文档 | 条件 |
|------|---------|------|
| **合并** | `TRY_IT.md` + `TRY_IT_v1_7.md` | 当 v1.7 特定功能不再需要单独试用路径时 |
| **合并** | `INTERNAL_TRIAL.md` + `INTERNAL_TRIAL_QUICKSTART.md` + `INTERNAL_TRIAL_LAUNCH_PACK.md` | 当内部试用流程稳定、不再需要多份文档覆盖不同场景时 |
| **删除** | `PUSH_READINESS_SUMMARY.md` | 当确认所有内容已被 `V2_X_RELEASE_CANDIDATE_NOTES.md` 覆盖时 |
| **删除** | `FIRST_INTERNAL_TRIAL_HANDOFF.md` | 当首次试用交接完成、不再需要参考时 |
| **删除** | `FIRST_INTERNAL_TRIAL_INVITE_TEMPLATE.md` | 当确认不再需要邀请更多试用者时 |
| **归档** | `V1_3_LIVE_TRANSPORT_DESIGN.md` + `V1_4_LIVE_TRANSPORT_IMPLEMENTATION.md` | 可移至 `docs/archive/` 目录（如果认为 `[HISTORICAL]` 标签不够） |

---

## 四、本轮不删除旧文档的原因

1. **测试依赖**：多份旧文档被 `tests/test_doc_*.py` 系列测试 pin 住（如 `test_doc_try_it.py`、`test_docs_index.py`、`test_docs_cli_snippets.py`、`test_doc_roadmap_consistency.py`）。删除会破坏测试。

2. **历史上下文**：旧文档记录了 v0.1 → v2.0 的完整演进过程，对理解"为什么某些设计是这样"有不可替代的参考价值。例如 `V1_3_LIVE_TRANSPORT_DESIGN.md` 记录了双标志 opt-in 契约的设计动机。

3. **渐进式替换**：新文档体系需要在人工 Review 和实际使用中验证其有效性，不能一次性替换所有旧文档。旧文档作为 fallback 保留是安全的做法。

4. **安全边界**：任何删除操作都有不可逆风险。`[HISTORICAL]` 标记和重定向文件是最低风险的渐进式清理方式。

---

## 五、与新文档体系的对照

| 新文档（本轮创建） | 对应的旧文档（内容来源） | 关系 |
|-------------------|----------------------|------|
| `docs/product/PRODUCT_INTENT.md` | README:3-25, ROADMAP:42-100 | 从多处提炼，形成独立的产品意图论述 |
| `docs/product/USER_SCENARIOS.md` | INTERNAL_TRIAL_QUICKSTART, ONBOARDING, TRY_IT, INDEX | 从操作手册提炼为用户场景视角 |
| `docs/product/PROJECT_CONSTRAINTS.md` | ROADMAP 各阶段"非目标"+"停止规则", README 能力边界 | 从散落的约束中提炼为统一约束文档 |
| `docs/architecture/PRODUCT_ARCHITECTURE.md` | ARCHITECTURE 核心链路, ARTIFACTS | 从技术视角转化为产品视角 |
| `docs/architecture/TECHNICAL_ARCHITECTURE.md` | **ARCHITECTURE.md（直接迁移）** | 内容升级，增加稳定接口标记 |
| `docs/architecture/MODULE_BOUNDARIES.md` | ARCHITECTURE 模块职责段, 源码 docstring | 从 ARCHITECTURE 提炼 + 新增边界规则 |
| `docs/roadmap/ROADMAP.md` | **ROADMAP.md（直接迁移）** | 保留全部内容，头部加说明 |
| `docs/roadmap/MILESTONES.md` | ROADMAP 阶段总览表 | 从 85KB ROADMAP 提炼为可扫描的里程碑表 |
| `docs/roadmap/NEXT_STEPS.md` | ROADMAP v2.0 终点定义 + v3.0 backlog | 全新文档，填补"下一步做什么"的空白 |
| `docs/modules/*_DESIGN.md` (5 份) | ARCHITECTURE 模块职责段, 源码 docstring, ROADMAP 各轮记录 | 从散落信息整合为模块级设计文档 |
| `docs/review/ENGINEERING_REVIEW_CHECKLIST.md` | TESTING.md, ROADMAP 停止规则 | 全新文档，系统化 Review 标准 |
| `docs/review/STALE_DOCS_AUDIT.md` | （本文档本身） | 全新文档，本轮清理依据 |
