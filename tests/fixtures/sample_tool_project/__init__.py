"""sample_tool_project：bootstrap 端到端 smoke 测试用的最小工具源码 fixture。

存在意义
--------
- 给 `tests/test_bootstrap_pipeline_smoke.py` 提供一个**安全、稳定、可复现**
  的"假装是用户项目"的目录，用来端到端验证
  `scaffold-tools → scaffold-evals → scaffold-fixtures` 三步链路。
- 故意混入 `tools_unsafe.py`：模块顶层 `raise RuntimeError(...)`，
  用来钉死"scaffold 绝不动态 import 用户代码"这一安全不变量——
  任何静默 `importlib` 退路都会立刻让端到端 smoke FAIL。

不是什么
--------
- **不是**真实工具实现示例，**不要**被 user 当 ToolSpec 模板复制。真实模板
  请看 `examples/runtime_debug/demo_tools.py`。
- 这里函数都是纯 Python、零副作用、零 IO，仅作为 ast scaffold 的输入文本。
"""
