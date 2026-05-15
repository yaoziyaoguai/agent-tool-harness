# LLM Provider 配置指南

真实 LLM judge 是**可选功能**。默认情况下 agent-tool-harness 只用确定性规则评测，不需要任何 LLM。

仅当你希望获得额外的 advisory 信号（JudgeFinding）时，才需要配置 LLM provider。

## 重要前提

- **RuleFinding 仍然决定 pass/fail** — LLM judge 的 JudgeFinding 只是参考
- **不会自动调 LLM** — 必须显式传入 `--live --confirm-i-have-real-key --env-file`
- **不会自动读 .env** — 需要显式指定 `--env-file` 路径
- **配置不包含真实 key** — 只写环境变量名，不写 key 本体

## 配置示例

`examples/llm_providers.example.yaml`：

```yaml
providers:
  openai-compatible:
    family: openai
    compatibility: compatible
    api_key_env: AGENT_TOOL_HARNESS_OPENAI_COMPAT_API_KEY
    base_url_env: AGENT_TOOL_HARNESS_OPENAI_COMPAT_BASE_URL
    model_env: AGENT_TOOL_HARNESS_OPENAI_COMPAT_MODEL

  anthropic-compatible:
    family: anthropic
    compatibility: compatible
    api_key_env: AGENT_TOOL_HARNESS_ANTHROPIC_COMPAT_API_KEY
    base_url_env: AGENT_TOOL_HARNESS_ANTHROPIC_COMPAT_BASE_URL
    model_env: AGENT_TOOL_HARNESS_ANTHROPIC_COMPAT_MODEL
```

支持四种 provider 类型：
- `openai` + `native` — 官方 OpenAI API
- `openai` + `compatible` — 第三方兼容 API（DeepSeek、阿里云等）
- `anthropic` + `native` — 官方 Anthropic API
- `anthropic` + `compatible` — 第三方兼容 API

## 创建 .env 文件

```env
# .env（不要 commit 到 git）
AGENT_TOOL_HARNESS_OPENAI_COMPAT_API_KEY=你的-key
AGENT_TOOL_HARNESS_OPENAI_COMPAT_BASE_URL=https://api.deepseek.com
AGENT_TOOL_HARNESS_OPENAI_COMPAT_MODEL=deepseek-chat
```

## 启用真实 LLM judge

三重 opt-in，缺一不可：

```bash
python -m agent_tool_harness.cli run \
  --core-flow \
  --judge-provider llm \
  --llm-config examples/llm_providers.example.yaml \
  --llm-provider openai-compatible \
  --env-file .env \
  --live \
  --confirm-i-have-real-key \
  ...
```

## 安全边界

- `api_key_env` 只存环境变量名，不存 key 本体
- 禁止在 YAML 中写 `api_key: sk-xxx` 这种 inline key
- 测试默认使用 FakeJudgeProvider，不调真实 API
- 真实调用需要经过 JudgeProviderFactory 的多重安全闸门

## 相关文档

- [LLM_PROVIDER_CONFIG.md](LLM_PROVIDER_CONFIG.md) — 完整技术参考（含 Python API、SecretSource Protocol、架构边界）
- [USER_GUIDE](USER_GUIDE.md) — 完整使用流程
