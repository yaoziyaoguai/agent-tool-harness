"""Tool Portfolio Review —— 5 类工具组合结构检查。

所有检查 deterministic、零网络依赖、不修改 ToolSpec。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agent_tool_harness.config.tool_spec import ToolSpec


@dataclass(frozen=True)
class PortfolioFinding:
    """工具组合级发现 —— 跨工具的架构性问题。

    架构边界：
    - **负责**：描述跨工具的结构性问题及改进方向。
    - **不负责**：不修改 tool spec、不判断单个工具质量（那是 inspectors 的事）。
    """

    check_name: str  # namespacing_consistency | overlapping_tools | ...
    severity: str  # warning | info
    affected_tools: list[str]  # 受影响的工具 qualified_name
    description: str  # 人类可读描述
    suggestion: str  # 改进建议
    evidence: list[str] = field(default_factory=list)


class ToolPortfolioReview:
    """工具组合级别设计评审。

    5 类检查（RFC Decision 2）：
    1. namespacing_consistency — 命名空间一致性（静态）
    2. overlapping_tools — 工具重叠（静态）
    3. shallow_wrappers — 浅层包装（静态）
    4. missing_higher_level — 缺失高层工具（信号聚合）
    5. resource_grouping — 资源分组合理性（静态）
    """

    # ------------------------------------------------------------------
    # 配置常量
    # ------------------------------------------------------------------

    # namespacing: 不含点号的工具比例超过此阈值时告警
    _NAMESPACING_THRESHOLD: float = 0.30

    # overlap: 名称编辑距离阈值
    _OVERLAP_EDIT_DISTANCE_MAX: int = 2
    _OVERLAP_DESC_SIMILARITY_MIN: float = 0.25

    # 浅层包装检测：CRUD 前缀集合
    _CRUD_PREFIXES: tuple[str, ...] = (
        "get_", "set_", "create_", "delete_",
        "update_", "list_", "add_", "remove_",
    )

    # 常见停用词，用于领域词汇提取
    _STOPWORDS: frozenset[str] = frozenset({
        "the", "a", "an", "is", "are", "was", "were", "be", "been",
        "being", "have", "has", "had", "do", "does", "did", "will",
        "would", "could", "should", "may", "might", "can", "shall",
        "to", "of", "in", "for", "on", "with", "at", "by", "from",
        "as", "into", "through", "during", "before", "after",
        "above", "below", "between", "under", "again", "further",
        "then", "once", "here", "there", "when", "where", "why",
        "how", "all", "both", "each", "few", "more", "most", "other",
        "some", "such", "no", "nor", "not", "only", "own", "same",
        "so", "than", "too", "very", "and", "but", "or", "if",
        "that", "this", "it", "its", "use", "used", "using",
        "tool", "tools", "first", "second", "also", "get", "set",
    })

    # missing_higher_level: frequently_chained 最少出现次数
    _CHAINED_MIN_OCCURRENCES: int = 3

    # resource_grouping: 单组占比超过此值视为失衡
    _GROUP_IMBALANCE_RATIO: float = 0.60

    # ------------------------------------------------------------------
    # 公共接口
    # ------------------------------------------------------------------

    def review(
        self,
        tool_specs: list[ToolSpec],
        findings: list | None = None,
        task_outcomes: list | None = None,
        transcript_signals: list | None = None,
    ) -> list[PortfolioFinding]:
        """运行全部 5 类检查。

        Args:
            tool_specs: 工具规格列表（必须）
            findings: v3.1-v3.5 累积 findings（可选，用于 missing_higher_level）
            task_outcomes: v3.2 TaskOutcome 列表（预留，P2 扩展）
            transcript_signals: v3.5 transcript analysis signals（预留，P2 扩展）

        Returns:
            PortfolioFinding 列表，可能为空
        """
        results: list[PortfolioFinding] = []
        results.extend(self._check_namespacing(tool_specs))
        results.extend(self._check_overlap(tool_specs))
        results.extend(self._check_shallow_wrappers(tool_specs))
        results.extend(self._check_missing_higher_level(findings or []))
        results.extend(self._check_resource_grouping(tool_specs))
        return results

    # ------------------------------------------------------------------
    # Check 1: namespacing consistency
    # ------------------------------------------------------------------

    def _check_namespacing(
        self, tool_specs: list[ToolSpec],
    ) -> list[PortfolioFinding]:
        """检查命名空间一致性。

        统计 qualified_name 中不含 '.' 的工具比例。
        比例 > 30% 时产生 warning。
        qualified_name 来自 ToolSpec.namespace + '.' + ToolSpec.name，
        如果 namespace 为空则 qualified_name = name（不含点号）。
        """
        if not tool_specs:
            return []

        non_namespaced = [
            ts for ts in tool_specs
            if "." not in ts.qualified_name
        ]
        ratio = len(non_namespaced) / len(tool_specs)

        if ratio > self._NAMESPACING_THRESHOLD:
            return [PortfolioFinding(
                check_name="namespacing_consistency",
                severity="warning",
                affected_tools=[ts.qualified_name for ts in non_namespaced],
                description=(
                    f"{len(non_namespaced)}/{len(tool_specs)} 个工具 "
                    f"({ratio:.0%}) 未遵循 'namespace.name' 命名格式"
                ),
                suggestion=(
                    "为每个工具添加 namespace 前缀，"
                    "如 'doc_search'、'doc_read'，"
                    "帮助 Agent 按功能域理解和选择工具"
                ),
                evidence=[
                    f"ToolSpec.qualified_name={ts.qualified_name}"
                    for ts in non_namespaced[:5]
                ],
            )]
        return []

    # ------------------------------------------------------------------
    # Check 2: overlapping tools
    # ------------------------------------------------------------------

    @staticmethod
    def _levenshtein(s1: str, s2: str) -> int:
        """计算两个字符串的 Levenshtein 编辑距离。"""
        if len(s1) < len(s2):
            return ToolPortfolioReview._levenshtein(s2, s1)
        if len(s2) == 0:
            return len(s1)
        prev = list(range(len(s2) + 1))
        for i, c1 in enumerate(s1):
            curr = [i + 1]
            for j, c2 in enumerate(s2):
                sub_cost = 0 if c1 == c2 else 1
                curr.append(min(
                    curr[j] + 1,
                    prev[j + 1] + 1,
                    prev[j] + sub_cost,
                ))
            prev = curr
        return prev[-1]

    @staticmethod
    def _desc_jaccard(desc1: str, desc2: str) -> float:
        """计算两个 description 的去停用词后 Jaccard 相似度。"""
        words1 = set(desc1.lower().split()) - ToolPortfolioReview._STOPWORDS
        words2 = set(desc2.lower().split()) - ToolPortfolioReview._STOPWORDS
        if not words1 or not words2:
            return 0.0
        return len(words1 & words2) / len(words1 | words2)

    def _check_overlap(
        self, tool_specs: list[ToolSpec],
    ) -> list[PortfolioFinding]:
        """检测名称或描述高度相似的工具对。

        名称编辑距离 ≤ 2 且描述 Jaccard 相似度 ≥ 阈值时标记。
        """
        results: list[PortfolioFinding] = []
        n = len(tool_specs)

        for i in range(n):
            for j in range(i + 1, n):
                a, b = tool_specs[i], tool_specs[j]
                name_dist = self._levenshtein(a.name, b.name)
                if name_dist > self._OVERLAP_EDIT_DISTANCE_MAX:
                    continue

                desc_sim = self._desc_jaccard(a.description, b.description)
                if desc_sim < self._OVERLAP_DESC_SIMILARITY_MIN:
                    continue

                results.append(PortfolioFinding(
                    check_name="overlapping_tools",
                    severity="warning",
                    affected_tools=[a.qualified_name, b.qualified_name],
                    description=(
                        f"'{a.name}' 与 '{b.name}' 名称编辑距离为 {name_dist}，"
                        f"描述相似度 {desc_sim:.0%}，可能存在功能重叠"
                    ),
                    suggestion=(
                        f"合并 '{a.name}' 和 '{b.name}'，"
                        "或在各自的 description 中明确区分使用场景"
                    ),
                    evidence=[
                        f"ToolSpec.name='{a.name}' vs '{b.name}'",
                        f"edit_distance={name_dist}",
                        f"desc_jaccard={desc_sim:.2f}",
                    ],
                ))

        return results

    # ------------------------------------------------------------------
    # Check 3: shallow wrappers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_domain_words(description: str) -> set[str]:
        """从 description 中提取领域词汇（去停用词后）。"""
        return set(description.lower().split()) - ToolPortfolioReview._STOPWORDS

    def _check_shallow_wrappers(
        self, tool_specs: list[ToolSpec],
    ) -> list[PortfolioFinding]:
        """检测浅层包装工具。

        工具名以 CRUD 前缀开头，且 description 缺乏领域特定词汇（< 3 个）。
        """
        results: list[PortfolioFinding] = []

        for ts in tool_specs:
            matched_prefix = None
            for prefix in self._CRUD_PREFIXES:
                if ts.name.startswith(prefix):
                    matched_prefix = prefix
                    break

            if matched_prefix is None:
                continue

            domain_words = self._extract_domain_words(ts.description)

            if len(domain_words) < 3:
                results.append(PortfolioFinding(
                    check_name="shallow_wrappers",
                    severity="info",
                    affected_tools=[ts.qualified_name],
                    description=(
                        f"'{ts.name}' 疑似浅层包装：名称以 '{matched_prefix}' 开头，"
                        "description 缺乏领域特定词汇"
                    ),
                    suggestion=(
                        f"在 description 中说明 '{ts.name}' 操作的领域对象、"
                        "业务语义和适用场景，或考虑合并到更高级别的领域工具中"
                    ),
                    evidence=[
                        f"ToolSpec.name='{ts.name}'",
                        f"crud_prefix='{matched_prefix}'",
                        f"domain_word_count={len(domain_words)}",
                    ],
                ))

        return results

    # ------------------------------------------------------------------
    # Check 4: missing higher-level tool
    # ------------------------------------------------------------------

    def _check_missing_higher_level(
        self, findings: list,
    ) -> list[PortfolioFinding]:
        """从 findings 中检测 frequently_chained_tools 信号。

        扫描 finding_id 或 rule_type 含 'chained' 的 finding，
        累计 ≥3 次时建议创建高层 workflow 工具。
        """
        chained_count = 0
        evidence_refs: list[str] = []

        for f in findings:
            fid = getattr(f, "finding_id", "")
            rule_type = getattr(f, "rule_type", "")
            if "chained" in fid.lower() or "chained" in rule_type.lower():
                chained_count += 1
                ev_ref = getattr(f, "evidence_ref", "")
                if ev_ref:
                    evidence_refs.append(ev_ref)

        if chained_count < self._CHAINED_MIN_OCCURRENCES:
            return []

        return [PortfolioFinding(
            check_name="missing_higher_level",
            severity="info",
            affected_tools=[],
            description=(
                f"发现 {chained_count} 次工具链式调用信号，"
                "某些工具对被频繁连续调用，可能需要合并为更高层工具"
            ),
            suggestion=(
                "考虑将被频繁链式调用的工具对封装为一个 workflow 工具，"
                "减少 Agent 的调用步数和上下文消耗"
            ),
            evidence=evidence_refs[:5] if evidence_refs else [
                f"finding_count_with_chained_signal={chained_count}",
            ],
        )]

    # ------------------------------------------------------------------
    # Check 5: resource grouping
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_resource(tool_name: str) -> str:
        """从工具名提取 resource 分组 key。

        例如 'doc_search' → 'doc', 'user_profile_lookup' → 'user'
        """
        normalized = tool_name.replace(".", "_")
        parts = normalized.split("_")
        return parts[0] if parts else tool_name

    def _check_resource_grouping(
        self, tool_specs: list[ToolSpec],
    ) -> list[PortfolioFinding]:
        """检查工具按 resource 分组的分布合理性。

        检测两个问题：
        - 某个 resource 组占比过高（> 60%），提示 god-tool 风险
        - 存在孤立的 resource 组（仅 1 个工具），提示功能域不完整
        """
        if len(tool_specs) < 4:
            return []

        groups: dict[str, list[str]] = {}
        for ts in tool_specs:
            resource = self._extract_resource(ts.name)
            groups.setdefault(resource, []).append(ts.qualified_name)

        total = len(tool_specs)
        results: list[PortfolioFinding] = []

        # 检测资源过度集中
        max_resource = max(groups, key=lambda k: len(groups[k]))
        max_ratio = len(groups[max_resource]) / total

        if max_ratio > self._GROUP_IMBALANCE_RATIO:
            tool_list = groups[max_resource]
            results.append(PortfolioFinding(
                check_name="resource_grouping",
                severity="info",
                affected_tools=tool_list,
                description=(
                    f"resource '{max_resource}' 组包含 {len(tool_list)}/{total} "
                    f"({max_ratio:.0%}) 的工具，可能存在职责过度集中"
                ),
                suggestion=(
                    f"检查 '{max_resource}' 组是否承担了过多职责，"
                    "考虑按子资源或操作类型拆分"
                ),
                evidence=[
                    f"resource='{max_resource}'",
                    f"tool_count={len(tool_list)}",
                    f"total_tools={total}",
                ],
            ))

        # 检测孤立的 resource 组
        singleton_groups = [
            (res, names)
            for res, names in groups.items()
            if len(names) == 1
        ]
        if len(singleton_groups) >= 2 and len(groups) >= 3:
            affected = [names[0] for _, names in singleton_groups]
            results.append(PortfolioFinding(
                check_name="resource_grouping",
                severity="info",
                affected_tools=affected,
                description=(
                    f"{len(singleton_groups)} 个 resource 组各只有 1 个工具 "
                    f"({', '.join(r for r, _ in singleton_groups)})，"
                    "可能需要补充相关工具或合并资源组"
                ),
                suggestion=(
                    "检查这些孤立工具是否属于某个已有资源组，"
                    "或是否需要补充同组工具以形成完整的功能域"
                ),
                evidence=[
                    f"singleton_resources={[r for r, _ in singleton_groups]}",
                ],
            ))

        return results
