"""TraceImportAdapter — 把用户已有 trace JSON 导入为 Agent2Harness ExecutionTrace。

架构边界
--------
- **负责**: 读取 trace JSON 文件、校验必要字段、映射到 ``ExecutionTrace`` dataclass。
- **不负责**: 不运行 Agent、不调用外部 API、不读取 .env、不猜测复杂格式、不用 LLM
  解析 trace。
- **为什么 TraceImportAdapter 不运行 Agent**: TraceImportAdapter 是纯数据导入器——
  输入是用户已经产出的 trace JSON 文件，不是评测场景。它把已有 trace 转成 Core
  Flow 可以消费的 ``ExecutionTrace``，让用户可以先验证下游链路（judge / report /
  review）而不需要先跑通真实 Agent。运行 Agent 是 ``CLIAgentAdapter`` 的职责（未来）。
- **为什么第一版只支持 native schema**: native schema 直接对应 ``ExecutionTrace``
  的字段结构，反序列化后只需校验不需映射，实现最稳定、错误信息最明确。simple mapping
  引入字段映射的复杂度（嵌套路径、类型转换、缺失处理），应该在 native 模式验证通过
  后再叠加。
- **为什么不自动猜测任意 JSON**: 猜测意味着"假设用户意图"，出错了用户无法排查。
  明确的错误信息（"缺少 call_id"）比静默的错误结果（"评测结果不通过，但你不知道
  是 trace 格式问题还是 Agent 行为问题"）对用户更有价值。
- **为什么不用 LLM 自动解析 trace**: LLM 解析 trace 是不可靠的——它可能猜测错误、
  幻觉字段、遗漏关键数据。trace 解析必须是确定性的，否则评测结果的信号质量不可信。
- **为什么 tool_name / call_id 必须严格保留**: call_id 串联 ToolCall ↔ ToolResult，
  是回溯证据链的关键索引。tool_name 标识具体工具，RuleJudge 依赖它做 must_call_tool /
  forbidden_first 检查。如果这两个字段在导入时丢失或映射错误，整个评测链路的结果
  就不可信。
- **为什么 TraceImportAdapter 不生成 ReviewDecision**: ReviewDecision 必须由人工
  Reviewer 显式创建。TraceImportAdapter 是纯数据导入器，它的输出是机械数据转换，
  不具备评测语义。即使导入后的 trace 被 CoreEvaluation 判定为 PASS/FAIL，
  最终是否接受结论必须由人决定。

与 Core Contract 的关系
-----------------------
- 输入: trace JSON（文件路径或 dict）
- 输出: ``ExecutionTrace`` + 可选的 ``Evidence``
- 所有输出对象定义见 ``agent_tool_harness.core_contract``
- 不依赖 demo adapter / real provider / RuleJudge / JudgeProvider

native schema 与 ExecutionTrace 的对应关系
------------------------------------------
native JSON 中有 ``observations`` 字段，但 ``ExecutionTrace`` 当前没有对应字段。
导入时 ``observations`` 会被存入 ``Evidence.artifacts["observations"]``，
不会丢失数据。``messages`` 直接映射到 ``ExecutionTrace.messages``。

未来扩展点
----------
- Phase B: simple mapping mode（字段映射 YAML）
- 当 ``ExecutionTrace`` 增加 ``observations`` 字段时，直接映射而非存入 artifacts
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_tool_harness.core_contract import (
    Evidence,
    ExecutionTrace,
    ToolCall,
    ToolResult,
)
from agent_tool_harness.signal_quality import RECORDED_TRAJECTORY


class TraceImportError(Exception):
    """用户 trace 格式错误。

    架构边界:
    - **负责**: 携带明确的错误路径和原因，让用户能定位到具体字段。
    - **不负责**: 不携带 secrets / API key / 文件内容。
    """

    def __init__(self, message: str, *, field_path: str = ""):
        super().__init__(message)
        self.field_path = field_path


# ---------------------------------------------------------------------------
# TraceImportAdapter
# ---------------------------------------------------------------------------


class TraceImportAdapter:
    """导入用户 trace 文件为 ExecutionTrace。

    架构边界:
    - **负责**: 读取 trace JSON 文件或 dict，校验必要字段，产出 ExecutionTrace 和
      可选的 Evidence。
    - **不负责**: 不运行 Agent、不调用外部 API、不读取 .env、不猜测复杂格式、
      不用 LLM 解析 trace。
    - **当前只实现 native schema mode**——用户 trace 必须直接符合 ExecutionTrace
      的字段结构。simple mapping mode 将在 Phase B 实现。

    native schema 最小 JSON:
        {
          "scenario_id": "...",
          "tool_calls": [{"call_id": "c1", "tool_name": "...", "arguments": {...}}],
          "tool_results": [
              {"call_id": "c1", "tool_name": "...", "status": "success", "output": {...}}
          ],
          "final_answer": "...",
          "messages": [],
          "observations": []
        }
    """

    def import_file(self, path: Path | str) -> ExecutionTrace:
        """从文件路径导入 trace JSON → ExecutionTrace。

        Raises:
            TraceImportError: JSON 解析失败或字段校验失败。
        """
        path = Path(path)
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError as exc:
            raise TraceImportError(
                f"无法读取文件: {path} — {exc}", field_path=str(path)
            ) from exc
        return self._import(raw, source=str(path))

    def import_dict(self, data: dict[str, Any]) -> ExecutionTrace:
        """从 dict 导入 trace → ExecutionTrace。

        Raises:
            TraceImportError: 字段校验失败。
        """
        return self._import_dict(data)

    def to_evidence(
        self,
        trace: ExecutionTrace,
        *,
        artifacts: dict[str, Any] | None = None,
        signal_quality: str = RECORDED_TRAJECTORY,
        observations: list[dict[str, Any]] | None = None,
    ) -> Evidence:
        """把 ExecutionTrace 打包为 Evidence。

        TraceImportAdapter 导入的 trace 来自用户已有记录，signal_quality 默认
        为 ``recorded_trajectory``——不是真实 Agent 当前运行产出。
        """
        merged_artifacts: dict[str, Any] = dict(artifacts or {})
        if observations:
            merged_artifacts["observations"] = observations
        return Evidence(
            trace=trace,
            artifacts=merged_artifacts,
            cost_usd=None,
            latency_ms=None,
            signal_quality=signal_quality,
        )

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _import(self, raw: str, *, source: str = "<string>") -> ExecutionTrace:
        """解析 JSON 字符串 → ExecutionTrace。"""
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TraceImportError(
                f"invalid JSON: {exc}", field_path=source
            ) from exc
        return self._import_dict(data)

    def _import_dict(self, data: dict[str, Any]) -> ExecutionTrace:
        """校验并构造 ExecutionTrace。"""
        if not isinstance(data, dict):
            raise TraceImportError("trace data must be a JSON object")

        # 1. scenario_id
        scenario_id = data.get("scenario_id")
        if not isinstance(scenario_id, str) or not scenario_id.strip():
            raise TraceImportError(
                "missing scenario_id", field_path="scenario_id"
            )

        # 2. tool_calls
        raw_calls = data.get("tool_calls")
        if not isinstance(raw_calls, list):
            raise TraceImportError(
                "tool_calls must be a list", field_path="tool_calls"
            )

        # 3. tool_results
        raw_results = data.get("tool_results")
        if not isinstance(raw_results, list):
            raise TraceImportError(
                "tool_results must be a list", field_path="tool_results"
            )

        tool_calls = self._parse_tool_calls(raw_calls)
        tool_results = self._parse_tool_results(raw_results)

        # 4. call_id 交叉校验
        call_ids = {c.call_id for c in tool_calls}
        for r in tool_results:
            if r.call_id not in call_ids:
                raise TraceImportError(
                    f"tool_result.call_id={r.call_id!r} 在 tool_calls 中找不到对应项",
                    field_path=f"tool_results[call_id={r.call_id}]",
                )

        # 5. final_answer / messages
        final_answer = data.get("final_answer")
        if not isinstance(final_answer, str):
            final_answer = ""
        raw_messages = data.get("messages")
        if not isinstance(raw_messages, list):
            raw_messages = []
        # 深层拷贝避免外部引用污染
        messages: list[dict[str, Any]] = [
            dict(m) if isinstance(m, dict) else {} for m in raw_messages
        ]

        # 6. observations（存入 Evidence artifacts，非 ExecutionTrace）
        # 当前 ExecutionTrace 没有 observations 字段，此处仅存储引用供 to_evidence 使用
        raw_observations = data.get("observations")
        if not isinstance(raw_observations, list):
            raw_observations = []
        observations: list[dict[str, Any]] = [
            dict(o) if isinstance(o, dict) else {} for o in raw_observations
        ]

        trace = ExecutionTrace(
            scenario_id=scenario_id.strip(),
            tool_calls=tool_calls,
            tool_results=tool_results,
            messages=messages,
            final_answer=final_answer,
        )
        # 把 observations 挂在 trace 上供 to_evidence 读取（临时属性，
        # 不在 ExecutionTrace 定义中，仅本模块内部使用）
        trace._trace_import_observations = observations  # type: ignore[attr-defined]
        return trace

    # ------------------------------------------------------------------
    # 字段解析
    # ------------------------------------------------------------------

    def _parse_tool_calls(self, raw_calls: list[Any]) -> list[ToolCall]:
        result: list[ToolCall] = []
        for i, item in enumerate(raw_calls):
            prefix = f"tool_calls[{i}]"
            if not isinstance(item, dict):
                raise TraceImportError(
                    f"{prefix} must be a JSON object", field_path=prefix
                )
            call_id = item.get("call_id")
            if not isinstance(call_id, str) or not call_id.strip():
                raise TraceImportError(
                    f"{prefix} missing call_id", field_path=f"{prefix}.call_id"
                )
            tool_name = item.get("tool_name")
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise TraceImportError(
                    f"{prefix} missing tool_name",
                    field_path=f"{prefix}.tool_name",
                )
            arguments = item.get("arguments")
            if not isinstance(arguments, dict):
                arguments = {}
            timestamp = item.get("timestamp")
            if timestamp is not None and not isinstance(timestamp, str):
                timestamp = None
            result.append(
                ToolCall(
                    call_id=call_id.strip(),
                    tool_name=tool_name.strip(),
                    arguments=dict(arguments),
                    timestamp=timestamp,
                )
            )
        if not result:
            raise TraceImportError("tool_calls 不能为空", field_path="tool_calls")
        return result

    def _parse_tool_results(self, raw_results: list[Any]) -> list[ToolResult]:
        result: list[ToolResult] = []
        for i, item in enumerate(raw_results):
            prefix = f"tool_results[{i}]"
            if not isinstance(item, dict):
                raise TraceImportError(
                    f"{prefix} must be a JSON object", field_path=prefix
                )
            call_id = item.get("call_id")
            if not isinstance(call_id, str) or not call_id.strip():
                raise TraceImportError(
                    f"{prefix} missing call_id",
                    field_path=f"{prefix}.call_id",
                )
            tool_name = item.get("tool_name")
            if not isinstance(tool_name, str) or not tool_name.strip():
                raise TraceImportError(
                    f"{prefix} missing tool_name",
                    field_path=f"{prefix}.tool_name",
                )
            # status normalize: "ok" → "success"
            status = item.get("status", "success")
            if not isinstance(status, str) or not status.strip():
                status = "success"
            elif status.strip().lower() == "ok":
                status = "success"

            output = item.get("output")
            if not isinstance(output, dict):
                output = {}

            error = item.get("error")
            if error is not None and not isinstance(error, str):
                error = None

            result.append(
                ToolResult(
                    call_id=call_id.strip(),
                    tool_name=tool_name.strip(),
                    status=status.strip(),
                    output=dict(output),
                    error=error,
                )
            )
        if not result:
            raise TraceImportError(
                "tool_results 不能为空", field_path="tool_results"
            )
        return result


# ---------------------------------------------------------------------------
# convenience function
# ---------------------------------------------------------------------------


def import_trace_as_evidence(
    path: Path | str,
    *,
    artifacts: dict[str, Any] | None = None,
    signal_quality: str = RECORDED_TRAJECTORY,
) -> Evidence:
    """一键导入 trace JSON 文件 → Evidence。

    这是 TraceImportAdapter.import_file + to_evidence 的便捷封装。
    """
    adapter = TraceImportAdapter()
    trace = adapter.import_file(path)
    observations = getattr(trace, "_trace_import_observations", None)
    return adapter.to_evidence(
        trace,
        artifacts=artifacts,
        signal_quality=signal_quality,
        observations=observations,
    )
