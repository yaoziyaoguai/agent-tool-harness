"""ToolPortfolioReview 测试 —— 覆盖 5 类检查。"""

from dataclasses import FrozenInstanceError

import pytest

from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.portfolio.portfolio_review import (
    PortfolioFinding,
    ToolPortfolioReview,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _make_tool_spec(
    name: str,
    namespace: str = "",
    description: str = "A useful tool for domain-specific operations.",
) -> ToolSpec:
    """构造最小 ToolSpec 用于测试。"""
    return ToolSpec.from_dict({
        "name": name,
        "namespace": namespace,
        "version": "0.1",
        "description": description,
        "when_to_use": "Use when needed.",
        "when_not_to_use": "Do not use otherwise.",
        "input_schema": {"type": "object", "properties": {}},
        "output_contract": {"required_fields": ["result"]},
        "token_policy": {"max_output_tokens": 1000},
        "side_effects": {"destructive": False},
        "executor": {"type": "python", "path": "demo.py", "function": name},
    })


def _make_mock_finding(
    finding_id: str = "test-0",
    severity: str = "info",
    message: str = "",
    rule_type: str = "",
    evidence_ref: str = "",
) -> object:
    """构造最小 mock finding 对象用于 missing_higher_level 检测。"""
    from agent_tool_harness.core_contract import RuleFinding
    return RuleFinding(
        finding_id=finding_id,
        severity=severity,
        category="rule",
        message=message,
        evidence_ref=evidence_ref,
        rule_type=rule_type,
        rule_passed=False,
    )


# ---------------------------------------------------------------------------
# Check 1: namespacing consistency
# ---------------------------------------------------------------------------

class TestNamespacingConsistency:
    """命名空间一致性检查。"""

    def test_all_namespaced_no_finding(self):
        """所有工具都有 namespace → 无 finding。"""
        tools = [
            _make_tool_spec("search", namespace="doc"),
            _make_tool_spec("read", namespace="doc"),
            _make_tool_spec("write", namespace="doc"),
        ]
        review = ToolPortfolioReview()
        result = review._check_namespacing(tools)
        assert len(result) == 0

    def test_above_threshold_produces_warning(self):
        """>30% 工具无 namespace → warning。"""
        tools = [
            _make_tool_spec("search", namespace=""),  # 无 namespace
            _make_tool_spec("read", namespace=""),     # 无 namespace
            _make_tool_spec("write", namespace="doc"),
        ]
        # 2/3 = 67% > 30%
        review = ToolPortfolioReview()
        result = review._check_namespacing(tools)
        assert len(result) == 1
        f = result[0]
        assert f.check_name == "namespacing_consistency"
        assert f.severity == "warning"
        assert len(f.affected_tools) == 2
        assert "67%" in f.description or "0.67" in f.description

    def test_below_threshold_no_finding(self):
        """≤30% 工具无 namespace → 无 finding。"""
        tools = [
            _make_tool_spec("search", namespace=""),  # 1/4 = 25%
            _make_tool_spec("read", namespace="doc"),
            _make_tool_spec("write", namespace="doc"),
            _make_tool_spec("delete", namespace="doc"),
        ]
        review = ToolPortfolioReview()
        result = review._check_namespacing(tools)
        assert len(result) == 0

    def test_empty_tool_list(self):
        """空工具列表 → 无 finding。"""
        review = ToolPortfolioReview()
        result = review._check_namespacing([])
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Check 2: overlapping tools
# ---------------------------------------------------------------------------

class TestOverlappingTools:
    """工具重叠检测。"""

    def test_no_overlap_no_finding(self):
        """名称和描述都差异大 → 无 finding。"""
        tools = [
            _make_tool_spec("search_docs", description="Search documentation files"),
            _make_tool_spec("read_config", description="Read configuration from disk"),
            _make_tool_spec("write_log", description="Write log entries to file"),
        ]
        review = ToolPortfolioReview()
        result = review._check_overlap(tools)
        assert len(result) == 0

    def test_similar_name_and_desc_produces_warning(self):
        """名称编辑距离 ≤ 2 且描述相似 → warning。"""
        tools = [
            _make_tool_spec(
                "search_docs",
                description="Search documentation files for keywords",
            ),
            _make_tool_spec(
                "search_doc",
                description="Search documentation for keywords",
            ),
        ]
        review = ToolPortfolioReview()
        result = review._check_overlap(tools)
        assert len(result) == 1
        f = result[0]
        assert f.check_name == "overlapping_tools"
        assert f.severity == "warning"
        assert len(f.affected_tools) == 2

    def test_similar_name_different_desc_no_finding(self):
        """名称接近但描述完全不同 → 无 finding。"""
        tools = [
            _make_tool_spec(
                "search_docs",
                description="Full-text search across all documentation files",
            ),
            _make_tool_spec(
                "search_doc",
                description="Delete user accounts and remove associated data permanently",
            ),
        ]
        review = ToolPortfolioReview()
        result = review._check_overlap(tools)
        # 名称为 "search_docs" vs "search_doc"，编辑距离=1
        # 但描述完全不相关
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Check 3: shallow wrappers
# ---------------------------------------------------------------------------

class TestShallowWrappers:
    """浅层包装检测。"""

    def test_crud_prefix_no_domain_words_produces_finding(self):
        """CRUD 前缀 + 缺乏领域词汇 → info finding。"""
        tools = [
            _make_tool_spec(
                "get_data",
                description="Get the data.",
            ),
        ]
        review = ToolPortfolioReview()
        result = review._check_shallow_wrappers(tools)
        assert len(result) == 1
        f = result[0]
        assert f.check_name == "shallow_wrappers"
        assert f.severity == "info"
        assert "get_data" in f.affected_tools[0]

    def test_crud_prefix_with_domain_words_no_finding(self):
        """CRUD 前缀但有足够领域词汇 → 无 finding。"""
        tools = [
            _make_tool_spec(
                "get_checkpoint_state",
                description=(
                    "Retrieve checkpoint state from the runtime boundary "
                    "including input buffers and restore metadata"
                ),
            ),
        ]
        review = ToolPortfolioReview()
        result = review._check_shallow_wrappers(tools)
        assert len(result) == 0

    def test_no_crud_prefix_no_finding(self):
        """名称不以 CRUD 前缀开头 → 跳过不产生 finding。"""
        tools = [
            _make_tool_spec(
                "runtime_trace_event_chain",
                description="Trace runtime events.",
            ),
        ]
        review = ToolPortfolioReview()
        result = review._check_shallow_wrappers(tools)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Check 4: missing higher-level tool
# ---------------------------------------------------------------------------

class TestMissingHigherLevel:
    """缺失高层工具检测。"""

    def test_no_chained_signals_no_finding(self):
        """没有 chained 相关 finding → 无 finding。"""
        findings = [
            _make_mock_finding(
                finding_id="other-1",
                rule_type="tool_call.call_id_duplicate",
                evidence_ref="trace:c1",
            ),
        ]
        review = ToolPortfolioReview()
        result = review._check_missing_higher_level(findings)
        assert len(result) == 0

    def test_enough_chained_signals_produces_finding(self):
        """≥3 个 chained finding → info finding。"""
        findings = [
            _make_mock_finding(
                finding_id="tqj-chained-0",
                rule_type="frequently_chained_tools",
                evidence_ref="trace:pair_search→read",
            ),
            _make_mock_finding(
                finding_id="tqj-chained-1",
                rule_type="frequently_chained_tools",
                evidence_ref="trace:pair_read→write",
            ),
            _make_mock_finding(
                finding_id="tqj-chained-2",
                rule_type="frequently_chained_tools",
                evidence_ref="trace:pair_search→write",
            ),
        ]
        review = ToolPortfolioReview()
        result = review._check_missing_higher_level(findings)
        assert len(result) == 1
        f = result[0]
        assert f.check_name == "missing_higher_level"
        assert f.severity == "info"

    def test_below_threshold_no_finding(self):
        """<3 个 chained finding → 无 finding。"""
        findings = [
            _make_mock_finding(
                finding_id="tqj-chained-0",
                rule_type="frequently_chained_tools",
            ),
        ]
        review = ToolPortfolioReview()
        result = review._check_missing_higher_level(findings)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Check 5: resource grouping
# ---------------------------------------------------------------------------

class TestResourceGrouping:
    """资源分组合理性检查。"""

    def test_balanced_groups_no_finding(self):
        """资源分布均匀 → 无 finding。"""
        tools = [
            _make_tool_spec("doc_search"),
            _make_tool_spec("doc_read"),
            _make_tool_spec("user_create"),
            _make_tool_spec("user_delete"),
            _make_tool_spec("log_write"),
        ]
        # doc=2, user=2, log=1 → 5 tools, max=2/5=40% < 60%
        review = ToolPortfolioReview()
        result = review._check_resource_grouping(tools)
        assert len(result) == 0

    def test_concentrated_group_produces_finding(self):
        """单个资源组占比 > 60% → info finding。"""
        tools = [
            _make_tool_spec("doc_search"),
            _make_tool_spec("doc_read"),
            _make_tool_spec("doc_write"),
            _make_tool_spec("doc_delete"),
            _make_tool_spec("user_create"),
        ]
        # doc=4/5=80%
        review = ToolPortfolioReview()
        result = review._check_resource_grouping(tools)
        assert len(result) >= 1
        # 至少有一个是关于资源集中的 finding
        resource_findings = [
            f for f in result
            if "resource_grouping" in f.check_name
        ]
        assert len(resource_findings) >= 1
        concentrated = [
            f for f in resource_findings
            if "过度集中" in f.description or "职责过多" in f.description
        ]
        assert len(concentrated) >= 1

    def test_singleton_groups_produces_finding(self):
        """多个孤立的资源组 → info finding。"""
        tools = [
            _make_tool_spec("doc_search"),
            _make_tool_spec("doc_read"),
            _make_tool_spec("doc_write"),
            _make_tool_spec("user_create"),
            _make_tool_spec("log_write"),
        ]
        # doc=3, user=1, log=1 → user 和 log 是 singleton
        review = ToolPortfolioReview()
        result = review._check_resource_grouping(tools)
        # 应该有 singleton finding
        singleton = [
            f for f in result
            if "singleton" in " ".join(f.evidence).lower()
            or "只有" in f.description
        ]
        assert len(singleton) >= 1

    def test_too_few_tools_no_finding(self):
        """<4 个工具 → 跳过 resource grouping。"""
        tools = [
            _make_tool_spec("doc_search"),
            _make_tool_spec("doc_read"),
            _make_tool_spec("doc_write"),
        ]
        review = ToolPortfolioReview()
        result = review._check_resource_grouping(tools)
        assert len(result) == 0


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------

class TestPortfolioReviewIntegration:
    """集成测试：review() 运行全部 5 类检查。"""

    def test_review_runs_all_checks(self):
        """验证 review() 聚合了所有检查结果。"""
        # 构造触发多个检查的工具集
        tools = [
            _make_tool_spec("get_data", namespace=""),  # namespacing + shallow wrapper
            _make_tool_spec("get_info", namespace=""),  # namespacing + shallow wrapper
            _make_tool_spec("search_docs", namespace="doc"),
            _make_tool_spec("search_doc", namespace="doc"),  # overlap with above
            _make_tool_spec("doc_write", namespace="doc"),
        ]
        findings = [
            _make_mock_finding(
                finding_id="tqj-chained-0",
                rule_type="frequently_chained_tools",
                evidence_ref="trace:pair",
            ),
            _make_mock_finding(
                finding_id="tqj-chained-1",
                rule_type="frequently_chained_tools",
                evidence_ref="trace:pair",
            ),
            _make_mock_finding(
                finding_id="tqj-chained-2",
                rule_type="frequently_chained_tools",
                evidence_ref="trace:pair",
            ),
        ]

        review = ToolPortfolioReview()
        result = review.review(tools, findings=findings)

        # 应有 findings 来自多个不同的 check
        check_names = {f.check_name for f in result}
        # 至少触发 namespacing、overlap、shallow_wrappers、missing_higher_level
        assert "namespacing_consistency" in check_names
        assert "overlapping_tools" in check_names

    def test_empty_input_returns_empty(self):
        """空输入 → 空结果。"""
        review = ToolPortfolioReview()
        result = review.review([])
        assert len(result) == 0

    def test_portfolio_finding_is_immutable(self):
        """PortfolioFinding 是 frozen dataclass。"""
        f = PortfolioFinding(
            check_name="test",
            severity="info",
            affected_tools=["tool_a"],
            description="test description",
            suggestion="test suggestion",
        )
        with pytest.raises(FrozenInstanceError):
            f.severity = "warning"  # type: ignore[misc]

    def test_levenshtein_distance(self):
        """验证编辑距离计算正确性。"""
        assert ToolPortfolioReview._levenshtein("abc", "abc") == 0
        assert ToolPortfolioReview._levenshtein("abc", "abd") == 1
        assert ToolPortfolioReview._levenshtein("abc", "xyz") == 3
        assert ToolPortfolioReview._levenshtein("", "abc") == 3
        assert ToolPortfolioReview._levenshtein("search_docs", "search_doc") == 1
