# 真实用户接入常见坏配置

> 这些 YAML 不是 demo，**故意写错**，用于：
> 1. 在 `tests/test_bad_configs.py` 里锁死“坏配置 → 可行动错误信息”这一边界；
> 2. 给真实接入者一份对照表，看到框架报哪类错时能立刻知道改哪一行。
>
> 本目录不进入 demo 主链路；CLI run 不会消费这些文件。

## 文件清单

| 文件 | 模拟的真实用户错误 | 期望 harness 行为 |
|---|---|---|
| `tools_empty.yaml` | 用户写了占位 `tools: []` 想先跑一遍审计 | CLI 打印 warning（stderr）但允许继续；audit/report 显示 0 工具 |
| `evals_empty.yaml` | 用户先 commit 占位 `evals: []` | 同上：warning + 0 eval |
| `tools_scalar_root.yaml` | YAML 顶层错写成字符串 | `ConfigError`：`tools.yaml root must be a mapping or list` |
| `tools_bad_entry.yaml` | `tools[0]` 写成字符串而不是 mapping | `ConfigError`：`tools[0] must be a mapping` |
| `tools_duplicate_qualified.yaml` | 两个工具拥有相同 `namespace.name` | `ToolRegistryError`：`duplicate qualified tool names` |
| `evals_duplicate_id.yaml` | 两条 eval 用了相同 id | `ConfigError`：`eval.id must be unique` |
| `tool_missing_optional_fields.yaml` | 工具缺 `when_to_use` / `output_contract` / `token_policy` / `side_effects` | loader 不报错；`ToolDesignAuditor` 给出 `missing_*` finding |
| `eval_missing_outcome.yaml` | eval 缺 `initial_context` / `verifiable_outcome` | loader 不报错；`EvalQualityAuditor` 标 `runnable=false` 并给 high-severity finding |

## 使用方式

```python
import pathlib
from agent_tool_harness.config.loader import load_tools, ConfigError

bad = pathlib.Path("examples/bad_configs/tools_scalar_root.yaml")
try:
    load_tools(bad)
except ConfigError as exc:
    print(exc)  # 框架提示：tools.yaml root must be a mapping or list
```

具体测试见 `tests/test_bad_configs.py`。
