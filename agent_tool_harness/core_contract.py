"""Agent2Harness Core Contract — Demo 和 Real 共享的运行时对象与接口定义。

这个模块定义了 Agent 工具使用评测链路中所有核心数据对象和 adapter 接口。
Demo runtime（MockReplayAdapter + RuleJudge）和未来 Real runtime（RealAgentAdapter +
LLM Judge）都使用同一套对象传递数据，确保 Core Flow 对两边一致。

架构边界
--------
- **负责**：定义 ToolCall、ToolResult、ExecutionTrace、Evidence、Finding、
  RuleFinding、EvaluationResult、ReportSummary、ReviewDecision 的数据结构，
  以及 Agent2HarnessAdapter 协议。
- **不负责**：不执行工具、不调用 Agent、不评判结果、不生成报告文本、不读配置。
- **为什么不能依赖 demo**：如果 ExecutionTrace 的类型定义里引用了 MockReplayAdapter
  的实现细节，真实 Agent 就无法产出相同的 trace，整个评测链路就必须分叉成
  "demo 评测"和"真实评测"两套 —— 这正是我们要避免的。
- **为什么不能依赖 real provider**：如果 Finding 里硬编码了 Anthropic/OpenAI 的
  错误码，换 provider 就要改 contract，contract 就不叫 contract 了。
- **为什么 ReviewDecision 必须由人工 Reviewer 显式创建，不能由 LLM judge 自动生成**：
  LLM judge 产出的是 JudgeFinding（机器评分），ReviewDecision 是人工 Reviewer
  在看完所有 evidence（含 RuleFinding + JudgeFinding + trace + cost）后的最终裁决。
  混淆两者会让"LLM 自评自审"看起来像人工审核，造成"机器既当裁判又当运动员"的
  治理漏洞。在 Agent 工具评测中，**最终是否接受评测结论必须由人决定**。

与已有类型的关系
----------------
- ``config/tool_spec.py::ToolSpec`` — 工具契约描述（已有，Core 层），本模块不重复定义
- ``config/eval_spec.py::EvalSpec`` — eval 配置对象（已有，Core 层），可通过
  ``EvalSpec`` 构造 ``ScenarioSpec``
- ``agents/agent_adapter_base.py::AgentAdapter`` — 当前 adapter Protocol（签名含
  ToolRegistry/RunRecorder），未来将适配本模块的 ``Agent2HarnessAdapter``
- ``judges/rule_judge.py::JudgeResult`` / ``RuleCheckResult`` — 当前 judge 输出，
  未来将通过 ``Finding`` / ``RuleFinding`` 适配

未来扩展点
----------
- ToolCall/ToolResult 可增加 latency_ms、token_usage 等观测字段
- ExecutionTrace 可增加 observations（agentic loop 中间步骤）
- Evidence 可增加 cost_breakdown、latency_breakdown
- 新增 JudgeFinding（LLM judge 产出），与 RuleFinding 并列
- Agent2HarnessAdapter 可扩展 lifecycle 方法（setup/teardown）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_tool_harness.signal_quality import UNKNOWN

# ---------------------------------------------------------------------------
# 运行时原子对象
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolCall:
    """一次工具调用。

    架构边界：
    - **负责**：记录哪个工具被调用、传了什么参数、调用 ID。
    - **不负责**：不执行工具、不记录返回结果（那是 ToolResult 的事）。
    - 这是 Core Contract 中最原子的运行时事实——Demo 和 Real 的 tool call
      在结构上完全一致，区别只在于 call 的来源（mock replay vs LLM 推理）。

    call_id 是串联 ToolCall ↔ ToolResult 的关键字段，必须唯一。
    """

    tool_name: str
    arguments: dict[str, Any]
    call_id: str
    timestamp: str | None = None  # ISO8601，可选


@dataclass(frozen=True)
class ToolResult:
    """一次工具返回。

    架构边界：
    - **负责**：记录工具调用结果（成功/失败、输出、错误信息）。
    - **不负责**：不解释输出含义、不判断结果好坏（那是 Judge 的事）。
    - 通过 call_id 与 ToolCall 一一对应。
    """

    call_id: str
    status: str  # "success" | "error"
    output: dict[str, Any]
    error: str | None = None


# ---------------------------------------------------------------------------
# 轨迹与证据
# ---------------------------------------------------------------------------


@dataclass
class ExecutionTrace:
    """一次 Agent 执行轨迹。

    架构边界：
    - **负责**：承载一次评测场景中 Agent 的完整工具调用链路。
    - **不负责**：不关心 trace 来自 mock replay 还是真实 LLM agentic loop。
      只要 tool_calls 和 tool_responses 的结构符合 ToolCall/ToolResult，
      下游 judge/diagnose/report 就能统一消费。
    - messages 字段承载 Agent 推理过程中的中间消息（可选），
      为未来 agentic loop step-by-step observation 预留。
    """

    scenario_id: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)
    final_answer: str = ""


@dataclass
class Evidence:
    """可用于评估和 Review 的证据包。

    架构边界：
    - **负责**：把一次 run 的所有证据（trace + artifacts + cost + latency +
      warnings）打包成一个自描述对象，供 judge 和 human reviewer 消费。
    - **不负责**：不评判证据是否充分、不计算评分。
    - cost_usd / latency_ms 当前可为 None——字段边界已定义，数据由真实 provider
      在 future round 填充。
    - signal_quality 来自 adapter 的自我披露，写入 evidence 后下游无需回查
      adapter 即可知道信号等级。
    """

    trace: ExecutionTrace
    artifacts: dict[str, Any] = field(default_factory=dict)
    cost_usd: float | None = None
    latency_ms: float | None = None
    warnings: list[str] = field(default_factory=list)
    signal_quality: str = UNKNOWN


# ---------------------------------------------------------------------------
# 评测发现
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Finding:
    """评测发现 —— RuleFinding 和 JudgeFinding 的共同基础。

    架构边界：
    - **负责**：表达一条可追溯的评测发现，包含严重程度、分类、消息和证据引用。
    - **不负责**：不做最终裁决（那是 ReviewDecision 的事）；不区分规则/LLM 来源
      （通过 category 字段和子类区分）。
    - evidence_ref 指向具体证据位置（如 ``transcript.jsonl#L42`` 或
      ``tool_calls.jsonl::call_id=c1``），让 reviewer 能回溯到原始数据。
    """

    finding_id: str
    severity: str  # "critical" | "high" | "medium" | "low" | "info"
    category: str  # "rule" | "judge" | "audit" | "signal"
    message: str
    evidence_ref: str


@dataclass(frozen=True)
class RuleFinding(Finding):
    """确定性规则产生的 finding。

    与 JudgeFinding（未来 LLM judge 产出）的关键区别：
    - RuleFinding 来自 deterministic 规则检查（如 must_call_tool），
      结果是确定性的、可复现的；
    - JudgeFinding 来自 LLM 语义判断，结果带有 confidence/rubric，
      本质是 advisory。
    - 两者在 EvaluationResult.findings 中并列存在，但来源标记不同，
      让 reviewer 能区分"规则铁定失败"和"LLM 认为可能有问题"。
    """

    rule_type: str = ""
    rule_passed: bool = False


# ---------------------------------------------------------------------------
# 评测结果与报告
# ---------------------------------------------------------------------------


@dataclass
class EvaluationResult:
    """一次场景的评测结果聚合。

    架构边界：
    - **负责**：聚合一条 scenario 的所有 findings，给出 passed/failed 判定。
    - **不负责**：**不**产生 ReviewDecision。ReviewDecision 必须由人工 Reviewer
      显式创建——EvaluationResult 只是机器评分汇总，不是最终裁决。
      这个边界是防止"LLM 自评自审"的关键设计。
    """

    scenario_id: str
    findings: list[Finding] = field(default_factory=list)
    passed: bool = False
    summary: str = ""


@dataclass(frozen=True)
class ReportSummary:
    """报告摘要 —— 不等同于最终 Review。

    架构边界：
    - **负责**：提供一次 run 的统计摘要（总数/通过/失败/信号质量）。
    - **不负责**：不做通过/失败的价值判断（那是 ReviewDecision 的事）。
    - 这是机器生成的统计视图，reviewer 用它来快速了解 run 的整体情况，
      但最终结论必须由人下。
    """

    total_scenarios: int = 0
    passed: int = 0
    failed: int = 0
    errors: int = 0
    signal_quality: str = UNKNOWN
    generated_at: str = ""


@dataclass(frozen=True)
class ReviewDecision:
    """人工 Review 结论。

    架构边界：
    - **负责**：承载人工 Reviewer 在看完所有 evidence（含 RuleFinding +
      JudgeFinding + trace + cost + report）后的最终裁决。
    - **不负责**：不由 LLM judge 自动生成；不由 EvaluationResult 自动派生。
    - 为什么必须由人创建：Agent 工具评测的最终受众是人（工具开发者、eval 设计者、
      质量 reviewer）。LLM judge 可以提供 scoring signal，但"这个工具设计是否
      可以接受"、"这个 eval 是否真实可用"——这些判断涉及产品判断、领域知识、
      成本权衡，不是 scoring 能替代的。
    """

    decision: str  # "approved" | "needs_revision" | "rejected"
    reviewer: str
    notes: str
    reviewed_at: str = ""


# ---------------------------------------------------------------------------
# Scenario —— 评测场景的纯数据描述
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScenarioSpec:
    """一次评测场景的纯数据描述。

    架构边界：
    - **负责**：描述"测什么"——场景 ID、目标、可用工具、成功标准。
    - **不负责**：不执行评测、不加载配置。这是比 config/eval_spec.py::EvalSpec
      更薄的纯数据视图——EvalSpec 可以从 YAML 构造后转成 ScenarioSpec 传给 adapter。
    - 为什么需要它：EvalSpec 与 YAML 加载/校验逻辑耦合（from_dict/to_dict），
      ScenarioSpec 是纯 contract 对象，不携带任何 IO 语义。
    """

    scenario_id: str
    goal: str
    available_tools: list[str] = field(default_factory=list)
    success_criteria: list[str] = field(default_factory=list)
    constraints: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent2Harness Adapter Protocol
# ---------------------------------------------------------------------------


class Agent2HarnessAdapter(Protocol):
    """Agent adapter 的 Core Contract 接口。

    架构边界：
    - **负责**：定义所有 adapter（mock / replay / real）对 Core 暴露的最小契约。
      输入 ScenarioSpec（纯数据），输出 ExecutionTrace（纯数据）。
    - **不负责**：不规定 adapter 内部如何产生 tool call——mock replay 回放 fixture，
      真实 LLM 调 API，transcript replay 读历史 JSONL。Core 不关心实现细节。
    - **为什么签名只有 ScenarioSpec → ExecutionTrace**：
      旧 AgentAdapter（agents/agent_adapter_base.py）的 run() 还接收
      ToolRegistry 和 RunRecorder，把 IO 和业务逻辑混在一起。新 Protocol 让
      adapter 成为纯数据转换：场景进，轨迹出。ToolRegistry 和 RunRecorder
      由 Harness 在 adapter 外部管理，adapter 通过 Harness 获取工具执行能力。
      这需要后续轮次重构 runner 和 adapter 的协作方式，本轮只定义接口。

    与已有 AgentAdapter 的关系：
    - 当前 agents/agent_adapter_base.py::AgentAdapter 是实际运行的 Protocol，
      其 run(case, registry, recorder) -> AgentRunResult 在 EvalRunner 中工作。
    - Agent2HarnessAdapter 是 target state——后续轮次会把 EvalRunner 逐步迁移
      到消费这个更干净的接口。
    - 本轮不要求 MockReplayAdapter 实现 Agent2HarnessAdapter。
    """

    SIGNAL_QUALITY: str

    def run(self, scenario: ScenarioSpec) -> ExecutionTrace:
        """执行一次评测场景，返回执行轨迹。

        adapter 实现者必须保证 SIGNAL_QUALITY 与实现方式一致：
        - MockReplayAdapter → tautological_replay
        - TranscriptReplayAdapter → recorded_trajectory
        - RealAgentAdapter（未来）→ real_agent
        """
        ...
