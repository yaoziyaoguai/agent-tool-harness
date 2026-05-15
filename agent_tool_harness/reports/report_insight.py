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
- ReportMetrics：16 个基础指标，从 trace + findings 计算
- MetricsCollector：纯计算函数，trace + eval_result → ReportMetrics
- （后续 Phase 追加）FindingGrouper、ReportScorecard、RecommendationCatalog、
  ReportInsight
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
