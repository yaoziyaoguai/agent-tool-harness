import inspect
import re
from pathlib import Path

from agent_tool_harness.agents.agent_adapter_base import AgentAdapter
from agent_tool_harness.agents.mock_replay_adapter import MockReplayAdapter
from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor
from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.diagnose.transcript_analyzer import TranscriptAnalyzer
from agent_tool_harness.eval_generation.generator import EvalGenerator
from agent_tool_harness.judges.rule_judge import RuleJudge
from agent_tool_harness.recorder.run_recorder import RunRecorder
from agent_tool_harness.reports.markdown_report import MarkdownReport
from agent_tool_harness.runner.eval_runner import EvalRunner
from agent_tool_harness.tools.python_executor import PythonToolExecutor
from agent_tool_harness.tools.registry import ToolRegistry


def test_critical_classes_keep_chinese_learning_docstrings():
    """关键架构类必须保留中文学习型 docstring，避免后续只剩实现细节。"""

    critical_classes = [
        ToolDesignAuditor,
        EvalQualityAuditor,
        EvalGenerator,
        PythonToolExecutor,
        ToolRegistry,
        AgentAdapter,
        MockReplayAdapter,
        EvalRunner,
        RunRecorder,
        RuleJudge,
        TranscriptAnalyzer,
        MarkdownReport,
    ]

    for cls in critical_classes:
        doc = inspect.getdoc(cls) or ""
        assert "架构边界" in doc, f"{cls.__name__} docstring must explain architecture boundary"
        assert "不" in doc, f"{cls.__name__} docstring must state what it does not own"


def test_docs_preserve_evidence_first_and_testing_discipline():
    architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    testing = Path("docs/TESTING.md").read_text(encoding="utf-8")
    readme = Path("README.md").read_text(encoding="utf-8")

    assert "当前阶段非目标" in architecture
    assert "证据契约" in architecture
    assert "失败归因流程" in architecture
    assert "变更守卫" in architecture
    assert "不能替代 raw artifacts" in architecture

    assert "第二阶段强化" in roadmap
    assert "本轮和第二阶段均不实现" in roadmap
    assert "xfail 转正条件" in roadmap
    assert "当前没有 xfail 测试" in roadmap

    assert "改测试前的判断顺序" in testing
    assert "xfail 模板" in testing
    assert "Artifact 完整性门槛" in testing
    assert "不能把失败测试改成" in testing

    assert "当前阶段边界" in readme
    assert "不接真实模型" in readme


def test_current_phase_does_not_implement_out_of_scope_components():
    """第二阶段只做治理强化，不能悄悄落地真实 adapter/executor/UI。"""

    forbidden_path_patterns = [
        "openai",
        "anthropic",
        "mcp",
        "http_executor",
        "shell_executor",
        "web_ui",
    ]
    implementation_files = list(Path("agent_tool_harness").rglob("*.py"))

    for path in implementation_files:
        normalized = str(path).lower()
        for pattern in forbidden_path_patterns:
            assert pattern not in normalized, f"out-of-scope implementation file found: {path}"

    implementation_text = "\n".join(
        path.read_text(encoding="utf-8") for path in implementation_files
    )
    forbidden_classes = [
        r"class\s+OpenAI\w*Adapter",
        r"class\s+Anthropic\w*Adapter",
        r"class\s+MCP\w*Executor",
        r"class\s+Http\w*Executor",
        r"class\s+Shell\w*Executor",
    ]
    for pattern in forbidden_classes:
        assert not re.search(pattern, implementation_text), f"out-of-scope class found: {pattern}"
