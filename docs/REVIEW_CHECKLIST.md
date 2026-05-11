# Review Checklist

PR review 和代码变更前的自检清单。

## Demo / Core / Real 边界

> 边界定义见 [DEMO_CORE_REAL_BOUNDARY.md](DEMO_CORE_REAL_BOUNDARY.md)。

- [ ] Core 没有新增对 `examples/` 的 import
- [ ] Core 没有新增对 `mock_replay_adapter` 的 import
- [ ] Core 没有新增对 `LiveAnthropicTransport` 的 import
- [ ] Core 没有读取 `.env`
- [ ] Core 没有新增对 OpenAI / Anthropic / DeepSeek 的直接引用
- [ ] Core 没有散落 `if demo / if real` 条件分支
- [ ] Demo 没有 import Real Integration 模块
- [ ] Real Integration 雏形代码没有污染 Demo path

## 架构边界

- [ ] 没有往 `MockReplayAdapter` 里塞真实 Agent 逻辑
- [ ] 没有往 `RuleJudge` 里塞 LLM judge 逻辑
- [ ] CLI 层只做装配，不写业务逻辑
- [ ] reporter 只生成报告，不做通过/不通过决策
- [ ] 新功能通过独立模块 + Protocol 接口实现

## 信号质量

- [ ] 所有 `run` 输出声明了 `signal_quality`
- [ ] mock replay 的输出诚实标注 `tautological_replay`
- [ ] 没有把 deterministic rule check 的 PASS 宣传为"工具好用"

## 安全

- [ ] 没有硬编码 API Key / token / secret
- [ ] 没有读取 `.env` 内容
- [ ] bootstrap / scaffold 不 import 用户代码、不执行用户代码
- [ ] 默认不联网（CI 0 联网）

## 文档一致性

- [ ] README.md 中的 CLI 命令与 argparse 一致
- [ ] 配置文件格式示例与实际解析逻辑一致
- [ ] docs/ 中的文件路径引用指向真实存在的文件
- [ ] 没有引用已删除文档的死链
- [ ] `DEMO_CORE_REAL_BOUNDARY.md` 的模块分类与实际源码一致

## 测试

- [ ] 新功能有对应的测试
- [ ] 没有为让 suite 变绿而放宽断言
- [ ] 没有删除关键测试断言
- [ ] strict xfail 的转正条件仍然成立
- [ ] Demo tests 只证明 demo 跑通，不被当作真实能力证据
- [ ] Contract tests 在 CI（0 联网）中可跑
- [ ] 没有让 demo 方便而迫使 Core 迁就 demo

## 实现状态矩阵

- [ ] `HEADLESS_HARNESS_MODEL.md` 中的实现状态矩阵反映了本次变更
- [ ] `CURRENT_IMPLEMENTATION.md` 的模块分类反映了本次变更
- [ ] 代码存在但未验证的功能标注为 `⚠️ code exists, unverified`
- [ ] 不支持的能力标注为 `❌ not supported`
