"""FakeJudgeProvider —— 不调外部 API 的 LLM judge 骨架。

本模块负责什么
==============
提供一个 FakeJudgeProvider，接受 Core Contract 的 Evidence 并返回
JudgeFinding 列表。用于验证 JudgeProvider 接口，不调任何外部 API。

本模块**不**负责什么
====================
- 不调真实 LLM API
- 不读环境变量 / .env
- 不生成 ReviewDecision
- 不做语义判断——fake responses 是预置的 deterministic 数据

设计意图
========
1. 让 Core Flow 的 JudgeProvider 接口可以在不接真实 LLM 的情况下被验证
2. 为 future LLM judge 落地提供参考实现——真实 provider 只需换 transport，
   接口不变
3. 测试默认使用 FakeJudgeProvider，确保 CI 零网络依赖
"""

from __future__ import annotations

from typing import Any, Protocol

from agent_tool_harness.core_contract import Evidence, JudgeFinding

# ---------------------------------------------------------------------------
# Core Flow aligned JudgeProvider Protocol
# ---------------------------------------------------------------------------


class CoreJudgeProvider(Protocol):
    """Core Flow 对齐的 JudgeProvider 契约。

    与旧 judges/provider.py::JudgeProvider 的区别：
    - 旧接口：judge(case: EvalSpec, run: AgentRunResult) -> ProviderJudgeResult
    - 新接口：evaluate(evidence: Evidence) -> list[JudgeFinding]
    - 新接口消费 Core Contract 对象，不依赖旧 AgentRunResult / EvalSpec
    - 返回 JudgeFinding 列表（可与 RuleFinding 并列放入 EvaluationResult）
    """

    name: str
    mode: str

    def evaluate(self, evidence: Evidence) -> list[JudgeFinding]:
        ...


# ---------------------------------------------------------------------------
# FakeJudgeProvider
# ---------------------------------------------------------------------------


class FakeJudgeProvider:
    """不调外部 API 的 judge provider，用于接口验证和测试。

    模式：fake（deterministic，零网络依赖）。

    使用方式：
        provider = FakeJudgeProvider(responses={"eval-1": {...}})
        findings = provider.evaluate(evidence)

    responses dict 的 key 是 scenario_id，value 是预置的 finding 字段:
        {
            "scenario_id": {
                "passed": True,
                "rationale": "fake rationale",
                "confidence": 0.9,
                "rubric": "...",
            }
        }

    如果 scenario_id 不在 responses 中，默认返回 passed=True 的占位 finding。
    """

    name = "fake"
    mode = "fake"

    def __init__(
        self,
        responses: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._responses = dict(responses or {})

    def evaluate(self, evidence: Evidence) -> list[JudgeFinding]:
        """消费 Evidence，返回 JudgeFinding 列表。

        不调外部 API，只从预置 responses 或默认值构造 finding。
        """
        scenario_id = evidence.trace.scenario_id
        preset = self._responses.get(scenario_id, {})

        rationale = str(preset.get("rationale", "fake judge advisory"))
        confidence = preset.get("confidence")
        rubric = preset.get("rubric")

        finding = JudgeFinding(
            finding_id=f"{scenario_id}-judge-0",
            severity="info",
            category="judge",
            message=f"[{self.name}] {rationale}",
            evidence_ref=f"evidence.json::scenario_id={scenario_id}",
            confidence=float(confidence) if confidence is not None else None,
            rubric=str(rubric) if rubric else None,
            provider=self.name,
            rationale=rationale,
            model="fake-model",
        )

        return [finding]
