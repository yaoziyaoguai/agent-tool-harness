# realistic_offline_tool_trial sample

> v2.x **Realistic Offline Tool Trial** sample —— 比 toy lookup 更接近真实
> 内部工作流，但**完全 offline / deterministic / fake data**。

## 边界

- **不**联网；
- **不**读 `.env`；
- **不**调真实 LLM；
- **不**读数据库；
- **不**执行用户工具的危险副作用；
- **不**包含真实 API key / Authorization header / 请求体 / 响应体；
- **不**使用真实公司或个人数据。

如果你想接 MCP / Web UI / live LLM Judge / HTTP·Shell executor，那是 **v3.0**
backlog（still not started）。

## 工具

`sample_tools.py` 里的 3 个 deterministic 函数：

| 函数 | 作用 | offline 数据来源 |
|---|---|---|
| `search_fake_knowledge_base(query, top_k)` | 关键字 deterministic 排序，返回 fake KB hits | `_FAKE_KB` 硬编码 dict |
| `classify_fake_tool_failure(error_message, trace_excerpt)` | 关键字归类失败 | `_FAILURE_RULES` 硬编码列表 |
| `validate_fake_config_snippet(yaml_text)` | 关键字级 yaml 漏洞检查（不真 parse） | 纯字符串 `in` 判断 |

## 7 步路径（copy-paste 可跑）

```bash
# 1. 一条命令生成 draft 三件套 + REVIEW_CHECKLIST + validation_summary
python -m agent_tool_harness.cli bootstrap \
  --source examples/realistic_offline_tool_trial \
  --out /tmp/ath-realistic --force

# 2. 看 REVIEW_CHECKLIST（含 §6 First Tool Suitability Checklist）
cat /tmp/ath-realistic/REVIEW_CHECKLIST.md

# 3. doctor —— validate-generated 在 draft 上跑（status=warning 是预期）
python -m agent_tool_harness.cli validate-generated \
  --bootstrap-dir /tmp/ath-realistic

# 4. 用本目录已 reviewed 的 sample（reviewer 已经把 TODO 全填完）
#    跳过手工 review 步骤直接做 strict
python -m agent_tool_harness.cli validate-generated \
  --tools examples/realistic_offline_tool_trial/tools.reviewed.yaml \
  --evals examples/realistic_offline_tool_trial/evals.reviewed.yaml \
  --strict-reviewed

# 5. deterministic smoke run（mock 桩；不联网；不调真实 LLM）
python -m agent_tool_harness.cli run \
  --project examples/realistic_offline_tool_trial/project.yaml \
  --tools examples/realistic_offline_tool_trial/tools.reviewed.yaml \
  --evals examples/realistic_offline_tool_trial/evals.reviewed.yaml \
  --out runs/realistic-trial --mock-path good

# 6. 看 report.md + 10 件套 artifact
ls runs/realistic-trial/
open runs/realistic-trial/report.md
```

## maintainer rehearsal feedback

> **maintainer rehearsal only / not real internal team feedback /
> does not count toward the 3-feedback v3.0 gate.**

请把 maintainer rehearsal 反馈写进 `MAINTAINER_REHEARSAL.md`（与
`docs/INTERNAL_TRIAL_FEEDBACK_SUMMARY.md` 完全分离），不要污染真实团队反馈池。

## 不推荐做的事

- 不要把这个 sample 改造成真的查公司 KB / 真的 classify 真实工具失败 /
  真的 parse 业务 yaml —— 一旦接真实数据就**自动跨出 v2.x 范围**；
- 不要把任何真实 token / Authorization / base_url 粘进 `_FAKE_KB`；
- 不要在反馈里写真实工具名 / 真实 stack trace（脱敏后再贴）。
