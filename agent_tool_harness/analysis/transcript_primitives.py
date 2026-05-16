"""v3.5 P1: Transcript 分析基础原语。

提供序列窗口遍历、args 比较、tool switching 检测等底层函数。
所有函数为纯函数，不修改输入，不调 LLM。

架构边界
--------
- **负责**：字符串规范化、args 签名生成、窗口遍历、tool switching 计数。
- **不负责**：不做完整 confusion pattern 分析（那是 transcript_confusion.py 的事）、
  不做 context efficiency 分析、不生成 Finding。
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

# ---------------------------------------------------------------------------
# Args 规范化 & 比较
# ---------------------------------------------------------------------------


def normalize_args(args: dict[str, Any]) -> str:
    """将 args dict 规范化为确定性字符串签名。

    用于判断两次 tool call 是否使用了"相同"参数。
    JSON 序列化保证确定性（sort_keys=True, separators 紧凑格式）。

    Args:
        args: ToolCall.arguments dict。

    Returns:
        确定性签名串。空 dict → "{}"。
    """
    return json.dumps(args, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def args_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    """计算两次调用的参数相似度（0.0-1.0）。

    规则：
    - 两者都为空 dict → 1.0
    - 键集合相同、所有值 JSON 相等 → 1.0
    - 键集合相同、部分值变化 → Jaccard-like 分数
    - 键集合不同 → Jaccard(keys) × 值相等比例
    - 任一为空 → 0.0

    Args:
        a, b: 两次 ToolCall 的 arguments dict。

    Returns:
        0.0（完全不同）到 1.0（完全相同）之间的相似度。
    """
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0

    a_keys = set(a.keys())
    b_keys = set(b.keys())
    all_keys = a_keys | b_keys

    if not all_keys:
        return 1.0

    # 键级别相似度：多少键在两个 call 中都存在
    key_jaccard = len(a_keys & b_keys) / len(all_keys)

    # 值级别相似度：对于共同键，有多少值 JSON 相同
    common_keys = a_keys & b_keys
    if not common_keys:
        return 0.0

    same_values = sum(
        1 for k in common_keys
        if json.dumps(a[k], sort_keys=True, ensure_ascii=False)
        == json.dumps(b[k], sort_keys=True, ensure_ascii=False)
    )
    value_similarity = same_values / len(common_keys)
    # 确保至少有一个共同 key 时的值相似度

    return key_jaccard * value_similarity


# ---------------------------------------------------------------------------
# 序列窗口遍历
# ---------------------------------------------------------------------------


def sliding_window(items: list, size: int) -> Iterator[tuple]:
    """对列表做固定大小的滑动窗口遍历。

    Args:
        items: 任意列表。
        size: 窗口大小，必须 ≥ 1。

    Yields:
        len(items) - size + 1 个 tuple，每个包含 size 个连续元素。
    """
    if size < 1:
        raise ValueError(f"window size must be >= 1, got {size}")
    for i in range(len(items) - size + 1):
        yield tuple(items[i:i + size])


def consecutive_groups(items: list, key) -> list[list]:
    """将列表按 key 函数分组为连续段。

    与 itertools.groupby 不同：只合并相邻相等的元素，
    相同 key 但不相邻的元素分属不同组。

    Args:
        items: 任意列表。
        key: 函数，item → group key。

    Returns:
        分组列表，每组内元素 key 相同且连续相邻。
    """
    if not items:
        return []

    groups: list[list] = []
    current: list = [items[0]]
    current_key = key(items[0])

    for item in items[1:]:
        k = key(item)
        if k == current_key:
            current.append(item)
        else:
            groups.append(current)
            current = [item]
            current_key = k
    groups.append(current)
    return groups


# ---------------------------------------------------------------------------
# Tool switching 检测
# ---------------------------------------------------------------------------


def count_tool_switches(
    tool_names: list[str],
    window_size: int | None = None,
) -> int:
    """统计 tool_name 序列中的切换次数。

    一次切换 = 相邻两次调用的 tool_name 不同。

    Args:
        tool_names: 按时间顺序排列的 tool_name 列表。
        window_size: 可选，限制在最近 N 次调用内统计。

    Returns:
        切换次数。
    """
    if window_size is not None:
        tool_names = tool_names[-window_size:]
    if len(tool_names) < 2:
        return 0
    switches = 0
    for i in range(len(tool_names) - 1):
        if tool_names[i] != tool_names[i + 1]:
            switches += 1
    return switches


def find_repeated_sequences(
    tool_names: list[str],
    min_period: int = 2,
    min_cycles: int = 2,
) -> list[dict[str, Any]]:
    """在 tool_name 序列中找出重复的模式（A→B→A→B...）。

    用于检测 tool_switching_confusion。

    Args:
        tool_names: 按时间顺序的 tool_name 列表。
        min_period: 最小周期长度（如 period=2 表示 A→B 交替）。
        min_cycles: 最少完整循环次数。

    Returns:
        找到的重复序列信息列表，每个元素包含：
        - pattern: 重复的 tool_name 模式
        - cycles: 完整循环次数
        - start_idx: 起始位置
        - end_idx: 结束位置
    """
    results: list[dict[str, Any]] = []
    n = len(tool_names)

    for period in range(min_period, n // 2 + 1):
        i = 0
        while i <= n - period * min_cycles:
            pattern = tuple(tool_names[i:i + period])
            # 必须是不同的工具 name（否则不是 switching）
            if len(set(pattern)) < 2:
                i += 1
                continue

            # 查这个 period 重复了多少次
            cycles = 1
            j = i + period
            while j + period <= n and tuple(tool_names[j:j + period]) == pattern:
                cycles += 1
                j += period
            if cycles >= min_cycles:
                results.append({
                    "pattern": list(pattern),
                    "period": period,
                    "cycles": cycles,
                    "start_idx": i,
                    "end_idx": j,
                })
                i = j
            else:
                i += 1
    return results


# ---------------------------------------------------------------------------
# Truncation & response analysis
# ---------------------------------------------------------------------------


def is_truncated(output_text: str) -> bool:
    """检测 output 是否被截断。

    扫描以下截断标记：
    - 以 "..." 结尾
    - 以 "[truncated]" 或 "(truncated)" 结尾
    - 以 "…" 结尾

    Returns:
        True 如果检测到截断标记。
    """
    text = output_text.rstrip()
    truncation_markers = ("...", "[truncated]", "(truncated)", "…")
    for marker in truncation_markers:
        if text.endswith(marker):
            return True
    return False


def extract_fields_usage(
    output: dict[str, Any],
    referenced_fields: set[str] | None = None,
) -> dict[str, Any]:
    """分析 dict output 中各个字段的字符占比。

    用于 low_value_large_fields 检测：Agent 未引用的字段如果占用大量字符，
    就是浪费上下文。

    Args:
        output: ToolResult.output dict。
        referenced_fields: Agent 在后续步骤中引用的字段名集合。

    Returns:
        {
            "total_chars": int,
            "field_sizes": {field_name: char_count},
            "field_ratios": {field_name: ratio},
            "largest_field": str | None,
            "unreferenced_ratio": float,
        }
    """
    result: dict[str, Any] = {
        "total_chars": 0,
        "field_sizes": {},
        "field_ratios": {},
        "largest_field": None,
        "unreferenced_ratio": 0.0,
    }
    total = 0
    sizes: dict[str, int] = {}

    for key, val in output.items():
        char_count = len(str(val))
        sizes[key] = char_count
        total += char_count

    result["total_chars"] = total
    result["field_sizes"] = sizes

    if total > 0:
        result["field_ratios"] = {k: v / total for k, v in sizes.items()}
        largest = max(sizes, key=sizes.get) if sizes else None
        result["largest_field"] = largest

        if referenced_fields is not None:
            unreferenced_chars = sum(
                sizes[k] for k in sizes if k not in referenced_fields
            )
            result["unreferenced_ratio"] = unreferenced_chars / total

    return result


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 可靠截断标记
_TRUNCATION_MARKERS = ("...", "[truncated]", "(truncated)", "…")

# 常见分页参数名
_PAGINATION_PARAMS = {
    "limit", "page", "offset", "max_results", "cursor",
    "per_page", "next_token", "continuation_token", "start",
    "count", "size", "top", "skip",
}
