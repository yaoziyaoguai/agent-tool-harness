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
- `compatible` 必须提供 base_url 或 base_url_env（如 DeepSeek、阿里云 Coding Plan 等）
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
    api_key_env: AGENT_TOOL_HARNESS_DEEPSEEK_API_KEY
    base_url_env: AGENT_TOOL_HARNESS_DEEPSEEK_BASE_URL
    model_env: AGENT_TOOL_HARNESS_DEEPSEEK_MODEL

  anthropic-main:
    family: anthropic
    compatibility: native
    api_key_env: AGENT_TOOL_HARNESS_ANTHROPIC_API_KEY
    model: claude-3-5-sonnet-latest

  anthropic-compatible:
    family: anthropic
    compatibility: compatible
    api_key_env: AGENT_TOOL_HARNESS_ANTHROPIC_COMPAT_API_KEY
    base_url_env: AGENT_TOOL_HARNESS_ANTHROPIC_COMPAT_BASE_URL
    model_env: AGENT_TOOL_HARNESS_ANTHROPIC_COMPAT_MODEL
```

要求：
- 配置样例不能包含真实 key
- 只允许 `api_key_env`（环境变量名），禁止 `api_key` inline 字段
- `base_url` / `model` 可写死在 YAML，也可通过 `base_url_env` / `model_env` 引用 env
- `model` 与 `model_env` 互斥（不能同时存在），至少一个存在
- `base_url` 与 `base_url_env` 互斥（不能同时存在）
- `compatible` 必须有 `base_url` 或 `base_url_env`
- `timeout_seconds` / `max_tokens` / `temperature` 可选

### 第三方转接 API 推荐配置方式

对于 DeepSeek、阿里云、自建网关等第三方转接 API，推荐把 **所有三个值**（key / base_url / model）都放入显式 `.env` 文件：

1. 创建 `.env` 文件（不要 commit 到 git）：
   ```env
   AGENT_TOOL_HARNESS_OPENAI_COMPAT_API_KEY=sk-xxxx
   AGENT_TOOL_HARNESS_OPENAI_COMPAT_BASE_URL=https://api.deepseek.com
   AGENT_TOOL_HARNESS_OPENAI_COMPAT_MODEL=deepseek-chat

   AGENT_TOOL_HARNESS_ANTHROPIC_COMPAT_API_KEY=sk-ant-xxxx
   AGENT_TOOL_HARNESS_ANTHROPIC_COMPAT_BASE_URL=https://example.com/anthropic-compatible
   AGENT_TOOL_HARNESS_ANTHROPIC_COMPAT_MODEL=claude-compatible-model
   ```

2. YAML 配置只引用环境变量名：
   ```yaml
   openai-compatible:
     family: openai
     compatibility: compatible
     api_key_env: AGENT_TOOL_HARNESS_OPENAI_COMPAT_API_KEY
     base_url_env: AGENT_TOOL_HARNESS_OPENAI_COMPAT_BASE_URL
     model_env: AGENT_TOOL_HARNESS_OPENAI_COMPAT_MODEL
   ```

3. 真实调用命令：
   ```bash
   python -m agent_tool_harness.cli run \
     --core-flow \
     --judge-provider llm \
     --llm-config examples/llm_providers.example.yaml \
     --llm-provider openai-compatible \
     --env-file ./.env \
     --live \
     --confirm-i-have-real-key
   ```

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
    model: str                   # 模型名（与 model_env 互斥）
    api_key_env: str             # 环境变量名（非 key 本体）
    base_url: str | None = None  # 与 base_url_env 互斥
    base_url_env: str | None = None  # 从 SecretSource 解析 base_url
    model_env: str | None = None     # 从 SecretSource 解析 model
    timeout_seconds: float = 30.0
    max_tokens: int | None = None
    temperature: float | None = None

@dataclass
class ResolvedLLMProviderConfig:
    """resolve 后的运行时配置，持有真实 api_key / base_url / model。
    repr 不显示 api_key。"""
    api_key: str
    base_url: str
    model: str
```

## 4. Safety model

1. **默认不调用真实 LLM** — FakeJudgeProvider 是默认测试 provider
2. **默认不读取 .env** — 不自动 `load_dotenv()`，不自动扫描当前目录 `.env`
3. **不默认读取宿主 os.environ** — 需要显式 `--allow-os-env` 才读取
4. **真实调用必须指定 secret source** — `--env-file PATH` 或 `--allow-os-env`
5. **用户必须显式指定 provider** — 通过 `--llm-provider` 或代码构造
6. **用户必须显式传入 `--live`** — 否则 transport 走 fake / offline
7. **用户必须显式传入 `--confirm-i-have-real-key`** — 否则 live_enabled=False
8. **dry-run 不读取 env 值** — `--dry-run-provider` 只校验配置结构，不触碰 SecretSource
9. **测试默认只使用 fake provider** — `FakeJudgeProvider` / `FakeJudgeTransport`
10. **真实 provider 测试必须 opt-in 并默认 skip** — 使用 `@pytest.mark.skipif`

### parse config ≠ 读取 key

`LLMProviderConfig` 在 parse 阶段只存 `api_key_env` / `base_url_env` / `model_env`
（环境变量名），不读 SecretSource。只有在显式调用 `resolve_provider_runtime_config(config, secret_source)`
时才从 SecretSource 读取真实值。这样：
- parse 阶段可以在 CI / 无 key 环境正常运行
- 真实值读取是一个显式的、可审计的步骤
- 测试可以用 `MappingSecretSource` 注入

### 禁止 inline api_key

`api_key` 字段被显式拒绝——如果配置中出现 `api_key: sk-xxx`，parse 阶段报错。
原因：
- inline key 会通过 git / artifact / log / screen share 泄漏
- `api_key_env` 是环境变量名，不会出现在任何 artifact 里
- 只有显式 `resolve_provider_runtime_config()` 才短暂持有 key 值

## 5. CLI flags

| Flag | 必需 | 说明 |
|------|------|------|
| `--core-flow` | 是 | 启用 Core Contract 路径 |
| `--judge-provider llm` | 是 | 指定使用 LLM judge |
| `--llm-config PATH` | 是 | provider 配置文件路径 |
| `--llm-provider NAME` | 是 | 要使用的 provider 名称 |
| `--live` | 是 | 声明意图打开 live |
| `--confirm-i-have-real-key` | 是 | 二次确认持有真实 key |
| `--env-file PATH` | 是* | 显式指定 .env 文件路径 |
| `--allow-os-env` | 是* | 允许从 os.environ 读取 |

*`--env-file` 和 `--allow-os-env` 必须提供至少一个。

### 没有 --env-file / --allow-os-env 时

真实 LLM 调用被拒绝，提示：
```
error: 真实 LLM judge 需要显式 secret source：请传 --env-file PATH 或 --allow-os-env。
```

### dry-run-provider

- 不读取 `--env-file`
- 不读取 `os.environ`
- 只校验 provider config 结构并打印摘要

## 6. Architecture boundary

```
LLMProviderConfig           — 配置解析和校验（只存 env var name，不存 key）
LLMProviderRegistry         — 按名称查找 provider config
ResolvedLLMProviderConfig   — resolve 后的运行时配置（repr 不显示 api_key）
resolve_provider_runtime_config() — 从 SecretSource 解析 api_key / base_url / model
SecretSource (Protocol)     — 统一 secret 读取接口
EnvFileSecretSource          — 从显式 .env 文件读取
OsEnvSecretSource            — 从 os.environ 读取（需 --allow-os-env）
MappingSecretSource          — 测试用内存 dict
OpenAITransport             — OpenAI-compatible HTTPS transport
AnthropicTransport          — Anthropic-compatible HTTPS transport
LLMJudgeProvider            — CoreJudgeProvider 实现，消费 Evidence，输出 JudgeFinding[]
JudgeProviderFactory        — 安全门控工厂，唯一创建真实 LLM provider 的入口
FakeJudgeProvider           — 不调外部 API 的 fake，用于验证接口
RuleJudge                   — 继续作为 deterministic baseline，不受 LLM 影响
Reporter                    — 只展示 RuleFinding / JudgeFinding / Evidence，不做裁决
ReviewDecision              — 仍然由人类显式创建
```

**关键边界：**
- `LLMProviderConfig` 不依赖任何 IO —— 纯数据对象
- `LLMProviderRegistry` 不调网络 —— 纯内存查找
- `JudgeProvider` 不能自动生成 ReviewDecision
- `RuleJudge` 保持独立，不与 LLM judge 耦合
- 已有 `AnthropicCompatibleConfig` / `LiveAnthropicTransport`（`judges/provider.py`）保持不变
- 新 transport（`openai_transport.py` / `anthropic_transport.py`）独立于旧模块

## 7. Implementation phases

### Phase 1（已完成）：ProviderConfig + Registry + FakeJudgeProvider

### Phase 2（已完成 2026-05-12）：JudgeFinding + fake judge integration into Core Flow

### Phase 3（已完成 2026-05-12）：CLI flags + dry-run + fake judge

### Phase 4（已完成 2026-05-12）：OpenAI + Anthropic transport with CLI wiring

### Phase 4.5（已完成 2026-05-12）：Explicit env file provider settings
- `agent_tool_harness/secrets.py` — SecretSource Protocol + EnvFileSecretSource + OsEnvSecretSource + MappingSecretSource
- `base_url_env` / `model_env` 字段支持
- `ResolvedLLMProviderConfig` — runtime resolved config with repr hiding api_key
- `resolve_provider_runtime_config()` — 统一解析入口
- `--env-file` / `--allow-os-env` CLI flags
- 安全闸门：真实 LLM 调用必须指定 secret source
- dry-run 不触碰 SecretSource

### Phase 5（已验证 2026-05-12）：Real LLM infrastructure & safety gate verified
真实 LLM transport 基础设施、安全门控（--live/--confirm-i-have-real-key/--env-file）和 factory wiring 已通过验证。Semantic JudgeFinding 因 provider response parsing bad_response 尚未成功产出，待后续调试（详见 `docs/DOGFOOD_REAL_LLM_001.md`）。

**命令：**
```bash
python -m agent_tool_harness.cli run \
  --project examples/knowledge_search/project.yaml \
  --tools examples/knowledge_search/tools.yaml \
  --evals examples/knowledge_search/evals.yaml \
  --out /tmp/dogfood-out \
  --core-flow \
  --judge-provider llm \
  --live --confirm-i-have-real-key \
  --llm-config examples/llm_providers.example.yaml \
  --llm-provider openai-compatible \
  --env-file ./.env
```

**结果：**
- total_evals=1, passed=1, core_flow=true
- RuleFinding（deterministic rule judge）正常工作
- Transport + safety gates 验证通过（api_key / base_url / model 从 .env 正确解析）
- JudgeFinding 生成但 semantic verdict 未成功（provider response parsing bad_response，待调试）
- ReviewDecision 未自动生成（符合预期）
- `model_env` 从 .env 正确解析

**第三方 OpenAI-compatible provider 推荐配置：**
```yaml
# examples/llm_providers.example.yaml
providers:
  openai-compatible:
    family: openai
    compatibility: compatible
    api_key_env: AGENT_TOOL_HARNESS_OPENAI_COMPAT_API_KEY
    base_url_env: AGENT_TOOL_HARNESS_OPENAI_COMPAT_BASE_URL
    model_env: AGENT_TOOL_HARNESS_OPENAI_COMPAT_MODEL
```

```bash
# ./.env（gitignored）
AGENT_TOOL_HARNESS_OPENAI_COMPAT_API_KEY=sk-your-key
AGENT_TOOL_HARNESS_OPENAI_COMPAT_BASE_URL=https://your-proxy.com
AGENT_TOOL_HARNESS_OPENAI_COMPAT_MODEL=your-model-name
```

### Phase 6（未来）：real evaluation hardening
- prompt 工程 + rubric 设计
- 多 provider 分歧率分析
- 成本治理 + 预算上限
- 真实 API 验证（限于 opt-in trial）
