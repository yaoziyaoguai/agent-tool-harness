"""Report Insight -- v3.1 报告洞察层。

在 v3.0 ExecutionTrace + EvaluationResult 之上提供聚合指标、分组发现、
评分卡和可行动建议。所有组件为 deterministic、零网络依赖。

架构边界
--------
- **负责**：从 ExecutionTrace + EvaluationResult 派生聚合数据（metrics、
  scorecard、grouped findings、recommendations）。
- **不负责**：不修改 EvaluationResult / Finding 结构、不调 LLM、
  不访问文件系统、不依赖外部库。
- **为什么叫 insight 而非 analytics**：这些组件回答 reviewer 的四个递进问题：
  "整体怎样？" → Scorecard
  "数据面如何？" → Metrics
  "问题集中在哪？" → Grouped Findings
  "该先修什么？" → Recommendations

组件一览
--------
- ReportMetrics（P1）：16 个基础指标，从 trace + findings 计算
- MetricsCollector（P1）：纯计算函数，trace + eval_result → ReportMetrics
- GroupedFindings（P2）：4 种 finding 分组视图
- FindingGrouper（P2）：findings → GroupedFindings
- Recommendation（P4）：一条确定性修复建议
- RecommendationCatalog（P4）：rule_id → recommendation 映射表
- ReportScorecard（P3）：报告「一页纸」结论
- make_scorecard()（P3）：独立 builder 函数
- （后续 Phase 追加）ReportInsight（P5）
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field

from agent_tool_harness.core_contract import EvaluationResult, ExecutionTrace

# ---------------------------------------------------------------------------
# P1: ReportMetrics + MetricsCollector
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportMetrics:
    """一次 evaluation run 的聚合指标。

    所有字段由 MetricsCollector.collect() 从 ExecutionTrace + EvaluationResult
    计算得出。这 16 个字段是后续所有 insight 组件（Scorecard、Recommendations、
    报告渲染）的单一数据源。

    设计原则：
    - 只做聚合统计，不做语义判断（输出质量判断由 D5 findings 承担）
    - 所有计数型字段默认 0，rate 型字段默认 0.0
    - dict 型字段默认空 dict（非 None），方便下游无 None-check 遍历
    """

    # --- Tool call 统计 ---
    tool_call_count: int = 0
    """总工具调用次数。``len(trace.tool_calls)``。"""

    tool_result_count: int = 0
    """总工具返回次数。``len(trace.tool_results)``。"""

    unique_tool_count: int = 0
    """不重复工具数。``len(set(c.tool_name for c in trace.tool_calls))``。"""

    # --- 成功/失败 ---
    tool_success_count: int = 0
    """成功调用次数。仅按 ``status=="success"`` 计数，不检查 output 是否有意义。
    output 质量问题（low_signal、context_fields 缺失等）由 D5 response quality
    findings 和 recommendations 表达，不在此处与 success status 混在一起。"""

    tool_error_count: int = 0
    """错误调用次数。``status=="error"`` 的 tool_result 数量。"""

    tool_error_rate: float = 0.0
    """工具调用错误率。tool_error_count / max(tool_call_count, 1)。"""

    # --- 数据完整性 ---
    orphan_call_count: int = 0
    """孤立调用数。call_id 不在任何 tool_result 中的 tool_call 数量。"""

    orphan_result_count: int = 0
    """孤立返回数。call_id 不在任何 tool_call 中的 tool_result 数量。"""

    # --- 冗余 ---
    repeated_tool_call_count: int = 0
    """重复调用次数。同一 (tool_name, json.dumps(arguments, sort_keys=True,
    default=str)) 出现 ≥2 次的 tool_call 总数。用 json.dumps 序列化参数做等价
    比较，而非 frozenset——后者会丢失参数结构信息（如嵌套 dict/list）。"""

    # --- 响应大小 ---
    response_size_chars_total: int = 0
    """所有 tool_result.output 的 JSON 序列化后字符数之和。"""

    response_size_chars_by_tool: dict[str, int] = field(default_factory=dict)
    """按 tool_name 分组的响应大小。key: tool_name, value: 字符数。"""

    estimated_response_tokens_total: int = 0
    """估算 token 总数。response_size_chars_total // 4。
    这是粗估算（英文约 4 char/token，中文等 CJK 文本偏差可能较大），标注为
    estimate，不声称精确。v3.1 不做精确 token accounting。"""

    # --- Finding 统计 ---
    finding_count_by_severity: dict[str, int] = field(default_factory=dict)
    """按 severity 分桶的 finding 计数。
    key: "critical" | "high" | "medium" | "low" | "info"。"""

    finding_count_by_category: dict[str, int] = field(default_factory=dict)
    """按 category 分桶的 finding 计数。
    RuleFinding: 按 rule_type 的 top-level prefix 分子类别
    （如 tool_response、tool_spec、tool_ergonomics、tool_call、tool_result、
    tool_pair）。
    JudgeFinding: category="judge"。
    audit / signal: 防御性分桶，即使当前 v3.0 不产这类 finding。"""

    finding_count_by_tool: dict[str, int] = field(default_factory=dict)
    """按 tool_name 分桶的 finding 计数。
    工具名从 finding_id（首选）→ evidence_ref → message 中 best-effort 提取。
    无法提取时归入 "(unknown)"。
    注意：rule_type / rule_id 字段不编码具体 tool_name，故不从中提取。"""

    judge_finding_count: int = 0
    """LLM judge finding 总数。category=="judge" 的 finding 计数。"""


class MetricsCollector:
    """从 ExecutionTrace + EvaluationResult 计算 ReportMetrics。

    设计约束：
    - 不修改输入 —— trace 和 eval_result 只读
    - 不调 LLM —— 纯计算
    - 不访问文件系统 —— 不读写 JSON/artifact 文件
    - 不依赖外部库 —— 只用 stdlib json、collections.Counter

    用法::

        collector = MetricsCollector()
        metrics = collector.collect(trace, eval_result)
    """

    def collect(
        self,
        trace: ExecutionTrace,
        eval_result: EvaluationResult,
    ) -> ReportMetrics:
        """从 ExecutionTrace + EvaluationResult 计算 ReportMetrics。

        Args:
            trace: 一次 Agent 执行轨迹（tool_calls + tool_results）。
            eval_result: 一次场景的评测结果聚合（findings + passed）。

        Returns:
            ReportMetrics：16 个基础指标的聚合对象。
        """
        # ---- Tool call 统计 ----
        tool_call_count = len(trace.tool_calls)
        tool_result_count = len(trace.tool_results)

        tool_names = {c.tool_name for c in trace.tool_calls}
        unique_tool_count = len(tool_names)

        # ---- 成功/失败 ----
        # tool_success_count: 只看 status=="success"，不检查 output 是否为空/有意义
        tool_success_count = sum(
            1 for r in trace.tool_results if r.status == "success"
        )
        tool_error_count = sum(
            1 for r in trace.tool_results if r.status == "error"
        )
        tool_error_rate = (
            tool_error_count / max(tool_call_count, 1)
        )

        # ---- 数据完整性 ----
        result_call_ids = {r.call_id for r in trace.tool_results}
        orphan_call_count = sum(
            1 for c in trace.tool_calls if c.call_id not in result_call_ids
        )
        call_call_ids = {c.call_id for c in trace.tool_calls}
        orphan_result_count = sum(
            1 for r in trace.tool_results if r.call_id not in call_call_ids
        )

        # ---- 冗余 ----
        # 重复调用：相同 (tool_name, 序列化 arguments) 出现 ≥2 次
        # 用 json.dumps(sort_keys=True, default=str) 序列化参数做等价比较
        call_freq: Counter = Counter()
        for c in trace.tool_calls:
            key = (
                c.tool_name,
                json.dumps(c.arguments, sort_keys=True, default=str),
            )
            call_freq[key] += 1
        repeated_tool_call_count = sum(
            count for count in call_freq.values() if count >= 2
        )

        # ---- 响应大小 ----
        response_size_chars_total = 0
        response_size_chars_by_tool: dict[str, int] = {}
        for r in trace.tool_results:
            try:
                size = len(json.dumps(r.output))
            except (TypeError, ValueError):
                # output 中包含不可序列化对象时退避为 str
                size = len(str(r.output))
            response_size_chars_total += size
            tool_name = r.tool_name or "(unknown)"
            response_size_chars_by_tool[tool_name] = (
                response_size_chars_by_tool.get(tool_name, 0) + size
            )
        estimated_response_tokens_total = response_size_chars_total // 4

        # ---- Finding 统计 ----
        findings = eval_result.findings

        finding_count_by_severity: dict[str, int] = dict(
            Counter(f.severity for f in findings)
        )

        finding_count_by_category = self._compute_finding_count_by_category(findings)
        finding_count_by_tool = self._compute_finding_count_by_tool(findings)
        judge_finding_count = sum(
            1 for f in findings if f.category == "judge"
        )

        return ReportMetrics(
            tool_call_count=tool_call_count,
            tool_result_count=tool_result_count,
            unique_tool_count=unique_tool_count,
            tool_success_count=tool_success_count,
            tool_error_count=tool_error_count,
            tool_error_rate=tool_error_rate,
            orphan_call_count=orphan_call_count,
            orphan_result_count=orphan_result_count,
            repeated_tool_call_count=repeated_tool_call_count,
            response_size_chars_total=response_size_chars_total,
            response_size_chars_by_tool=response_size_chars_by_tool,
            estimated_response_tokens_total=estimated_response_tokens_total,
            finding_count_by_severity=finding_count_by_severity,
            finding_count_by_category=finding_count_by_category,
            finding_count_by_tool=finding_count_by_tool,
            judge_finding_count=judge_finding_count,
        )

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_finding_count_by_category(
        findings: list,
    ) -> dict[str, int]:
        """按 category 分桶 finding 计数。

        RuleFinding（category=="rule"）：按 rule_type 的 top-level prefix
        分子类别。例如 rule_type="tool_response.output.low_signal" →
        category="tool_response"。

        JudgeFinding（category=="judge"）：直接归入 "judge"。

        audit / signal：防御性分桶，即使当前 v3.0 不产这类 finding。
        """
        category_counter: Counter = Counter()
        for f in findings:
            cat = f.category
            if cat == "rule":
                rule_type = getattr(f, "rule_type", "")
                if rule_type:
                    # 取 top-level prefix：tool_response.output.low_signal → tool_response
                    prefix = rule_type.split(".")[0] if "." in rule_type else rule_type
                    category_counter[prefix] += 1
                else:
                    category_counter["rule"] += 1
            elif cat == "judge":
                category_counter["judge"] += 1
            elif cat in ("audit", "signal"):
                # 防御性分桶
                category_counter[cat] += 1
            else:
                # 未识别 category → 保留原值
                category_counter[cat] += 1
        return dict(category_counter)

    @staticmethod
    def _compute_finding_count_by_tool(
        findings: list,
    ) -> dict[str, int]:
        """从 finding 中 best-effort 提取 tool_name 并分桶计数。

        提取策略（按优先级）：
        1. finding_id 格式 ``rule_type::tool_name`` → 提取 tool_name
        2. evidence_ref 中包含 call_id → 暂无法直接映射到 tool_name，
           当前按 evidence_ref 文本匹配
        3. message 文本匹配已知工具名模式
        4. 兜底 → "(unknown)"

        注意：这是 best-effort 提取，覆盖率取决于 finding_id 命名规范是否
        包含 tool_name。P2 实现时会用真实 finding 样本验证覆盖率。
        """

        tool_counter: Counter = Counter()
        for f in findings:
            tool_name = MetricsCollector._extract_tool_name(f)
            tool_counter[tool_name] += 1
        return dict(tool_counter)

    @staticmethod
    def _extract_tool_name(f) -> str:
        """从单个 finding 中提取 tool_name。

        提取优先级：finding_id → evidence_ref → message → "(unknown)"。
        """
        finding_id = getattr(f, "finding_id", "") or ""
        evidence_ref = getattr(f, "evidence_ref", "") or ""
        message = getattr(f, "message", "") or ""

        # 策略 1：finding_id 格式 "rule_type::tool_name"
        # 例如 "tool_response.output.low_signal::search_documents"
        if "::" in finding_id:
            parts = finding_id.split("::", 1)
            if len(parts) == 2 and parts[1].strip():
                return parts[1].strip()

        # 策略 2：evidence_ref 中匹配 call_id→tool_name 映射
        # evidence_ref 可能包含 tool_name 信息
        # 例如 "tool_calls.jsonl::call_id=search_documents_001"
        import re
        if evidence_ref:
            # 尝试匹配 tool_name 模式（字母/下划线/连字符组成）
            # 优先匹配 call_id= 后面的部分
            m = re.search(r"call_id=([a-zA-Z_][a-zA-Z0-9_-]*)", evidence_ref)
            if m:
                tool_id = m.group(1)
                # 如果 call_id 包含工具名模式，尝试提取
                # 例如 search_documents_001 → search_documents
                # 去掉尾部数字后缀
                base = re.sub(r"_\d+$", "", tool_id)
                if base:
                    return base

        # 策略 3：message 中匹配
        # message 格式可能如 "工具 'search_documents' 的 ..."
        if message:
            m = re.search(r"'([a-zA-Z_][a-zA-Z0-9_-]*)'", message)
            if m:
                return m.group(1)
            # 反引号包裹的工具名
            m = re.search(r"`([a-zA-Z_][a-zA-Z0-9_-]*)`", message)
            if m:
                return m.group(1)

        return "(unknown)"


# ======================================================================
# 辅助函数：从 MetricsCollector 提升为模块级，供 FindingGrouper 复用
# ======================================================================

# _extract_tool_name 别名，保持 MetricsCollector._extract_tool_name 可用
_extract_tool_name_from_finding = MetricsCollector._extract_tool_name

# severity 排序权重（越小优先级越高）
_SEVERITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
    "info": 4,
}


def _sort_by_severity(findings: list) -> list:
    """按 severity 降序排列 findings（critical 排最前）。"""
    return sorted(findings, key=lambda f: _SEVERITY_ORDER.get(f.severity, 99))


def _sort_groups_by_count(groups: dict[str, list]) -> dict[str, list]:
    """按 finding count 降序重排 group 顺序，同 count 按 key 字母序。"""
    return dict(
        sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    )


# ---------------------------------------------------------------------------
# P2: FindingGrouper
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GroupedFindings:
    """4 种 finding 分组视图。

    设计原则（不变式）：
    - 每个视图内 finding 的 multiset 等于原始 findings 的 multiset
    - 同一 group 内无重复 finding_id（通过 ID 集合 vs 列表长度验证）
    - group 内按 severity 降序排列（critical → high → medium → low → info）
    - group 级别按 finding count 降序排列

    为什么需要 4 种视图：
    reviewer 在不同场景下需要从不同维度看同一份 findings——
    按 severity 看优先级、按 category 看问题分布、按 tool 看工具质量、
    按 rule_id_prefix 看规则命中情况。单视图无法同时满足这些需求。
    """

    by_severity: dict[str, list] = field(default_factory=dict)
    """按 Finding.severity 分组。key: "critical"|"high"|"medium"|"low"|"info"。
    unknown severity → "(unknown)"。"""

    by_category: dict[str, list] = field(default_factory=dict)
    """按问题类别分组。
    RuleFinding: 按 rule_type 的 top-level prefix 分
    （tool_call, tool_result, tool_pair, tool_response, tool_spec, tool_ergonomics）。
    JudgeFinding: category="judge"。
    audit / signal: 防御性分桶，使用 category 字段原值。
    未知 category → "(unknown)"。"""

    by_tool: dict[str, list] = field(default_factory=dict)
    """按 tool_name 分组。工具名从 finding_id / evidence_ref / message 中
    best-effort 提取。无法提取时归入 "(unknown)"。
    为什么允许 "(unknown)" fallback：rule_type 不编码具体 tool_name，
    且当前 Finding 数据结构没有 tool_name 字段，提取是 best-effort 的。"""

    by_rule_id_prefix: dict[str, list] = field(default_factory=dict)
    """按 rule_type 的 top-level prefix 分组（如 tool_call, tool_result,
    tool_pair, tool_response, tool_spec, tool_ergonomics）。
    用于查看各规则类别的命中频率。无 rule_type 的 finding → "(unknown)"。"""


class FindingGrouper:
    """从 findings 列表生成 4 种分组视图。

    设计约束：
    - 不修改原始 findings
    - 不调 LLM，不访问文件系统
    - 所有分组为 deterministic

    用法::

        grouper = FindingGrouper()
        groups = grouper.group(eval_result.findings)
        for severity, items in groups.by_severity.items():
            print(f"{severity}: {len(items)} findings")
    """

    def group(self, findings: list) -> GroupedFindings:
        """从 findings 生成 4 种分组视图。

        Args:
            findings: EvaluationResult.findings 列表。

        Returns:
            GroupedFindings：4 个分组 dict。
        """
        by_severity = self._group_by_severity(findings)
        by_category = self._group_by_category(findings)
        by_tool = self._group_by_tool(findings)
        by_rule_id_prefix = self._group_by_rule_id_prefix(findings)

        return GroupedFindings(
            by_severity=by_severity,
            by_category=by_category,
            by_tool=by_tool,
            by_rule_id_prefix=by_rule_id_prefix,
        )

    # ------------------------------------------------------------------
    # by_severity
    # ------------------------------------------------------------------

    @staticmethod
    def _group_by_severity(findings: list) -> dict[str, list]:
        """按 Finding.severity 分组。

        unknown severity → "(unknown)"。
        """
        groups: dict[str, list] = {}
        for f in findings:
            sev = f.severity or "(unknown)"
            if sev not in _SEVERITY_ORDER:
                sev = "(unknown)"
            groups.setdefault(sev, []).append(f)

        # 每组内按 severity 降序排列
        for key in groups:
            groups[key] = _sort_by_severity(groups[key])

        return _sort_groups_by_count(groups)

    # ------------------------------------------------------------------
    # by_category
    # ------------------------------------------------------------------

    @staticmethod
    def _group_by_category(findings: list) -> dict[str, list]:
        """按问题类别分组。

        RuleFinding（category=="rule"）：按 rule_type 的 top-level prefix
        分子类别（tool_call, tool_result, tool_pair, tool_response,
        tool_spec, tool_ergonomics）。无法获取 rule_type 时归入 "rule"。

        JudgeFinding（category=="judge"）：归入 "judge"。

        audit / signal：防御性分桶，归入对应 cat。

        未知 category → "(unknown)"。
        """
        groups: dict[str, list] = {}
        for f in findings:
            cat = f.category
            if cat == "rule":
                rule_type = getattr(f, "rule_type", "") or ""
                if rule_type and "." in rule_type:
                    prefix = rule_type.split(".")[0]
                elif rule_type:
                    prefix = rule_type
                else:
                    prefix = "rule"
                groups.setdefault(prefix, []).append(f)
            elif cat in ("judge", "audit", "signal"):
                groups.setdefault(cat, []).append(f)
            elif cat:
                # 非标准 category → "(unknown)" 兜底
                groups.setdefault("(unknown)", []).append(f)
            else:
                groups.setdefault("(unknown)", []).append(f)

        for key in groups:
            groups[key] = _sort_by_severity(groups[key])

        return _sort_groups_by_count(groups)

    # ------------------------------------------------------------------
    # by_tool
    # ------------------------------------------------------------------

    @staticmethod
    def _group_by_tool(findings: list) -> dict[str, list]:
        """按 tool_name 分组（best-effort 提取）。

        提取优先级：finding_id（primary）→ evidence_ref → message → "(unknown)"。
        为什么允许 "(unknown)"：rule_type 不编码具体 tool_name，
        Finding 结构无 tool_name 字段。
        """
        groups: dict[str, list] = {}
        for f in findings:
            tool_name = _extract_tool_name_from_finding(f)
            groups.setdefault(tool_name, []).append(f)

        for key in groups:
            groups[key] = _sort_by_severity(groups[key])

        # "(unknown)" 排最后，其他按 count 降序
        unknown_items = groups.pop("(unknown)", [])
        result = _sort_groups_by_count(groups)
        if unknown_items:
            result["(unknown)"] = _sort_by_severity(unknown_items)
        return result

    # ------------------------------------------------------------------
    # by_rule_id_prefix
    # ------------------------------------------------------------------

    @staticmethod
    def _group_by_rule_id_prefix(findings: list) -> dict[str, list]:
        """按 rule_type 的 top-level prefix 分组。

        例如 rule_type="tool_call.arguments.present" → prefix="tool_call"。
        无 rule_type 的 finding（如 JudgeFinding）→ "(unknown)"。
        """
        groups: dict[str, list] = {}
        for f in findings:
            rule_type = getattr(f, "rule_type", "") or ""
            if rule_type:
                prefix = rule_type.split(".")[0] if "." in rule_type else rule_type
            else:
                prefix = "(unknown)"
            groups.setdefault(prefix, []).append(f)

        for key in groups:
            groups[key] = _sort_by_severity(groups[key])

        # "(unknown)" 排最后
        unknown_items = groups.pop("(unknown)", [])
        result = _sort_groups_by_count(groups)
        if unknown_items:
            result["(unknown)"] = _sort_by_severity(unknown_items)
        return result


# ---------------------------------------------------------------------------
# P4: RecommendationCatalog
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Recommendation:
    """一条确定性修复建议。

    设计原则：
    - 不是 LLM 生成的——所有内容来自确定性映射表
    - 不自动修改工具 spec——建议仅供人工 review 参考
    - 不改变 EvaluationResult.passed——建议是旁路信息
    - 每条建议指向具体 rule_id 和修复方向

    字段说明：
    - what: 问题是什么（中文，面向工具开发者）
    - why: 为什么重要（引用 Anthropic 工具设计原则）
    - how_to_fix: 具体修复方向（可操作、不模糊）
    - affected_count: 受此 rule_id 影响的 finding 数（去重后）
    """

    rule_id: str
    """对应的 rule_type/rule_id。"""

    category: str
    """rule_type 的 top-level prefix。"""

    severity: str
    """从 finding 继承的最高 severity。"""

    what: str
    """问题描述。"""

    why: str
    """为什么重要。"""

    how_to_fix: str
    """具体修复方向。"""

    affected_count: int = 1
    """受影响 finding 数（去重后）。"""


# ---------------------------------------------------------------------------
# 31 条确定性 rule_id → recommendation 映射表
# ---------------------------------------------------------------------------

# 所有 recommendation text 均为固定中文文本，不调 LLM、不拼真实 URL。
# 格式: (what, why, how_to_fix)
_RECOMMENDATION_CATALOG: dict[str, tuple[str, str, str]] = {
    # ---- D2: tool_inspection (9 rules) ----
    "tool_call.call_id.duplicate": (
        "工具调用 ID 重复：同一 call_id 被多次使用，破坏了 call_id 的唯一性约束。",
        "call_id 是串联 ToolCall ↔ ToolResult 的关键字段，重复会导致配对混乱、"
        "无法区分不同调用。",
        "检查 Agent runner 中 call_id 的生成逻辑，确保每次 tool_call 使用唯一 ID"
        "（如 UUID v4 或递增序列号）。",
    ),
    "tool_result.call_id.duplicate": (
        "工具返回 ID 重复：同一 call_id 有多个 tool_result，破坏了 call_id 的唯一性约束。",
        "每个 tool_call 最多对应一个 tool_result，重复 result 会污染评测数据。",
        "检查 Agent runner 中 tool_result 的写入逻辑，确保每次 call_id 只写入一次 result。",
    ),
    "tool_pair.orphan_call": (
        "存在孤立 tool_call：Agent 调用了工具但没有收到 tool_result。",
        "缺少 tool_result 意味着工具调用的结果未被记录，评测无法判断调用是否成功。",
        "检查 Agent runner 的工具执行链路，确保每次 tool_call 都返回 tool_result（包括 error）。",
    ),
    "tool_pair.orphan_result": (
        "存在孤立 tool_result：tool_result 存在但无对应的 tool_call。",
        "无对应 call 的 result 无法追溯到具体调用上下文，可能表明 trace 记录不完整。",
        "检查 trace 记录流程，确保 tool_result 只在 tool_call 之后写入，"
        "并核对 call_id 匹配的完整性。",
    ),
    "tool_call.arguments.present": (
        "tool_call 缺少 arguments：Agent 调用了工具但未传参数。",
        "工具调用无参数可能意味着 Agent 不理解工具的输入要求，或 prompt 未引导正确填充参数。",
        "检查 Agent prompt 是否包含参数填充指引；确认工具描述中明确说明了必需参数。",
    ),
    "tool_call.arguments.is_object": (
        "工具参数格式不正确：arguments 应为 JSON object（dict），但传入了其他类型。",
        "非 object 参数会导致工具无法正确解析输入，造成调用失败。",
        "检查 Agent 的工具调用格式化逻辑，确保 arguments 始终序列化为 JSON object。",
    ),
    "tool_call.tool_name.non_empty": (
        "工具名为空：tool_call 的 tool_name 字段为空字符串。",
        "空的 tool_name 无法标识调用的是哪个工具，trace 无法被正确分析。",
        "检查 Agent runner 的 tool_call 构造逻辑，确保 tool_name 永远为非空字符串。",
    ),
    "tool_result.tool_name.non_empty": (
        "工具返回中 tool_name 为空：tool_result 的 tool_name 字段为空字符串。",
        "空的 tool_name 使得 tool_result 无法关联到具体工具，影响后续分析。",
        "检查 tool_result 构造逻辑，确保从 tool_call 继承 tool_name 时正确赋值。",
    ),
    "tool_result.status.valid": (
        "工具返回状态无效：status 字段不是 \"success\" 或 \"error\"。",
        "非标准 status 值会导致 success/error 统计失真，影响错误率等核心指标。",
        "检查 Agent runner 中 status 字段的设置逻辑，确保只使用 \"success\" 或 \"error\"。",
    ),

    # ---- D6: tool_spec_inspection (10 rules) ----
    "tool_spec.description.exists": (
        "工具缺少描述：ToolSpec 的 description 字段为空或缺失。",
        "Agent 依赖工具描述来决定何时调用此工具，无描述会导致 Agent 无法正确选择工具。",
        "为工具添加 1-2 句清晰的描述，说明工具做什么、何时使用、输入输出是什么。",
    ),
    "tool_spec.description.useful_length": (
        "工具描述过短（<20 字符）：Agent 无法从过短描述中充分理解工具用途。",
        "Anthropic 工具设计指南建议描述应足够详细，让 Agent 能判断工具适用场景和边界。",
        "将 description 扩展为 1-2 句话，说明工具做什么、何时使用、输入输出格式。",
    ),
    "tool_spec.input_schema.exists": (
        "工具缺少输入 schema：ToolSpec 的 input_schema 字段为空或缺失。",
        "Agent 需要 input_schema 来理解工具接受的参数格式和类型，无 schema 会导致参数传递错误。",
        "为工具添加 JSON Schema 格式的 input_schema，至少包含必需的参数定义。",
    ),
    "tool_spec.parameter.name.explicit": (
        "参数名不明确：input_schema 中部分参数名称不能清晰表达其含义。",
        "参数名是 Agent 理解参数用途的第一线索，模糊的参数名会导致 Agent 填充错误值。",
        "重命名参数，使用自描述的名称（如 file_path 而非 fp）、添加 description 字段说明每个参数。",
    ),
    "tool_spec.required_parameter.documented": (
        "必需参数未文档化：input_schema 中 required 字段与实际定义的参数不一致。",
        "required 列表让 Agent 知道哪些参数必须填，缺失会导致 Agent 漏填关键参数。",
        "在 input_schema 中设置 required 数组，列出所有必需参数名。",
    ),
    "tool_spec.output_contract.documented": (
        "输出契约未文档化：ToolSpec 未定义 output_contract。",
        "Agent 需要知道工具返回什么格式的数据才能正确解析和推理，"
        "无输出契约会导致 Agent 忽略关键信息。",
        "为工具定义 output_contract，包含 output 的字段名、类型、含义描述。",
    ),
    "tool_spec.side_effects.documented": (
        "副作用未文档化：ToolSpec 未说明工具的副作用（如写入文件、发送请求等）。",
        "Agent 需要了解工具的副作用才能安全地编排调用顺序，避免不可逆操作。",
        "在工具描述中增加 side_effects 字段，说明工具是否只读、是否会修改外部状态。",
    ),
    "tool_spec.when_to_use.documented": (
        "使用场景未文档化：ToolSpec 未说明何时应使用此工具。",
        "Agent 需要 when_to_use 指导才能在不熟悉工具集时做出正确的工具选择。",
        "在工具描述中增加 when_to_use 指导，说明工具的典型使用场景和前置条件。",
    ),
    "tool_spec.when_not_to_use.documented": (
        "不使用场景未文档化：ToolSpec 未说明何时不应使用此工具。",
        "明确的边界声明帮助 Agent 避免在不适合的场景下使用此工具，减少错误调用。",
        "在工具描述中增加 when_not_to_use 声明，说明工具的适用边界和替代方案。",
    ),
    "tool_spec.token_policy.defined": (
        "token 策略未定义：ToolSpec 未声明工具的 token 消耗策略。",
        "token policy 帮助 Agent 判断调用此工具的成本，影响工具选择决策。",
        "在工具描述中增加 token_policy 说明，标注工具输出的大致 token 消耗范围。",
    ),

    # ---- D4: tool_ergonomics (6 rules) ----
    "tool_ergonomics.name.too_generic": (
        "工具名过于通用：工具名称过于泛化（如 search、get、list），Agent 容易混淆。",
        "Anthropic 工具设计原则建议工具名应体现具体能力边界，避免与其他工具名称重叠。",
        "为工具名增加领域前缀（如 search_documents 而非 search、list_users 而非 list），"
        "体现工具的具体能力范围。",
    ),
    "tool_ergonomics.name.namespace_present": (
        "工具名缺少命名空间：工具名中没有明确的功能域前缀。",
        "命名空间前缀帮助 Agent 区分不同功能域的工具，减少工具选择歧义。",
        "为工具名增加命名空间前缀（如 file_read、db_query），让 Agent 一眼识别工具所属功能域。",
    ),
    "tool_ergonomics.names.overlap": (
        "工具名称重叠：多个工具的名称高度相似，Agent 难以区分。",
        "名称重叠会导致 Agent 在相似工具之间犹豫或选错工具，降低工具调用准确率。",
        "重命名重叠工具，使用更具区分度的名称；或在工具描述中明确说明各工具的区别和适用场景。",
    ),
    "tool_ergonomics.too_many_similar_tools": (
        "相似工具过多：工具集中存在大量功能重叠的工具，增加 Agent 选择负担。",
        "过多相似工具会稀释 Agent 的注意力，降低工具选择准确率和效率。",
        "合并功能重叠的工具，或通过参数化减少工具数量；保留 1-2 个最通用的版本。",
    ),
    "tool_ergonomics.description.shallow_wrapper": (
        "工具描述为浅封装：工具描述仅复述了底层 API 的函数签名，未解释其业务语义。",
        "Anthropic 工具设计原则要求工具描述应面向 Agent 的理解需求，而非面向实现细节。"
        "浅封装描述无法帮助 Agent 理解何时使用。",
        "重写工具描述，从 Agent 视角说明做什么、何时用、输入输出含义，"
        "而非仅复述底层 API 的函数名和参数列表。",
    ),
    "tool_ergonomics.action_resource_clarity": (
        "动作/资源不清晰：工具名或描述中动作（verb）和资源（noun）的界定模糊。",
        "Anthropic 建议工具名采用 verb_noun 或 resource_action 格式，"
        "让 Agent 快速识别工具做什么、操作什么对象。",
        "重命名工具以清晰表达动作和资源（如 file_delete 而非 remove、"
        "user_search 而非 find），确保 verb 和 noun 各一个且不模糊。",
    ),

    # ---- D5: tool_response_quality (6 rules) ----
    "tool_response.success.output_present": (
        "成功响应缺少输出：status==\"success\" 但 output 为空或缺失。",
        "即使工具执行成功，Agent 也需要从 output 中获取信息才能继续推理。"
        "空 output 让 Agent 无法确认操作结果。",
        "确保成功响应时 output 至少包含关键结果字段（如 id、status、summary），"
        "即使是确认性操作也应返回确认信息。",
    ),
    "tool_response.failure.error_present": (
        "失败响应缺少错误信息：status==\"error\" 但 error 字段为空。",
        "Agent 需要从错误信息中了解失败原因才能决定如何修正或重试。"
        "空的 error 让 Agent 盲猜失败原因。",
        "确保错误响应时 error 字段包含可操作的错误描述（如\"文件不存在：/path/to/file\"），"
        "而非仅\"error\"。",
    ),
    "tool_response.output.size_reasonable": (
        "输出大小不合理：工具输出过大（>100KB）或过小（<10 字符）。",
        "过大的输出浪费 token 和上下文窗口，过小的输出可能缺少必要信息。",
        "为工具输出设置合理的大小边界；对大结果集支持分页；对单条结果确保包含必要字段。",
    ),
    "tool_response.output.low_signal": (
        "工具输出信号过低：返回内容以 IDs/状态码为主，缺少有意义的上下文。",
        "Anthropic 工具设计指南强调工具输出应\"帮助 Agent 做下一步推理\"。"
        "低信号输出迫使 Agent 做额外的 follow-up 调用。",
        "为 output 增加 context_fields（如名称、描述、状态），"
        "确保返回内容包含有意义的上下文而非仅 IDs。",
    ),
    "tool_response.error.actionable": (
        "工具错误消息不可操作：当前 error 内容无法指导 Agent 或开发者定位问题。",
        "Anthropic 工具设计原则要求错误消息应\"可操作\"——告诉 Agent 为什么失败、"
        "如何修正。不可操作的错误导致 Agent 反复重试相同操作。",
        "在 error 中增加 suggested_action 字段，含期望输入格式或修复提示；"
        "错误消息格式化为\"失败原因 + 修复建议\"。",
    ),
    "tool_response.output.context_fields_present": (
        "输出缺少上下文字段：工具返回了数据但缺少帮助 Agent 理解数据含义的上下文字段。",
        "Anthropic 建议工具输出应包含 context_fields，让 Agent 不依赖工具描述就能"
        "理解返回值的含义。",
        "在 output 中增加 context_fields（如 name、description、status），"
        "让返回数据自描述。",
    ),
}

# Fallback recommendation 文本，按 severity 分级
_FALLBACK_RECOMMENDATIONS: dict[str, tuple[str, str, str]] = {
    "critical": (
        "发现严重问题但暂无针对该 rule_id 的具体建议。",
        "严重问题可能影响工具可用性或评测准确性。",
        "定位 evidence_ref 指向的原始数据，确认是否为数据错误或 inspector 规则过严。",
    ),
    "high": (
        "发现高优先级问题但暂无针对该 rule_id 的具体建议。",
        "高优先级问题可能影响 Agent 工具使用的正确性。",
        "定位 evidence_ref 指向的原始数据，评估是否需要修复或调整 inspector 规则。",
    ),
    "medium": (
        "发现中优先级问题但暂无针对该 rule_id 的具体建议。",
        "中优先级问题通常属于改进项，不影响基本功能。",
        "评估是否需要修复，或标记为已知限制。",
    ),
    "low": (
        "发现低优先级问题但暂无针对该 rule_id 的具体建议。",
        "低优先级问题通常属于风格或最佳实践建议。",
        "评估是否值得修复，在资源允许时改进。",
    ),
    "info": (
        "仅供参考的发现，暂无针对该 rule_id 的具体建议。",
        "info 级别发现不构成问题，仅为信息提示。",
        "仅供参考，不需要立即行动。",
    ),
}


class RecommendationCatalog:
    """确定性建议映射表。

    设计原则：
    - 所有建议文本为硬编码中文文本——不调 LLM、不联网
    - 同一份 findings 每次产生相同建议（deterministic）
    - 未匹配到 rule_id 的 finding 走 severity fallback
    - 建议是旁路信息，不改变 pass/fail、不自动修复

    为什么是确定性的：CI 中可离线生成、输出稳定可 diff、无幻觉风险。

    用法::

        catalog = RecommendationCatalog()
        recs = catalog.recommend_all(eval_result.findings)
        for rec in recs:
            print(f"[{rec.severity}] {rec.what} → {rec.how_to_fix}")
    """

    def recommend(self, finding) -> Recommendation:
        """为单条 finding 生成 recommendation。

        Args:
            finding: RuleFinding 或 JudgeFinding 实例。

        Returns:
            Recommendation：确定性修复建议。
        """
        rule_type = getattr(finding, "rule_type", "") or ""
        severity = finding.severity or "info"
        category = finding.category

        # 从 rule_type 提取 category prefix
        if rule_type and "." in rule_type:
            cat_prefix = rule_type.split(".")[0]
        elif rule_type:
            cat_prefix = rule_type
        else:
            cat_prefix = category

        # 查找已知 rule_id 的精确建议
        if rule_type in _RECOMMENDATION_CATALOG:
            what, why, how_to_fix = _RECOMMENDATION_CATALOG[rule_type]
            return Recommendation(
                rule_id=rule_type,
                category=cat_prefix,
                severity=severity,
                what=what,
                why=why,
                how_to_fix=how_to_fix,
                affected_count=1,
            )

        # JudgeFinding：如无法匹配则给出 advisory fallback
        if category == "judge":
            return Recommendation(
                rule_id=rule_type or "judge",
                category="judge",
                severity=severity,
                what="LLM judge 发现了一个 advisory 级别的问题。",
                why="LLM judge 的判定为辅助参考，不等同于确定性规则发现。",
                how_to_fix="查看 judge finding 的 rationale 和 confidence，"
                "结合原始 evidence 判断是否需要人工介入。",
                affected_count=1,
            )

        # Fallback：按 severity 给通用建议
        fallback_severity = severity if severity in _FALLBACK_RECOMMENDATIONS else "info"
        what, why, how_to_fix = _FALLBACK_RECOMMENDATIONS[fallback_severity]
        return Recommendation(
            rule_id=rule_type or "(unknown)",
            category=cat_prefix,
            severity=severity,
            what=what,
            why=why,
            how_to_fix=how_to_fix,
            affected_count=1,
        )

    def recommend_all(self, findings: list) -> list[Recommendation]:
        """批量生成 recommendations（含去重）。

        去重策略：同一 rule_id 前缀只输出一条 recommendation，
        affected_count 反映受影响的 finding 数。

        Args:
            findings: EvaluationResult.findings 列表。

        Returns:
            去重后的 Recommendation 列表，按 severity 降序排列。
        """
        # 收集每条 finding 的 recommendation
        recs_by_rule: dict[str, Recommendation] = {}
        for f in findings:
            rule_type = getattr(f, "rule_type", "") or ""
            rec = self.recommend(f)

            # 去重：同一 rule_id 合并 affected_count
            if rule_type and rule_type in recs_by_rule:
                existing = recs_by_rule[rule_type]
                # 保留更严重的 severity
                merged_severity = (
                    rec.severity
                    if _SEVERITY_ORDER.get(rec.severity, 99)
                    < _SEVERITY_ORDER.get(existing.severity, 99)
                    else existing.severity
                )
                recs_by_rule[rule_type] = Recommendation(
                    rule_id=existing.rule_id,
                    category=existing.category,
                    severity=merged_severity,
                    what=existing.what,
                    why=existing.why,
                    how_to_fix=existing.how_to_fix,
                    affected_count=existing.affected_count + 1,
                )
            elif rule_type:
                recs_by_rule[rule_type] = rec
            else:
                # 无 rule_type（如 judge finding），用 finding_id 去重
                fid = getattr(f, "finding_id", "") or str(id(f))
                if fid not in recs_by_rule:
                    recs_by_rule[fid] = rec
                else:
                    existing = recs_by_rule[fid]
                    recs_by_rule[fid] = Recommendation(
                        rule_id=existing.rule_id,
                        category=existing.category,
                        severity=existing.severity,
                        what=existing.what,
                        why=existing.why,
                        how_to_fix=existing.how_to_fix,
                        affected_count=existing.affected_count + 1,
                    )

        # 按 severity 降序排列
        return sorted(
            recs_by_rule.values(),
            key=lambda r: _SEVERITY_ORDER.get(r.severity, 99),
        )


# ---------------------------------------------------------------------------
# P3: ReportScorecard
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ReportScorecard:
    """报告「一页纸」结论。

    设计原则：
    - 纯数据对象（value object），不包含复杂 factory method
    - 构造逻辑放在独立 builder 函数 make_scorecard() 中
    - Scorecard 只帮助人快速理解报告，不改变 pass/fail
    - 所有字段从 P1 ReportMetrics + P2 GroupedFindings 派生

    为什么 make_scorecard 是独立函数而非 dataclass method：
    - Scorecard 是聚合视图，不依赖自身状态
    - 独立函数可以独立测试、独立替换
    - 避免让 dataclass 耦合构造逻辑
    """

    passed: bool
    """评测是否通过。直接从 EvaluationResult.passed 透传。"""

    total_findings: int
    """finding 总数。"""

    errors: int
    """error 级 finding 数。severity=="critical" + severity=="high"。"""

    warnings: int
    """warning 级 finding 数。severity=="medium" + severity=="low"。"""

    info: int
    """info 级 finding 数。severity=="info"。"""

    advisory_count: int
    """LLM judge 产生的 advisory finding 数。"""

    tools_called: int
    """本次 trace 调用的不重复工具数。从 metrics.unique_tool_count 取值。"""

    tool_errors: int
    """工具调用返回 error 的次数。从 metrics.tool_error_count 取值。"""

    top_issue_categories: list[str] = field(default_factory=list)
    """问题最多的前 5 个类别（按 finding count 降序）。从 groups.by_category 派生。
    tie 时按类别名字母序稳定排列。"""

    top_affected_tools: list[str] = field(default_factory=list)
    """问题最多的前 5 个工具（按 finding count 降序）。从 metrics.finding_count_by_tool
    派生，排除 "(unknown)"。tie 时按工具名字母序稳定排列。"""


def make_scorecard(
    metrics: ReportMetrics,
    groups: GroupedFindings,
    passed: bool,
) -> ReportScorecard:
    """从 metrics + groups 构建 ReportScorecard。

    这是独立 builder 函数（非 dataclass method），原因是：
    - Scorecard 是聚合视图，不依赖自身状态
    - 独立函数可以独立测试、独立替换
    - 避免让纯数据对象耦合构造逻辑

    计算规则：
    - errors = critical + high
    - warnings = medium + low
    - info = info
    - top_issue_categories: groups.by_category 的 keys 按 count 降序取前 5
    - top_affected_tools: finding_count_by_tool 的 keys（排除了 "(unknown)"）按 count 降序取前 5

    Args:
        metrics: P1 ReportMetrics，提供 finding 分桶计数和工具统计。
        groups: P2 GroupedFindings，提供 by_category 分组视图。
        passed: bool from EvaluationResult.passed。

    Returns:
        ReportScorecard：「一页纸」评分结论。
    """
    sev = metrics.finding_count_by_severity

    total_findings = sum(sev.values())
    errors = sev.get("critical", 0) + sev.get("high", 0)
    warnings = sev.get("medium", 0) + sev.get("low", 0)
    info = sev.get("info", 0)

    # top_issue_categories: 前 5 个按 finding count 降序
    # 排序规则：先按 count 降序，tie 时按 category 名字母序（稳定排序）
    categories_by_count = sorted(
        groups.by_category.items(),
        key=lambda item: (-len(item[1]), item[0]),
    )
    top_issue_categories = [cat for cat, _ in categories_by_count[:5]]

    # top_affected_tools: 前 5 个按 count 降序，排除 "(unknown)"
    # 排序规则：先按 count 降序，tie 时按工具名字母序（稳定排序）
    tools_sorted = sorted(
        metrics.finding_count_by_tool.items(),
        key=lambda item: (-item[1], item[0]),
    )
    top_affected_tools = [
        tool for tool, _ in tools_sorted
        if tool != "(unknown)"
    ][:5]

    return ReportScorecard(
        passed=passed,
        total_findings=total_findings,
        errors=errors,
        warnings=warnings,
        info=info,
        advisory_count=metrics.judge_finding_count,
        tools_called=metrics.unique_tool_count,
        tool_errors=metrics.tool_error_count,
        top_issue_categories=top_issue_categories,
        top_affected_tools=top_affected_tools,
    )
