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

## Agent2Harness Main Flow

> 主流程定义见 [AGENT2HARNESS_MAIN_FLOW.md](AGENT2HARNESS_MAIN_FLOW.md)。

- [ ] Agent2HarnessAdapter wrapper 不改旧 inner adapter 行为
- [ ] CoreEvaluation 不自动生成 ReviewDecision
- [ ] core_report_bridge 只做数据转换，不做 pass/fail 裁决
- [ ] report_summary_to_report_dict 不添加 decision / reviewer 字段
- [ ] evaluation_result_to_report_dict 不添加 decision / reviewer 字段
- [ ] build_demo_core_flow() 返回的 DemoCoreFlowResult 是纯数据（无 IO 引用）
- [ ] assembly.py 中旧路径（build_demo_runtime）和新路径（build_demo_core_flow）并存
- [ ] Core Flow 新模块不 import dotenv / os.environ
- [ ] Core Flow 新模块不 import 真实 provider（LiveAnthropicTransport 等）
- [ ] ReviewDecision 必须人工显式创建，EvaluationResult 无 decision 字段

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

## LLM Provider Config / Fake Judge

> 设计文档见 [LLM_PROVIDER_CONFIG.md](LLM_PROVIDER_CONFIG.md)。

- [ ] 配置中没有 inline `api_key` 字段（只允许 `api_key_env`）
- [ ] `LLMProviderConfig` 不存储 API key 本体（只存环境变量名）
- [ ] `resolve_api_key()` 是唯一读取 `os.environ` 的入口
- [ ] parse 阶段不读取环境变量
- [ ] 没有自动调用 `load_dotenv()`
- [ ] `FakeJudgeProvider` 不发起任何网络请求
- [ ] `JudgeFinding` 不包含 `decision` / `reviewer` 字段
- [ ] `FakeJudgeProvider.evaluate()` 不调用 `resolve_api_key()`
- [ ] `compatible` provider 必须提供 `base_url`
- [ ] `compatible` provider 无 `base_url` 时 `ConfigValidationError` 被正确抛出
- [ ] `api_key` inline 字段被显式拒绝（`ConfigValidationError`）
- [ ] 测试默认只使用 `FakeJudgeProvider`（零联网）
- [ ] 真实 provider 测试标记为 opt-in（`@pytest.mark.skipif` 或明确隔离）

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
