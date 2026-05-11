# Project Constraints（项目约束）

> 本文档定义 agent-tool-harness 当前阶段**明确不做什么**，以及为什么。
> 它是范围控制的第一道闸门——任何新增能力必须先过本文档的约束检查。
> 约束可能随项目阶段演进而调整，但调整必须先更新本文档并经过人工 Review。

---

## 一、核心设计原则（约束的来源）

以下原则来自 `docs/roadmap/ROADMAP.md` §设计原则，是项目约束的理论基础：

1. **小步、根因、可证伪**：每一步只做"让最小闭环更可信"的事。不是毕业标准一部分的事不做。
2. **fake-first（模拟优先）**：默认用 mock/fake/deterministic 路径验证，不依赖真实外部系统。
3. **local-first（本地优先）**：所有核心路径默认纯本地运行，不联网。
4. **review-first（审核优先）**：任何自动化生成（eval 候选、工具草稿）必须经过人工 review 才能进入正式流程。
5. **artifact-first（产物优先）**：不只看最终回答。每次 run 必须生成完整 10 个 artifact，失败复盘以 raw JSONL 为准。
6. **signal-quality-disclosure（信号质量披露）**：任何评估信号必须诚实标记其能力边界（如 `tautological_replay`、`deterministic_heuristic`）。

---

## 二、当前阶段明确不做什么

以下能力在 v2.0（当前主线终点）及之前的版本中，**明确不做**。
来源：`docs/roadmap/ROADMAP.md` §v2.0 不包含的能力 + 各阶段"非目标"。

### 2.1 不做真实 LLM Judge 自动评估服务

**定义**：不接真实 OpenAI / Anthropic API 作为评估裁判（Judge），不发送用户 prompt / tool response 到外部 LLM 服务。

**为什么**：
- 真实 LLM Judge 会引入密钥管理（API key 泄漏风险）
- 费用不可控（每次 judge call 消耗 token）
- 网络依赖（CI 不能跑、离线环境不能跑）
- 非确定性（同一份 artifact 两次 judge 可能不同结果，违背"可复现评估"的设计原则）

**当前替代方案**：`RuleJudge`（deterministic rule-based）+ `CompositeJudgeProvider`（多 advisory dry-run）+ 双标志 opt-in 的 `AnthropicCompatibleJudgeProvider`（用户在自己环境显式授权后才能触发）。

**未来可能打开的条件**：v3.0+，且有明确的密钥管理 / 费用控制 / 脱敏方案。

### 2.2 不做 Web UI

**定义**：不开发任何 Web 界面（包括但不限于 dashboard、报告浏览器、在线编辑器）。

**为什么**：
- Web UI 是独立的产品 surface，需要前端技术栈、部署运维、认证授权——与 CLI + artifact 的核心定位无关
- 所有 artifact 已是 machine-readable JSON + human-readable Markdown，可以被任何现有工具消费
- 保持"一个仓库只做一件事"

**当前替代方案**：`report.md` + 10 个 JSON/JSONL artifact，用户用自己习惯的编辑器/查看器打开。

**未来可能打开的条件**：v3.0+，且作为独立仓库/独立服务开发，不进入本仓库。

### 2.3 不做 MCP / HTTP / Shell Executor（真实执行器）

**定义**：不实现能连接真实外部 MCP server、HTTP API、Shell 命令的工具执行器。

**为什么**：
- 真实执行器需要独立的安全模型（sandbox、网络隔离、超时控制）
- 每个执行器类型的错误模式、超时行为、副作用管理完全不同
- 当前只有 `PythonToolExecutor`（本地 Python 函数调用），且仅仅覆盖 `required/type/enum` 三类 schema 校验
- 真实执行器的引入会让 `run` 变成"有副作用的操作"，违背 artifact-first 的复盘原则

**当前替代方案**：`MockReplayAdapter` + `TranscriptReplayAdapter`，工具响应来自 fixture 或已有 run 的录制，不需要真实执行。

**未来可能打开的条件**：v3.0+，且每个新 executor 类型有独立的安全模型文档 + sandbox 测试。

### 2.4 不做自动修改用户工具代码（auto-patch）

**定义**：不自动修改用户的 `tools.yaml` 或 Python 工具源码。

**为什么**：
- 永久 dry-run 原则：框架只诊断和报告，不替用户做修改决策
- 自动修改工具代码可能引入 bug 或改变工具语义——风险评估必须由人类完成

**当前替代方案**：audit findings 的 `suggestion` / `suggested_fix` 字段给出可执行的修复方向，但由人类执行修改。

### 2.5 不做大规模 Benchmark / Leaderboard

**定义**：不维护公开的 Agent 工具评分排行榜，不收集跨团队的评估数据做横向对比。

**为什么**：
- 需要独立 dataset 治理（benchmark 的维护本身就是独立工程）
- 需要跨团队的隐私隔离
- v2.0 定位是"内部小团队本地自评工具"，不是"平台化评分服务"

### 2.6 不做多租户 / SaaS / 计费

**定义**：不做账号体系、权限系统、租户隔离、计费系统。

**为什么**：v2.0 是本地 CLI 工具，不托管任何服务。多租户架构需要独立的合规和安全体系。

### 2.7 不做向量库 / RAG 集成

**定义**：不引入向量数据库、embedding 模型、RAG pipeline。

**为什么**：超出"工具评估"范围。evaluation harness 的评测对象是工具契约和 Agent 调用链路，不是检索质量。

### 2.8 不做跨语言工具支持（当前阶段仅 Python）

**定义**：`scaffold-tools` 只支持 Python AST 静态扫描，`PythonToolExecutor` 只支持 Python 函数调用。不支持 JavaScript / Go / Rust 工具。

**为什么**：每种语言的 AST 解析、动态加载、安全隔离机制完全不同。Python 优先是因为当前内部团队的 Agent 工具主要是 Python。

**未来可能打开的条件**：v3.0+，通过 MCP executor（协议标准，不依赖语言）间接覆盖。

---

## 三、安全与工程边界

### 3.1 联网策略

| 场景 | 联网？ | 条件 |
|------|--------|------|
| CI / smoke 测试 | **0 联网** | monkeypatch 禁用 `socket.socket` |
| `run`（默认） | 不联网 | deterministic mock replay |
| `judge-provider-preflight` | **不联网**（纯本地） | 只检查 env/gitignore 配置 |
| `audit-tools` / `audit-evals` | 不联网 | deterministic 启发式 |
| `scaffold-tools` / `bootstrap` | 不联网 | AST 静态扫描 |
| 真实 live judge | **用户显式 opt-in** | 双标志（`--live` + `--confirm-i-have-real-key`）+ 4 个 env var |

### 3.2 密钥与敏感数据处理

- `.env` 文件永久排除在 git 之外（`.gitignore` 已配置）
- `.env.example` 仅含占位符，不含真实值
- 任何 artifact / report / log **不写入** `api_key` / `Authorization` / `Bearer` / 完整 prompt body / 完整 response body
- 环境变量命名空间隔离：使用 `AGENT_TOOL_HARNESS_LLM_*` 前缀，不与 `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` 等通用名冲突
- 此边界由 69+ 条 contract test 钉死

### 3.3 依赖添加策略

- 当前运行时依赖：**仅 PyYAML>=6.0**（`pyproject.toml:11`）
- 原则：**0 新增依赖** —— 任何功能优先用标准库实现
- 如需新增依赖，必须满足：
  1. 无法用标准库合理实现（如 YAML 解析）
  2. 依赖本身稳定、安全、0 子依赖或极少子依赖
  3. 在 `pyproject.toml` 中声明
  4. 更新本文档的依赖策略说明

### 3.4 不被允许的代码模式

来自 `docs/roadmap/ROADMAP.md` §全局停止规则 + `docs/TESTING.md` 测试纪律：

- 不允许放宽断言来追求测试通过
- 不允许删除关键断言
- 不允许把失败测试改成空测试
- 不允许忽略 bad path
- 不允许给 `examples/runtime_debug` 之外的真实业务符号做硬编码
- 不允许在 RuleJudge / Auditor 里加"为了让本次 run PASS"的临时支路
- 不允许把 `MockReplayAdapter.SIGNAL_QUALITY` 改成更高等级
- 不允许用 xfail 掩盖当前阶段应该满足的需求

---

## 四、版本号管理策略（当前状态与建议）

**当前状态（事实）**：
- `agent_tool_harness/__init__.py:14`: `__version__ = "0.1.0"`
- `pyproject.toml:8`: `version = "0.1.0"`
- `git tag`: 最新为 `v2.0`

**存在的问题**：代码级版本号（0.1.0）与 git tag（v2.0）严重不一致。`0.1.0` 是项目初始化时写的，之后未更新。

**约束决定**：版本号统一策略待人工确认后执行，在此之前不修改任一版本号。详见 `docs/roadmap/NEXT_STEPS.md`。

---

## 五、文档维护策略

- **canonical 文档**（产品意图、架构、约束、Roadmap、MILESTONES、模块设计）：每个 milestone 结束时 review 是否仍准确
- **历史层文档**：标记 `[HISTORICAL]`，不删除但也不更新（除非发现事实错误）
- **运行日志类文档**（DOGFOODING_LOG）：仅追加，不修改历史记录
- **文档不得相互矛盾**：如发现矛盾，以 `PRODUCT_INTENT.md` → `PROJECT_CONSTRAINTS.md` → `TECHNICAL_ARCHITECTURE.md` 的优先级顺序为准

---

## 六、约束例外流程

如果需要突破上述任一约束（例如：确实需要新增一个依赖，或确实需要接真实 LLM judge）：

1. 在对应的设计文档或 Roadmap 中提出
2. 更新本文档，修改对应约束并注明原因
3. 人工 Review 通过后才能进入实现
4. **不允许**"先在代码里实现，再补文档"——约束变更是设计决策，必须在实现之前
