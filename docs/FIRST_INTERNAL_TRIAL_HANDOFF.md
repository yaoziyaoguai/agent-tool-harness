# First Internal Trial Handoff Pack

> **面向**：第一个非维护者内部同事；**篇幅**：可在 10 分钟内读完；
> **不是**：长篇产品文档，不是 release note，不是 v3.0 需求收集会。

## 中文学习型说明（为什么要有这份文档）

agent-tool-harness 走到 v2.x 的核心目标，是让一个**没参与开发**的内部
同事能在本地 10–15 分钟内独立把"小工具评测"闭环跑通。前面所有的
``scaffold-*`` / ``bootstrap`` / ``validate-generated`` / ``REVIEW_CHECKLIST``
/ ``REAL_TRIAL_CANDIDATE`` 都是在为这一刻铺路。维护者已经做完
``examples/realistic_offline_tool_trial`` 端到端 rehearsal——但
**maintainer rehearsal 不算真实反馈**，因为维护者无法暴露"作者盲区"。
本文档把第一位试用者需要的所有边界一次性写在一个地方，避免他/她在 6
份 INTERNAL_TRIAL_* 文档之间反复跳。

> **本文档不会重复**已经写在 ``README`` / ``REAL_TRIAL_CANDIDATE`` /
> ``REVIEW_CHECKLIST.md`` (bootstrap 生成) 里的命令细节；遇到歧义，以
> ``REVIEW_CHECKLIST.md`` §6 First Tool Suitability + ``REAL_TRIAL_CANDIDATE.md``
> §1-§3 为准。

---

## 1. 试用目标（务必先读这一段）

- ✅ **要做**：验证一个内部同事能否独立把"一个小工具的离线评测"闭环跑通
- ❌ **不要做**：评估 agent-tool-harness 所有能力 / 启动 v3.0 / 接真实 LLM judge / 接 MCP / 真实 HTTP/Shell executor / 用真实公司数据
- ⚠️ **不可逾越的红线**：no secret / no network / no live LLM / no untrusted code execution / no real user data / no production API key

## 2. 工具选择标准（10 秒决策表）

| 工具属性 | 选 ✅ | 不选 ❌ |
|---|---|---|
| 输入输出 | 简单纯函数 / 字符串 / dict | 文件系统 / 数据库 / 外部 API |
| 副作用 | 只读 / 纯计算 | 写文件 / 网络请求 / 改 DB |
| 依赖 | 仅标准库 / 可 mock | 真实 SDK / 需要登录 / 需要 secret |
| Eval 数 | 2–3 条 deterministic | 一上来就 10+ |
| 数据 | 假数据 / fake fixture | 真实公司 / 用户数据 |

> **示例参考**：``examples/realistic_offline_tool_trial/sample_tools.py``
> 三个函数（``search_fake_knowledge_base`` / ``classify_fake_tool_failure``
> / ``validate_fake_config_snippet``）就是合格的"第一个工具"形态——
> 但请**不要**直接复用它们；从你自己工具仓库挑一个最简单的纯函数。

更详细的"推荐 / 不推荐"清单见 ``docs/REAL_TRIAL_CANDIDATE.md`` §1。

## 3. 最短 7 步试用路径

```bash
# 1. 用 agent-tool-harness 一条命令生成 draft（不执行你的代码、不联网、不读 .env）
.venv/bin/python -m agent_tool_harness.cli bootstrap \
    --source path/to/your_single_tool_dir \
    --out ./ath-first-trial

# 2. 打开 ath-first-trial/REVIEW_CHECKLIST.md，按 §1-§6 review
#    重点看 §6 First Tool Suitability —— 如果不通过，请换一个更简单的工具

# 3. 修 ath-first-trial/{tools.generated.yaml,evals.generated.yaml}
#    把所有 TODO_xxx 占位换成真实业务语义；evals 里把 runnable: false 改成 true

# 4. 第一次校验（warning 友好模式）
.venv/bin/python -m agent_tool_harness.cli validate-generated \
    --bootstrap-dir ./ath-first-trial

# 5. 第二次校验（reviewer 声明已 review，TODO=fail）
.venv/bin/python -m agent_tool_harness.cli validate-generated \
    --bootstrap-dir ./ath-first-trial --strict-reviewed
# 必须 status=pass 才能继续

# 6. Deterministic mock-replay smoke run
.venv/bin/python -m agent_tool_harness.cli run \
    --project ./ath-first-trial/project.yaml \
    --tools ./ath-first-trial/tools.generated.yaml \
    --evals ./ath-first-trial/evals.generated.yaml \
    --out runs/first-trial-good --mock-path good
# 期望：metrics.json 里 passed >= 1；report.md 顶部 signal_quality
# 是 tautological_replay（这是 v2.x 已知边界，不是 bug）

# 7. 看 report 与 10 件套 artifact
open runs/first-trial-good/report.md
ls runs/first-trial-good/   # 应有 transcript / tool_calls / tool_responses /
                            # metrics / audit_tools / audit_evals /
                            # judge_results / diagnosis / llm_cost / report.md
```

> **任何一步卡住 ≥ 5 分钟**，请停下来记到反馈表（§4），那本身就是有价值的
> 试用反馈，不要硬撑。

## 4. 反馈模板（必须填，结构化）

复制下面 markdown 到 ``docs/INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`` 末尾，
按真实情况填，**不要**伪造数据，**不要**把 maintainer rehearsal 算进来。

```markdown
### Trial #1 — <YYYY-MM-DD> — <reviewer github handle>

- trial date: 2024-mm-dd
- reviewer: @your-handle  (must NOT be a maintainer)
- project / tool type: e.g. internal log parser / config linter / data validator
- selected tool name: <function_or_module_name>
- needs secret / network / database: no / no / no   (如有 yes 必须解释为什么仍选它)
- bootstrap command used: `python -m agent_tool_harness.cli bootstrap --source ... --out ...`
- bootstrap result: succeeded / failed (附 stderr 摘要)
- TODO count after bootstrap: <N>
- review time (read REVIEW_CHECKLIST + fix TODO): <minutes>
- strict-reviewed result: pass / fail (附第一条 fail 摘要)
- run result (mock-path good): passed=<N> failed=<N>
- report.md / artifacts path: runs/first-trial-good/
- most useful artifact: e.g. report.md / tool_calls.jsonl / diagnosis.json
- most confusing report field: e.g. signal_quality / judge_disagreement / suggested_fix
- v2.x patch suggestion (small, fits offline/deterministic 边界): <one sentence>
- v3.0 candidate request (only if truly needed): <one sentence or "none">
- if v3.0 candidate, why offline/deterministic/replay-first is insufficient:
  <必须具体；"我想要 LLM judge"不算理由；要写"我的工具语义判定无法用 RuleJudge 表达，因为..."  >
- does this count as real internal feedback: **yes**   (maintainer rehearsal 永远是 no)
```

> **未填全的反馈不计入 v3.0 gate**。v3.0 gate = 收齐 ≥ 3 份 ``does this
> count as real internal feedback: yes`` 且其中至少 1 份 ``v3.0 candidate
> request != "none"`` + 有具体 offline/deterministic 不足理由。

## 5. Live judge 说明（试用者通常**不需要**关心）

- v2.x 主线**完全是** offline / deterministic / replay-first；上面 7 步**不**触发任何网络请求
- ``--judge-provider anthropic_compatible_live --live --confirm-i-have-real-key`` 是 opt-in 路径，**第一轮试用不要开**
- 维护者已对阿里云 Anthropic-compatible gateway 3 个模型（``qwen3-coder-next`` / ``glm-5`` / ``kimi-k2.5``）做过受控 live smoke：3/3 模型返回 ``bad_response``（gateway envelope 与严格 Anthropic Messages 格式不一致）。**这不阻塞 offline 主线**——deterministic RuleJudge 仍照常 PASS。详情见 ``docs/ROADMAP.md`` item #11
- multi-format live judge（兼容 OpenAI Chat Completions / 厂商 native 格式）属 v3.0+ backlog，**still not started**——除非真实反馈触发，否则不启动

## 6. 安全边界（违反任何一条都属 release-blocking）

- ❌ 不要提交 ``.env``（已在 ``.gitignore``）
- ❌ 不要把 API key / Authorization header / 完整 prompt body / 完整 response body 贴到 issue / PR / 反馈文档 / 任何 chat
- ❌ 不要使用真实公司 / 用户敏感数据作为试用工具的输入
- ❌ 不要在反馈里贴出真实 endpoint URL（如 ``https://*.aliyuncs.com``）
- ❌ 不要为了"让 live judge PASS"修改 v2.x 任何核心代码——那是 v3.0 工作

## 7. v3.0 gate（仍然 not started）

| 条件 | 当前状态 |
|---|---|
| ≥ 3 份真实内部反馈（``does this count as real internal feedback: yes``） | 0 / 3 |
| 至少 1 份明确 ``v3.0 candidate request`` 且解释清楚 offline/deterministic 不够的原因 | 0 |
| **v3.0 总状态** | **still backlog / not started** |

> v3.0 候选能力一律**不在** v2.x 主线排期：MCP discovery / Web UI /
> 真实 HTTP-Shell executor / 多格式 live judge / 企业级平台。即使内部
> 同事提了，请按本文档 §4 写到 ``v3.0 candidate request`` 字段而**不是**
> 直接做 v2.x patch。
