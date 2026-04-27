from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from agent_tool_harness.config.tool_spec import ToolSpec


@dataclass
class AuditFinding:
    rule_id: str
    severity: str
    message: str
    suggestion: str


@dataclass
class ToolAuditResult:
    tool_name: str
    qualified_name: str
    category_scores: dict[str, int]
    findings: list[AuditFinding] = field(default_factory=list)

    @property
    def overall_score(self) -> float:
        if not self.category_scores:
            return 0.0
        return round(sum(self.category_scores.values()) / len(self.category_scores), 2)

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "qualified_name": self.qualified_name,
            "overall_score": self.overall_score,
            "category_scores": self.category_scores,
            "findings": [finding.__dict__ for finding in self.findings],
        }


class ToolDesignAuditor:
    """按 Agent 工具设计原则审计 tools.yaml。

    架构边界：
    - 负责检查工具“是否适合给 Agent 使用”，而不是检查 Python 函数能否运行。
    - 输出五类评分：right_tools、namespacing、meaningful_context、token_efficiency、prompt_spec。
    - 不执行工具、不读取用户运行时状态，也不修改工具实现。

    为什么这样拆：
    Agent 工具是确定性系统和非确定性 Agent 之间的契约。这个 auditor 先检查契约设计，
    后续 runner 才检查 Agent 在真实 transcript 中是否正确使用这些契约。

    扩展点：
    - 可以增加项目领域规则，例如 destructive 工具必须要求 evidence。
    - 可以接入 LLM reviewer，但当前 MVP 保持 deterministic rule audit。
    """

    CATEGORY_KEYS = [
        "right_tools",
        "namespacing",
        "meaningful_context",
        "token_efficiency",
        "prompt_spec",
    ]

    GENERIC_NAME_TOKENS = {"get", "list", "set", "update", "run", "call", "api", "query"}
    LOW_LEVEL_HINTS = {"api wrapper", "raw api", "endpoint", "crud", "database row", "直接封装"}

    def audit(self, tools: list[ToolSpec]) -> dict[str, Any]:
        name_counts = Counter(tool.name for tool in tools)
        namespace_counts = Counter(tool.namespace for tool in tools)
        results = [
            self.audit_tool(tool, tools, name_counts=name_counts, namespace_counts=namespace_counts)
            for tool in tools
        ]
        # 顶层 warnings 字段（P0 治理）：
        # 真实坑——之前空 tools 时 CLI 只在 stderr 打印 "(warning) tools file is
        # empty"，但 audit_tools.json 完全无 finding、average_score=0，CI/远程消费者
        # 看不到任何信号；用户接 pipeline 会以为"audit 通过"。这里把"零输入"作为
        # 显式 warning 写进 artifact，让派生数据真实反映"零输入"这一接入失败。
        warnings: list[str] = []
        if not tools:
            warnings.append(
                "empty_input: tools list is empty; nothing to audit. "
                "请确认 tools.yaml 已经声明了真实工具，否则后续 run/judge 都会无效。"
            )
        return {
            "summary": {
                "tool_count": len(tools),
                "average_score": self._average(result.overall_score for result in results),
                "low_score_tools": [
                    result.qualified_name for result in results if result.overall_score < 3.5
                ],
                "warnings": warnings,
            },
            "tools": [result.to_dict() for result in results],
        }

    def audit_tool(
        self,
        tool: ToolSpec,
        all_tools: list[ToolSpec] | None = None,
        *,
        name_counts: Counter[str] | None = None,
        namespace_counts: Counter[str] | None = None,
    ) -> ToolAuditResult:
        all_tools = all_tools or [tool]
        name_counts = name_counts or Counter(item.name for item in all_tools)
        namespace_counts = namespace_counts or Counter(item.namespace for item in all_tools)
        findings: list[AuditFinding] = []
        scores = {
            "right_tools": self._score_right_tool(tool, all_tools, findings),
            "namespacing": self._score_namespace(tool, name_counts, namespace_counts, findings),
            "meaningful_context": self._score_context(tool, findings),
            "token_efficiency": self._score_token_efficiency(tool, findings),
            "prompt_spec": self._score_prompt_spec(tool, findings),
        }
        return ToolAuditResult(
            tool_name=tool.name,
            qualified_name=tool.qualified_name,
            category_scores=scores,
            findings=findings,
        )

    def _score_right_tool(
        self, tool: ToolSpec, all_tools: list[ToolSpec], findings: list[AuditFinding]
    ) -> int:
        score = 5
        combined = f"{tool.description} {tool.when_to_use}".lower()
        if any(hint in combined for hint in self.LOW_LEVEL_HINTS):
            score -= 2
            findings.append(
                AuditFinding(
                    "right_tools.low_level_wrapper",
                    "high",
                    "工具描述像底层 API wrapper，而不是面向 Agent 的工作流工具。",
                    "把多个底层操作合并成一个高影响任务边界，并返回决策所需上下文。",
                )
            )
        if len(tool.description.split()) < 10 and len(tool.description) < 80:
            score -= 1
            findings.append(
                AuditFinding(
                    "right_tools.too_little_intent",
                    "medium",
                    "description 没有清楚说明真实工作流和任务价值。",
                    "用新同事能理解的语言说明该工具解决什么诊断/执行任务。",
                )
            )
        if not tool.when_to_use:
            score -= 1
            findings.append(
                AuditFinding(
                    "right_tools.missing_when_to_use",
                    "medium",
                    "缺少 when_to_use，Agent 难以判断何时调用。",
                    "补充触发场景、输入前提和典型用户问题。",
                )
            )
        if len(all_tools) > 12:
            score -= 1
            findings.append(
                AuditFinding(
                    "right_tools.too_many_tools",
                    "medium",
                    "工具数量偏多，可能增加 Agent 选择负担。",
                    "按 workflow 聚合高频链路，保留少量高信号工具。",
                )
            )
        overlap = self._overlap_count(tool, all_tools)
        if overlap:
            score -= 1
            findings.append(
                AuditFinding(
                    "right_tools.overlap",
                    "medium",
                    "存在名称或职责相近的工具，Agent 可能分心。",
                    "明确边界，或合并为一个支持 mode/filter 的工具。",
                )
            )
        return max(score, 1)

    def _score_namespace(
        self,
        tool: ToolSpec,
        name_counts: Counter[str],
        namespace_counts: Counter[str],
        findings: list[AuditFinding],
    ) -> int:
        score = 5
        if not tool.namespace:
            score -= 2
            findings.append(
                AuditFinding(
                    "namespacing.missing_namespace",
                    "high",
                    "缺少 namespace，工具来源和资源边界不清。",
                    "按 service/resource/workflow 设置 namespace，例如 runtime.trace。",
                )
            )
        if name_counts[tool.name] > 1:
            score -= 2
            findings.append(
                AuditFinding(
                    "namespacing.duplicate_name",
                    "high",
                    "工具名重复，Agent 和 recorder 难以稳定区分。",
                    "使用能表达任务边界的唯一工具名。",
                )
            )
        tokens = set(tool.name.lower().replace("-", "_").split("_"))
        if tokens & self.GENERIC_NAME_TOKENS and len(tokens) <= 2:
            score -= 1
            findings.append(
                AuditFinding(
                    "namespacing.generic_name",
                    "medium",
                    "工具名过于泛化，没有自然表达任务边界。",
                    "把资源和动作写进名称，例如 <domain>_<resource>_<action>。",
                )
            )
        if tool.namespace and namespace_counts[tool.namespace] == 1 and "." not in tool.namespace:
            score -= 0
        return max(score, 1)

    def _score_context(self, tool: ToolSpec, findings: list[AuditFinding]) -> int:
        score = 5
        contract = tool.output_contract
        required_fields = set(contract.get("required_fields", []))
        if not {"summary", "evidence"}.issubset(required_fields):
            score -= 2
            findings.append(
                AuditFinding(
                    "meaningful_context.missing_summary_evidence",
                    "high",
                    "output_contract 没有强制 summary/evidence，返回可能无法支撑判断。",
                    "要求工具返回简明 summary、证据列表和可追踪 technical ID。",
                )
            )
        if "next_action" not in required_fields and not contract.get("next_actions"):
            score -= 1
            findings.append(
                AuditFinding(
                    "meaningful_context.missing_next_action",
                    "medium",
                    "输出没有下一步建议，Agent 可能停在低层观察。",
                    "返回 next_action 或 next_actions，说明下一步应查什么。",
                )
            )
        if not contract.get("technical_ids") and "technical_id" not in required_fields:
            score -= 1
            findings.append(
                AuditFinding(
                    "meaningful_context.missing_technical_id",
                    "medium",
                    "输出没有稳定 technical ID，后续工具调用难以衔接。",
                    "同时提供人类可读 label 和后续调用需要的 ID。",
                )
            )
        if contract.get("raw_fields_allowed", True) is True:
            score -= 1
            findings.append(
                AuditFinding(
                    "meaningful_context.raw_fields_unbounded",
                    "low",
                    "未限制低层技术字段泛滥，可能浪费上下文。",
                    "只返回和诊断/决策相关的字段，把原始详情放到 detailed 模式。",
                )
            )
        return max(score, 1)

    def _score_token_efficiency(self, tool: ToolSpec, findings: list[AuditFinding]) -> int:
        score = 5
        policy = tool.token_policy
        checks = {
            "supports_pagination": "支持 pagination，避免一次返回过多事件。",
            "supports_filtering": "支持 filtering，让 Agent 缩小范围。",
            "supports_range_selection": "支持 range selection，适合 trace/log 工具。",
            "max_output_tokens": "设置 max_output_tokens，避免工具吞掉上下文窗口。",
            "default_limit": "设置合理 default_limit，避免默认返回过宽。",
        }
        for key, message in checks.items():
            if not policy.get(key):
                score -= 1
                findings.append(
                    AuditFinding(
                        f"token_efficiency.missing_{key}",
                        "medium",
                        message.replace("支持", "缺少").replace("设置", "缺少"),
                        message,
                    )
                )
        if not policy.get("truncation_guidance"):
            score -= 1
            findings.append(
                AuditFinding(
                    "token_efficiency.missing_truncation_guidance",
                    "medium",
                    "截断时没有告诉 Agent 如何缩小查询范围。",
                    "返回 truncation_guidance，例如建议 event_id/time_range/filter。",
                )
            )
        if not policy.get("actionable_errors", False):
            score -= 1
            findings.append(
                AuditFinding(
                    "token_efficiency.non_actionable_errors",
                    "medium",
                    "错误响应可能只是裸 traceback。",
                    "错误应包含 cause、retryable、suggested_fix 和可用参数提示。",
                )
            )
        return max(score, 1)

    def _score_prompt_spec(self, tool: ToolSpec, findings: list[AuditFinding]) -> int:
        score = 5
        if len(tool.description) < 80:
            score -= 1
            findings.append(
                AuditFinding(
                    "prompt_spec.short_description",
                    "medium",
                    "description 太短，不像在教新同事如何使用。",
                    "说明工具目的、输入语义、输出解释和典型误用。",
                )
            )
        if not tool.when_to_use or not tool.when_not_to_use:
            score -= 2
            findings.append(
                AuditFinding(
                    "prompt_spec.missing_usage_boundaries",
                    "high",
                    "缺少 when_to_use/when_not_to_use 边界。",
                    "同时写清适用场景和不适用场景，减少误调用。",
                )
            )
        if not tool.input_schema.get("properties"):
            score -= 1
            findings.append(
                AuditFinding(
                    "prompt_spec.weak_input_schema",
                    "high",
                    "input_schema 不严格，参数语义不稳定。",
                    "使用 JSON Schema properties/required 描述参数。",
                )
            )
        if not tool.output_contract:
            score -= 1
            findings.append(
                AuditFinding(
                    "prompt_spec.missing_output_contract",
                    "high",
                    "缺少 output_contract，Agent 无法预期返回结构。",
                    "声明 required_fields、evidence 格式、ID 字段和错误结构。",
                )
            )
        if "destructive" not in tool.side_effects and "open_world_access" not in tool.side_effects:
            score -= 1
            findings.append(
                AuditFinding(
                    "prompt_spec.missing_side_effect_labels",
                    "medium",
                    "side_effects 没有标注 destructive/open_world_access。",
                    "明确副作用等级，供 runner/judge 检查证据前禁止修改。",
                )
            )
        return max(score, 1)

    def _overlap_count(self, tool: ToolSpec, all_tools: list[ToolSpec]) -> int:
        tokens = set(tool.name.lower().replace("-", "_").split("_"))
        count = 0
        for other in all_tools:
            if other is tool:
                continue
            other_tokens = set(other.name.lower().replace("-", "_").split("_"))
            min_shared = max(2, min(len(tokens), len(other_tokens)) - 1)
            if tokens and len(tokens & other_tokens) >= min_shared:
                count += 1
        return count

    def _average(self, values: Any) -> float:
        values = list(values)
        if not values:
            return 0.0
        return round(sum(values) / len(values), 2)
