"""Core Evaluation —— Evidence → EvaluationResult 的编排层。

架构边界
--------
- **负责**：消费 Evidence（含 ExecutionTrace）和 EvalSpec，通过 RuleJudge 做确定性
  规则检查，可选消费 JudgeProvider 做 LLM 辅助评估，产出 Core Contract 的
  EvaluationResult（含 RuleFinding + 可选 JudgeFinding）。
- **不负责**：不实现 LLM judge、不生成 ReviewDecision、不读/写磁盘。
- **为什么存在**：旧 EvalRunner 内部混了 adapter 调用 + judge + diagnose + report，
  没有独立的"Evidence → EvaluationResult"步骤。本模块把这个步骤提取为独立函数，
  让 Core Flow 的每一步都可独立测试、独立替换。
- **为什么本轮不改 RuleJudge**：RuleJudge 是稳定的 deterministic baseline，签名
  ``judge(case: EvalSpec, run: AgentRunResult) -> JudgeResult`` 已被全量测试验证。
  改为接受 Core Contract 对象会增加不必要的迁移风险。本轮通过反向桥接
  ``execution_trace_to_agent_run_result`` 临时适配，后续轮次再让 RuleJudge 原生
  消费 Core Contract。

未来扩展点
----------
- 当 RuleJudge 原生支持 Core Contract 时，删除反向桥接调用
- 当前已支持可选 JudgeProvider（Phase 2：FakeJudgeProvider 接入）——
  CoreEvaluation 可并列调用 RuleJudge + JudgeProvider，产出
  RuleFinding + JudgeFinding 混合的 EvaluationResult
- 当 RealAgentAdapter 产出真实 ExecutionTrace 时，本模块无需任何修改即可消费
"""

from __future__ import annotations

from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.core_contract import EvaluationResult, Evidence, RuleFinding
from agent_tool_harness.demo_core_bridge import (
    execution_trace_to_agent_run_result,
    judge_result_to_evaluation_result,
)
from agent_tool_harness.fake_judge import CoreJudgeProvider
from agent_tool_harness.judges.rule_judge import RuleJudge
from agent_tool_harness.tool_inspection import ToolUseInspector

_SENTINEL = object()


class CoreEvaluation:
    """Evidence → EvaluationResult 的编排器。

    架构边界：
    - **负责**：把 Evidence 中的 ExecutionTrace 交给 RuleJudge 做确定性规则检查，
      可选消费 JudgeProvider 做辅助评估，产出 EvaluationResult（含 RuleFinding +
      可选 JudgeFinding 列表）。
    - **不负责**：不实现 LLM 语义判断、不生成 ReviewDecision、不读配置。
    - **EvaluationResult.passed 仍然只由 deterministic RuleJudge 决定**——
      JudgeFinding 是辅助信号，不改变 passed/failed 判定。

    使用方式：
        # 仅 RuleJudge（向后兼容）
        eval_result = CoreEvaluation().evaluate(evidence, eval_spec)

        # RuleJudge + FakeJudgeProvider（Phase 2）
        eval_result = CoreEvaluation(
            judge_provider=FakeJudgeProvider()
        ).evaluate(evidence, eval_spec)
        # eval_result.findings 同时包含 RuleFinding 和 JudgeFinding
    """

    def __init__(
        self,
        judge: RuleJudge | None = None,
        judge_provider: CoreJudgeProvider | None = None,
        inspector: ToolUseInspector | None = _SENTINEL,
    ):
        """初始化 CoreEvaluation。

        judge 参数允许注入（测试可注入 mock），默认使用 RuleJudge。
        judge_provider 可选——传入 CoreJudgeProvider 实现（如 FakeJudgeProvider）
        后，evaluate() 会将 JudgeFinding 追加到 EvaluationResult.findings 中。
        """
        self._judge = judge or RuleJudge()
        self._judge_provider = judge_provider
        self._inspector = ToolUseInspector() if inspector is _SENTINEL else inspector

    def evaluate(
        self, evidence: Evidence, eval_spec: EvalSpec
    ) -> EvaluationResult:
        """消费 Evidence，产出 EvaluationResult。

        内部流程：
        1. ExecutionTrace → AgentRunResult（反向桥接，供 RuleJudge 消费）
        2. RuleJudge.judge(eval_spec, agent_run_result) → JudgeResult
        3. JudgeResult → EvaluationResult（通过 demo_core_bridge）
        4. 如果配置了 judge_provider：
           a. 调用 judge_provider.evaluate(evidence) → list[JudgeFinding]
           b. 追加到 EvaluationResult.findings
           c. **不改变** RuleJudge 的 passed 判定

        EvaluationResult 不自动生成 ReviewDecision——人工 Reviewer 必须在查看
        所有 evidence 后显式创建 ReviewDecision。
        """
        # 反向桥接：ExecutionTrace → AgentRunResult
        agent_run_result = execution_trace_to_agent_run_result(evidence.trace)

        # trace-level 确定性不变量检查（ToolUseInspector）
        trace_findings: list[RuleFinding] = []
        if self._inspector is not None:
            trace_findings = self._inspector.inspect(evidence.trace)

        # 确定性规则检查
        judge_result = self._judge.judge(eval_spec, agent_run_result)

        # JudgeResult → EvaluationResult
        evaluation_result = judge_result_to_evaluation_result(judge_result)

        # 合并 trace-level RuleFinding 到 EvaluationResult
        evaluation_result.findings = list(trace_findings) + list(evaluation_result.findings)

        # 可选 LLM judge 辅助评估
        if self._judge_provider is not None:
            judge_findings = self._judge_provider.evaluate(evidence)
            evaluation_result.findings = list(evaluation_result.findings) + list(judge_findings)

        # 重算 passed：所有 deterministic RuleFinding 都通过才为 True
        # (JudgeFinding 不影响 passed)
        evaluation_result.passed = all(
            f.rule_passed
            for f in evaluation_result.findings
            if isinstance(f, RuleFinding)
        )

        return evaluation_result
