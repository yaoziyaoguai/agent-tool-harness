"""Tool ergonomics inspection —— deterministic tool name/namespace/description hints.

架构边界
--------
- **负责**：消费 ToolSpec 列表，对 tool name / namespace / description 做确定性
  ergonomics 启发式检查，产出 RuleFinding 列表。所有检查 zero-network, deterministic。
- **不负责**：不检查 runtime tool-use behavior（那是 ToolUseInspector 的事）、
  不检查 tool spec 文档完整性（那是 ToolSpecInspector 的事）、不分析
  tool response 质量（那是 ToolResponseQualityInspector 的事）、
  不做 LLM semantic similarity、不自动修改 tool spec、不调用 LLM。
- **与 ToolDesignAuditor 的关系**：ToolDesignAuditor 做 D4 层面的完整工效学审计
  （输出 AuditFinding / ToolAuditResult，含五类评分），独立 audit 路径。
  本模块做 D4 层面的轻量 deterministic hints（输出 RuleFinding），
  通过 CoreEvaluation 集成到主评测链路。两者互补共存，不重叠。

当前规则集（6 条，全部 deterministic，全部 WARNING，全部产出 RuleFinding）
------------------------------------------------------------------------------
1. tool_ergonomics.name.too_generic          — tool name 过于泛化
2. tool_ergonomics.name.namespace_present    — tool name 缺少 namespace 前缀
3. tool_ergonomics.names.overlap             — 多个 tool names 高度相似
4. tool_ergonomics.too_many_similar_tools    — 同 namespace 下过多相似工具
5. tool_ergonomics.description.shallow_wrapper — description 只是 API wrapper 描述
6. tool_ergonomics.action_resource_clarity   — tool name 是否含 action + resource

全部 WARNING: severity="medium", rule_passed=True, 不影响 EvaluationResult.passed。

明确 deferred:
- LLM semantic similarity / tool consolidation optimizer
- frequently chained tools pattern mining
- missing higher-level domain tool (LLM advisory)
- wrong tool selected analysis (LLM advisory)
"""

from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher

from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.core_contract import RuleFinding

# ---------------------------------------------------------------------------
# 启发式常量
# ---------------------------------------------------------------------------

# 仅由这些 token 组成的 tool name 过于泛化，Agent 难以判断工具的领域功能。
_GENERIC_NAME_TOKENS = frozenset({
    "search", "list", "get", "set", "run", "execute", "update", "delete",
    "create", "read", "write", "query", "fetch", "do", "process", "handle",
    "call", "api", "check", "analyze", "debug", "compute", "apply", "sync",
})

# 工具名应同时包含 action（动词）和 resource（名词）。
# 以下为典型 action token —— 如果 tool name 不含其中任一，可能缺少 action 表达。
_ACTION_TOKENS = frozenset({
    "search", "list", "get", "set", "run", "execute", "update", "delete",
    "create", "read", "write", "query", "fetch", "find", "check", "analyze",
    "debug", "compute", "apply", "sync", "resolve", "validate", "generate",
    "import", "export", "build", "deploy", "start", "stop", "restart",
    "enable", "disable", "add", "remove", "install", "uninstall",
})

# description 中包含这些短语 → 可能是 shallow API wrapper，没有 agent-facing purpose。
_SHALLOW_WRAPPER_PHRASES = (
    "api wrapper",
    "raw api",
    "rest api",
    "http endpoint",
    "endpoint",
    "crud",
    "database row",
    "直接封装",
    "wraps the",
    "wrapper around",
    "thin wrapper",
    "simple wrapper",
    "calls the",
)

# 跨 tool name 相似度阈值。
_NAME_SIMILARITY_THRESHOLD = 0.75

# 同 namespace 下相似工具数量阈值。
_SIMILAR_TOOLS_PER_NAMESPACE_THRESHOLD = 5


class ToolErgonomicsInspector:
    """对 ToolSpec 列表做确定性 ergonomics 启发式检查，产出 RuleFinding 列表。

    所有规则均为 WARNING（severity="medium", rule_passed=True），不影响 passed。
    不依赖网络、不依赖 LLM、不依赖 runtime trace。
    """

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    def inspect(self, tool_specs: list[ToolSpec]) -> list[RuleFinding]:
        """运行全部 6 条确定性检查，返回 RuleFinding 列表。"""
        findings: list[RuleFinding] = []

        # per-tool checks
        for spec in tool_specs:
            findings.extend([
                self._check_name_too_generic(spec),
                self._check_namespace_present(spec),
                self._check_description_shallow_wrapper(spec),
                self._check_action_resource_clarity(spec),
            ])

        # cross-tool checks（需要完整 tool list）
        if len(tool_specs) >= 2:
            findings.extend(self._check_names_overlap(tool_specs))
        findings.extend(self._check_too_many_similar_tools(tool_specs))

        return findings

    # ------------------------------------------------------------------
    # Rule 1: tool_ergonomics.name.too_generic
    # ------------------------------------------------------------------

    def _check_name_too_generic(self, spec: ToolSpec) -> RuleFinding:
        tokens = set(spec.name.lower().replace("-", "_").split("_"))
        generic_tokens = tokens & _GENERIC_NAME_TOKENS
        is_generic = tokens and tokens == generic_tokens

        return RuleFinding(
            finding_id=f"tool_ergonomics.name.too_generic::{spec.qualified_name}",
            severity="medium",
            category="rule",
            message=(
                f"tool name '{spec.name}' composed entirely of generic tokens:"
                f" {sorted(generic_tokens)}"
                if is_generic
                else f"tool name '{spec.name}' is specific enough"
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_ergonomics.name.too_generic",
            rule_passed=True,
        )

    # ------------------------------------------------------------------
    # Rule 2: tool_ergonomics.name.namespace_present
    # ------------------------------------------------------------------

    def _check_namespace_present(self, spec: ToolSpec) -> RuleFinding:
        has_namespace = bool(spec.namespace and spec.namespace.strip())

        return RuleFinding(
            finding_id=f"tool_ergonomics.name.namespace_present::{spec.qualified_name}",
            severity="medium",
            category="rule",
            message=(
                f"tool '{spec.qualified_name}' has namespace '{spec.namespace}'"
                if has_namespace
                else f"tool '{spec.name}' is missing namespace prefix"
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_ergonomics.name.namespace_present",
            rule_passed=True,
        )

    # ------------------------------------------------------------------
    # Rule 3: tool_ergonomics.names.overlap
    # ------------------------------------------------------------------

    def _check_names_overlap(self, tool_specs: list[ToolSpec]) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        names = [spec.qualified_name for spec in tool_specs]

        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                similarity = SequenceMatcher(None, names[i], names[j]).ratio()
                if similarity >= _NAME_SIMILARITY_THRESHOLD:
                    findings.append(RuleFinding(
                        finding_id=(
                            f"tool_ergonomics.names.overlap::"
                            f"{tool_specs[i].qualified_name}__{tool_specs[j].qualified_name}"
                        ),
                        severity="medium",
                        category="rule",
                        message=(
                            f"similar tool names: '{names[i]}' and '{names[j]}'"
                            f" (similarity={similarity:.2f})"
                        ),
                        evidence_ref=(
                            f"tool_spec:{tool_specs[i].qualified_name},"
                            f"{tool_specs[j].qualified_name}"
                        ),
                        rule_type="tool_ergonomics.names.overlap",
                        rule_passed=True,
                    ))

        # 无 overlap 时产出一条通过记录
        if not findings and len(names) >= 2:
            findings.append(RuleFinding(
                finding_id="tool_ergonomics.names.overlap::all_tools",
                severity="medium",
                category="rule",
                message="no overlapping tool names detected",
                evidence_ref=f"tool_specs[{len(names)} tools]",
                rule_type="tool_ergonomics.names.overlap",
                rule_passed=True,
            ))

        return findings

    # ------------------------------------------------------------------
    # Rule 4: tool_ergonomics.too_many_similar_tools
    # ------------------------------------------------------------------

    def _check_too_many_similar_tools(
        self, tool_specs: list[ToolSpec]
    ) -> list[RuleFinding]:
        findings: list[RuleFinding] = []
        namespace_counts: Counter[str] = Counter(
            spec.namespace for spec in tool_specs if spec.namespace
        )

        for namespace, count in namespace_counts.items():
            if count > _SIMILAR_TOOLS_PER_NAMESPACE_THRESHOLD:
                findings.append(RuleFinding(
                    finding_id=(
                        f"tool_ergonomics.too_many_similar_tools::{namespace}"
                    ),
                    severity="medium",
                    category="rule",
                    message=(
                        f"namespace '{namespace}' has {count} tools"
                        f" (threshold: {_SIMILAR_TOOLS_PER_NAMESPACE_THRESHOLD})"
                    ),
                    evidence_ref=f"namespace:{namespace}",
                    rule_type="tool_ergonomics.too_many_similar_tools",
                    rule_passed=True,
                ))

        # 无超标时产出一条通过记录
        if not findings and tool_specs:
            findings.append(RuleFinding(
                finding_id="tool_ergonomics.too_many_similar_tools::all_namespaces",
                severity="medium",
                category="rule",
                message="no namespace exceeds similar-tool threshold",
                evidence_ref=f"namespaces[{len(namespace_counts)} unique]",
                rule_type="tool_ergonomics.too_many_similar_tools",
                rule_passed=True,
            ))

        return findings

    # ------------------------------------------------------------------
    # Rule 5: tool_ergonomics.description.shallow_wrapper
    # ------------------------------------------------------------------

    def _check_description_shallow_wrapper(self, spec: ToolSpec) -> RuleFinding:
        desc_lower = (spec.description or "").lower()
        matched = [p for p in _SHALLOW_WRAPPER_PHRASES if p in desc_lower]
        is_shallow = len(matched) > 0

        return RuleFinding(
            finding_id=(
                f"tool_ergonomics.description.shallow_wrapper::{spec.qualified_name}"
            ),
            severity="medium",
            category="rule",
            message=(
                f"description matches shallow wrapper phrase(s): {matched}"
                if is_shallow
                else "description describes agent-facing purpose"
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_ergonomics.description.shallow_wrapper",
            rule_passed=True,
        )

    # ------------------------------------------------------------------
    # Rule 6: tool_ergonomics.action_resource_clarity
    # ------------------------------------------------------------------

    def _check_action_resource_clarity(self, spec: ToolSpec) -> RuleFinding:
        tokens = spec.name.lower().replace("-", "_").split("_")
        has_action = bool(set(tokens) & _ACTION_TOKENS)
        has_resource = bool(set(tokens) - _ACTION_TOKENS)

        return RuleFinding(
            finding_id=(
                f"tool_ergonomics.action_resource_clarity::{spec.qualified_name}"
            ),
            severity="medium",
            category="rule",
            message=(
                f"tool name '{spec.name}' has action and resource tokens"
                if has_action and has_resource
                else (
                    f"tool name '{spec.name}' missing "
                    + ("action" if not has_action else "resource")
                    + " token"
                )
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_ergonomics.action_resource_clarity",
            rule_passed=True,
        )
