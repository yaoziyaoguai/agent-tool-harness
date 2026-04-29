# Push Readiness Summary — v2.x

> **历史层文档**（保留作 historical reference + 被测试 pin 防 drift）。
>
> **新读者请直接看
> [`V2_X_RELEASE_CANDIDATE_NOTES.md`](V2_X_RELEASE_CANDIDATE_NOTES.md)**，
> 那是当前 maintainer 封板判断的 canonical 文档；本页保留下面历史记录
> 仅供时间线追溯。
>
> ---
>
> **不是** release note；**是**当前 16 commits ahead origin/main 的
> push 前自检清单。维护者 review 后人工 ``git push origin main``。

## 1. Commits 概览

- ahead origin/main: **16 commits**（含本文档 commit）
- working tree: clean
- 没有 mindforge / my-first-agent 串入

## 2. Commits 分组（Roadmap 节点对应）

| Commit 范围 | Roadmap 节点 | 性质 |
|---|---|---|
| `5e8ea8b` | internal trial docs / dogfooding 三件套 + 27 regression test | docs + test |
| `ce3de8e` | internal team self-serve trial pack | docs |
| `e7fd55f` | 9→10 artifact count drift 修复 | docs (real bug) |
| `b1db4e6` `14980e5` | scaffold-tools CLI + invalid yaml fix | feat + fix |
| `377ebd8` | scaffold-evals + scaffold-fixtures | feat |
| `504aa53` | validate-generated CLI | feat |
| `16f8c11` | strict-reviewed TODO comment 漂误判 fix | fix (real bug) |
| `a2d7b01` | bootstrap-to-run sample pack + strict reviewed validation | feat |
| `bf70f4d` | user-friendly bootstrap (one-command) | feat |
| `32c611f` | bootstrap UX hardening + doctor checks | feat |
| `c5a2540` | Real Trial Candidate Pack + REVIEW_CHECKLIST §6 | feat + docs |
| `6398307` | Realistic Offline Tool Trial sample (3 functions + 14 tests) | feat + test |
| `3b06060` | .env.example productionization + namespace safety test | chore + test |
| `4be3f64` | Controlled live smoke 3-model matrix 脱敏 ROADMAP record | docs |
| (本 commit) | First Internal Trial Handoff Pack + invite + push readiness | docs + test |

## 3. Release gate 自检

| 检查 | 结果 |
|---|---|
| `ruff check .` | All checks passed |
| `pytest -q` | **580+ passed, 1 xfailed**（xfailed 是 ROADMAP-tracked 的 v0.2 candidate-A subtle decoy） |
| docs CLI snippet drift | 全过 |
| internal trial smoke / readiness | 全过 |
| no-leak / safety (22 keyword tests) | 全过 |
| bootstrap pipeline smoke (7) | 全过 |
| bootstrap-to-run / validate-generated / user-friendly bootstrap | 全过 |
| real trial readiness / realistic sample | 全过 |
| live/preflight safety (69) | 全过 |
| First trial handoff（本轮新增） | 全过 |

## 4. Realistic offline trial 验证

最近一次 maintainer rehearsal（commit `6398307`）：7 步路径全过，
strict-reviewed=pass，run good=2/2 passed，10 件套 artifact 完整。
本轮无回归。

## 5. Live compatibility 验证（受控、真实网络）

3 个模型（``qwen3-coder-next`` / ``glm-5`` / ``kimi-k2.5``）真实 live
network call × 1 each：

- 3/3 model: deterministic RuleJudge **PASS**
- 3/3 model: live judge → 脱敏 ``bad_response`` 路径
- 3/3 model: 0 leak across api_key / base_url / Authorization /
  full request / full response / raw exception traceback

> ``bad_response`` 是 v1.x 8 类 error taxonomy 的预期且安全的失败路径，
> **不阻塞** v2.x offline 主线。Multi-format live judge 属 v3.0 backlog。

## 6. 安全自检

- `.env`：present、ignored、NOT tracked ✅
- `.env.example`：no real key / no real URL ✅
- 16 commits 全 grep：0 个真实 key / 真实 endpoint URL / 完整请求响应 ✅
- runs/ 目录：在 `.gitignore`，不会被误提交 ✅

## 7. Push 建议

| 选项 | 建议 |
|---|---|
| **现在 push** | ✅ **可以**，前提是你（人工）已 review 16 commits 的 commit message + 关键 diff。我**不**自动 push。|
| 现在 tag | ❌ **不建议**——tag 应该等收到 ≥ 1 份真实内部反馈再打。让 tag 真正代表"试用过的版本"，而不是"自测过的版本"。|
| Tag 时机 | 第一位非维护者同事按 ``docs/FIRST_INTERNAL_TRIAL_HANDOFF.md`` 跑通 + 反馈追加到 ``INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`` 后，tag `v2.1` 或 `v2.x-real-trial-readiness`（语义化优先）。|

## 8. 第一位内部同事下一步

按 ``docs/FIRST_INTERNAL_TRIAL_INVITE_TEMPLATE.md`` 复制邀请话术，
私聊或 IM 发给一位**非维护者**同事；让 ta 按
``docs/FIRST_INTERNAL_TRIAL_HANDOFF.md`` §3 7 步走查 + §4 反馈模板填写。

## 9. 推荐执行顺序

1. **第一位真实内部同事试用**（最高优先级）—— 等真实反馈
2. **push 16 commits**（次优先级）—— 人工 review 后执行 `git push origin main`
3. **Tag**（最低优先级）—— 收到 ≥ 1 份真实反馈后再 tag
4. **继续 v2.x patch** —— 仅在反馈触发时；不要为了"凑提交"乱改
