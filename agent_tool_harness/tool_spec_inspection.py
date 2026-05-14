"""Tool spec quality inspection —— deterministic tool definition document checks.

架构边界
--------
- **负责**：消费 ToolSpec 列表，对 tool description / input_schema / output_contract /
  side_effects / when_to_use / when_not_to_use / token_policy 做确定性文档质量检查，
  产出 RuleFinding 列表。所有检查 zero-network, deterministic。
- **不负责**：不检查运行时 tool-use behavior（那是 ToolUseInspector 的事）、
  不做工具工效学分析（那是 ToolDesignAuditor 的事）、不调用 LLM、不修改 tool spec。
- **为什么独立于 ToolDesignAuditor**：ToolDesignAuditor 做的是 D4 层面的工效学检查
  （low-level wrapper / namespace / overlap / semantic similarity / shallow wrapper
  decoy）。ToolSpecInspector 做的是 D6 层面的文档完整性检查（description /
  schema / side_effects / when_to_use 是否写了、写清楚了没有）。
  两者互补但不重叠，不应混在同一个类里。
- **为什么独立于 ToolUseInspector**：ToolUseInspector 检查 ExecutionTrace 的结构
  不变量（call_id 重复、orphan 等），输入是运行时 trace。ToolSpecInspector 检查
  工具 spec 的文档质量，输入是静态 ToolSpec。两者输入类型完全不同。

当前规则集（10 条，全部 deterministic，全部产出 RuleFinding）
--------------------------------------------------------------
ERROR（rule_passed=False 当违规 → 影响 EvaluationResult.passed）:
1. tool_spec.description.exists       — description 非空字符串
2. tool_spec.input_schema.exists      — input_schema.properties 非空

WARNING（rule_passed=True，severity="medium"）:
3. tool_spec.description.useful_length     — description >= 10 words
4. tool_spec.parameter.name.explicit       — 参数名无泛化 token
5. tool_spec.required_parameter.documented — input_schema.required 已声明
6. tool_spec.output_contract.documented    — output_contract 非空
7. tool_spec.side_effects.documented       — side_effects 有标注
8. tool_spec.when_to_use.documented        — when_to_use 非空
9. tool_spec.when_not_to_use.documented    — when_not_to_use 非空

INFO（rule_passed=True，severity="low"）:
10. tool_spec.token_policy.defined         — token_policy 有内容

明确 deferred（因 ToolSpec schema 不支持）:
- tool_spec.examples.present        — ToolSpec 无 stable examples 字段
- tool_spec.auth_requirements.documented — ToolSpec 无 stable auth 字段
"""

from __future__ import annotations

from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.core_contract import RuleFinding

# ---------------------------------------------------------------------------
# 参数名泛化 token —— 出现在参数名中几乎一定是"未命名清楚"
# ---------------------------------------------------------------------------

_GENERIC_PARAM_TOKENS = frozenset(
    {
        "data",
        "input",
        "value",
        "arg",
        "param",
        "id",
        "result",
        "output",
        "info",
        "item",
        "obj",
        "object",
        "config",
        "options",
        "body",
        "content",
        "payload",
        "request",
        "response",
        "record",
        "entry",
    }
)


class ToolSpecInspector:
    """对 ToolSpec 列表做确定性文档质量检查，产出 RuleFinding 列表。

    所有检查不依赖网络、不依赖 LLM、不依赖 runtime trace。
    ERROR 级别 rule 违规时 rule_passed=False（影响 EvaluationResult.passed），
    WARNING / INFO 级别 rule 始终 rule_passed=True（不影响 passed）。
    """

    # ------------------------------------------------------------------
    # 公共入口
    # ------------------------------------------------------------------

    def inspect(self, tool_specs: list[ToolSpec]) -> list[RuleFinding]:
        """运行全部 10 条确定性检查，返回 RuleFinding 列表。"""
        findings: list[RuleFinding] = []
        for spec in tool_specs:
            findings.extend(
                [
                    self._check_description_exists(spec),
                    self._check_description_useful_length(spec),
                    self._check_input_schema_exists(spec),
                    self._check_parameter_names_explicit(spec),
                    self._check_required_parameter_documented(spec),
                    self._check_output_contract_documented(spec),
                    self._check_side_effects_documented(spec),
                    self._check_when_to_use_documented(spec),
                    self._check_when_not_to_use_documented(spec),
                    self._check_token_policy_defined(spec),
                ]
            )
        return findings

    # ------------------------------------------------------------------
    # ERROR: description.exists
    # ------------------------------------------------------------------

    def _check_description_exists(self, spec: ToolSpec) -> RuleFinding:
        passed = isinstance(spec.description, str) and bool(spec.description.strip())
        return RuleFinding(
            finding_id=f"tool_spec.description.exists::{spec.qualified_name}",
            severity="high",
            category="rule",
            message=(
                "tool_spec.description exists and is non-empty"
                if passed
                else "description is empty or missing"
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_spec.description.exists",
            rule_passed=passed,
        )

    # ------------------------------------------------------------------
    # WARNING: description.useful_length
    # ------------------------------------------------------------------

    def _check_description_useful_length(self, spec: ToolSpec) -> RuleFinding:
        desc = spec.description or ""
        word_count = len(desc.split())
        sufficient = word_count >= 10
        return RuleFinding(
            finding_id=f"tool_spec.description.useful_length::{spec.qualified_name}",
            severity="medium",
            category="rule",
            message=(
                f"description has {word_count} words (threshold: 10)"
                if sufficient
                else f"description too short: {word_count} words (threshold: 10)"
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_spec.description.useful_length",
            rule_passed=True,  # WARNING — 不影响 passed
        )

    # ------------------------------------------------------------------
    # ERROR: input_schema.exists
    # ------------------------------------------------------------------

    def _check_input_schema_exists(self, spec: ToolSpec) -> RuleFinding:
        schema = spec.input_schema or {}
        properties = schema.get("properties")
        has_props = isinstance(properties, dict) and len(properties) > 0
        return RuleFinding(
            finding_id=f"tool_spec.input_schema.exists::{spec.qualified_name}",
            severity="high",
            category="rule",
            message=(
                f"input_schema has {len(properties)} parameter(s)"
                if has_props
                else "input_schema has no properties defined"
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_spec.input_schema.exists",
            rule_passed=has_props,
        )

    # ------------------------------------------------------------------
    # WARNING: parameter.name.explicit
    # ------------------------------------------------------------------

    def _check_parameter_names_explicit(self, spec: ToolSpec) -> RuleFinding:
        schema = spec.input_schema or {}
        properties = schema.get("properties") or {}
        generic_params: list[str] = []
        for param_name in properties:
            tokens = set(
                param_name.lower().replace("-", "_").replace(".", "_").split("_")
            )
            if tokens & _GENERIC_PARAM_TOKENS and len(tokens) <= 2:
                generic_params.append(param_name)

        has_generic = len(generic_params) > 0
        return RuleFinding(
            finding_id=f"tool_spec.parameter.name.explicit::{spec.qualified_name}",
            severity="medium",
            category="rule",
            message=(
                f"generic parameter name(s): {', '.join(generic_params)}"
                if has_generic
                else "all parameter names are explicit"
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_spec.parameter.name.explicit",
            rule_passed=True,  # WARNING — 不影响 passed
        )

    # ------------------------------------------------------------------
    # WARNING: required_parameter.documented
    # ------------------------------------------------------------------

    def _check_required_parameter_documented(self, spec: ToolSpec) -> RuleFinding:
        schema = spec.input_schema or {}
        properties = schema.get("properties")
        required = schema.get("required")

        has_props = isinstance(properties, dict) and len(properties) > 0
        has_required = isinstance(required, list) and len(required) > 0

        if not has_props:
            # 没有 properties 时不检查 required（由 input_schema.exists 覆盖）
            return RuleFinding(
                finding_id=(
                    f"tool_spec.required_parameter.documented::{spec.qualified_name}"
                ),
                severity="medium",
                category="rule",
                message="no properties to check required parameters for",
                evidence_ref=f"tool_spec:{spec.qualified_name}",
                rule_type="tool_spec.required_parameter.documented",
                rule_passed=True,
            )

        undocumented: list[str] = []
        if has_required and isinstance(required, list):
            required_set = set(required)
            all_params = set(properties.keys())
            undocumented = sorted(all_params - required_set)

        return RuleFinding(
            finding_id=(
                f"tool_spec.required_parameter.documented::{spec.qualified_name}"
            ),
            severity="medium",
            category="rule",
            message=(
                f"required field not declared;"
                f" {list(properties.keys())} are implicitly optional"
                f" by JSON Schema convention"
                if not has_required
                else (
                    f"parameters not in required list"
                    f" (implicitly optional by JSON Schema convention):"
                    f" {undocumented}"
                    if undocumented
                    else "required parameters are documented"
                )
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_spec.required_parameter.documented",
            rule_passed=True,  # WARNING — 不影响 passed
        )

    # ------------------------------------------------------------------
    # WARNING: output_contract.documented
    # ------------------------------------------------------------------

    def _check_output_contract_documented(self, spec: ToolSpec) -> RuleFinding:
        contract = spec.output_contract or {}
        has_contract = isinstance(contract, dict) and len(contract) > 0
        return RuleFinding(
            finding_id=f"tool_spec.output_contract.documented::{spec.qualified_name}",
            severity="medium",
            category="rule",
            message=(
                f"output_contract has {len(contract)} field(s)"
                if has_contract
                else "output_contract is empty"
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_spec.output_contract.documented",
            rule_passed=True,  # WARNING — 不影响 passed
        )

    # ------------------------------------------------------------------
    # WARNING: side_effects.documented
    # ------------------------------------------------------------------

    def _check_side_effects_documented(self, spec: ToolSpec) -> RuleFinding:
        se = spec.side_effects or {}
        has_destructive = isinstance(se.get("destructive"), bool)
        has_open_world = isinstance(se.get("open_world_access"), bool)
        documented = has_destructive or has_open_world
        labels = []
        if has_destructive:
            labels.append("destructive")
        if has_open_world:
            labels.append("open_world_access")
        return RuleFinding(
            finding_id=f"tool_spec.side_effects.documented::{spec.qualified_name}",
            severity="medium",
            category="rule",
            message=(
                f"side_effects labeled: {', '.join(labels)}"
                if documented
                else "side_effects not documented (no destructive/open_world_access)"
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_spec.side_effects.documented",
            rule_passed=True,  # WARNING — 不影响 passed
        )

    # ------------------------------------------------------------------
    # WARNING: when_to_use.documented
    # ------------------------------------------------------------------

    def _check_when_to_use_documented(self, spec: ToolSpec) -> RuleFinding:
        wtu = spec.when_to_use or ""
        has_wtu = isinstance(wtu, str) and bool(wtu.strip())
        return RuleFinding(
            finding_id=f"tool_spec.when_to_use.documented::{spec.qualified_name}",
            severity="medium",
            category="rule",
            message=(
                "when_to_use is documented"
                if has_wtu
                else "when_to_use is empty"
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_spec.when_to_use.documented",
            rule_passed=True,  # WARNING — 不影响 passed
        )

    # ------------------------------------------------------------------
    # WARNING: when_not_to_use.documented
    # ------------------------------------------------------------------

    def _check_when_not_to_use_documented(self, spec: ToolSpec) -> RuleFinding:
        wntu = spec.when_not_to_use or ""
        has_wntu = isinstance(wntu, str) and bool(wntu.strip())
        return RuleFinding(
            finding_id=f"tool_spec.when_not_to_use.documented::{spec.qualified_name}",
            severity="medium",
            category="rule",
            message=(
                "when_not_to_use is documented"
                if has_wntu
                else "when_not_to_use is empty"
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_spec.when_not_to_use.documented",
            rule_passed=True,  # WARNING — 不影响 passed
        )

    # ------------------------------------------------------------------
    # INFO: token_policy.defined
    # ------------------------------------------------------------------

    def _check_token_policy_defined(self, spec: ToolSpec) -> RuleFinding:
        policy = spec.token_policy or {}
        has_policy = isinstance(policy, dict) and len(policy) > 0
        return RuleFinding(
            finding_id=f"tool_spec.token_policy.defined::{spec.qualified_name}",
            severity="info",
            category="rule",
            message=(
                f"token_policy has {len(policy)} field(s)"
                if has_policy
                else "token_policy is empty"
            ),
            evidence_ref=f"tool_spec:{spec.qualified_name}",
            rule_type="tool_spec.token_policy.defined",
            rule_passed=True,  # INFO — 不影响 passed
        )
