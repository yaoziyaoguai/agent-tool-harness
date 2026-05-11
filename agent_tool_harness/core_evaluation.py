"""Core Evaluation —— Evidence → EvaluationResult 的编排层。

架构边界
--------
- **负责**：消费 Evidence（含 ExecutionTrace）和 EvalSpec，通过 RuleJudge 做确定性
  规则检查，产出 Core Contract 的 EvaluationResult。
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
- 当 JudgeProvider（LLM judge）落地时，CoreEvaluation 可并列调用 RuleJudge +
  JudgeProvider，产出 RuleFinding + JudgeFinding 混合的 EvaluationResult
- 当 RealAgentAdapter 产出真实 ExecutionTrace 时，本模块无需任何修改即可消费
"""

from __future__ import annotations

from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.core_contract import EvaluationResult, Evidence
from agent_tool_harness.demo_core_bridge import (
    execution_trace_to_agent_run_result,
    judge_result_to_evaluation_result,
)
from agent_tool_harness.judges.rule_judge import RuleJudge


class CoreEvaluation:
    """Evidence → EvaluationResult 的编排器。

    架构边界：
    - **负责**：把 Evidence 中的 ExecutionTrace 交给 RuleJudge 做确定性规则检查，
      产出 EvaluationResult（含 RuleFinding 列表）。
    - **不负责**：不实现 LLM 语义判断、不生成 ReviewDecision、不读配置。
    - **为什么是独立类而非函数**：为后续并列 LLM Judge 预留实例化空间——
      ``CoreEvaluation(judge=RuleJudge(), llm_judge=None)`` 的扩展比纯函数更自然。
      但当前只使用 RuleJudge。

    使用方式：
        eval_result = CoreEvaluation().evaluate(evidence, eval_spec)
        # eval_result.findings 包含 RuleFinding 列表
        # eval_result.passed 是确定性规则的聚合判定
        # eval_result 不包含 ReviewDecision——人工 Reviewer 必须显式创建
    """

    def __init__(self, judge: RuleJudge | None = None):
        """初始化 CoreEvaluation。

        judge 参数允许注入（测试可注入 mock），默认使用 RuleJudge。
        """
        self._judge = judge or RuleJudge()

    def evaluate(
        self, evidence: Evidence, eval_spec: EvalSpec
    ) -> EvaluationResult:
        """消费 Evidence，产出 EvaluationResult。

        内部流程：
        1. ExecutionTrace → AgentRunResult（反向桥接，供 RuleJudge 消费）
        2. RuleJudge.judge(eval_spec, agent_run_result) → JudgeResult
        3. JudgeResult → EvaluationResult（通过 demo_core_bridge）

        EvaluationResult 不自动生成 ReviewDecision——人工 Reviewer 必须在查看
        所有 evidence 后显式创建 ReviewDecision。
        """
        # 反向桥接：ExecutionTrace → AgentRunResult
        # 这是临时适配层——RuleJudge 消费旧对象，后续轮次改为原生 Core Contract
        agent_run_result = execution_trace_to_agent_run_result(evidence.trace)

        # 确定性规则检查
        judge_result = self._judge.judge(eval_spec, agent_run_result)

        # JudgeResult → EvaluationResult
        return judge_result_to_evaluation_result(judge_result)
