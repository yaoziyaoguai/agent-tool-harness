# LLM Provider Configuration and Judge Foundation

## 1. Goal

LLM provider 接入是为了让 Agent2Harness 在未来可以用大模型生成 JudgeFinding，
辅助评估 Agent tool-use 行为。

**不是为了：**
- 取代 RuleJudge（deterministic baseline 永远是 ground truth）
- 自动裁决（ReviewDecision 必须人工显式创建）
- 默认调用真实 API（必须 opt-in：`--live` + `--confirm-i-have-real-key`）
- 绕过 human review（LLM 产出是 advisory，不是最终结论）

**是为了：**
- 让 RuleFinding + JudgeFinding 在 EvaluationResult 中并列存在
- 让人工 Reviewer 看到"规则引擎怎么说 vs LLM 怎么说"的完整图景
- 为 future 提供安插多 provider（OpenAI / Anthropic / compatible）的配置模型

## 2. Provider families

支持四类 provider：

1. **OpenAI native** — 使用官方 OpenAI API endpoint（`https://api.openai.com/v1`）
2. **OpenAI-compatible** — 用户指定 base_url，遵循 OpenAI chat completions 协议
3. **Anthropic native** — 使用官方 Anthropic Messages API endpoint
4. **Anthropic-compatible** — 用户指定 base_url，遵循 Anthropic Messages 协议

说明：
- `native` 使用官方默认 endpoint，无需显式 base_url
- `compatible` 必须提供 base_url（如 DeepSeek、阿里云 Coding Plan 等）
- `compatible` 仍然遵守同一个协议族的 request/response 约束
- 未来可扩展（如 Gemini / Groq），通过新增 ProviderFamily 枚举值实现

## 3. Configuration model

```yaml
providers:
  openai-main:
    family: openai
    compatibility: native
    api_key_env: AGENT_TOOL_HARNESS_OPENAI_API_KEY
    model: gpt-4.1-mini

  deepseek:
    family: openai
    compatibility: compatible
    base_url: https://api.deepseek.com/v1
    api_key_env: AGENT_TOOL_HARNESS_DEEPSEEK_API_KEY
    model: deepseek-chat

  anthropic-main:
    family: anthropic
    compatibility: native
    api_key_env: AGENT_TOOL_HARNESS_ANTHROPIC_API_KEY
    model: claude-3-5-sonnet-latest

  anthropic-compatible:
    family: anthropic
    compatibility: compatible
    base_url: https://example.com/anthropic-compatible
    api_key_env: AGENT_TOOL_HARNESS_ANTHROPIC_COMPAT_API_KEY
    model: claude-compatible-model
```

要求：
- 配置样例不能包含真实 key
- 只允许 `api_key_env`（环境变量名），禁止 `api_key` inline 字段
- `base_url` 对 `compatible` 必填，对 `native` 可选
- `model` 必填
- `timeout_seconds` / `max_tokens` / `temperature` 可选

### 核心数据类型

```python
class ProviderFamily(str, Enum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"

class ProviderCompatibility(str, Enum):
    NATIVE = "native"
    COMPATIBLE = "compatible"

@dataclass
class LLMProviderConfig:
    name: str                    # provider 唯一标识
    family: ProviderFamily       # openai / anthropic
    compatibility: ProviderCompatibility  # native / compatible
    model: str                   # 模型名
    api_key_env: str             # 环境变量名（非 key 本体）
    base_url: str | None = None  # compatible 必填
    timeout_seconds: float = 30.0
    max_tokens: int | None = None
    temperature: float | None = None
```

## 4. Safety model

1. **默认不调用真实 LLM** — FakeJudgeProvider 是默认测试 provider
2. **默认不读取 .env** — `load_dotenv()` 不在任何模块启动时自动调用
3. **不自动 load_dotenv** — 用户如果想用 .env，需自行在调用前 `load_dotenv()`
4. **只从 os.environ 读取已存在的环境变量** — `resolve_api_key()` 是显式方法
5. **用户必须显式指定 provider** — 通过 `--llm-provider` 或代码构造
6. **用户必须显式传入 `--live`** — 否则 transport 走 fake / offline
7. **用户必须显式传入 `--confirm-i-have-real-key`** — 否则 live_enabled=False
8. **测试默认只使用 fake provider** — `FakeJudgeProvider` / `FakeJudgeTransport`
9. **真实 provider 测试必须 opt-in 并默认 skip** — 使用 `@pytest.mark.skipif`

### parse config ≠ 读取 key

`LLMProviderConfig` 在 parse 阶段只存 `api_key_env`（环境变量名），不读环境变量。
只有在显式调用 `resolve_api_key(config)` 时才从 `os.environ` 读取。这样：
- parse 阶段可以在 CI / 无 key 环境正常运行
- 真实 key 读取是一个显式的、可审计的步骤
- 测试可以用 monkeypatch 覆盖 `os.environ`

### 禁止 inline api_key

`api_key` 字段被显式拒绝——如果配置中出现 `api_key: sk-xxx`，parse 阶段报错。
原因：
- inline key 会通过 git / artifact / log / screen share 泄漏
- `api_key_env` 是环境变量名，不会出现在任何 artifact 里
- 只有显式 `resolve_api_key()` 才短暂持有 key 值

## 5. Architecture boundary

```
LLMProviderConfig      — 配置解析和校验（只存 env var name，不存 key）
LLMProviderRegistry    — 按名称查找 provider config
resolve_api_key()      — 从 os.environ 读取 key（显式调用）
OpenAITransport        — OpenAI-compatible HTTPS transport（openai_transport.py）
AnthropicTransport     — Anthropic-compatible HTTPS transport（anthropic_transport.py）
LLMJudgeProvider       — CoreJudgeProvider 实现，消费 Evidence，输出 JudgeFinding[]（llm_judge.py）
JudgeProviderFactory   — 安全门控工厂，唯一创建真实 LLM provider 的入口（judge_provider_factory.py）
FakeJudgeProvider      — 不调外部 API 的 fake，用于验证接口（fake_judge.py）
RuleJudge              — 继续作为 deterministic baseline，不受 LLM 影响
Reporter               — 只展示 RuleFinding / JudgeFinding / Evidence，不做裁决
ReviewDecision         — 仍然由人类显式创建
```

**关键边界：**
- `LLMProviderConfig` 不依赖任何 IO —— 纯数据对象
- `LLMProviderRegistry` 不调网络 —— 纯内存查找
- `JudgeProvider` 不能自动生成 ReviewDecision
- `RuleJudge` 保持独立，不与 LLM judge 耦合
- 已有 `AnthropicCompatibleConfig` / `LiveAnthropicTransport`（`judges/provider.py`）保持不变
- 新 transport（`openai_transport.py` / `anthropic_transport.py`）独立于旧模块

## 6. Implementation phases

### Phase 1（本轮）：ProviderConfig + Registry + FakeJudgeProvider
- `agent_tool_harness/llm_config.py` — LLMProviderConfig + LLMProviderRegistry + resolve_api_key
- `agent_tool_harness/core_contract.py` — 新增 JudgeFinding dataclass
- `agent_tool_harness/fake_judge.py` — FakeJudgeProvider（Core Flow 接口）
- `examples/llm_providers.example.yaml` — 四类 provider 样例
- `tests/test_llm_provider_config.py` — 配置解析测试
- `tests/test_fake_judge_provider.py` — FakeJudgeProvider 测试

### Phase 2（已完成 2026-05-12）：JudgeFinding + fake judge integration into Core Flow
- CoreEvaluation 可选消费 JudgeProvider（`judge_provider` 参数）
- EvaluationResult 聚合 RuleFinding + JudgeFinding
- 12 个 core evaluation 测试

### Phase 3（已完成 2026-05-12）：CLI flags + dry-run + fake judge
- `--judge-provider fake` CLI flag（仅与 `--core-flow` 配合）
- `--llm-config` / `--llm-provider` CLI flags
- `--dry-run-provider` 校验配置不读 key
- `load_provider_registry_from_file()` 文件加载入口
- 30 个新测试（12 file loading + 11 CLI flags + 7 integration）

### Phase 4（已完成 2026-05-12）：OpenAI + Anthropic transport with CLI wiring
- `openai_transport.py` — OpenAI-compatible HTTPS transport（19 tests）
- `anthropic_transport.py` — Anthropic-compatible HTTPS transport（15 tests）
- `llm_judge.py` — LLMJudgeProvider（CoreJudgeProvider 实现，11 tests）
- `judge_provider_factory.py` — 安全门控 factory（10 tests）
- CLI `--judge-provider llm` 接入 + 双标志 + config 校验（10 tests）
- 零新依赖（stdlib `http.client` only）
- injected `http_factory` 保证零网络测试
- 8 类错误 taxonomy + retry/backoff
- 真实 LLM 调用必须显式 opt-in：`--core-flow --judge-provider llm --live --confirm-i-have-real-key --llm-config PATH --llm-provider NAME`
- 44 个新测试，691 全量测试通过

### Phase 5（未来）：real evaluation hardening
- prompt 工程 + rubric 设计
- 多 provider 分歧率分析
- 成本治理 + 预算上限
- 真实 API 验证（限于 opt-in trial）

Phase 1—4 已完成。Phase 5 为未来工作。
