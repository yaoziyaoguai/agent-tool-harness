"""Tool Improvement Brief —— 含证据引用的结构化改进建议。

提供 EvidenceRef + ToolImprovementBrief 数据结构及证据收集逻辑。
所有分析 deterministic、零网络依赖、不自动修改 ToolSpec。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# 数据结构
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EvidenceRef:
    """多来源证据引用。

    架构边界：
    - **负责**：汇总来自 v3.1-v3.5 各层的证据指针，让每条建议都可追溯。
    - **不负责**：不存储证据内容本身（通过 finding_id / metric 名 / case_id 引用）。
    """

    finding_ids: list[str] = field(default_factory=list)
    """v3.1 findings 的 finding_id 列表。"""

    metric_values: dict[str, float] = field(default_factory=dict)
    """v3.1 metrics 中与该工具相关的指标名→值。如 {'tool_error_rate': 0.4}。"""

    task_outcome_ids: list[str] = field(default_factory=list)
    """v3.2 TaskOutcome 中与该工具相关的 case_id 列表。"""

    transcript_signal_types: list[str] = field(default_factory=list)
    """v3.5 transcript analysis 中与该工具相关的 signal 类型。
    如 ['repeated_retry', 'arg_micro_tuning']。"""


@dataclass(frozen=True)
class ToolImprovementBrief:
    """单工具改进建议卡片。

    架构边界：
    - **负责**：提供人类可读的改进建议，含可追溯证据。
    - **不负责**：不自动修改 tool spec、不替代人工判断。
    - 设计目标：给人（或 Claude Code）看的参考卡片，不是 machine-executable patch。
    """

    tool_name: str
    """目标工具名（qualified_name 或 name）。"""

    priority: str
    """建议优先级: critical | high | medium | low。"""

    category: str
    """改进类别: spec_quality | ergonomics | response | portfolio。"""

    evidence: EvidenceRef
    """多来源证据引用。"""

    current_state: str
    """当前状态的自然语言描述。"""

    recommended_state: str
    """推荐状态的自然语言描述。"""

    rationale: str
    """改进理由说明。"""

    effort_estimate: str
    """工作估计: small | medium | large。"""


# ---------------------------------------------------------------------------
# 证据收集器
# ---------------------------------------------------------------------------


class EvidenceCollector:
    """从 v3.1-v3.5 各层信号中为指定工具收集证据引用。

    设计约束：
    - 不修改输入
    - 不调 LLM
    - 不访问文件系统
    - 只产出 EvidenceRef（引用指针，不存证据内容）

    用法::

        collector = EvidenceCollector()
        evidence = collector.collect_for_tool(
            tool_name="search",
            findings=findings,
            metrics=metrics,
            task_outcomes=task_outcomes,
            transcript_signals=transcript_signals,
        )
    """

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def collect_for_tool(
        self,
        tool_name: str,
        findings: list | None = None,
        metrics: Any = None,
        task_outcomes: list | None = None,
        transcript_signals: list | None = None,
    ) -> EvidenceRef:
        """为指定工具聚合所有来源的证据引用。

        Args:
            tool_name: 目标工具名
            findings: v3.1 RuleFinding/JudgeFinding 列表
            metrics: v3.1 ReportMetrics 实例
            task_outcomes: v3.2 TaskOutcome 列表
            transcript_signals: v3.5 transcript analysis RuleFinding 列表

        Returns:
            EvidenceRef 包含所有来源的证据指针
        """
        return EvidenceRef(
            finding_ids=self._collect_finding_ids(tool_name, findings or []),
            metric_values=self._collect_metric_values(tool_name, metrics),
            task_outcome_ids=self._collect_task_outcome_ids(
                tool_name, task_outcomes or []
            ),
            transcript_signal_types=self._collect_transcript_signals(
                tool_name, transcript_signals or []
            ),
        )

    def collect_cross_tool(
        self,
        portfolio_findings: list | None = None,
        findings: list | None = None,
        metrics: Any = None,
    ) -> EvidenceRef:
        """为跨工具（portfolio 级别）建议收集证据。

        Args:
            portfolio_findings: ToolPortfolioReview 产出的 PortfolioFinding 列表
            findings: v3.1-v3.5 findings
            metrics: v3.1 ReportMetrics

        Returns:
            EvidenceRef 包含跨工具证据指针
        """
        pf = portfolio_findings or []
        return EvidenceRef(
            finding_ids=[
                f"portfolio:{pf_item.check_name}"
                for pf_item in pf
            ],
            metric_values=self._collect_cross_tool_metrics(metrics),
            task_outcome_ids=[],
            transcript_signal_types=[],
        )

    # ------------------------------------------------------------------
    # Finding ID 收集
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_finding_ids(
        tool_name: str, findings: list,
    ) -> list[str]:
        """从 findings 中筛选与 tool_name 相关的 finding_id。

        匹配策略（按优先级）：
        1. evidence_ref 中包含 tool_name
        2. message 中包含 tool_name
        3. finding_id 中包含 tool_name
        """
        matched: list[str] = []
        for f in findings:
            fid = getattr(f, "finding_id", "")
            ev_ref = getattr(f, "evidence_ref", "")
            msg = getattr(f, "message", "")

            if tool_name in ev_ref:
                matched.append(fid)
            elif tool_name in msg:
                matched.append(fid)
            elif tool_name in fid:
                matched.append(fid)

        return matched

    # ------------------------------------------------------------------
    # Metric 值收集
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_metric_values(
        tool_name: str, metrics: Any,
    ) -> dict[str, float]:
        """从 ReportMetrics 中提取与 tool_name 相关的指标值。

        提取以下指标：
        - tool_error_rate（全局）
        - finding_count_by_tool[tool_name]
        - response_size_chars_by_tool[tool_name]
        - orphan_call_count / orphan_result_count（全局）
        - repeated_tool_call_count（全局）
        """
        if metrics is None:
            return {}

        result: dict[str, float] = {}

        # 工具级指标（从 dict 字段中提取）
        for dict_field, metric_key in [
            ("finding_count_by_tool", "finding_count"),
            ("response_size_chars_by_tool", "response_chars"),
        ]:
            field_val = getattr(metrics, dict_field, {})
            if isinstance(field_val, dict) and tool_name in field_val:
                result[metric_key] = float(field_val[tool_name])

        # 全局指标
        for attr_name in [
            "tool_error_rate",
            "orphan_call_count",
            "orphan_result_count",
            "repeated_tool_call_count",
        ]:
            val = getattr(metrics, attr_name, None)
            if val is not None:
                result[attr_name] = float(val)

        return result

    # ------------------------------------------------------------------
    # Task Outcome 收集
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_task_outcome_ids(
        tool_name: str, task_outcomes: list,
    ) -> list[str]:
        """从 TaskOutcome 列表中筛选与 tool_name 相关的 case_id。

        匹配策略：
        1. outcome.details 中包含 tool_name
        2. verifier_results 的 details 中包含 tool_name
        """
        matched: list[str] = []
        for to in task_outcomes:
            case_id = getattr(to, "case_id", "")
            details = getattr(to, "details", "")
            vr_list = getattr(to, "verifier_results", [])

            if tool_name in details:
                matched.append(case_id)
                continue

            for vr in vr_list:
                vr_details = getattr(vr, "details", "")
                if tool_name in vr_details:
                    matched.append(case_id)
                    break

        return matched

    # ------------------------------------------------------------------
    # Transcript Signal 收集
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_transcript_signals(
        tool_name: str, transcript_signals: list,
    ) -> list[str]:
        """从 v3.5 transcript analysis findings 中提取 signal 类型。

        匹配策略：
        1. evidence_ref 中包含 tool_name
        2. message 中包含 tool_name
        提取 rule_type 作为 signal 类型。
        """
        signal_types: list[str] = []
        for f in transcript_signals:
            ev_ref = getattr(f, "evidence_ref", "")
            msg = getattr(f, "message", "")
            rule_type = getattr(f, "rule_type", "")

            if tool_name in ev_ref or tool_name in msg:
                if rule_type and rule_type not in signal_types:
                    signal_types.append(rule_type)

        return signal_types

    # ------------------------------------------------------------------
    # 跨工具 metric 收集
    # ------------------------------------------------------------------

    @staticmethod
    def _collect_cross_tool_metrics(metrics: Any) -> dict[str, float]:
        """收集跨工具级别的指标。"""
        if metrics is None:
            return {}

        result: dict[str, float] = {}
        for attr_name in [
            "tool_error_rate",
            "tool_call_count",
            "unique_tool_count",
            "orphan_call_count",
            "orphan_result_count",
            "repeated_tool_call_count",
            "judge_finding_count",
        ]:
            val = getattr(metrics, attr_name, None)
            if val is not None:
                result[attr_name] = float(val)

        return result
