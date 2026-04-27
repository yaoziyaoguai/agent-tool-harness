from __future__ import annotations

import re
from typing import Any

from agent_tool_harness.config.project_spec import ProjectSpec
from agent_tool_harness.config.tool_spec import ToolSpec


class FromToolsGenerator:
    """从 tools.yaml 生成 eval candidate。

    架构边界：
    - 只根据工具契约生成“可能值得测”的用户任务候选。
    - 不把候选直接写进正式 evals.yaml。
    - 不生成“请调用某某工具”的作弊题；工具名只出现在 expected_tool_behavior。

    候选审核流程（P1，与 docs/ROADMAP.md 同步）：
    - 所有候选默认 ``review_status="candidate"``，必须经过人工 review 才能转正。
    - ``review_notes`` 解释为什么仍是候选，例如缺 fixture / 缺 root cause / prompt 需润色。
    - ``difficulty`` 把 ``complexity`` 映射成读者一眼能看懂的等级，便于审核分流。
    - 候选转正流程：candidate -> 手工补 fixture/initial_context/expected_root_cause ->
      audit-evals 跑过 -> 合并进正式 evals.yaml。详见 README 与 docs/ARTIFACTS.md。

    扩展点（仅 ROADMAP）：
    - 后续可结合真实 transcript、incident 或项目测试 fixture 生成更强上下文。
    - 后续可加交互式 reviewer，但本轮坚决不做。
    """

    def generate(self, project: ProjectSpec, tools: list[ToolSpec]) -> list[dict[str, Any]]:
        candidates = []
        for index, tool in enumerate(tools, start=1):
            hint = dict(tool.metadata.get("eval_generation", {}))
            prompt = hint.get("user_prompt") or self._prompt_from_tool(project, tool)
            prompt = self._remove_tool_name(prompt, tool)
            missing_context = []
            if not hint.get("fixture"):
                missing_context.append("fixture")
            if not hint.get("expected_root_cause"):
                missing_context.append("expected_root_cause")
            runnable = not missing_context
            required_tools = hint.get("required_tools") or [tool.name]
            complexity = hint.get("complexity", "multi_step")
            candidate = {
                "id": hint.get("id", f"candidate_from_tool_{index:03d}_{tool.name}"),
                "name": hint.get("name", f"Candidate from {tool.namespace}.{tool.name}"),
                "category": hint.get("category", "tool_contract_candidate"),
                "split": "training",
                "realism_level": "synthetic_realistic",
                "complexity": complexity,
                "source": "generated_from_tools",
                "user_prompt": prompt,
                "initial_context": hint.get("fixture", {}),
                "verifiable_outcome": {
                    "expected_root_cause": hint.get("expected_root_cause", ""),
                    "evidence": hint.get("evidence", []),
                },
                "success_criteria": hint.get(
                    "success_criteria",
                    [
                        "结论必须引用工具返回的 evidence。",
                        "不能在没有证据前修改用户系统状态。",
                    ],
                ),
                "expected_tool_behavior": {
                    "required_tools": required_tools,
                    "notes": "候选只要求关键证据工具，不强制唯一调用路径。",
                },
                "judge": {
                    "rules": [
                        {"type": "must_call_tool", "tool": required_tools[0]},
                        {"type": "must_use_evidence"},
                    ]
                },
                "runnable": runnable,
                "missing_context": missing_context,
                "difficulty": self._difficulty(complexity),
                "review_status": "candidate",
                "review_notes": self._review_notes(missing_context, prompt),
            }
            candidates.append(candidate)
        return candidates

    def _difficulty(self, complexity: str) -> str:
        """把 complexity 映射成审核分流用的 difficulty 等级。

        Anthropic 文章强调 evaluation 必须真实、多步；这里把 complexity 映射成更容易
        被审核者扫读的 trivial / single_step / multi_step / unknown 四档，便于 review
        时优先合并 multi_step 候选、过滤 trivial 候选。
        """

        normalized = (complexity or "").lower().strip()
        if normalized in {"multi_step", "multi-step", "multistep"}:
            return "multi_step"
        if normalized in {"single_step", "single-step", "singlestep"}:
            return "single_step"
        if normalized == "trivial":
            return "trivial"
        return "unknown"

    def _review_notes(self, missing_context: list[str], prompt: str) -> list[str]:
        """生成候选审核 checklist。

        所有候选都至少带一条“人工核对 prompt 是否真实”的提醒；缺 fixture / 缺
        expected_root_cause 时分别追加；prompt 过短时再加一条。审核者拿到候选后
        可按 checklist 逐项判断是否转正。
        """

        notes: list[str] = []
        if "fixture" in missing_context:
            notes.append(
                "需要补 initial_context/fixture：当前候选没有真实用户上下文，无法运行。"
            )
        if "expected_root_cause" in missing_context:
            notes.append(
                "需要补 expected_root_cause：缺少可被 RuleJudge 验证的真实根因。"
            )
        notes.append(
            "需要人工核对 user_prompt 的真实性，确认它来自真实用户问题而非工具描述改写。"
        )
        if len(prompt) < 40:
            notes.append("user_prompt 偏短，可能缺少必要业务背景，请人工补充。")
        return notes

    def _prompt_from_tool(self, project: ProjectSpec, tool: ToolSpec) -> str:
        domain = project.domain or "这个系统"
        intent = tool.when_to_use or tool.description
        intent = re.sub(r"\s+", " ", intent).strip(" .。")
        if not intent:
            intent = "定位一次用户报告的问题"
        return (
            f"线上 {domain} 出现一个需要复盘的异常。请根据已有上下文定位最可能的根因，"
            f"说明你依赖的证据，并给出下一步处理建议。场景线索：{intent}"
        )

    def _remove_tool_name(self, prompt: str, tool: ToolSpec) -> str:
        cleaned = prompt.replace(tool.name, "相关诊断能力")
        if tool.namespace:
            cleaned = cleaned.replace(f"{tool.namespace}.{tool.name}", "相关诊断能力")
        return cleaned
