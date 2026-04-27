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

    # ROADMAP 治理断言（原则级，不锁字面阶段名）：
    # 历史上这里钉的是 ``"第二阶段强化"`` / ``"本轮和第二阶段均不实现"`` /
    # ``"test_tool_design_audit_decoy_xfail"`` 这些字面措辞，等于把"v0.1 临时
    # 阶段名"写进了治理硬约束。当 ROADMAP 升级阶段命名（例如改用 v0.1 / v0.2 /
    # v0.3 / v1.0）时，这条测试就成了阻碍真实重构的补丁——这是把"测试为发现真实
    # bug"原则用错地方的典型例子。本轮升级为只钉以下原则：
    #   1. ROADMAP 必须明确划分**阶段**（不允许"啥都做"的无边界范围）；
    #   2. ROADMAP 必须显式披露**非目标 / 暂不做**（防止能力悄悄外溢）；
    #   3. ROADMAP 必须披露 signal_quality + tautological_replay（与 MockReplayAdapter
    #      的 SIGNAL_QUALITY 标签同步，让用户知道当前 PASS 不代表真实能力）；
    #   4. ROADMAP 必须保留 xfail 纪律段，且明确"不允许用 xfail 掩盖当前阶段
    #      应该满足的需求"。
    # 字面阶段名（v0.1 / v0.2 / 第八阶段 / 候选 A 等）允许随版本调整，但**原则
    # 不允许被拿掉**。
    roadmap_lower = roadmap.lower()
    assert any(stage in roadmap for stage in ("v0.1", "v0.2", "v1.0", "阶段")), (
        "ROADMAP 必须明确划分阶段（v0.x 或同义阶段命名），不允许无边界范围。"
    )
    assert "非目标" in roadmap or "暂不做" in roadmap, (
        "ROADMAP 必须显式披露非目标 / 暂不做范围，防止能力悄悄外溢。"
    )
    assert "signal_quality" in roadmap_lower, (
        "ROADMAP 必须披露 signal_quality 等级与升级路径。"
    )
    assert "tautological_replay" in roadmap_lower, (
        "ROADMAP 必须显式声明 MockReplayAdapter 的 tautological_replay 信号等级。"
    )
    assert "xfail" in roadmap_lower, (
        "ROADMAP 必须保留 xfail 纪律段，避免用 xfail 掩盖当前阶段应做的工作。"
    )
    assert "掩盖" in roadmap or "假装" in roadmap or "不能用 xfail" in roadmap, (
        "ROADMAP 必须明文说明 xfail 不允许用来掩盖应做的工作。"
    )

    assert "改测试前的判断顺序" in testing
    assert "xfail 模板" in testing
    assert "Artifact 完整性门槛" in testing
    assert "不能把失败测试改成" in testing
    assert "signal_quality 测试纪律" in testing

    assert "当前阶段边界" in readme
    assert "不接真实模型" in readme
    assert "signal_quality" in readme
    assert "tautological_replay" in readme
    assert "structural" in readme


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
