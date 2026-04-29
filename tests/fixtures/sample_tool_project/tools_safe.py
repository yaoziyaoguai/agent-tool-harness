"""tools_safe —— 一组安全的、可被 ast 静态扫描的"伪工具"函数。

设计目的：作为 `scaffold-tools` 的输入样本。所有函数都是纯函数、零 IO、
零副作用、无网络；docstring 首行简短（首行会被 scaffold 抄进 description）。

注意：函数体内容和 scaffold 无关——scaffold 只看 def signature + docstring。
"""

from __future__ import annotations


def query_user_profile(user_id: str, include_preferences: bool = False) -> dict:
    """根据用户 id 查询基础 profile。

    更长的 docstring 段落不会被 scaffold 抄进 description（避免敏感内容泄漏）。
    本函数纯属 fixture，函数体不会被 scaffold 执行——但即便被执行也是安全的。
    """
    return {"id": user_id, "preferences_included": include_preferences}


def list_recent_orders(user_id: str, limit: int = 10) -> list[dict]:
    """列出用户最近订单（fixture stub）。"""
    return [{"order_id": f"o-{i}", "user_id": user_id} for i in range(limit)]


def _internal_helper(x: int) -> int:
    """私有 helper，scaffold 应跳过（名字 `_` 开头）。"""
    return x * 2
