"""tools_unsafe —— **故意**在模块顶层 raise 的诱饵文件。

存在意义（**关键安全契约**）
----------------------------
- 如果 scaffold-tools 走任何动态 `import` / `exec` / `compile` 路径，本文件
  顶层的 `raise RuntimeError(...)` 一定会触发，端到端 smoke 会立刻 FAIL。
- 这是"scaffold 绝不执行用户代码"这一不变量的**最后防线**。任何想引入
  "便捷"动态 import 的改动，都必须先把本文件删掉——而删本文件会让
  `tests/test_bootstrap_pipeline_smoke.py` FAIL。

scaffold 应当：
- 用 `ast.parse(source_text)` 读取本文件；
- 抽出 `risky_action` 函数的 signature/docstring；
- 然后**继续**扫描下一个文件，绝不触发本模块顶层语句。
"""

from __future__ import annotations

# 顶层副作用：scaffold 路径如果不小心 import 这个 module，立刻 RuntimeError。
raise RuntimeError(
    "scaffold-tools must NEVER import user modules — "
    "this file's import-time side effect is the safety canary"
)


def risky_action(target: str) -> dict:  # pragma: no cover - 永远不会被执行
    """模拟一个高风险动作工具（fixture：只为 scaffold 静态扫描可见）。"""
    return {"target": target, "executed": False}
