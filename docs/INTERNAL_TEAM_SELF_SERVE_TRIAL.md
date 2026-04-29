# Internal Team Self-Serve Trial — 内部小组自助试用入口

> **本文目标读者 = 公司内部小组成员**（不是 maintainer），想拿**自己的
> AI Tool**来跑 agent-tool-harness 做一次 deterministic / offline 评估。
> 你**不需要**懂框架内部架构、不需要联系 maintainer 才能开始；按下面
> 10 个问题逐项做完即可。**全程离线、不调真实 LLM、不联网、不需要密钥**。

> 想要更短的 10-15 分钟最小路径？请先读
> [INTERNAL_TRIAL_QUICKSTART.md](INTERNAL_TRIAL_QUICKSTART.md)。
> 想要 maintainer 视角的发布闭环？请读
> [INTERNAL_TRIAL_FEEDBACK_SUMMARY.md](INTERNAL_TRIAL_FEEDBACK_SUMMARY.md)。

---

## 1. 我有一个 AI Tool，什么时候适合用这个 harness 测？

适合的场景：

- 你的 tool 是 **结构化函数 / API 调用型工具**（输入参数、输出 JSON
  / 文本，能写 `output_contract`），例如：SQL 查询、grep 代码、查询
  内部 KB、调试 runtime 状态、查询监控指标；
- 你想验证：tool 的 **`description` / `when_to_use` /
  `when_not_to_use`** 是否能让 Agent 在合理场景下选对、在错误场景下
  避开；
- 你已经有 **真实 transcript / 录像带**，希望 deterministic 重放，
  不想每次测试都烧 token；
- 你想看 **eval 设计本身有没有问题**（contract 缺字段、required_tools
  与 must_use_evidence 不一致等）。

**不适合**的场景：

- 你的 tool 必须依赖**真实 live LLM Judge** 做主观语义评分 → 当前 v2.0
  不内置（仅 advisory deterministic RuleJudge）；
- 你的 tool 必须依赖 **MCP / HTTP / Shell executor** 真跑 → v2.0 不
  支持；
- 你需要 **Web UI / 多租户 / 企业 RBAC** → 不在 v2.0 范围；
- 你的输入包含 **真实生产秘密 / 用户隐私** 且**不能脱敏** → 不要试用，
  先做脱敏。

---

## 2. 第一次怎么安装？

```bash
git clone https://github.com/yaoziyaoguai/agent-tool-harness.git
cd agent-tool-harness && python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
python -m pytest -q   # 预期：>= 470 passed, 1 xfailed
```

> 必须带 `[dev]` extras，否则 pytest 不会被装上。详见
> [INTERNAL_TRIAL_QUICKSTART.md §0](INTERNAL_TRIAL_QUICKSTART.md#0-前提3-行装好)。

---

## 3. 怎么从 example project 复制一份自己的 trial project？

推荐**最小复制**路径：

```bash
mkdir -p projects/<your-team>/<your-tool>
cp examples/runtime_debug/project.yaml projects/<your-team>/<your-tool>/
cp examples/runtime_debug/tools.yaml   projects/<your-team>/<your-tool>/
cp examples/runtime_debug/evals.yaml   projects/<your-team>/<your-tool>/
```

> `projects/` 已被 `.gitignore` 忽略；这里写的 yaml **不会**被
> 误推到 git。如果要保留，请放到团队自己的私有仓库或本地。

---

## 4. 最少需要改哪些配置？

只需改这 3 个 YAML 的关键字段：

**`project.yaml`**：
- `name` → 改成你的项目名；
- 其余字段（`tools_path` / `evals_path` 默认指向同目录即可）。

**`tools.yaml`**（**1 个**真实 tool 起步）：
- `id` → 唯一 id；
- `name` → 简短名；
- `description` → 写**1-3 句**真实用途，不要泛化；
- `when_to_use` / `when_not_to_use` → 各 1-3 条具体场景；
- `output_contract` → 至少包含 `evidence` + `next_action` 字段；
- `response_format` → 描述 JSON / 文本结构。

**`evals.yaml`**（**2-3 条** eval 起步）：
- `id` → 唯一 id；
- `prompt` → 真实场景提示；
- `expected_tool_behavior.required_tools` → 必须调的 tool id 列表；
- `expected_tool_behavior.must_use_evidence` → 必须出现在响应里的关键
  evidence 字段名；
- `expected_tool_behavior.failure_modes` → bad path 时的失败模式（可选
  但强烈推荐）。

> 字段含义 + 完整 schema 见 [docs/ARTIFACTS.md](ARTIFACTS.md) +
> `examples/runtime_debug/{project,tools,evals}.yaml` 注释。

---

## 5. 怎么放入自己的 tool definition / transcript / cases？

- **tool definition**：填到 `tools.yaml`（见 §4）；
- **transcript**（如果你已经有真实 Agent 的对话录像带）：
  1. 把 transcript 转成 `tool_calls.jsonl` / `tool_responses.jsonl`
     格式（参考 `runs/<example>/tool_calls.jsonl`）；
  2. 用 `replay-run` 重放：
     ```bash
     python -m agent_tool_harness.cli replay-run \
       --project projects/<your-team>/<your-tool>/project.yaml \
       --tools   projects/<your-team>/<your-tool>/tools.yaml \
       --evals   projects/<your-team>/<your-tool>/evals.yaml \
       --run     <存放你的 transcript 的目录> \
       --out     runs/<your-team>-replay
     ```
- **cases**（你想测的具体场景）：每条写成一个 eval 放到 `evals.yaml`。

> 没有真实 transcript 也能跑 → 用 MockReplayAdapter（默认）走结构性
> mock；但请理解 `signal_quality = tautological_replay`，PASS/FAIL 是
> 结构性的，不代表 Agent 真实能力。详见
> [LAUNCH_PACK §0.5 关键词速懂](INTERNAL_TRIAL_LAUNCH_PACK.md#05-新同事关键词速懂每词-1-2-句看完再读下面)。

---

## 6. 怎么跑 deterministic / offline evaluation？

最小四步：

```bash
# 1. audit 工具设计
python -m agent_tool_harness.cli audit-tools \
  --tools projects/<your-team>/<your-tool>/tools.yaml \
  --out runs/<your-team>-audit-tools

# 2. audit eval 设计
python -m agent_tool_harness.cli audit-evals \
  --evals projects/<your-team>/<your-tool>/evals.yaml \
  --out runs/<your-team>-audit-evals

# 3. 跑 bad path（必须故意失败，才能看到 diagnosis 信号）
python -m agent_tool_harness.cli run \
  --project projects/<your-team>/<your-tool>/project.yaml \
  --tools   projects/<your-team>/<your-tool>/tools.yaml \
  --evals   projects/<your-team>/<your-tool>/evals.yaml \
  --out     runs/<your-team>-bad \
  --mock-path bad

# 4. 跑 good path
python -m agent_tool_harness.cli run \
  --project projects/<your-team>/<your-tool>/project.yaml \
  --tools   projects/<your-team>/<your-tool>/tools.yaml \
  --evals   projects/<your-team>/<your-tool>/evals.yaml \
  --out     runs/<your-team>-good \
  --mock-path good
```

> 全程**不调真实 LLM、不联网、不需要密钥**。

---

## 7. 怎么生成 report？

`report.md` 在每次 `run` / `replay-run` 后**自动生成**到 `--out` 目录：

```bash
cat runs/<your-team>-bad/report.md
```

包含：
- 顶部 `Signal Quality` 段（说明 PASS/FAIL 的可信度）；
- `Tool Design Audit` / `Eval Quality Audit` 段；
- `Per-Eval Details` 段（每条 eval 的判定）；
- `Failure Attribution` 段（启发式归因到 tool / eval / agent）；
- `Improvement Suggestions` 段（可行动的修复建议）；
- `Artifacts` 段（10 个 artifact 速查）。

> 9+ artifact 字段含义见 [docs/ARTIFACTS.md](ARTIFACTS.md)。

---

## 8. 怎么判断失败属于哪一类？

按下面**自助决策树**判定：

| 症状 | 看哪 | 多半属于 |
|------|------|---------|
| `audit-tools` 报 `weak_when_to_use` / `generic_description` / `missing_output_contract` | `audit_tools.json::findings[]` | **tool 本身问题** → 改 `tools.yaml` |
| `audit-evals` 报 `required_tools_missing` / `evidence_contract_misaligned` | `audit_evals.json::findings[]` | **test case 问题** → 改 `evals.yaml` |
| `run` 退出码非 0 / Yaml parse error | stderr | **harness 配置问题** → 修 yaml 路径 / 字段名 |
| `signal_quality = tautological_replay` 但 PASS | `metrics.json` | **mock 结构性 PASS** → 这是预期；要真实信号必须用 `replay-run` + 真 transcript |
| `Failure Attribution` 类别 = `agent_tool_choice` | `report.md::Failure Attribution` | **Agent 行为问题** → tool 设计可能让 Agent 选错；改 `when_to_use` / `when_not_to_use` |
| `diagnosis.json::findings[]` 报 `grounding_missing` | `transcript.jsonl` 真实事件流 | **Agent 没回真实证据** → tool 设计可能没强制 evidence；改 `output_contract` |
| 框架本身崩 / 出 stack trace 提及 `agent_tool_harness/` 内部代码 | stderr + `runs/<dir>/` | **需要 maintainer 介入** → 提反馈 |
| 你写的 yaml 完全合法、命令也没崩，但 PASS/FAIL 看起来"明显错" | `transcript.jsonl` + `tool_calls.jsonl` | **可能是 RuleJudge MVP 边界** → deterministic substring 校验有限；记录在反馈中 |

---

## 9. 怎么提交反馈给 maintainer？

3 种方式（任选一种）：

1. **5 分钟极简反馈**：填
   [INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md "5 分钟极简版"段](INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md#0-5-分钟极简版可选)。
2. **完整反馈（推荐）**：复制
   [INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md](INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md)
   到 `feedback/<your-team>-<YYYY-MM-DD>.md`，并按
   [INTERNAL_TRIAL_DOGFOODING_LOG.md "试用记录模板"段](INTERNAL_TRIAL_DOGFOODING_LOG.md#试用记录模板复制下面整段填好后追加到文件末尾)
   追加到 dogfooding log。
3. **正式 trial 申请**：复制
   [docs/templates/INTERNAL_TRIAL_REQUEST_TEMPLATE.md](templates/INTERNAL_TRIAL_REQUEST_TEMPLATE.md)
   填好后发给 maintainer，用于"我打算开始 / 已完成一次试用"的对外
   登记，含必填的 redaction 自查。

> **反馈数量与 v3.0 关系**：当前真实团队反馈 = 0；v3.0 = not started。
> v3.0 的启动**严格需要**至少 3 份不同团队反馈，且每份满足
> [LAUNCH_PACK §8 v3.0 触发条件](INTERNAL_TRIAL_LAUNCH_PACK.md#8-v30-触发条件严格保持-backlog)
> 中的 4 项硬约束。**单次反馈不会**让 v3.0 启动。

---

## 10. 哪些情况**不要**自己乱试（安全 / 泄漏硬红线）

下面任意一项命中 → **立即停止试用**，先脱敏再继续：

- ❌ 真实 secret（API key / SSH key / DB 密码 / 内部 token）；
- ❌ 真实生产请求体 / 响应体（含真实用户数据 / 真实订单 / 真实日志）；
- ❌ 真实 `Authorization` header（`Bearer ...` / `Basic ...`）；
- ❌ 敏感 `base_url`（含 `?token=` / `?cookie=` / 内部网段地址）；
- ❌ 用户隐私数据（手机号 / 身份证 / 邮箱 / 支付信息 / 个人健康）；
- ❌ 未脱敏日志（HTTP / SDK 原始异常长文本，常含 token / cookie）；
- ❌ 把任何上述内容粘到 `runs/` artifact、`report.md`、issue、
  PR description、git commit message、dogfooding log、feedback 模板。

如果发现自己已经粘进去：

1. **立即** `rm -rf runs/<污染目录>`；
2. **立即** `git reset --hard` 撤销本地未推送 commit；
3. **如果已经 push**：联系 maintainer 走 secret rotation + git history
   清洗流程；
4. 先做脱敏，再继续试用。

> 默认配置下框架**不读取真实 `.env`、不调真实 LLM、不联网**；live
> judge 是**强 opt-in**，需要本地 env + 双标志确认才会启动，详见
> [LAUNCH_PACK §9 安全 / no-leak 硬约束](INTERNAL_TRIAL_LAUNCH_PACK.md#9-安全--no-leak-硬约束试用全程必须遵守)。

---

## 维护说明（给改这份文档的人看）

- 本文是**面向内部小组试用者**的自助入口；不重复 LAUNCH_PACK / QUICKSTART
  的命令大段，只回答"我有一个 AI Tool 怎么开始 / 失败属于哪类 / 怎么
  提交反馈 / 哪些不要碰"10 个问题；
- 不允许在本文中**伪造**已有团队成功案例；任何示例必须明显标占位
  （`<your-team>` / `<your-tool>` 等）；
- 命令片段**不引入**新 CLI flag；与 `INTERNAL_TRIAL_QUICKSTART.md` /
  `INTERNAL_TRIAL_LAUNCH_PACK.md` 中的命令对齐（drift 测试见
  `tests/test_docs_cli_snippets.py` / `tests/test_docs_cli_schema_drift.py`）；
- 测试 `tests/test_internal_team_self_serve_trial.py` 钉死本文件
  10 个问题段 + no-leak 硬红线 + v3.0 不会因单次反馈启动等关键契约。
