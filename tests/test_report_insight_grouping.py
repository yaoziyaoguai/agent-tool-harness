"""P2 FindingGrouper 测试。

覆盖 12+ 场景：空 findings、按 severity/category/tool/rule_id_prefix 分组、
不变量验证、judge finding 处理、输入不可变性。
"""

from __future__ import annotations

from agent_tool_harness.core_contract import (
    Finding,
    JudgeFinding,
    RuleFinding,
)
from agent_tool_harness.reports.report_insight import FindingGrouper, GroupedFindings

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_rule_finding(
    finding_id: str = "f1",
    severity: str = "high",
    rule_type: str = "tool_response.output.low_signal",
    message: str = "",
    evidence_ref: str = "ref",
    category: str = "rule",
) -> RuleFinding:
    return RuleFinding(
        finding_id=finding_id,
        severity=severity,
        category=category,
        message=message or f"规则发现: {rule_type}",
        evidence_ref=evidence_ref,
        rule_type=rule_type,
        rule_passed=False,
    )


def _make_judge_finding(
    finding_id: str = "j1",
    severity: str = "medium",
    message: str = "LLM judge 发现输出质量一般",
) -> JudgeFinding:
    return JudgeFinding(
        finding_id=finding_id,
        severity=severity,
        category="judge",
        message=message,
        evidence_ref="ref",
        provider="openai-native",
        model="gpt-4o",
        confidence=0.7,
        rationale="输出缺少上下文",
        rubric="response_quality",
    )


# ---------------------------------------------------------------------------
# 测试 1: 空 findings
# ---------------------------------------------------------------------------


class TestEmptyFindings:
    def test_all_groups_empty(self):
        """空 findings → 4 个 dict 均为空。"""
        grouper = FindingGrouper()
        groups = grouper.group([])

        assert groups.by_severity == {}
        assert groups.by_category == {}
        assert groups.by_tool == {}
        assert groups.by_rule_id_prefix == {}

    def test_frozen_dataclass(self):
        """GroupedFindings 为 frozen=True。"""
        import pytest

        g = GroupedFindings()
        with pytest.raises(AttributeError):
            g.by_severity = {}  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 测试 2: by_severity
# ---------------------------------------------------------------------------


class TestGroupBySeverity:
    def test_single_severity(self):
        """单一 severity → by_severity 只有一个 key，长度等于原始。"""
        findings = [
            _make_rule_finding("f1", severity="high", rule_type="tool_response.output.low_signal"),
            _make_rule_finding("f2", severity="high", rule_type="tool_spec.description.exists"),
            _make_rule_finding("f3", severity="high", rule_type="tool_ergonomics.name.too_generic"),
        ]

        groups = FindingGrouper().group(findings)

        assert list(groups.by_severity.keys()) == ["high"]
        assert len(groups.by_severity["high"]) == 3

    def test_mixed_severity(self):
        """混合 severity → keys 正确，各组 finding 数正确。"""
        mk = _make_rule_finding
        findings = [
            mk("f1", severity="critical", rule_type="tool_pair.orphan_call"),
            mk("f2", severity="high", rule_type="tool_response.output.low_signal"),
            mk("f3", severity="high", rule_type="tool_spec.description.exists"),
            mk("f4", severity="medium", rule_type="tool_ergonomics.name.too_generic"),
            mk("f5", severity="low", rule_type="tool_spec.when_to_use.documented"),
            mk("f6", severity="info", rule_type="tool_spec.token_policy.defined"),
        ]

        groups = FindingGrouper().group(findings)

        assert groups.by_severity["critical"][0].finding_id == "f1"
        assert len(groups.by_severity["high"]) == 2
        assert len(groups.by_severity["medium"]) == 1
        assert len(groups.by_severity["low"]) == 1
        assert len(groups.by_severity["info"]) == 1

    def test_unknown_severity_fallback(self):
        """非标准 severity → "(unknown)"。"""
        f = RuleFinding(
            finding_id="f1",
            severity="weird_value",
            category="rule",
            message="test",
            evidence_ref="ref",
            rule_type="tool_spec.description.exists",
        )
        groups = FindingGrouper().group([f])

        assert "(unknown)" in groups.by_severity
        assert len(groups.by_severity["(unknown)"]) == 1

    def test_severity_total_invariant(self):
        """by_severity 各组 finding 总数 = 原始 findings 数。"""
        findings = [
            _make_rule_finding("f1", severity="high", rule_type="t1"),
            _make_rule_finding("f2", severity="medium", rule_type="t2"),
            _make_rule_finding("f3", severity="low", rule_type="t3"),
        ]
        groups = FindingGrouper().group(findings)
        total = sum(len(v) for v in groups.by_severity.values())
        assert total == len(findings)


# ---------------------------------------------------------------------------
# 测试 3: by_category
# ---------------------------------------------------------------------------


class TestGroupByCategory:
    def test_rule_prefix_subcategories(self):
        """Rule finding 按 rule_type prefix 分子类别。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_response.output.low_signal"),
            _make_rule_finding("f2", rule_type="tool_response.error.actionable"),
            _make_rule_finding("f3", rule_type="tool_spec.description.exists"),
            _make_rule_finding("f4", rule_type="tool_spec.description.useful_length"),
            _make_rule_finding("f5", rule_type="tool_ergonomics.name.too_generic"),
        ]

        groups = FindingGrouper().group(findings)

        assert len(groups.by_category["tool_response"]) == 2
        assert len(groups.by_category["tool_spec"]) == 2
        assert len(groups.by_category["tool_ergonomics"]) == 1

    def test_judge_category(self):
        """JudgeFinding → category="judge"。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_spec.description.exists"),
            _make_judge_finding("j1"),
            _make_judge_finding("j2"),
        ]

        groups = FindingGrouper().group(findings)

        assert len(groups.by_category["tool_spec"]) == 1
        assert len(groups.by_category["judge"]) == 2

    def test_audit_signal_defensive(self):
        """category="audit" 或 "signal" → 防御性分桶。"""
        f_audit = Finding(
            finding_id="a1",
            severity="low",
            category="audit",
            message="audit note",
            evidence_ref="ref",
        )
        f_signal = Finding(
            finding_id="s1",
            severity="info",
            category="signal",
            message="signal note",
            evidence_ref="ref",
        )
        groups = FindingGrouper().group([f_audit, f_signal])

        assert "audit" in groups.by_category
        assert "signal" in groups.by_category

    def test_unknown_category_fallback(self):
        """未知 category → "(unknown)"。"""
        f = Finding(
            finding_id="f1",
            severity="medium",
            category="bizarre",
            message="test",
            evidence_ref="ref",
        )
        groups = FindingGrouper().group([f])
        assert "(unknown)" in groups.by_category

    def test_category_total_invariant(self):
        """by_category 各组 finding 总数 = 原始 findings 数。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_spec.description.exists"),
            _make_rule_finding("f2", rule_type="tool_response.output.low_signal"),
            _make_judge_finding("j1"),
        ]
        groups = FindingGrouper().group(findings)
        total = sum(len(v) for v in groups.by_category.values())
        assert total == len(findings)

    def test_category_id_uniq_invariant(self):
        """同 group 内无重复 finding_id。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_spec.description.exists"),
            _make_rule_finding("f2", rule_type="tool_spec.description.useful_length"),
        ]
        groups = FindingGrouper().group(findings)
        ids = [f.finding_id for f in groups.by_category["tool_spec"]]
        assert len(ids) == len(set(ids))


# ---------------------------------------------------------------------------
# 测试 4: by_tool
# ---------------------------------------------------------------------------


class TestGroupByTool:
    def test_from_finding_id_double_colon(self):
        """finding_id 格式 rule_type::tool_name → 提取 tool_name。"""
        f = _make_rule_finding(
            finding_id="tool_response.output.low_signal::search_documents",
            rule_type="tool_response.output.low_signal",
        )
        groups = FindingGrouper().group([f])
        assert "search_documents" in groups.by_tool

    def test_from_evidence_ref(self):
        """从 evidence_ref 提取 tool_name（call_id 后缀）。"""
        f = _make_rule_finding(
            finding_id="tool_response.output.low_signal",
            evidence_ref="tool_calls.jsonl::call_id=read_file_001",
            rule_type="tool_response.output.low_signal",
        )
        groups = FindingGrouper().group([f])
        assert "read_file" in groups.by_tool

    def test_from_message_quoted(self):
        """从 message 中引号包裹的工具名提取。"""
        f = _make_rule_finding(
            finding_id="tool_response.output.low_signal",
            evidence_ref="ref",
            message="工具 'write_file' 的输出信号过低",
            rule_type="tool_response.output.low_signal",
        )
        groups = FindingGrouper().group([f])
        assert "write_file" in groups.by_tool

    def test_unknown_fallback(self):
        """无法提取 tool_name → "(unknown)"。"""
        f = _make_rule_finding(
            finding_id="some_generic_id",
            evidence_ref="some_ref",
            message="no tool name here",
            rule_type="tool_response.output.low_signal",
        )
        groups = FindingGrouper().group([f])
        assert "(unknown)" in groups.by_tool

    def test_multiple_tools_aggregated(self):
        """多个 finding 按 tool_name 正确聚合。"""
        findings = [
            _make_rule_finding("f1::search", rule_type="tool_response.output.low_signal"),
            _make_rule_finding("f2::search", rule_type="tool_response.error.actionable"),
            _make_rule_finding("f3::read", rule_type="tool_spec.description.exists"),
        ]
        groups = FindingGrouper().group(findings)
        assert len(groups.by_tool["search"]) == 2
        assert len(groups.by_tool["read"]) == 1

    def test_unknown_tool_last(self):
        """"(unknown)" group 排在 by_tool dict 最后。"""
        findings = [
            _make_rule_finding("f1::search", rule_type="tool_response.output.low_signal"),
            _make_rule_finding(
                "f2", rule_type="tool_response.error.actionable",
                evidence_ref="no_call_id_here", message="no name",
            ),
        ]
        groups = FindingGrouper().group(findings)
        keys = list(groups.by_tool.keys())
        # "(unknown)" 应在最后
        assert keys[-1] == "(unknown)" if "(unknown)" in keys else True
        # 其他 group 按 count 降序
        if "search" in keys:
            assert keys.index("search") < keys.index("(unknown)") if "(unknown)" in keys else True

    def test_tool_total_invariant(self):
        """by_tool 各组 finding 总数 = 原始 findings 数。"""
        findings = [
            _make_rule_finding("f1::search", rule_type="tool_response.output.low_signal"),
            _make_rule_finding("f2::read", rule_type="tool_spec.description.exists"),
            _make_rule_finding("f3::search", rule_type="tool_response.error.actionable"),
        ]
        groups = FindingGrouper().group(findings)
        total = sum(len(v) for v in groups.by_tool.values())
        assert total == len(findings)


# ---------------------------------------------------------------------------
# 测试 5: by_rule_id_prefix
# ---------------------------------------------------------------------------


class TestGroupByRuleIdPrefix:
    def test_prefix_separation(self):
        """不同 rule_type prefix 正确分开。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_call.arguments.present"),
            _make_rule_finding("f2", rule_type="tool_call.arguments.is_object"),
            _make_rule_finding("f3", rule_type="tool_result.status.valid"),
            _make_rule_finding("f4", rule_type="tool_pair.orphan_call"),
        ]
        groups = FindingGrouper().group(findings)

        assert len(groups.by_rule_id_prefix["tool_call"]) == 2
        assert len(groups.by_rule_id_prefix["tool_result"]) == 1
        assert len(groups.by_rule_id_prefix["tool_pair"]) == 1

    def test_judge_finding_unknown(self):
        """JudgeFinding 无 rule_type → "(unknown)"。"""
        f = _make_judge_finding("j1")
        groups = FindingGrouper().group([f])
        assert "(unknown)" in groups.by_rule_id_prefix

    def test_unknown_prefix_last(self):
        """by_rule_id_prefix 中 "(unknown)" 排在最后。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_spec.description.exists"),
            _make_judge_finding("j1"),
        ]
        groups = FindingGrouper().group(findings)
        keys = list(groups.by_rule_id_prefix.keys())
        if "(unknown)" in keys:
            assert keys[-1] == "(unknown)"

    def test_prefix_total_invariant(self):
        """by_rule_id_prefix 各组 finding 总数 = 原始 findings。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_spec.description.exists"),
            _make_rule_finding("f2", rule_type="tool_response.output.low_signal"),
            _make_judge_finding("j1"),
        ]
        groups = FindingGrouper().group(findings)
        total = sum(len(v) for v in groups.by_rule_id_prefix.values())
        assert total == len(findings)


# ---------------------------------------------------------------------------
# 测试 6: 排序不变量
# ---------------------------------------------------------------------------


class TestSortingInvariants:
    def test_within_group_sorted_by_severity_desc(self):
        """group 内 finding 按 severity 降序排列（critical → high → ... → info）。"""
        mk = _make_rule_finding
        findings = [
            mk("f1", severity="info", rule_type="tool_response.output.low_signal"),
            mk("f2", severity="critical", rule_type="tool_response.error.actionable"),
            mk("f3", severity="low",
               rule_type="tool_response.output.size_reasonable"),
        ]
        groups = FindingGrouper().group(findings)
        severities = [f.severity for f in groups.by_category["tool_response"]]
        assert severities == ["critical", "low", "info"]

    def test_groups_sorted_by_count_desc(self):
        """group 级别按 finding count 降序排列。"""
        mk = _make_rule_finding
        findings = [
            mk("f1", severity="high", rule_type="tool_spec.description.exists"),
            mk("f2", severity="high", rule_type="tool_spec.description.useful_length"),
            mk("f3", severity="high", rule_type="tool_spec.input_schema.exists"),
            mk("f4", severity="medium", rule_type="tool_response.output.low_signal"),
        ]
        groups = FindingGrouper().group(findings)
        keys = list(groups.by_category.keys())
        # tool_spec 有 3 条，tool_response 有 1 条 → tool_spec 排在前面
        assert keys.index("tool_spec") < keys.index("tool_response")

    def test_all_views_id_set_invariant(self):
        """所有分组的 finding ID 集合等于原始 finding ID 集合。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_response.output.low_signal"),
            _make_rule_finding("f2", rule_type="tool_spec.description.exists"),
            _make_rule_finding("f3", rule_type="tool_ergonomics.name.too_generic"),
            _make_judge_finding("j1"),
        ]
        original_ids = {f.finding_id for f in findings}
        groups = FindingGrouper().group(findings)

        for view_name, view in [
            ("by_severity", groups.by_severity),
            ("by_category", groups.by_category),
            ("by_tool", groups.by_tool),
            ("by_rule_id_prefix", groups.by_rule_id_prefix),
        ]:
            view_ids = set()
            for items in view.values():
                for item in items:
                    view_ids.add(item.finding_id)
            assert view_ids == original_ids, f"{view_name}: ID set mismatch"

    def test_no_duplicates_in_groups(self):
        """同一 group 内无重复 finding_id。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_spec.description.exists"),
            _make_rule_finding("f2", rule_type="tool_spec.description.useful_length"),
            _make_rule_finding("f3", rule_type="tool_spec.input_schema.exists"),
        ]
        groups = FindingGrouper().group(findings)
        for view_name, view in [
            ("by_severity", groups.by_severity),
            ("by_category", groups.by_category),
            ("by_tool", groups.by_tool),
            ("by_rule_id_prefix", groups.by_rule_id_prefix),
        ]:
            for key, items in view.items():
                ids = [f.finding_id for f in items]
                assert len(ids) == len(set(ids)), f"{view_name}/{key}: duplicates found"


# ---------------------------------------------------------------------------
# 测试 7: 输入不可变
# ---------------------------------------------------------------------------


class TestImmutabilityOfInputs:
    def test_original_findings_not_mutated(self):
        """FindingGrouper.group() 不修改传入的 findings 列表。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_response.output.low_signal"),
            _make_rule_finding("f2", rule_type="tool_spec.description.exists"),
        ]
        original_len = len(findings)
        original_ids = [f.finding_id for f in findings]

        FindingGrouper().group(findings)

        assert len(findings) == original_len
        assert [f.finding_id for f in findings] == original_ids


# ---------------------------------------------------------------------------
# 测试 8: mixed RuleFinding + JudgeFinding
# ---------------------------------------------------------------------------


class TestMixedFindings:
    def test_mixed_rule_and_judge(self):
        """混合 RuleFinding + JudgeFinding 正确分组。"""
        findings = [
            _make_rule_finding("f1", severity="critical", rule_type="tool_pair.orphan_call"),
            _make_rule_finding("f2", severity="high", rule_type="tool_response.output.low_signal"),
            _make_judge_finding("j1", severity="low"),
            _make_judge_finding("j2", severity="info"),
        ]
        groups = FindingGrouper().group(findings)

        # by_severity: 4 findings 按各自 severity
        total_sev = sum(len(v) for v in groups.by_severity.values())
        assert total_sev == 4

        # by_category: rule → tool_pair + tool_response; judge → judge
        assert len(groups.by_category["tool_pair"]) == 1
        assert len(groups.by_category["tool_response"]) == 1
        assert len(groups.by_category["judge"]) == 2

        # by_rule_id_prefix: judge → "(unknown)"
        assert len(groups.by_rule_id_prefix["tool_pair"]) == 1
        assert len(groups.by_rule_id_prefix["tool_response"]) == 1
        assert len(groups.by_rule_id_prefix["(unknown)"]) == 2

        # by_tool: judge → likely "(unknown)"
        total_tool = sum(len(v) for v in groups.by_tool.values())
        assert total_tool == 4

    def test_finding_id_set_invariant_mixed(self):
        """混合 findings 的 ID 集合不变量。"""
        findings = [
            _make_rule_finding("f1", rule_type="tool_response.output.low_signal"),
            _make_judge_finding("j1"),
            _make_judge_finding("j2"),
        ]
        original_ids = {f.finding_id for f in findings}
        groups = FindingGrouper().group(findings)

        for view in [
            groups.by_severity,
            groups.by_category,
            groups.by_tool,
            groups.by_rule_id_prefix,
        ]:
            view_ids = {f.finding_id for items in view.values() for f in items}
            assert view_ids == original_ids
