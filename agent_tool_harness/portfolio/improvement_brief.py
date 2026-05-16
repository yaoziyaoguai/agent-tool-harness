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


# ---------------------------------------------------------------------------
# 改进建议生成器
# ---------------------------------------------------------------------------


class ToolImprovementBriefGenerator:
    """从 v3.1-v3.5 累积信号生成 ToolImprovementBrief。

    设计约束：
    - 只生成人类可读建议，不自动修改 ToolSpec
    - 优先级和类别基于 evidence 中的信号强度确定
    - 所有逻辑 deterministic，不调 LLM

    用法::

        generator = ToolImprovementBriefGenerator()
        brief = generator.generate_per_tool(
            tool_name="search",
            findings=findings,
            metrics=metrics,
            task_outcomes=task_outcomes,
            transcript_signals=transcript_signals,
        )
    """

    # 严重度 → 优先级映射
    _SEVERITY_PRIORITY: dict[str, str] = {
        "critical": "critical",
        "high": "high",
        "medium": "medium",
        "warning": "medium",
        "low": "low",
        "info": "low",
    }

    # finding category → brief category 映射
    _CATEGORY_MAP: dict[str, str] = {
        "tool_spec": "spec_quality",
        "tool_ergonomics": "ergonomics",
        "tool_response": "response",
        "tool_call": "ergonomics",
        "tool_pair": "ergonomics",
        "portfolio": "portfolio",
        "transcript": "ergonomics",
        "context": "response",
    }

    def __init__(self):
        self._collector = EvidenceCollector()

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def generate_per_tool(
        self,
        tool_name: str,
        findings: list | None = None,
        metrics: Any = None,
        task_outcomes: list | None = None,
        transcript_signals: list | None = None,
    ) -> ToolImprovementBrief | None:
        """为单个工具生成改进建议。

        Args:
            tool_name: 目标工具名
            findings: v3.1-v3.5 findings 列表
            metrics: v3.1 ReportMetrics
            task_outcomes: v3.2 TaskOutcome 列表
            transcript_signals: v3.5 transcript 信号

        Returns:
            ToolImprovementBrief，或 None（无足够证据时）
        """
        evidence = self._collector.collect_for_tool(
            tool_name,
            findings=findings,
            metrics=metrics,
            task_outcomes=task_outcomes,
            transcript_signals=transcript_signals,
        )

        if not self._has_actionable_evidence(evidence):
            return None

        priority = self._determine_priority(findings or [], evidence)
        category = self._determine_category(findings or [], evidence)
        current_state = self._describe_current_state(tool_name, findings or [], evidence)
        recommended_state = self._describe_recommended_state(
            tool_name, category, findings or [], evidence
        )
        rationale = self._build_rationale(findings or [], evidence)
        effort = self._estimate_effort(category, findings or [], evidence)

        return ToolImprovementBrief(
            tool_name=tool_name,
            priority=priority,
            category=category,
            evidence=evidence,
            current_state=current_state,
            recommended_state=recommended_state,
            rationale=rationale,
            effort_estimate=effort,
        )

    def generate_cross_tool(
        self,
        portfolio_findings: list | None = None,
        findings: list | None = None,
        metrics: Any = None,
    ) -> list[ToolImprovementBrief]:
        """从 PortfolioFinding 列表生成跨工具改进建议。

        Args:
            portfolio_findings: ToolPortfolioReview 产出的发现列表
            findings: v3.1-v3.5 findings
            metrics: v3.1 ReportMetrics

        Returns:
            ToolImprovementBrief 列表，每个 PortfolioFinding 对应一条建议
        """
        briefs: list[ToolImprovementBrief] = []
        pf_list = portfolio_findings or []

        for pf in pf_list:
            evidence = self._collector.collect_cross_tool(
                portfolio_findings=[pf],
                findings=findings,
                metrics=metrics,
            )
            briefs.append(ToolImprovementBrief(
                tool_name=", ".join(pf.affected_tools[:3]) if pf.affected_tools
                else "(cross-tool)",
                priority="medium" if pf.severity == "warning" else "low",
                category="portfolio",
                evidence=evidence,
                current_state=pf.description,
                recommended_state=pf.suggestion,
                rationale=f"工具组合检查 '{pf.check_name}' 发现结构性问题",
                effort_estimate="medium",
            ))

        return briefs

    # ------------------------------------------------------------------
    # 证据充分性判断
    # ------------------------------------------------------------------

    @staticmethod
    def _has_actionable_evidence(evidence: EvidenceRef) -> bool:
        """判断是否有足够证据生成建议。"""
        return bool(
            evidence.finding_ids
            or evidence.metric_values
            or evidence.task_outcome_ids
            or evidence.transcript_signal_types
        )

    # ------------------------------------------------------------------
    # 优先级确定
    # ------------------------------------------------------------------

    @classmethod
    def _determine_priority(
        cls, findings: list, evidence: EvidenceRef,
    ) -> str:
        """根据 finding 严重度分布确定优先级。

        规则：
        - 有 critical → critical
        - 有 high → high
        - tool_error_rate > 0.5 → high
        - 有 medium/warning → medium
        - 其他 → low
        """
        max_severity = "info"

        for f in findings:
            fid = getattr(f, "finding_id", "")
            if fid not in evidence.finding_ids:
                continue
            sev = getattr(f, "severity", "info")
            sev_order = ["info", "low", "warning", "medium", "high", "critical"]
            if sev_order.index(sev) > sev_order.index(max_severity):
                max_severity = sev

        # 指标驱动的优先级提升
        error_rate = evidence.metric_values.get("tool_error_rate", 0)
        if error_rate > 0.5 and max_severity not in ("critical", "high"):
            max_severity = "high"
        elif error_rate > 0.25 and max_severity not in ("critical", "high", "medium"):
            max_severity = "medium"

        return cls._SEVERITY_PRIORITY.get(max_severity, "low")

    # ------------------------------------------------------------------
    # 类别确定
    # ------------------------------------------------------------------

    @classmethod
    def _determine_category(
        cls, findings: list, evidence: EvidenceRef,
    ) -> str:
        """根据 finding 类别分布确定改进类别。

        规则：
        - 统计所有 referenced findings 的 category/rule_type 前缀
        - 取出现最多的类别
        - 默认 'ergonomics'
        """
        from collections import Counter

        cat_counts: Counter = Counter()

        for f in findings:
            fid = getattr(f, "finding_id", "")
            if fid not in evidence.finding_ids:
                continue
            cat = getattr(f, "category", "")
            rule_type = getattr(f, "rule_type", "")

            # 按 rule_type 前缀映射
            for prefix, brief_cat in cls._CATEGORY_MAP.items():
                if rule_type.startswith(prefix) or cat.startswith(prefix):
                    cat_counts[brief_cat] += 1
                    break
            else:
                cat_counts["ergonomics"] += 1

        if cat_counts:
            return cat_counts.most_common(1)[0][0]
        return "ergonomics"

    # ------------------------------------------------------------------
    # 状态描述生成
    # ------------------------------------------------------------------

    @staticmethod
    def _describe_current_state(
        tool_name: str, findings: list, evidence: EvidenceRef,
    ) -> str:
        """生成当前状态的自然语言描述。"""
        parts: list[str] = []

        # finding 驱动的描述
        finding_count = len(evidence.finding_ids)
        if finding_count > 0:
            parts.append(f"存在 {finding_count} 个相关发现")

        # 指标驱动的描述
        error_rate = evidence.metric_values.get("tool_error_rate", 0)
        if error_rate > 0.3:
            parts.append(f"错误率 {error_rate:.0%}")

        response_chars = evidence.metric_values.get("response_chars", 0)
        if response_chars > 5000:
            parts.append(f"响应大小 {response_chars:.0f} 字符，偏高")

        # transcript 信号驱动的描述
        signals = evidence.transcript_signal_types
        if "repeated_retry" in signals:
            parts.append("存在重复调用模式")
        if "arg_micro_tuning" in signals:
            parts.append("存在参数微调行为")
        if "response_bloat" in signals:
            parts.append("工具响应膨胀")

        if not parts:
            parts.append("未发现明显问题")

        return f"[{tool_name}] " + "；".join(parts)

    @staticmethod
    def _describe_recommended_state(
        tool_name: str, category: str, findings: list, evidence: EvidenceRef,
    ) -> str:
        """生成推荐状态的自然语言描述。"""
        suggestions: dict[str, str] = {
            "spec_quality": "完善工具描述、输入输出契约和参数文档",
            "ergonomics": "优化工具命名、减少参数冗余、明确使用场景",
            "response": "启用 concise 模式、添加分页、优化响应大小",
            "portfolio": "调整工具组合结构，合并或拆分相关工具",
        }

        base = suggestions.get(category, "根据证据审查并优化工具设计")

        # 根据具体信号细化
        signals = evidence.transcript_signal_types
        if "repeated_retry" in signals:
            base += "；消除重复调用模式"
        if "response_bloat" in signals:
            base += "；实施响应大小控制"

        metric_count = len(evidence.metric_values)
        if metric_count > 3:
            base += "；持续监控指标变化"

        return base

    # ------------------------------------------------------------------
    # 理由构建
    # ------------------------------------------------------------------

    @staticmethod
    def _build_rationale(
        findings: list, evidence: EvidenceRef,
    ) -> str:
        """构建改进理由说明。"""
        parts: list[str] = []

        finding_count = len(evidence.finding_ids)
        task_count = len(evidence.task_outcome_ids)
        signal_count = len(evidence.transcript_signal_types)

        if finding_count > 0:
            parts.append(f"{finding_count} 条相关发现")
        if task_count > 0:
            parts.append(f"{task_count} 个任务用例受影响")
        if signal_count > 0:
            parts.append(f"{signal_count} 种困惑/浪费信号")

        if not parts:
            return "缺乏明确证据，建议人工审查"

        return (
            "证据来源：v3.1-v3.5 累积信号（"
            + "，".join(parts)
            + "）。建议基于确定性模式匹配生成，需人工确认后执行。"
        )

    # ------------------------------------------------------------------
    # 工作量估计
    # ------------------------------------------------------------------

    @classmethod
    def _estimate_effort(
        cls, category: str, findings: list, evidence: EvidenceRef,
    ) -> str:
        """估算改进工作量。

        规则：
        - portfolio（结构调整）→ large
        - spec_quality + 多 finding → medium
        - response（参数调整）→ small/medium
        - ergonomics（命名等）→ small/medium
        """
        finding_count = len(evidence.finding_ids)

        if category == "portfolio":
            return "large"
        if finding_count >= 5:
            return "large"
        if finding_count >= 3:
            return "medium"
        if category == "spec_quality":
            return "medium"
        return "small"
