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

    扩展点：
    - 后续可结合真实 transcript、incident 或项目测试 fixture 生成更强上下文。
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
            candidate = {
                "id": hint.get("id", f"candidate_from_tool_{index:03d}_{tool.name}"),
                "name": hint.get("name", f"Candidate from {tool.namespace}.{tool.name}"),
                "category": hint.get("category", "tool_contract_candidate"),
                "split": "training",
                "realism_level": "synthetic_realistic",
                "complexity": hint.get("complexity", "multi_step"),
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
            }
            candidates.append(candidate)
        return candidates

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
