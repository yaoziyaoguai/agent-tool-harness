from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_tool_harness.config.project_spec import ProjectSpec
from agent_tool_harness.config.tool_spec import ToolSpec
from agent_tool_harness.eval_generation.from_tests import FromTestsGenerator
from agent_tool_harness.eval_generation.from_tools import FromToolsGenerator


class EvalGenerator:
    """统一的 eval candidate 生成门面。

    架构边界：
    - 负责根据 source 分发到 from_tools 或 from_tests。
    - 不做质量审计，不写正式 evals.yaml。
    - 所有生成结果都保留 runnable/missing_context，方便后续 audit 和人工转正。
    """

    def from_tools(self, project: ProjectSpec, tools: list[ToolSpec]) -> list[dict[str, Any]]:
        return FromToolsGenerator().generate(project, tools)

    def from_tests(self, tests_path: str | Path) -> list[dict[str, Any]]:
        return FromTestsGenerator().generate(tests_path)
