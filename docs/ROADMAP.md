# Roadmap

## 设计原则

1. **离线优先** — 默认不联网、不需要 API Key，任何需要网络的能力必须 opt-in
2. **确定性优先** — 优先用确定性规则解决问题，LLM 是最后手段
3. **证据驱动** — 每一步产出结构化 artifact，可追溯、可复现
4. **接口隔离** — rule checks ≠ LLM judge，mock replay ≠ RealAgentAdapter
5. **诚实声明** — signal_quality 必须在每次 run 输出中显式披露
6. **范围可控** — 新功能通过独立模块 + Protocol 接口实现，不往现有模块塞逻辑

## 当前阶段：Headless CLI Demo Prototype

**已完成：**
- [x] 13 个 CLI 子命令
- [x] Config Loader（YAML → Spec）
- [x] MockReplayAdapter（good/bad 分支）
- [x] TranscriptReplayAdapter（历史轨迹重放）
- [x] RuleJudge（deterministic 规则）
- [x] ToolDesignAuditor（启发式）
- [x] MarkdownReport（10 artifact + report.md）
- [x] CostTracker（advisory-only）
- [x] TraceSignalAnalyzer（5 类 deterministic 信号）
- [x] TranscriptAnalyzer（failure attribution）
- [x] Bootstrap/Scaffold（AST 扫描生成 draft）
- [x] 58 个测试文件
- [x] 6 个可运行 example

**当前 signal_quality 上限：** `tautological_replay`（mock replay）和
`recorded_trajectory`（transcript replay）。这些不是真实 Agent 能力信号。

## 下一步

### 文档瘦身 + 入口收敛（当前）
- 从 56 份文档精简到 9 份核心文档
- 删除所有历史层、内部试用、push preflight 文档
- 新用户入口收敛为 `README.md` → `docs/START_HERE.md`

### RealAgentAdapter / JudgeProvider / ProviderConfig 设计
- 独立模块 + Protocol 接口实现
- 不往 MockReplayAdapter / RuleJudge 里塞逻辑
- LiveAnthropicTransport 代码已存在但从未验证，需在真实端点测试

### opt-in 真实 LLM trial
- 需要双标志：`--live --confirm-i-have-real-key`
- 需要 4 个 env var
- 仅限内部、有明确安全边界的环境

## 明确不做

以下能力当前明确不做（除非未来独立设计并经过审批）：

- Web UI
- MCP executor
- HTTP / Shell executor
- RAG / 向量库
- 多租户 / 企业 RBAC
- Benchmark / Leaderboard 平台
- Python SDK（`__init__.py` 只导出版本号）
- 跨语言工具支持（当前 Python only）
- 把 rule checks 升级成 LLM judge 巨石
- 把 mock replay 升级成 RealAgentAdapter 巨石
- reporter 自动做通过/不通过决策
