# bootstrap_to_run sample pack

把 v2.x bootstrap chain 的最小闭环跑一遍：
**scaffold → validate → reviewed → run → report/artifacts**。

> 完全 deterministic / offline-first / 0 真实 LLM / 0 网络 / 0 .env。

## 文件清单

| 文件 | 角色 |
|------|------|
| `sample_tools.py` | 安全纯函数 demo 工具（PythonToolExecutor 会 import 它） |
| `project.yaml` | 最小 ProjectSpec |
| `tools.reviewed.yaml` | reviewer 在 scaffold-tools 草稿基础上人工填完 TODO 的产物 |
| `evals.reviewed.yaml` | reviewer 在 scaffold-evals 草稿基础上填完 TODO 的产物（`runnable: true`） |

## 5 步跑通

```bash
# 1. （演示用）从 sample_tools.py 生成 draft tools.yaml
python -m agent_tool_harness.cli scaffold-tools \
  --source examples/bootstrap_to_run \
  --out runs/bootstrap-sample/tools.draft.yaml --force

# 2. 从 draft tools.yaml 生成 draft evals.yaml + fixtures 占位
python -m agent_tool_harness.cli scaffold-evals \
  --tools runs/bootstrap-sample/tools.draft.yaml \
  --out runs/bootstrap-sample/evals.draft.yaml --force
python -m agent_tool_harness.cli scaffold-fixtures \
  --tools runs/bootstrap-sample/tools.draft.yaml \
  --out-dir runs/bootstrap-sample/fixtures.draft --force

# 3. validate draft → 期望 status=warning（draft 还有 TODO 未 review，不 fail）
python -m agent_tool_harness.cli validate-generated \
  --tools runs/bootstrap-sample/tools.draft.yaml \
  --evals runs/bootstrap-sample/evals.draft.yaml \
  --fixtures-dir runs/bootstrap-sample/fixtures.draft

# 4. validate reviewed → 期望 status=pass（这里直接用本目录已 reviewed 的产物）
python -m agent_tool_harness.cli validate-generated \
  --tools examples/bootstrap_to_run/tools.reviewed.yaml \
  --evals examples/bootstrap_to_run/evals.reviewed.yaml

# 5. 用 reviewed config 跑 deterministic smoke run
python -m agent_tool_harness.cli run \
  --project examples/bootstrap_to_run/project.yaml \
  --tools examples/bootstrap_to_run/tools.reviewed.yaml \
  --evals examples/bootstrap_to_run/evals.reviewed.yaml \
  --out runs/bootstrap-sample-good \
  --mock-path good
```

跑完会在 `runs/bootstrap-sample-good/` 看到 10 件套 artifact（含 `report.md`）。

## 为什么 draft → reviewed 要明确分两种文件

| 状态 | 是否能进 `run` | 原因 |
|------|----------------|------|
| `*.draft.yaml`（scaffold 写的） | ❌ 不能 | `runnable: false` + TODO 占位 + 业务字段没填；强行跑会写出 misleading PASS/FAIL |
| `*.reviewed.yaml`（人工填完的） | ✅ 可以 | TODO 全部清掉、`runnable: true`、`judge.rules` 实际语义、required_tools 引用真实工具 |

`validate-generated` 用同一套校验区分两者：draft → warning（in-review 是预期）；
reviewed 引用错工具或残留 TODO → fail（会让下游写假结果）。

## 不在范围

- 真实 LLM Judge / live API（v2.0 边界，强 opt-in 才能开本地 smoke）
- MCP / HTTP / Shell executor（v3.0+ backlog）
- 自动 patch 用户工具
- Web UI / 多租户

## 端到端测试

`tests/test_bootstrap_to_run_sample.py` 真跑上面 5 步，钉死：
draft warning → reviewed pass → run 产 10 artifact + 不联网 + 不读 .env。
