# Product Intent（产品意图）

> 本文档回答"这个项目到底是什么、给谁用、解决什么问题"。
> 它是所有架构文档、Roadmap（路线图）、模块设计的根锚点。
> 任何后续设计决策都必须先与本文档对齐。

---

## 一、项目定义

**Agent Tool Harness（Agent 工具执行与约束框架）** 是一个 CLI-first（命令行优先）、offline-first（离线优先）的 **AI Agent 工具设计与使用评估框架**。

它不做以下事情：
- 不运行真实 AI Agent（当前阶段使用 deterministic mock replay）
- 不替代 pytest / unittest 等单元测试框架
- 不提供 Web UI
- 不连接真实外部 API（除非用户通过双标志 opt-in 显式授权）

它做的事情：
- **审计（Audit）** Agent 工具的设计契约是否合理（基于 Anthropic 5 类工具设计原则）
- **生成（Generate）** 评估用例候选，供人工 Review 后转正
- **运行（Run）** deterministic mock replay，记录 Agent 工具调用的完整轨迹
- **评判（Judge）** 工具调用链路是否正确（deterministic rule-based）
- **诊断（Diagnose）** 失败原因，归因到工具设计、eval 设计或 Agent 路径
- **报告（Report）** 生成人类可读的评估报告和 10 个 machine-readable artifact（产物文件）

一句话定位（来自 README:3-5）：

> Agent Tool Harness 是一个 Agent 工具检查、评估集生成与工具使用评估框架。它关注的是：工具作为确定性系统和非确定性 Agent 之间的契约，是否足够适合 Agent 使用。

---

## 二、目标用户

当前阶段（v2.0 Internal Trial Ready）面向 **3 类内部用户**：

### Persona 1：Agent 工具开发者

- **谁**：公司内写 AI Agent 工具（Python 函数/MCP 工具/HTTP 工具）的工程师
- **痛点**：不知道自己的工具设计是否合理——命名是否清晰、输出是否包含 Agent 需要的 evidence、token 策略是否合理、是否容易被 Agent 误用
- **使用方式**：写一份 `tools.yaml` 描述工具契约 → 跑 `audit-tools` 看设计问题 → 跑 `run` 看 mock Agent 能否正确使用
- **关键文档**：`ONBOARDING.md`、`INTERNAL_TRIAL_QUICKSTART.md`

### Persona 2：Eval（评估用例）设计者

- **谁**：为 Agent 的行为正确性设计评估用例的工程师或 QA
- **痛点**：不知道如何写一个"能真正测出 Agent 是否用对工具"的 eval——容易写得太简单（泄露工具名）、或太过拟合（只接受唯一调用顺序）
- **使用方式**：从 `tools.yaml` 生成候选 eval → 人工补充 initial_context / expected_root_cause / judge.rules → promote 转正 → 跑 `audit-evals` 验证
- **关键文档**：`docs/ARTIFACTS.md`（eval 字段约定）、`README.md` §"如何写自己的 evals.yaml"

### Persona 3：质量 Reviewer / 技术管理者

- **谁**：Review 工具设计和 eval 质量的人——可能是 TL、架构师或 on-call reviewer
- **痛点**：Agent 的行为难以复盘——最终回答看起来对，但工具调用链路可能完全错误（用了错误工具、跳过了关键步骤、证据来自不该用的工具）
- **使用方式**：读 `report.md` 看评估摘要 → 回到 `transcript.jsonl` / `tool_calls.jsonl` / `tool_responses.jsonl` 三件套复盘子路径 → 用 `analyze-artifacts` 离线复盘 trace 信号
- **关键文档**：`docs/ARTIFACTS.md`、`docs/architecture/TECHNICAL_ARCHITECTURE.md` §失败归因流程

### 当前阶段**不是**为以下用户设计的

- 外部开源社区用户（当前只面向公司内部小团队）
- 非技术角色的产品经理或业务方
- 需要 Web UI 或 SaaS 平台的用户

---

## 三、解决的核心问题

### 问题 1：Agent 工具设计没有反馈闭环

**现状**：工程师写完一个 Agent 工具（如 `kb.search.search_articles`），通常只验证它"能被调用且不报错"。至于 Agent 是否会在正确时机选它、参数是否来自真实上下文、输出是否给了足够的 evidence——这些在传统开发流程中完全不可见。

**Harness 的解法**：`audit-tools` 对工具设计做 5 维 deterministic 审计（right tools / namespacing / meaningful context / token efficiency / prompt spec），在 Agent 实际使用之前就发现设计问题。

### 问题 2：Agent 行为无法可复现地评估

**现状**：真实 AI Agent 的行为是非确定性的——同一个 prompt，两次运行可能选择不同工具、不同参数顺序。这导致"这次 Agent 用对了工具"无法被固化成一个可复现的评估。

**Harness 的解法**：使用 deterministic mock replay（`MockReplayAdapter`），把 eval 中声明的期望工具调用路径直接回放，产生完全可复现的 PASS/FAIL 信号。同时通过 `signal_quality: tautological_replay` 诚实披露"这不是真实 Agent 行为"。（详见 `docs/architecture/TECHNICAL_ARCHITECTURE.md` §信号质量披露）

### 问题 3：失败无法归因

**现状**：Agent 使用了错误的工具——是工具描述写得太模糊？还是 eval 写得太宽松？还是 Agent prompt 没有要求 evidence grounding？

**Harness 的解法**：`diagnose.json` 和 `report.md` 的 Failure Attribution 段按 4 个 category（tool_design / eval_definition / agent_tool_choice / runtime）归因每一条失败，让 reviewer 知道"该改什么"而不是只知道"FAIL 了"。

---

## 四、与竞品/替代方案的差异

| 维度 | pytest + mock | LLM-as-Judge benchmark | 通用 eval harness | Agent Tool Harness |
|------|-------------|----------------------|-------------------|-------------------|
| 评测对象 | 函数输入→输出 | Agent 最终回答 | 模型输出文本 | **工具的 Agent-适用性 + Agent 工具调用链路** |
| 评判方式 | assert 语句 | LLM 打分（非确定性） | 规则或 LLM | **deterministic rule judge（可复现）** |
| 证据类型 | pass/fail | 单一分数 | 文本相似度 | **10 个 artifact（含 transcript/tool_calls/tool_responses 三件套）** |
| 工具设计审计 | 无 | 无 | 无 | **有（5 类 Anthropic 原则）** |
| 离线可用 | 是 | 否（需联网调 LLM） | 视实现 | **是（默认 0 联网）** |
| 人类 Review 点 | 无显式设计 | 无 | 视实现 | **有（候选审核→promote→audit 的显式人工门）** |
| 失败归因 | 无 | 无 | 有限 | **11 类 deterministic finding + 4 category** |
| 信号质量披露 | 无 | 无 | 无 | **有（signal_quality 字段显式标记能力边界）** |

关键差异总结：

1. **不是测"Agent 最终回答对不对"，而是测"Agent 选工具的链路是否合理"。**
2. **不是用 LLM 打分（非确定性、需联网），而是用 deterministic rules（可复现、离线）。**
3. **不是只管"过还是没过"，而是管"为什么没过、该改什么"。**
4. **不是替代单测，而是在单测之上加了一层"工具 Agent-适用性"评估。**

理论来源（README:5-12 引用）：Anthropic Engineering — [Writing effective tools for AI agents—using AI agents](https://www.anthropic.com/engineering/writing-tools-for-agents)，对应五类工具设计原则：
- Choosing the right tools for agents
- Namespacing your tools
- Returning meaningful context from tools
- Optimizing tool responses for token efficiency
- Prompt-engineering tool descriptions and specs

---

## 五、当前阶段最小可用场景

v2.0 Internal Trial Ready 的最小可用场景（来自 `INTERNAL_TRIAL_QUICKSTART.md` 和 ROADMAP v2.0 终点定义）：

**一个内部小团队（1-5 人），在自己的 laptop 上，10-15 分钟内**：

1. Clone 仓库 + 创建虚拟环境 + `pip install -e .`
2. 写一份最小 `tools.yaml`（或跑 `bootstrap --source <dir>` 自动生成草稿）
3. 跑 `audit-tools` 检查工具设计
4. 跑 `generate-evals` → 人工 review → `promote-evals` 生成正式 eval
5. 跑 `run --mock-path good` + `run --mock-path bad`（good 全 PASS / bad 全 FAIL）
6. 看 `report.md` 了解结果，看 `tool_calls.jsonl` / `tool_responses.jsonl` 复盘细节
7. 通过 `INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md` 提交结构化反馈

**最小可用意味着**：
- 不需要连接真实 AI Agent（mock replay 足够验证工具契约和 eval 质量）
- 不需要配置密钥或外部服务（纯本地、0 联网）
- 不需要理解全部 24 份文档（只需看 QUICKSTART 的 5 条命令）

---

## 六、当前不追求什么

以下能力明确不在 v2.0 范围（来自 ROADMAP v2.0 不包含表），不属于当前产品定位：

| 不追求的能力 | 原因 |
|------------|------|
| 真实 LLM Agent 自动评估 | 需要密钥管理 + 费用 + 隐私 + 网络依赖，v2.0 仅是本地 offline-first harness |
| Web UI | CLI + artifact 优先，UI 是另一个独立 surface |
| MCP/HTTP/Shell executor | 真实执行器需要独立安全模型 + 长期维护 |
| 自动修改用户工具代码（auto-patch） | 永久 dry-run |
| 大规模 benchmark / leaderboard | 需要独立 dataset 治理 |
| 多租户 SaaS / 计费 / RBAC | 需要独立账号体系 |
| 向量库 / RAG 集成 | 超出工具评估范围 |
| 跨语言工具支持（非 Python） | v2.0 仅 Python |

---

## 七、文档与意图的关系

本文档是产品意图的**根定义**。如果后续文档（架构、Roadmap、模块设计）与本文档冲突，以本文档为准。如需改变产品意图（例如扩展到开源社区、增加 Web UI），必须先更新本文档并经过人工 Review。
