# First Real Trial Execution Plan — 第一次真实试用执行包

> **这是给 maintainer 用的一页执行包**，不是给试用者本人看的。
> 给试用者请直接复制 [`PUSH_PREFLIGHT_CHECKLIST.md`](PUSH_PREFLIGHT_CHECKLIST.md)
> §② 中文 IM。
>
> 关联文档：
> - 试用 7 步细节 → [`FIRST_INTERNAL_TRIAL_HANDOFF.md`](FIRST_INTERNAL_TRIAL_HANDOFF.md)
> - 反馈模板 → [`INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md`](INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md)
> - 反馈分流 → [`FEEDBACK_TRIAGE_WORKFLOW.md`](FEEDBACK_TRIAGE_WORKFLOW.md)
> - 失败处置 → [`PUSH_PREFLIGHT_CHECKLIST.md`](PUSH_PREFLIGHT_CHECKLIST.md) §④

---

## 1. 试用目标（不是验证所有功能 / 不是启动 v3.0）

只验证 8 件事：

1. 非维护者能否理解试用路径；
2. 能否选一个合适的小工具；
3. 能否跑 `bootstrap`；
4. 能否 review TODO；
5. 能否 strict-validate；
6. 能否跑 deterministic `run` / `replay-run`；
7. 能否看懂 `report.md` + 10 件 artifact；
8. 能否提交可分流的反馈。

**不验证**：live judge / multi-format provider / MCP / Web UI / 真实 LLM /
HTTP-Shell executor / 企业平台。

## 2. 试用者选择标准

第一位试用者建议：

- 有基本 Python / CLI 能力；
- 能读 YAML；
- 手头有一个小工具 / 能从已有项目拆出一个小工具；
- 愿意记录失败路径，不只报 PASS；
- 不会一上来就要 Web UI / MCP / live judge。

**避开**：从未跑过 CLI 的同事 / 期望"开箱即生产"的同事 /
只愿试用不愿写反馈的同事。

## 3. 工具选择标准（试用者选第一个工具时必过）

第一个工具必须满足全部 13 条：

1. 单一工具（不是工具集）；
2. 输入输出简单（结构化 dict / str）；
3. 不依赖真实 secret / API key；
4. 不需要联网；
5. 不需要数据库；
6. 不需要真实用户数据；
7. 可以 mock fixture；
8. 可以写 2-3 个 deterministic eval；
9. 不涉及真实公司敏感路径；
10. 不涉及真实请求体 / 响应体；
11. 不需要 HTTP / Shell executor；
12. 不需要 MCP；
13. 不需要 live LLM judge。

不确定时让试用者参考 `examples/realistic_offline_tool_trial/` 的样本。

## 4. 试用前 Maintainer 自检（已就绪可发邀请）

| 检查 | 当前状态 |
|---|---|
| 远端 main 含 latest v2.x commits | ✅ origin/main = 229a6fe |
| 未 tag | ✅ 仍为 v2.0 |
| v3.0 still not started | ✅ |
| README / QUICKSTART / HANDOFF / TRIAGE 可用 | ✅ |
| 反馈模板 §11 triage hint | ✅ |
| no-leak 边界已说明 | ✅ |
| IM 含"不要贴 key/Authorization/完整请求响应" | ✅ |
| IM 含"maintainer rehearsal 不算反馈" | ✅ |
| IM 含"只跑一个小工具" | ✅ |

→ **可发邀请**。直接复制 `PUSH_PREFLIGHT_CHECKLIST.md` §② IM。

## 5. 七步执行路径（CLI 真实命令名）

试用者执行：

```bash
# 1. 选一个小工具（参考 §3 13 条）
# 2. bootstrap：一条命令出 tools/evals/fixtures/checklist/summary 草稿
.venv/bin/python -m agent_tool_harness.cli bootstrap \
  --source <module-or-path> \
  --out runs/trial-1/

# 3. review REVIEW_CHECKLIST.md（在 runs/trial-1/ 下）
# 4. 修 # TODO_REVIEW 占位（编辑 runs/trial-1/tools.yaml 与 evals.yaml）

# 5. validate-generated：先非 strict 看 warning
.venv/bin/python -m agent_tool_harness.cli validate-generated \
  --bootstrap-dir runs/trial-1/

# 6. validate-generated --strict-reviewed：必须全过才进入 run
.venv/bin/python -m agent_tool_harness.cli validate-generated \
  --bootstrap-dir runs/trial-1/ --strict-reviewed

# 7. deterministic run（不开 --live，不接真实 LLM）
.venv/bin/python -m agent_tool_harness.cli run \
  --project runs/trial-1/project.yaml \
  --tools   runs/trial-1/tools.yaml \
  --evals   runs/trial-1/evals.yaml \
  --out     runs/trial-1/run-good \
  --mock-path good

# 8. 看 runs/trial-1/run-good/report.md + 10 件 artifact
# 9. 复制 docs/INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md 填反馈
```

**绝不**让试用者跑 `cli run --judge-provider anthropic_compatible_live --live`。

## 6. 反馈收集路径

| 文档 | 用途 |
|---|---|
| `docs/INTERNAL_TRIAL_FEEDBACK_TEMPLATE.md` | 试用者**复制一份**填，发回 maintainer |
| `docs/INTERNAL_TRIAL_DOGFOODING_LOG.md` | maintainer 把试用者反馈摘要追加在此（含日期 / 来源 / 是否 real） |
| `docs/INTERNAL_TRIAL_FEEDBACK_SUMMARY.md` | maintainer 更新"真实反馈数量"+ A/B/C/D 分类小结 |
| `docs/FEEDBACK_TRIAGE_WORKFLOW.md` | maintainer 跑 §2 决策表给出 5 类之一 |

反馈必须含：real_feedback / maintainer_rehearsal / selected_tool /
bootstrap_result / TODO_count / review_time / strict_reviewed_result /
run_result / report_artifacts_path / most_useful_artifact / most_confusing_field /
reproduction_steps / security_risk / v2.x patch candidate / v3.0 backlog candidate /
offline-deterministic gap explanation / final triage decision。

模板 §11 已 1:1 对齐。

## 7. 失败排查顺序（artifact-first）

| 排查序 | 看什么 | 处置 |
|---|---|---|
| 1 | source path 是否存在 | 文档/UX 问题（v2.x patch） |
| 2 | bootstrap 是否生成 5 件草稿 | 看 `runs/trial-1/REVIEW_CHECKLIST.md` 是否有 |
| 3 | REVIEW_CHECKLIST 是否看懂 | 文档/UX 问题（v2.x patch） |
| 4 | TODO 是否未处理 | strict-reviewed 会失败，正常 |
| 5 | validate-generated 非 strict 是 warning 还是 error | warning 仅提示，error 看 stderr |
| 6 | strict-reviewed 失败原因（TODO / broken ref / missing fixture） | stderr 已带 actionable hint |
| 7 | fixture 是否 example-only | 试用者要补真实 mock 数据 |
| 8 | run 是否生成 10 件 artifact | 缺 → bug，看 stderr |
| 9 | report.md / artifact 是否定位到 finding | 不能定位 → v2.x patch |
| 10 | 是否文档/UX 问题 | 默认归 v2.x patch |
| 11 | 是否 security 问题（key / Authorization / 完整请求响应落盘） | **立即** security-blocker |

**不要做的事**：
- 不要先猜代码；
- 不要因为一次失败启动 v3.0；
- 不要把 bad_response 改成 PASS；
- 不要让试用者贴敏感数据；
- 不要把 maintainer 自跑算反馈。

## 8. 试用结束后的 Maintainer 操作

按 [`FEEDBACK_TRIAGE_WORKFLOW.md`](FEEDBACK_TRIAGE_WORKFLOW.md) §4 11 步走：
1. 复制反馈到 `INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`；
2. 标 `real_feedback` + `trial_completed`；
3. 列 artifact 路径；
4. 跑 §2 决策表；
5. 按 5 类之一行动；
6. 更新"真实反馈数量"；
7. 第 1 份真实反馈到位 → 才考虑 `git tag v2.1`；
8. **不**自动 push、**不**自动 tag、**不**因单份反馈启动 v3.0。

## 9. v3.0 Gate（仍关闭）

当前真实反馈数 = **0 / 3**。本执行包**不**启动 v3.0、**不**实现
MCP / Web UI / live judge / HTTP-Shell executor / multi-format provider /
企业平台能力中的任何一项。
