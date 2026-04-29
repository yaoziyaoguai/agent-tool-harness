# Push Preflight Checklist — v2.x

> **面向**：维护者自己；**篇幅**：可在 5 分钟内执行完。
> **不是**：release note / 长篇运营文档。
> 包含 4 段：①push 前自检；②给同事的中文 IM；③operator checklist；
> ④第一次试用失败时的处理路径。

## 中文学习型说明

写成单一短文档而不是分成 4 个文件的原因：
- 维护者执行第一次真实内部试用时，需要"一页流程图"，跳来跳去会漏步骤
- 4 段都是**操作级**短指引，不是产品文档；与 README / HANDOFF / INVITE
  解释类文档分离
- 任何改动都要让 ``tests/test_first_internal_trial_handoff.py`` 仍通过；
  本文档新增独立测试覆盖见 ``tests/test_push_preflight_checklist.py``

---

## ① Push 前自检（5 分钟，缺一不可）

```bash
cd /Users/jinkun.wang/work_space/agent-tool-harness
git status --short                                                # 必须 empty
git rev-list --left-right --count origin/main...HEAD              # 必须 0  16
.venv/bin/python -m ruff check .                                  # 必须 All checks passed
.venv/bin/python -m pytest -q                                     # 必须 0 fail；xfailed 计数允许 1（v0.2 candidate-A subtle decoy）
git --no-pager log --oneline origin/main..HEAD                    # 16 行；逐行扫一眼，commit message 是否描述真实改动
git --no-pager diff origin/main..HEAD --name-only | grep "^runs/" # 必须 empty（runs/ 永远不应该入 commit）
git ls-files .env                                                 # 必须 empty（.env 永远不应该被 track）
```

只要任一行 fail，**不要 push**；先回到对应根因。

人工 spot-check：
- 16 个 commit message 全部 ``v2.x`` 范围：✅
- 没有 ``mindforge`` / ``my-first-agent`` 内容（不计 PUSH_READINESS_SUMMARY 自我声明）：✅
- 没有真实 key / Authorization / 完整请求体 / 完整响应体（可用 ``git --no-pager diff origin/main..HEAD | grep -F "$ANTHROPIC_API_KEY"`` 验证，期望**完全无输出**）：✅
- v3.0 仍 not started：✅

确认全部 ✅ 后人工执行：

```bash
git push origin main
```

**不**做 ``git tag``。Tag 等收到第一份真实反馈再打。

---

## ② 给第一位内部同事的中文 IM（300-500 字，可直接复制）

```
Hi <同事昵称>，想请你帮忙 10-15 分钟做一次 agent-tool-harness 的"第一位试用者"走查。

背景：这是一个内部用的 Agent 工具评测框架（offline / deterministic，
不需要 LLM key、不联网、不读你 .env）。我已经做完所有 maintainer
自测，但作者盲区永远存在，所以想请你以"完全没参与开发的人"身份
独立跑一遍。

只要 3 件事：

1. 从你自己的工具仓库挑 1 个**最简单的纯函数**（不需要 secret /
   不联网 / 不连数据库 / 不用真实公司或用户数据）。如果一时挑不出，
   就别选——这本身是有价值的反馈，告诉我即可。

2. 按 docs/FIRST_INTERNAL_TRIAL_HANDOFF.md §3 跑 7 步命令：
   bootstrap → review checklist → 修 TODO → validate-generated →
   strict-reviewed → run --mock-path good → 看 report.md。
   任何一步**卡 ≥ 5 分钟**请停下来，把 stderr 摘要给我。

3. 把 §4 反馈模板填好（17 个字段，结构化）追加到
   docs/INTERNAL_TRIAL_FEEDBACK_SUMMARY.md，发个 PR 或者直接贴给我。

⚠️ 请注意：
- 不要贴 API key / Authorization / 完整请求体 / 完整响应体
  到任何地方（IM / PR / issue / 反馈文档）
- 不要使用真实公司或用户敏感数据作为试用工具的输入
- 不要开 ``--live`` flag（v2.x 第一轮试用不需要）
- 这**不是** v3.0 需求收集会。如果觉得"必须有 LLM judge / MCP /
  真实 executor 才有用"，请在反馈 ``v3.0 candidate request`` 字段写
  **具体**理由（"我的工具语义判定无法用 RuleJudge 表达，因为..."），
  而不是泛泛"想要更多能力"

如果卡住，把 ``runs/<your-out-dir>/report.md`` 路径 + 错误摘要给我，
不要贴敏感内容。谢谢！
```

---

## ③ Operator Checklist（维护者执行第一轮试用）

按顺序，逐条勾掉：

| # | 行动 | 完成条件 |
|---|---|---|
| 1 | 完成 ①Push 前自检 9 行命令 + 4 项 spot-check | 全 ✅ |
| 2 | 人工 ``git push origin main``（不 tag） | origin/main 包含 23b3cb9 |
| 3 | 复制 ②IM 模板，发给 1 位**非维护者**同事 | IM 已发送 |
| 4 | 同事开始前确认工具选择（按 HANDOFF §2 决策表） | 同事确认 ✅ 或换工具 |
| 5 | 同事跑 ``bootstrap`` | stderr 无 fail |
| 6 | 同事 review ``REVIEW_CHECKLIST.md`` + 修 TODO | TODO 全部填完 |
| 7 | 同事跑 ``validate-generated`` | warning 友好模式不阻塞 |
| 8 | 同事跑 ``validate-generated --strict-reviewed`` | status=pass |
| 9 | 同事跑 ``run --mock-path good`` | passed >= 1，10 件套 artifact 齐 |
| 10 | 同事看 ``report.md`` + 1-2 个 artifact | 同事能解释 signal_quality 含义 |
| 11 | 同事填 §4 反馈模板 17 字段（含 ``does this count as real internal feedback: yes``） | 17 字段非空 |
| 12 | 我把反馈追加到 ``docs/INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`` 末尾 | commit 进 git |
| 13 | 反馈中所有 ``v2.x patch suggestion`` → 进 ``docs/ROADMAP.md`` v2.x backlog 段；只挑根因清晰 + 小改动的做 | ROADMAP 更新 commit |
| 14 | 反馈中所有 ``v3.0 candidate request`` 且理由具体 → 进 ``docs/ROADMAP.md`` v3.0 backlog 段（**不**自动启动 v3.0） | ROADMAP 更新 |
| 15 | 反馈中泛泛"想要更多能力"无具体根因 → **不算 v3.0 触发**，写个简短回应给同事即可 | — |
| 16 | 收齐 ≥ 3 份真实反馈 + ≥ 1 份具体 v3.0 候选根因 → 才正式 review v3.0 立项 | 触发条件未满足前**不**做 v3.0 |
| 17 | 第一份真实反馈进入 git 后，可以人工 ``git tag v2.1`` 或 ``git tag v2.x-real-trial-readiness``（tag message 引用反馈 commit hash） | tag 推 origin |

---

## ④ First Trial Failure Handling Guide（不要先猜）

同事报告"卡住"时，按从浅到深排查（**先看 artifact，不要先看代码**）：

| 失败现象 | 第一步看 | 可能根因 | 处置 |
|---|---|---|---|
| `bootstrap` 命令 not found / import 错 | stderr 摘要 | venv 未激活 / Python 版本 | 让同事 ``which python`` + ``python -V``；可能是 README 安装段需要补充 |
| `bootstrap` 跑完没生成 4 件套 | ``ath-first-trial/`` ls 输出 | ``--source`` 路径错 / 用户工具目录是空的 | 检查 source 路径；如果工具目录是空的，让同事换工具 |
| ``REVIEW_CHECKLIST.md`` 看不懂 | 同事用自己的话描述卡在哪一节 | 文档措辞 / §6 决策表不清 | **真 v2.x patch 候选**：改 ``bootstrap.py`` 模板措辞，加测试 |
| TODO 数量异常多 | ``grep -c TODO_ tools.generated.yaml`` | 用户工具 docstring 缺失 | 不是 bug——本身就是 v2.x 设计：让 reviewer 强制补语义 |
| ``validate-generated`` warning 友好模式都 fail | ``validation_summary.json`` | 真实 schema 错 / 缺 fixture | 按 fail message 修；如果 message 不可行动，**真 v2.x patch 候选** |
| ``--strict-reviewed`` fail | 同上 + 看是否漏改 ``runnable: true`` / 漏填 TODO | 通常是 reviewer 没改 | 让同事改完再跑；如果是漂误判（如 commit 16f8c11 历史），**真 v2.x patch 候选** |
| ``run --mock-path good`` passed=0 | ``judge_results.json`` + ``tool_calls.jsonl`` + ``tool_responses.jsonl`` | evidence 格式错（dict vs str）/ tool 顺序错 | 看 ``RuleJudge`` 报告的 fail rule；让同事按 ``REAL_TRIAL_CANDIDATE.md`` §2 evidence 形态修 |
| 10 件套 artifact 缺 | ``ls runs/<out>/`` | 早期失败导致提前退出 | 看最早一个错误日志；通常上面某条已先 fail |
| ``signal_quality`` 看不懂 | 同事用自己的话描述误解 | 文档解释不到位 | **真 v2.x patch 候选**：改 ``MarkdownReport`` 措辞 |
| live judge ``bad_response`` | 提醒同事："v2.x 第一轮不开 ``--live``" | gateway envelope 不严格 Anthropic | **不是** v2.x bug；记到 ROADMAP item #11 已记录的 backlog |
| 同事说"必须 LLM judge / MCP / Web UI 才能用" | 反馈 §4 ``v3.0 candidate request`` 字段 | 通常是工具选错（应该选更小的） | 先按 HANDOFF §2 决策表换更小工具再试；如果换了仍不行且理由具体，进 v3.0 backlog **不**启动 |

**不要做的事**：
- ❌ 因为一次失败就启动 v3.0
- ❌ 因为试用者贴出 ``--live`` 输出就改 ``LiveAnthropicTransport``
- ❌ 把 ``bad_response`` 改成 PASS 的 hack
- ❌ 让试用者贴 key / 完整请求 / 完整响应 / 真实 endpoint URL 到任何地方
- ❌ 把 maintainer 自己复跑一遍当成"第二份真实反馈"
