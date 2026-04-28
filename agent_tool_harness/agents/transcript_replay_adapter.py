"""Transcript replay adapter（v0.3 第一项）。

这个模块是 v0.3 的第一项受控落地：把一份**已有 run 目录**当成"录像带"，
按 eval_id deterministic 重新播放给当前 EvalRunner，让 harness 在不调用
任何真实 LLM / 真实工具 / 网络的前提下，能复盘一段历史 trajectory。

它解决什么真实问题（架构边界 - 负责什么）：
- 真实团队拿到一份历史 ``runs/.../`` 目录（同事丢过来的、CI 归档的、或者
  v0.2 之前生成的旧 run），希望用最新的 ToolDesignAuditor / RuleJudge /
  TraceSignalAnalyzer / MarkdownReport 重新跑一遍**派生分析**，但又不想
  / 不能再次调用真实 Agent。
- ``analyze-artifacts`` CLI 解决了"派生 trace 信号"那一半，但它**不重建
  judge / metrics / report**。本 adapter 让 ``EvalRunner.run`` 整条主链
  路都能跑一次，而 Agent 行为只是按历史 transcript 严格复刻。

它不负责什么（架构边界 - 不负责）：
- **不调用任何真实模型**：没有 OpenAI / Anthropic / MCP / HTTP 调用。
- **不调用 ``registry.execute``**：工具响应直接来自历史 ``tool_responses.jsonl``。
  这是"replay"的本意——历史是什么就是什么；重新执行工具会让结果偏离原
  trajectory，反而无法复盘原始 bug。这条边界由 ``test_transcript_replay_adapter``
  的 ``test_replay_does_not_call_registry_execute`` 钉死。
- **不伪造任何 tool decision / final answer**：源 run 没记录的事件就是没有，
  本 adapter 不会"补一个看起来合理的"——那是真实 LLM adapter 的工作。
- **不做 LLM Judge / 语义级证明**：信号质量只是 ``RECORDED_TRAJECTORY``，
  比 ``TAUTOLOGICAL_REPLAY`` 高，但仍**不是** ``REAL_AGENT``——历史
  trajectory 不等于"当前模型对当前工具集还会做出同样选择"。

为什么这样设计：
- v0.2 已经把 ``signal_quality`` / ``recorder`` / ``trace_signal_analyzer`` /
  ``analyze-artifacts`` 这条**派生分析**链路打通；v0.3 第一项要做的最小
  增量是"让 trajectory 来源不再只是 mock"，而**不是**一上来就接真实
  模型。先把 deterministic replay 做扎实，下一轮（v0.3 后续）再做
  ``RealLLMAdapter``——届时它需要的所有 recorder/judge/report 接口已经
  被 replay adapter 反复验证过。
- 选择"使用历史响应、不重新执行工具"而不是"重跑 registry.execute"是为了
  让 replay 真的可复现：真实工具可能 stateful（数据库、文件、外部 API），
  重跑会让相同输入得到不同输出，违背"录像带"的语义。

用户项目自定义入口：
- ``TranscriptReplayAdapter(source_run_dir=...)`` 直接构造即可；
- 或者通过 ``agent_tool_harness.cli replay-run --source-run <dir> ...`` 跑一次
  完整 EvalRunner 闭环。
- 不需要修改 tools.yaml / project.yaml / evals.yaml（它们仍是 EvalRunner 的
  输入；replay adapter 只决定 Agent 行为来源）。

如何通过 artifacts 查问题：
- 新 run 目录里 ``transcript.jsonl`` 的每条 ``tool_call`` / ``tool_response``
  事件都会带 ``metadata.replayed_from = {source_call_id, source_timestamp,
  source_run}``，方便对照原 run；
- ``transcript.jsonl`` 顶部会有一条 ``runner.replay_summary`` system 事件，
  写明本次 replay 的源目录、命中的事件数；
- 如果某条 eval 在源 run 中**没有** tool_call / tool_response / final answer，
  会在新 transcript 中追加 ``runner.replay_warning`` 事件，并在 AgentRunResult
  里返回空 final_answer——这样 RuleJudge 会 deterministic 地 FAIL，下游
  能立刻看到"replay 源没覆盖这条 eval"，而不是被静默吞掉。
- ``metrics.json`` 顶部 ``signal_quality = recorded_trajectory``；
  ``report.md`` banner 同步显示。

只做 MVP / 不做：
- 不做 ``--diff`` 双 run 对比；
- 不做 trajectory 字段级 schema 校验（只校验关键文件存在与否）；
- 不做 partial-eval slicing（一次 replay 整条 eval 的全部记录，不能挑
  "前 3 步"）；
- 不在 replay 时再调一次 ToolDesignAuditor 之外的真实工具——所有外部
  effect 都被冻结。

未来扩展点：
- ``--diff PREV_RUN`` 在 replay 后对比 judge / signals 差异；
- 支持把 source 限定到特定 eval_id 子集；
- ``RealLLMAdapter`` 落地后，可由它生成 trajectory，再用本 adapter 的
  Run-to-Run 校验工具确认 deterministic regression。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.recorder.run_recorder import RunRecorder
from agent_tool_harness.signal_quality import RECORDED_TRAJECTORY
from agent_tool_harness.tools.registry import ToolRegistry


class TranscriptReplaySourceError(FileNotFoundError):
    """source run 目录结构不可用时抛出的友好错误。

    继承 FileNotFoundError 是为了让 ``cli.main`` 现有的 except 通道
    （已有 ``except FileNotFoundError`` 分支）能直接捕获并打印可行动 hint，
    避免出现裸 traceback——这条契约由 ``test_replay_cli_actionable_error`` 钉住。
    """


class TranscriptReplayAdapter:
    """从一份已有 run 目录 deterministic 重放历史 trajectory。

    详见模块 docstring。本类的所有行为都不调用 LLM、不调用 registry.execute、
    不发起任何网络/磁盘外部副作用（除 recorder 写新 run 目录外）。
    """

    SIGNAL_QUALITY = RECORDED_TRAJECTORY

    # 源 run 目录里需要的关键 raw artifact 文件名。这里硬编码字符串列表，
    # 而不是从 RunRecorder.JSONL_FILES 取，是因为 replay 关心的是 schema 兼容
    # （未来 recorder 可能增加新文件，但 replay 仍只消费这三份）。
    REQUIRED_ANY_OF = ("tool_calls.jsonl", "tool_responses.jsonl")
    OPTIONAL_FILES = ("transcript.jsonl",)

    def __init__(self, source_run_dir: str | Path):
        self.source_run_dir = Path(source_run_dir)
        if not self.source_run_dir.exists():
            raise TranscriptReplaySourceError(
                f"replay source run 目录不存在: {self.source_run_dir}\n"
                "hint: 请传入一份用 `agent-tool-harness run` 写出的 run 目录"
                "（包含 transcript.jsonl / tool_calls.jsonl / tool_responses.jsonl）。"
            )
        if not self.source_run_dir.is_dir():
            raise TranscriptReplaySourceError(
                f"replay source 必须是目录，不是文件: {self.source_run_dir}"
            )

        # 载入三份 JSONL；任意两份关键文件全缺就 fail-fast，避免 replay 跑了
        # 一遍才发现源里压根没有可重放的内容。
        self._tool_calls_by_eval = self._load_jsonl_grouped("tool_calls.jsonl")
        self._tool_responses_by_eval = self._load_jsonl_grouped("tool_responses.jsonl")
        self._transcript_by_eval = self._load_jsonl_grouped("transcript.jsonl")

        if not self._tool_calls_by_eval and not self._tool_responses_by_eval:
            raise TranscriptReplaySourceError(
                f"replay source 目录里既没有 tool_calls.jsonl 也没有 tool_responses.jsonl: "
                f"{self.source_run_dir}\n"
                "hint: 该目录看起来不是一份 harness run。请先用 `agent-tool-harness run` "
                "生成 artifacts，再用本 adapter 重放。"
            )

    def _load_jsonl_grouped(self, filename: str) -> dict[str, list[dict[str, Any]]]:
        """读一份 JSONL 并按 ``eval_id`` 分组。

        - 文件不存在返回空 dict（transcript.jsonl 是 OPTIONAL，不应让 replay 整体失败）；
        - 行为空跳过；
        - 行 JSON 损坏直接抛 ValueError——这是真实数据损坏，宁可 fail-fast 也不要
          静默丢事件让 replay 偏离历史。
        """
        path = self.source_run_dir / filename
        grouped: dict[str, list[dict[str, Any]]] = {}
        if not path.exists():
            return grouped
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            row = json.loads(line)
            eval_id = str(row.get("eval_id", ""))
            grouped.setdefault(eval_id, []).append(row)
        return grouped

    def run(
        self, case: EvalSpec, registry: ToolRegistry, recorder: RunRecorder
    ) -> AgentRunResult:
        """按 eval_id 重放历史 trajectory。

        核心步骤：
        1. 写一条 ``runner.replay_summary`` system 事件，把源目录写进 transcript；
        2. 把源 transcript 中**与本次 replay 相关**的事件透传到新 recorder；
           (跳过 system/runner_* 事件，避免与新 EvalRunner 自己写的事件重复)；
        3. 重放 tool_calls / tool_responses 事件，每条带 ``metadata.replayed_from``；
        4. 从源 transcript 提取最后一条 ``assistant`` + ``type=final`` 作为 final_answer；
           找不到就写 warning + 空 final_answer，让 RuleJudge 自然 FAIL。
        """

        source_calls = self._tool_calls_by_eval.get(case.id, [])
        source_responses = self._tool_responses_by_eval.get(case.id, [])
        source_transcript = self._transcript_by_eval.get(case.id, [])

        recorder.record_transcript(
            case.id,
            {
                "role": "system",
                "type": "runner.replay_summary",
                "content": (
                    "TranscriptReplayAdapter is replaying recorded trajectory; "
                    "no LLM and no real tool execution were invoked."
                ),
                "metadata": {
                    "source_run": str(self.source_run_dir),
                    "source_tool_call_count": len(source_calls),
                    "source_tool_response_count": len(source_responses),
                    "source_transcript_event_count": len(source_transcript),
                    "signal_quality": RECORDED_TRAJECTORY,
                },
            },
        )

        if not source_calls and not source_responses:
            # 源里根本没有这条 eval 的记录——deterministic FAIL 而不是吞掉。
            # 这条 warning 是测试 ``test_replay_missing_eval_records_warning`` 的钉子。
            recorder.record_transcript(
                case.id,
                {
                    "role": "system",
                    "type": "runner.replay_warning",
                    "content": (
                        f"Source run has no tool_calls / tool_responses for eval "
                        f"{case.id!r}; replay returned an empty trajectory."
                    ),
                    "metadata": {"source_run": str(self.source_run_dir)},
                },
            )
            return AgentRunResult(case.id, "", [], [])

        # 透传源 transcript 事件（除 system/runner_* —— 它们由新 EvalRunner 写）。
        for event in source_transcript:
            event_type = str(event.get("type", ""))
            event_role = str(event.get("role", ""))
            if event_role == "system" or event_type.startswith("runner."):
                continue
            payload = {k: v for k, v in event.items() if k not in {"timestamp", "eval_id"}}
            metadata = dict(payload.get("metadata") or {})
            metadata.setdefault("replayed_from", {
                "source_run": str(self.source_run_dir),
                "source_timestamp": event.get("timestamp"),
            })
            payload["metadata"] = metadata
            recorder.record_transcript(case.id, payload)

        replayed_calls: list[dict[str, Any]] = []
        for source_call in source_calls:
            call_payload = {
                k: v for k, v in source_call.items() if k != "timestamp"
            }
            # 保留原 call_id（不调 recorder.next_call_id），让 response 仍然能用
            # 同一个 call_id 关联到 call——这是 replay 的核心契约。
            call_payload.setdefault("call_id", recorder.next_call_id(case.id))
            call_payload["replayed_from"] = {
                "source_run": str(self.source_run_dir),
                "source_timestamp": source_call.get("timestamp"),
            }
            recorder.record_tool_call(call_payload)
            replayed_calls.append(call_payload)

        replayed_responses: list[dict[str, Any]] = []
        for source_response in source_responses:
            response_payload = {
                k: v for k, v in source_response.items() if k != "timestamp"
            }
            response_payload["replayed_from"] = {
                "source_run": str(self.source_run_dir),
                "source_timestamp": source_response.get("timestamp"),
            }
            recorder.record_tool_response(response_payload)
            replayed_responses.append(response_payload)

        final_answer = self._extract_final_answer(source_transcript)
        if final_answer is None:
            recorder.record_transcript(
                case.id,
                {
                    "role": "system",
                    "type": "runner.replay_warning",
                    "content": (
                        "Source transcript has no assistant final message for eval "
                        f"{case.id!r}; replay returns empty final_answer and judge will FAIL."
                    ),
                    "metadata": {"source_run": str(self.source_run_dir)},
                },
            )
            final_answer = ""

        return AgentRunResult(case.id, final_answer, replayed_calls, replayed_responses)

    def _extract_final_answer(self, transcript: list[dict[str, Any]]) -> str | None:
        """从源 transcript 中找出 assistant 的最终回答。

        约定遵循 MockReplayAdapter / 未来 RealLLMAdapter 的写入模式：
        ``role == 'assistant' and type == 'final'`` 的事件 ``content`` 字段。
        如果有多条，取最后一条；找不到返回 None（让上层走 warning 分支）。
        """
        final_text: str | None = None
        for event in transcript:
            if event.get("role") == "assistant" and event.get("type") == "final":
                content = event.get("content")
                if isinstance(content, str):
                    final_text = content
        return final_text
