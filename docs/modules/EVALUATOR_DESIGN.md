# Evaluator Design（评测器模块设计）

> 本文档描述 agent-tool-harness 中 Evaluator（评测器）的设计意图、判定规则、Provider 协议与 error taxonomy。
> 在源码中，Evaluator 对应 `judges/` 子包：`rule_judge.py` + `provider.py` + `preflight.py`。
>
> 面向读者：eval 设计者、Coding Agent、模块维护者。

---

## 一、模块目的

Evaluator 模块负责**判定 Agent 的工具调用行为是否符合 eval 期望**。

它由两层构成：
- **RuleJudge**（`rule_judge.py`）：确定性规则引擎，是 ground truth
- **JudgeProvider**（`provider.py`）：可插拔 provider 协议，支持 dry-run / advisory / composite / future LLM judge

核心设计原则：deterministic baseline 永远是 ground truth；任何 advisory（包括未来真实 LLM judge）只能作为旁路 metadata 写入，不能覆盖 deterministic PASS/FAIL。

---

## 二、RuleJudge（确定性规则引擎）

### 2.1 数据模型

```python
@dataclass
class RuleCheckResult:
    rule: dict[str, Any]   # 触发规则（含 type）
    passed: bool           # 本条规则是否通过
    message: str           # 可读失败原因

@dataclass
class JudgeResult:
    eval_id: str
    passed: bool                    # 所有 checks 都为 True
    checks: list[RuleCheckResult]   # 每条规则的判定
```

### 2.2 8 条确定性规则

| 规则 type | 判定逻辑 | 用途 |
|-----------|---------|------|
| `must_call_tool` | 工具名在 tool_calls 中出现 | 验证必须调特定工具 |
| `must_call_one_of` | tool_calls 中至少出现 options 之一 | 验证必须调至少一个需要的工具 |
| `forbidden_first_tool` | 第一个工具调用不是 forbidden 工具 | 防止 Agent 用错误工具入口 |
| `max_tool_calls` | `len(tool_calls) <= limit` | 限制工具调用次数预算 |
| `expected_root_cause_contains` | final_answer 包含期望文本（非空校验） | 验证 Agent 归因到了正确根因 |
| `must_use_evidence` | final_answer 引用 tool_responses 中的 evidence id/label | 防模板化回答（不能只说 "based on evidence"） |
| `evidence_from_required_tools` | 引用的 evidence 至少一条来自 required_tools | anti-decoy：防止 Agent 调 decoy 工具收 evidence 后引用 |
| `must_not_modify_before_evidence` | 在没有成功获取 evidence 前不调用 mutating 工具 | 防先改后查 |

### 2.3 关键设计决策

**`expected_root_cause_contains` 非空校验**：期望文本为空时直接 FAIL（而不是永真），避免"空字符串包含关系导致必须通过的规则"。

**短标识假阳性治理**：`_MIN_EVIDENCE_REF_LEN = 3`，长度 < 3 的 evidence id（如 `"1"` / `"a"`）被忽略——真实坑：工具实现里 evidence id 经常是短串，substring 匹配会导致 judge 必过。

**Anti-decoy 确定性加固（v1.0）**：`evidence_from_required_tools` 不验语义，只验 trajectory——引用的 evidence id 来自哪个 tool_name。它解决了 `must_use_evidence` 的盲区（Agent 调 decoy → 收 decoy evidence → 把 decoy id 写进答案 → still PASS）。

**仍是启发式，不是 LLM Judge**：所有 8 条规则都是 deterministic 字符串匹配 / 集合运算 / token 判断。不做语义理解。

---

## 三、JudgeProvider 协议层（`provider.py`）

### 3.1 Protocol 定义

```python
class JudgeProvider(Protocol):
    name: str              # 稳定标识
    mode: str              # "deterministic" | "dry_run" | "composite" | "fake_transport" | "offline_fixture"
    def judge(case: EvalSpec, run: AgentRunResult) -> ProviderJudgeResult: ...
```

### 3.2 Provider 实现矩阵

| Provider | mode | 用途 | 网络依赖 |
|----------|------|------|---------|
| `RuleJudgeProvider` | `deterministic` | 把 RuleJudge 包成 provider，EvalRunner 默认路径 | 零 |
| `RecordedJudgeProvider` | `dry_run` | 从离线 fixture dict 读取预录判定 | 零 |
| `CompositeJudgeProvider` | `composite` | 并列跑 deterministic + advisory，出分歧率信号 | 零（当 advisory 也是 zero-network 时） |
| `AnthropicCompatibleJudgeProvider` | `fake_transport` / `offline_fixture` | Anthropic-compatible API 骨架（默认 disabled） | 零（当前） |

### 3.3 RuleJudgeProvider

最简单的 provider——把 `RuleJudge` 包进 `ProviderJudgeResult`。`mode="deterministic"`，`name="rule"`。

### 3.4 RecordedJudgeProvider

从 `recordings: dict[eval_id → {passed, rationale, confidence, rubric}]` 读取预录判定。**绝**不调外部服务、**绝**不读磁盘以外来源。

关键：recording 缺失 → 抛 `MissingRecordingError`（不静默 PASS）。

### 3.5 CompositeJudgeProvider

组合 `deterministic` + `advisory`（单 advisory 或多 advisory list）。

- **单 advisory 模式**：`extra` 含 `agreement` / `advisory_result` / `deterministic_result`
- **多 advisory 模式**（v1.3）：`extra` 含 `agreement` / `majority_passed` / `vote_distribution` / `advisory_results[]`

多数投票规则：
- pass 票 > fail 票 → `majority_passed = True`
- fail 票 > pass 票 → `majority_passed = False`
- 平票或全 error → `majority_passed = None`（无效，不计入 disagreement）
- error advisory **不计入**投票（避免"advisory 错误"被当成"advisory FAIL"投票）

### 3.6 AnthropicCompatibleJudgeProvider

为未来接入 Anthropic Messages API 兼容端点（如阿里云 Coding Plan）准备的骨架。

行为矩阵：

| 条件 | mode | 行为 |
|------|------|------|
| 未注入 transport + 未给 offline_fixture | `offline_fixture` | 返回 `disabled_live_provider` 错误 |
| 未注入 transport + 给了 offline_fixture | `offline_fixture` | 按 fixture 构造 advisory |
| 注入了 fake transport | `fake_transport` | 调 transport，捕获 `_FakeTransportError` 走脱敏路径 |
| api_key 或 model 缺失 | — | **优先**返回 `missing_config` |

### 3.7 Error Taxonomy（8 类）

| error_code | 含义 | HTTP 映射 |
|-----------|------|----------|
| `missing_config` | 缺 provider/base_url/api_key/model 任一 | — |
| `disabled_live_provider` | 双标志未完整 opt-in | — |
| `auth_error` | 认证失败（已脱敏） | 401/403 |
| `rate_limited` | 被限流（已脱敏） | 429 |
| `network_error` | 网络错误（已脱敏） | 连接超时/DNS/socket |
| `timeout` | 超时（已脱敏） | socket.timeout |
| `bad_response` | 响应不可解析（已脱敏） | 非 2xx / JSON 解析失败 / 缺 passed 字段 |
| `provider_error` | 未分类错误（已脱敏） | 5xx / 其它 |

### 3.8 脱敏硬约束

- 永远**不**把 `base_url` / `api_key` / Authorization header 写入异常 message
- 永远**不**把 raw response body 落入 artifact
- 永远**不**把 raw exception repr 序列化——只透传 `error_code` slug
- 错误 message 走 `_safe_message()` 固定模板

### 3.9 LiveAnthropicTransport

真实 HTTPS transport 骨架（v1.4），默认 disabled。

- 使用标准库 `http.client`（不引入 `requests` / `httpx` / `anthropic`）
- 双标志 opt-in：`live_enabled=True` + `live_confirmed=True` — 任一为 False 时 `send()` 直接抛 `disabled_live_provider`
- 支持 `http_factory` 注入 fake connection（contract test 用）
- 支持 retry/backoff（v1.6）：index 退避 `min(max_delay, base * 2^(attempt-1))`，仅对 `rate_limited` / `network_error` / `timeout` 重试
- `attempts_summary` 序列写入 advisory extra

---

## 四、核心输入

- `EvalSpec.judge.rules` — eval 声明了哪些规则
- `AgentRunResult` — adapter 产出的 `tool_calls` + `tool_responses` + `final_answer`
- `EvalSpec.expected_tool_behavior.required_tools` — `evidence_from_required_tools` 需要
- `EvalSpec.verifiable_outcome.expected_root_cause` — `expected_root_cause_contains` 需要

---

## 五、核心输出

- `JudgeResult`（rule_judge.py）— 每条 eval 的 pass/fail + checks 列表
- `ProviderJudgeResult`（provider.py）— provider 包装，含 metadata（rationale/confidence/rubric/extra）

---

## 六、关键接口

| 接口 | 位置 | 稳定性 |
|------|------|--------|
| `RuleJudge.judge(case, run) -> JudgeResult` | `judges/rule_judge.py:63` | 稳定 |
| 8 条规则 type 全集 | `RuleJudge._check` 中的 if/elif 链 | 稳定（新增规则 type 不破坏已有） |
| `JudgeProvider` Protocol | `judges/provider.py:113` | 稳定 |
| `RuleJudgeProvider` | `judges/provider.py:130` | 稳定 |
| `RecordedJudgeProvider` | `judges/provider.py:156` | 稳定 |
| `CompositeJudgeProvider` | `judges/provider.py:227` | 稳定 |
| `AnthropicCompatibleJudgeProvider` | `judges/provider.py:984` | 实验性 |
| `JudgeTransport` Protocol | `judges/provider.py:561` | 实验性 |
| `LiveAnthropicTransport` | `judges/provider.py:697` | 实验性（默认 disabled） |
| 8 类 error taxonomy | `judges/provider.py:504-511` | 稳定 |
| `PROVIDER_SCHEMA_VERSION` | `judges/provider.py:56` | 稳定（SemVer） |

---

## 七、不负责什么

- ❌ 不执行工具（那是 `ToolRegistry` 的职责）
- ❌ 不收集运行事实（那是 `RunRecorder` 的职责）
- ❌ 不做语义级质量判断（那是未来真实 LLM judge 的职责）
- ❌ 不做 prompt 工程 / rubric 生成（v1.x 后续 backlog）
- ❌ 不在 deterministic baseline 被 advisory 覆盖的路径上运行
- ❌ 不调用任何外部网络 / LLM / 密钥（当前；v3.0 可能允许但需显式 opt-in）
- ❌ 不做密钥管理 / 成本治理 / 隐私合规（留给未来 live transport 治理层）

---

## 八、和其他模块的关系

```
agents/agent_adapter_base.py  →  AgentRunResult（judge 的输入）
config/eval_spec.py  →  EvalSpec（judge 读 rules / expected_tool_behavior）
runner/eval_runner.py  →  EvalRunner（调用 judge + dry_run_provider）
judges/rule_judge.py  →  JudgeResult / RuleCheckResult（所有 provider 的 inner）
reports/markdown_report.py  →  渲染 judge_results.json
reports/cost_tracker.py  →  消费 dry_run_provider 中的 usage/attempts_summary
```

---

## 九、测试证明方式

| 测试文件 | 覆盖内容 |
|---------|---------|
| `tests/test_rule_judge.py` 系列 | 8 条规则的 pass/fail path + edge case |
| `tests/test_judge_provider_skeleton.py` | Provider Protocol + RuleJudgeProvider + RecordedJudgeProvider + CompositeJudgeProvider + AnthropicCompatibleJudgeProvider |
| `tests/test_judge_provider_preflight.py` | CLI preflight（双标志 opt-in + 配置缺失检测） |
| `tests/test_anthropic_compatible_*.py` 系列 | Fake transport + error taxonomy 映射 + 脱敏路径 |
| strict xfail | deterministic 启发式的根本限制（语义级判断的已知盲区） |

---

## 十、后续实现或重构建议

1. **真实 LLM Judge Provider**（v3.0）：实现 `OpenAIJudgeProvider` + 真实 `AnthropicJudgeProvider`（基于真实 HTTP transport）。需同时落地 prompt 工程、成本治理、隐私脱敏、rate-limit 治理。

2. **RuleJudge 规则扩展**：当前 8 条规则覆盖了调用顺序/计数/evidence 引用，但没有覆盖"参数正确性"（Agent 调工具时传了什么参数）。可新增 `must_call_with_params` 规则。

3. **evidence grounding 语义级升级**：当前 `must_use_evidence` + `evidence_from_required_tools` 都是字符串级启发式。真实 LLM judge 可以判断"引用的 evidence 是否在语义上支持 Agent 结论"。

4. **provider 注册机制**：当前 provider 在 CLI 硬编码选择。可考虑 provider registry，让用户通过 `project.yaml` 声明自定义 provider。

---

## 十一、Review Checklist（审查清单）

Evaluator 模块变更 Review 时，检查以下项：

- [ ] 新增规则 type 是否 deterministic（不依赖 LLM 语义判断）
- [ ] 新增规则是否有对应的 bad path 测试（确保规则能捕捉到 failure）
- [ ] 规则失败 message 是否可行动（不只是 "failed"，而是"缺什么 / 调了什么不该调的"）
- [ ] Provider 实现是否 deterministic + offline（CI 可跑）
- [ ] Provider 是否在缺配置时给可行动错误而不是静默 PASS
- [ ] 异常路径是否走脱敏模板（不把 raw exception / key / url 落入 artifact）
- [ ] `CompositeJudgeProvider` 是否保证 deterministic baseline 永远是 inner.passed
- [ ] 新增 error_code 是否加入 `_safe_message()` 映射表
- [ ] `PROVIDER_SCHEMA_VERSION` 在字段不兼容变化时是否 bump major
