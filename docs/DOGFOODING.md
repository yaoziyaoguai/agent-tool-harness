# Dogfooding

> 本文档定义 Agent2Harness 项目的 dogfood 分层和对应安全边界。
> Dogfood = "吃自己的狗粮"，即在实际使用中验证 harness 自身。
>
> **重要定位（2026-05-13 架构收口）：** agent-tool-harness 不运行 Agent。
> 唯一接入路径是 TraceImportAdapter——用户用自己的 runner/CI 运行 Agent，
> 产出 trace/log，通过 TraceImportAdapter 导入。后续核心方向是 tool-use inspection
> （详见 [TOOL_USE_INSPECTION_SDD.md](TOOL_USE_INSPECTION_SDD.md)），不是跑更多 Agent。

---

## Dogfood 分层

### Level 0: Unit / Integration Tests

**状态**: ✅ 已覆盖（`tests/` 下所有测试）。

**含义**: 使用 pytest + tmp_path 验证每个模块的独立正确性。

**安全边界**: 零网络、零文件系统副作用（用 tmp_path）、deterministic。

---

### Level 4A: Real LLM Judge Dogfood（agent-tool-harness 侧）

**状态**: ✅ 已完成（2026-05-13）。

**含义**: 仅 agent-tool-harness 的 LLM JudgeProvider 调用真实 LLM/API
（anthropic-compatible 或 openai-compatible）。Agent 侧（my-first-agent wrapper）
仍使用 FakeProvider，不读 .env，不联网。

**安全门控**: `--env-file` + `--live` + `--confirm-i-have-real-key` 缺一不可。

**已知结果**: RuleJudge passed，JudgeFinding 生成（advisory），
LLM transport normalization layer 已修复（2026-05-14），openai-compatible + anthropic-compatible 均已验证。

**关键约束**: JudgeFinding 为 advisory only；RuleJudge 仍决定 EvaluationResult.passed；
ReviewDecision 不自动生成。

---

## 核心不变式

所有 dogfood level 共同遵守：
- ReviewDecision 不由机器自动生成
- RuleJudge 决定 deterministic passed
- JudgeFinding 为 advisory only
- signal_quality 必须在报告中显式披露
- 不自动读取 .env（除非用户显式 opt-in）
- 不自动调用外部 API
