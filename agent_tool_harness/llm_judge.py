"""LLMJudgeProvider —— CoreJudgeProvider 的真实 LLM 实现。

本模块负责什么
==============
实现 ``CoreJudgeProvider`` Protocol，消费 ``Evidence`` 并通过注入的 transport
调用真实 LLM API，返回 ``JudgeFinding`` 列表。

本模块**不**负责什么
====================
- 不做 HTTP 请求（由 transport 负责）
- 不读环境变量 / 配置（由 factory 负责）
- 不改变 EvaluationResult.passed（JudgeFinding 永远是 advisory）
- 不自动生成 ReviewDecision

架构边界
========
- **负责**：prompt 构建、transport 调用、响应解析、JudgeFinding 构造
- **不负责**：API key 管理、网络治理、错误脱敏（这些由 transport + factory 负责）

设计原则
========
1. transport 是可注入的——测试可注入 fake transport
2. prompt 构建是确定性的——从 Evidence 中提取字段，不依赖外部状态
3. 错误路径不静默——transport 异常返回 error-finding，不抛异常
4. JudgeFinding 不改变 passed——调用方（CoreEvaluation）保证这一点
"""

from __future__ import annotations

from typing import Any

from agent_tool_harness.core_contract import Evidence, JudgeFinding


class LLMJudgeProvider:
    """真实 LLM judge provider（通过注入 transport 调用 API）。

    实现 ``CoreJudgeProvider`` Protocol。

    使用方式
    --------
        provider = LLMJudgeProvider(
            transport=openai_transport,
            provider_name="openai-native",
            model="gpt-4.1-mini",
        )
        findings = provider.evaluate(evidence)
    """

    def __init__(
        self,
        transport: Any,
        *,
        provider_name: str,
        model: str,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int = 1024,
    ) -> None:
        self._transport = transport
        self._provider_name = provider_name
        self._model = model
        self._system_prompt = system_prompt or _DEFAULT_SYSTEM_PROMPT
        self._temperature = temperature
        self._max_tokens = max_tokens

    # CoreJudgeProvider Protocol 字段
    name: str = "llm"

    @property
    def model(self) -> str:
        return self._model

    @property
    def mode(self) -> str:
        return "live" if getattr(self._transport, "is_live_ready", False) else "disabled"

    def evaluate(self, evidence: Evidence) -> list[JudgeFinding]:
        """消费 Evidence，返回 JudgeFinding 列表。

        流程：
        1. 构建 prompt（system + user）
        2. 调用 transport.send(request)
        3. 解析响应为 JudgeFinding
        4. 如果 transport 抛异常，返回 error finding
        """
        scenario_id = evidence.trace.scenario_id
        request = self._build_request(evidence)
        try:
            response = self._transport.send(request)
        except Exception as exc:
            return self._error_finding(scenario_id, exc)

        return self._response_to_findings(scenario_id, response)

    # -------------------------------------------------------------------
    # prompt 构建
    # -------------------------------------------------------------------

    def _build_request(self, evidence: Evidence) -> dict:
        """从 Evidence 构建 API request body。"""
        trace = evidence.trace
        tool_calls_desc = self._describe_tool_calls(trace.tool_calls, trace.tool_results)
        final_answer = trace.final_answer or "(no final answer)"

        user_message = _USER_MESSAGE_TEMPLATE.format(
            scenario_id=trace.scenario_id,
            tool_calls=tool_calls_desc,
            final_answer=final_answer,
            signal_quality=evidence.signal_quality,
            cost_usd=evidence.cost_usd if evidence.cost_usd is not None else "N/A",
            latency_ms=evidence.latency_ms if evidence.latency_ms is not None else "N/A",
        )

        return {
            "messages": [
                {"role": "system", "content": self._system_prompt},
                {"role": "user", "content": user_message},
            ],
            "max_tokens": self._max_tokens,
            "temperature": self._temperature if self._temperature is not None else 0.3,
        }

    @staticmethod
    def _describe_tool_calls(
        tool_calls: list, tool_results: list
    ) -> str:
        """将 tool_calls + tool_results 序列化为可读文本。"""
        lines: list[str] = []
        for call in tool_calls:
            lines.append(
                f"- tool: {call.tool_name}, "
                f"call_id: {call.call_id}, "
                f"args: {_safe_json(call.arguments)}"
            )
        if not lines:
            return "(no tool calls)"
        lines.append("")
        lines.append("Results:")
        for result in tool_results:
            status = result.status
            output = _safe_json(result.output) if result.output else ""
            error = result.error or ""
            lines.append(
                f"- [{status}] {result.call_id}: "
                f"output={output}, error={error}"
            )
        return "\n".join(lines)

    # -------------------------------------------------------------------
    # 响应解析
    # -------------------------------------------------------------------

    def _response_to_findings(
        self, scenario_id: str, response: dict
    ) -> list[JudgeFinding]:
        """将 transport 响应解析为 JudgeFinding 列表。"""
        rationale = str(response.get("rationale", ""))
        confidence = response.get("confidence")
        rubric = response.get("rubric")
        usage = response.get("usage")

        finding = JudgeFinding(
            finding_id=f"{scenario_id}-judge-llm-0",
            severity="info",
            category="judge",
            message=f"[{self._provider_name}] {rationale[:200] if rationale else 'no rationale'}",
            evidence_ref=f"evidence.json::scenario_id={scenario_id}",
            confidence=float(confidence) if confidence is not None else None,
            rubric=str(rubric) if rubric else None,
            provider=self._provider_name,
            rationale=rationale,
            model=self._model,
            usage=dict(usage) if usage else None,
        )
        return [finding]

    def _error_finding(
        self, scenario_id: str, exc: Exception
    ) -> list[JudgeFinding]:
        """transport 异常 → 携带错误信息的 advisory finding。"""
        error_code = getattr(exc, "error_code", "provider_error")
        error_msg = getattr(exc, "error_message", str(exc))

        return [
            JudgeFinding(
                finding_id=f"{scenario_id}-judge-llm-error",
                severity="info",
                category="judge",
                message=(
                    f"[{self._provider_name}] transport error: "
                    f"{error_code} — {error_msg[:200]}"
                ),
                evidence_ref=f"evidence.json::scenario_id={scenario_id}",
                provider=self._provider_name,
                rationale=f"transport error ({error_code})",
                model=self._model,
            )
        ]


# ---------------------------------------------------------------------------
# 默认 prompt 模板
# ---------------------------------------------------------------------------

_DEFAULT_SYSTEM_PROMPT = """\
You are an evaluator for AI agent tool usage quality. Your job is to review \
the agent's tool calls and final answer, then produce a structured assessment.

Evaluate whether:
1. The agent selected appropriate tools for the task
2. The tool calls were efficient (no unnecessary or redundant calls)
3. The final answer correctly used the tool outputs
4. The agent avoided common failure modes (wrong tool, stale data, missing calls)

Output your assessment as a JSON object:
{"passed": true/false, "rationale": "...", "confidence": 0.0-1.0}

Where:
- passed: true if the agent's tool usage was correct and appropriate
- rationale: brief explanation of your judgment (2-4 sentences)
- confidence: your confidence in this judgment (0.0 to 1.0)"""

_USER_MESSAGE_TEMPLATE = """\
## Scenario
{scenario_id}

## Tool Calls
{tool_calls}

## Final Answer
{final_answer}

## Metadata
- signal_quality: {signal_quality}
- cost_usd: {cost_usd}
- latency_ms: {latency_ms}

Evaluate the agent's tool usage quality. Output JSON only."""


# ---------------------------------------------------------------------------
# helper
# ---------------------------------------------------------------------------


def _safe_json(obj: Any) -> str:
    """安全 JSON 序列化，失败返回 repr。"""
    try:
        import json as _json
        return _json.dumps(obj, ensure_ascii=False, default=repr)
    except Exception:
        return repr(obj)
