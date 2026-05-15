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


def test_docs_preserve_core_invariants():
    """核心文档必须保留关键边界声明，防止重写时悄悄删掉。"""

    readme = Path("README.md").read_text(encoding="utf-8")
    harness_model = Path("docs/architecture/HEADLESS_HARNESS_MODEL.md").read_text(encoding="utf-8")
    current_impl = Path("docs/CURRENT_IMPLEMENTATION.md").read_text(encoding="utf-8")
    roadmap = Path("docs/ROADMAP.md").read_text(encoding="utf-8")
    boundary = Path("docs/architecture/DEMO_CORE_REAL_BOUNDARY.md").read_text(encoding="utf-8")

    # DEMO_CORE_REAL_BOUNDARY 必须定义核心边界
    assert "One Core Flow" in boundary
    assert "Forbidden dependencies" in boundary or "禁止" in boundary
    assert "What belongs to Core" in boundary or "Core 负责" in boundary
    assert "What belongs to Demo" in boundary or "Demo 负责" in boundary
    assert "Real Integration" in boundary

    # HEADLESS_HARNESS_MODEL 必须保留架构边界
    assert "架构边界" in harness_model
    assert "rule checks ≠ LLM judge" in harness_model or "rule checks" in harness_model.lower()
    assert "mock replay ≠ RealAgentAdapter" in harness_model or "MockReplayAdapter" in harness_model
    assert "reporter ≠ decision maker" in harness_model or "reporter" in harness_model.lower()

    # CURRENT_IMPLEMENTATION 必须诚实声明限制
    assert "当前不支持" in current_impl or "not supported" in current_impl.lower()
    assert "signal_quality" in current_impl.lower() or "tautological_replay" in current_impl.lower()
    assert "Core candidate" in current_impl
    assert "Demo-only" in current_impl

    # ROADMAP 必须明确阶段与边界
    assert "设计原则" in roadmap
    assert "明确不做" in roadmap or "暂不做" in roadmap
    assert "Track A" in roadmap or "Track B" in roadmap

    # README 必须声明能力边界
    assert any(phrase in readme for phrase in [
        "What does not work yet",
        "What it does not do",
        "不支持",
    ]), "README must declare limitations"
    assert "signal_quality" in readme.lower()
    assert "tautological_replay" in readme.lower()


def test_readme_demonstrates_full_flow():
    """README 必须演示 trace import + generate-evals/promote-evals + mock-path good/bad。"""

    readme = Path("README.md").read_text(encoding="utf-8")

    # v3.0.0: trace import 为主路径，README 必须展示
    assert "import_trace_as_evidence" in readme, (
        "README 必须演示 import_trace_as_evidence 作为 primary quickstart。"
    )
    assert "TraceImportAdapter" in readme or "trace_import" in readme, (
        "README 必须引用 trace import 机制。"
    )

    # eval lifecycle 仍须可见
    assert "generate-evals" in readme, (
        "README 必须提及 generate-evals，否则新用户看不到候选 eval 流程。"
    )
    assert "promote-evals" in readme, (
        "README 必须提及 promote-evals，否则新用户不知道候选→正式怎么走。"
    )
    assert "--mock-path good" in readme, "README 至少演示一次 --mock-path good。"
    assert "--mock-path bad" in readme, (
        "README 至少演示一次 --mock-path bad；只跑 good 看不出 judge 是否退化。"
    )

    # README 命令风格必须统一使用 python -m，不允许 .venv/bin/python
    cli_lines = [
        line for line in readme.splitlines()
        if "agent_tool_harness.cli" in line and not line.lstrip().startswith(("#", ">"))
    ]
    assert cli_lines, "README 必须包含至少一条 CLI 调用示例。"
    venv_lines = [ln for ln in cli_lines if ".venv/bin/python" in ln]
    assert not venv_lines, (
        f"README 不允许出现 .venv/bin/python 硬编码路径：{venv_lines[:2]}"
    )


def test_current_phase_does_not_implement_out_of_scope_components():
    """第二阶段只做治理强化，不能悄悄落地真实 adapter/executor/UI。

    Phase 4 明确允许的文件（openai_transport.py / anthropic_transport.py /
    llm_judge.py / judge_provider_factory.py）通过白名单放行。
    """

    phase4_allowed = {
        "agent_tool_harness/openai_transport.py",
        "agent_tool_harness/anthropic_transport.py",
        "agent_tool_harness/llm_judge.py",
        "agent_tool_harness/judge_provider_factory.py",
    }

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
        if str(path) in phase4_allowed:
            continue
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
