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


def test_onboarding_walkthrough_preserves_promotion_flow_and_anti_bypass():
    """ONBOARDING/README 必须把候选→accepted→promote 流程完整暴露给新用户，
    并且明文禁止用脚本批量绕过 review。

    背景（v0.1 blocking 2 走查发现的真实 onboarding bug）：
    - 旧 README 的"快速开始"只演示 audit-tools / audit-evals / run，**完全
      跳过 generate-evals + promote-evals**，新用户复制粘贴后会以为本框架只能
      审计现成 yaml + 跑 mock，严重低估能力，也不会触发候选→正式的人工 review；
    - 旧 ONBOARDING 只说"把 review_status 改为 accepted"但没说怎么改，新用户
      最容易选的捷径就是 ``sed -i 's/review_status: candidate/.../g'`` 一刀切，
      这等于让所有未审 candidate 静默转正——下游 promote-evals 看的是字段是否
      齐全，不是字段是否真实，无法替你拦住；
    - 旧 README "运行 good/bad replay" 只演示 good 一条，与 ONBOARDING "good
      全 PASS、bad 全 FAIL 才能证明 judge 没退化"自相矛盾，新用户就只跑 good
      看不出 judge 退化；
    - 旧 ONBOARDING 用 ``.venv/bin/python``、README 用 ``python -m``，新用户
      没建 ``.venv/`` 时按 ONBOARDING 抄会失败。

    本测试把上述四个真实 onboarding bug 钉死成原则级断言，**不允许后续重写
    时悄悄删掉**——任何"为了让文档更清爽"的删除都会让同一坑再次出现。
    """

    readme = Path("README.md").read_text(encoding="utf-8")
    onboarding = Path("docs/ONBOARDING.md").read_text(encoding="utf-8")

    # 1) README 快速开始必须把 generate-evals + promote-evals 端到端写出来。
    assert "generate-evals" in readme, (
        "README 快速开始必须演示 generate-evals，否则新用户看不到候选 eval 流程。"
    )
    assert "promote-evals" in readme, (
        "README 快速开始必须演示 promote-evals，否则新用户不知道候选→正式怎么走。"
    )

    # 2) README 必须同时演示 good 和 bad 两条 mock-path，否则 judge 退化测不出。
    assert readme.count("--mock-path good") >= 1, "README 至少演示一次 --mock-path good。"
    assert readme.count("--mock-path bad") >= 1, (
        "README 至少演示一次 --mock-path bad；只跑 good 看不出 judge 是否退化为同义复读。"
    )

    # 3) ONBOARDING 必须明文禁止用脚本批量把候选 status 改成 accepted。
    assert "如何把候选转成 accepted" in onboarding or "怎么改" in onboarding, (
        "ONBOARDING 必须给出'如何把 review_status 改成 accepted'的具体步骤，"
        "否则新用户最容易选的捷径就是 sed 批量替换。"
    )
    assert "不要写脚本批量" in onboarding or "sed" in onboarding, (
        "ONBOARDING 必须显式警告'不允许用脚本批量 sed 替换 review_status'，"
        "否则候选→正式的人工 review 这一层语义保障会被静默绕过。"
    )

    # 4) ONBOARDING 必须解释 --mock-path good/bad 的差异由 fixture 决定，
    #    避免新用户在自家 eval 上跑 bad 看到 PASS 时误判 CLI bug。
    assert "fixture" in onboarding and "mock-path" in onboarding, (
        "ONBOARDING 必须解释 --mock-path good/bad 的差异由 eval 自带 fixture 决定，"
        "否则新用户在自家 eval 跑 bad 看到 PASS 会误判为 CLI bug。"
    )

    # 5) ONBOARDING 命令风格必须与 README 一致；不允许混用 .venv/bin/python 与 python -m。
    onboarding_command_lines = [
        line for line in onboarding.splitlines()
        if "agent_tool_harness.cli" in line and not line.lstrip().startswith(("#", ">"))
    ]
    assert onboarding_command_lines, "ONBOARDING 必须包含至少一条 CLI 调用示例。"
    venv_python_lines = [ln for ln in onboarding_command_lines if ".venv/bin/python" in ln]
    assert not venv_python_lines, (
        "ONBOARDING 不允许出现 ``.venv/bin/python -m`` 这种硬编码解释器路径——"
        "新用户没建 .venv/ 会直接失败。请统一使用 ``python -m`` 并在文档开头"
        f"说明'假设已激活虚拟环境'。违规行：{venv_python_lines[:2]}"
    )


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
