"""Tool scaffold 子包：把"第一次接入 agent-tool-harness"的成本压低。

模块职责（v2.x patch / Internal Trial Ready 后续效率增强）：
- 用 Python 标准库 `ast` **静态**扫描用户项目源码；
- 抽取候选 tool 函数的 name / docstring / 参数类型注解 / 返回类型注解；
- 写出 **draft** `tools.yaml`，**所有**不能可靠静态推断的字段（when_to_use /
  when_not_to_use / output_contract / token_policy / side_effects）一律标
  `TODO`，不得伪装成 production-approved 配置；
- 文件头明示：generated draft / review required / does not execute /
  does not read secrets / not production-approved。

边界（强约束，违反即视为 bug）：
- **绝不**动态 `import`/`exec`/`compile`/`eval` 任何用户代码（防止 import-side
  effects 触发联网 / 写文件 / 读 .env / 调真实 LLM）；
- **绝不**调 shell、**绝不**联网；
- **绝不**自动覆盖已存在的 output 文件（`--force` 必须显式给）；
- **绝不**为 `output_contract` 等需要业务真实样例的字段瞎猜——只能写 TODO。

为什么必须是 draft：tools.yaml 是 ToolSpec 的契约源，决定 Agent 看到的工具
描述、什么时候用、什么时候不用、token 策略、side effects——这些字段需要工具
作者人工审核，不是静态分析能保证准确的。scaffold 把"机械可推断"部分自动化，
"语义判断"部分留给 reviewer。

何处接入：
- CLI 入口：`python -m agent_tool_harness.cli scaffold-tools --source <dir> --out <yaml>`；
- Python API：`scaffold_tools_yaml(source_dir, output_path)`；
- 关闭/扩展：未来若要加 `from_mcp` / `from_openapi`，应**新增**子模块（例如
  `from_mcp.py`），不要把网络 / live 路径塞进当前 `from_python_ast.py`。

未来扩展点（v3.0 backlog，本轮**不做**）：
- 真实工具 instrumentation 抽 output 样例；
- LLM 协助生成 when_to_use / when_not_to_use 草稿；
- MCP 服务器 `tools/list` 自动 discovery；
- 与 audit-tools 联动一键 audit draft。
"""

from __future__ import annotations

from agent_tool_harness.scaffold.from_python_ast import (
    ScaffoldedTool,
    scaffold_tools_yaml,
    scan_python_module,
)

__all__ = ["ScaffoldedTool", "scaffold_tools_yaml", "scan_python_module"]
