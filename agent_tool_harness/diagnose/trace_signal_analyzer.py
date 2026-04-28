"""Trace-derived deterministic tool-use 信号分析器。

模块职责（架构边界）：

- **负责**：从一次 run 已经写下来的 raw 证据（``tool_calls.jsonl`` /
  ``tool_responses.jsonl`` / ``transcript.jsonl`` / ``judge_results.json`` /
  ``diagnosis.json``）+ 用户提供的 ``ToolSpec`` 契约出发，
  反向复盘出"工具是否真的兑现了它在 ``output_contract`` 里声明的字段"、
  "工具响应是否大到没有指引"、"Agent 是否反复用同一参数调同一个工具"、
  "Agent 是否在 ``when_not_to_use`` 明确禁止的场景里调用了该工具"等
  **deterministic** 信号。所有信号都能 grep 回某一行 raw 证据。

- **不负责**：
    - 不重新执行工具，不重新判定 PASS/FAIL，不调 LLM/MCP；
    - 不替代 :class:`agent_tool_harness.judges.rule_judge.RuleJudge`——judge
      负责"按规则定生死"，本分析器只产出"事后复盘的可视证据"；
    - 不替代 :class:`agent_tool_harness.diagnose.transcript_analyzer.TranscriptAnalyzer`
      ——后者主要消费 ``judge.checks``（rule-derived finding），本模块消费
      raw response payload + tool 契约，两层正交并存，让用户能区分
      "是 RuleJudge 规则没写"还是"工具响应没满足自己的 contract"。

为什么单独拆一层（不直接塞进 TranscriptAnalyzer）：

- 关注点不同：TranscriptAnalyzer 是"规则失败 → 归因"；本模块是
  "raw artifact 与 contract 是否对齐 → 信号"。把它们混到一起会让
  finding/signal 共用同一份 evidence_refs 时难以解释"信号来源是规则
  还是 contract"。
- 可独立 replay：把分析器与 EvalRunner 单 run 闭环解耦后，未来可以
  对历史 ``runs/`` 目录做独立 ``analyze-artifacts`` 复盘，不必 re-run
  Agent；本轮先把 in-memory 接入跑通，磁盘入口只提供 helper
  :func:`analyze_run_dir`，CLI 暂不上线（写入 ROADMAP）。

用户项目自定义入口：

- ``ToolSpec.output_contract.required_fields``：声明工具必须返回哪些字段。
  本分析器据此判断 ``tool_result_missing_required_field`` /
  ``tool_result_no_evidence`` / ``tool_result_missing_next_action``。
- ``ToolSpec.when_not_to_use``：声明工具的"禁用场景"。本分析器抽取
  其中的关键词与 eval ``user_prompt`` 取交集，触发
  ``tool_selected_in_when_not_to_use_context``——这是 deterministic 词袋
  启发式，**不是**自然语言理解。
- ``ToolSpec.token_policy.truncation_guidance``：当工具返回大型/截断响应
  但既无 ``next_action`` 也无截断指引时，触发
  ``large_or_truncated_tool_response_without_guidance``。

artifact 排查路径：

- 信号会被 :class:`agent_tool_harness.runner.eval_runner.EvalRunner` 嵌入
  ``diagnosis.json`` 每条记录的 ``tool_use_signals`` 列表；
  ``report.md`` 在 Per-Eval Details 段会渲染 "Trace-derived signals"
  小节。每个 signal 必带 ``evidence_refs``，指回
  ``tool_responses.jsonl#call_id=<id>`` 或 ``tools.yaml#name=<tool>``。

MVP 边界（**重要**）：

- 全部 5 类信号都是 deterministic 启发式。它们能稳定指向"contract
  没满足"和"模式异常"，但**不能**回答"语义上是不是选错了工具"——
  例如同一职责被改写成完全不同词汇时，词袋启发式会漏掉。
  这类 case 仍需要 LLM judge / 真实 trajectory（v0.3 路线）。
- 阈值都写在模块顶层常量，便于审计；调整阈值前必须重跑
  ``tests/test_trace_signal_analyzer.py`` 中的反向断言（避免误伤）。

未来扩展点（仅 ROADMAP，不在本轮实现）：

- ``unused_high_signal_tool``：when_to_use 命中 prompt 但工具未被调用；
- ``candidate_prompt_too_tautological``：候选 eval 的 judge 规则与
  prompt 是同义重复；
- token 用量统计、call graph、跨 run trend；
- LLM-based root cause 二次确认（与 deterministic 信号并列，不替代）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from agent_tool_harness.config.tool_spec import ToolSpec

# ---------------------------------------------------------------------------
# 严重度等级。沿用 TranscriptAnalyzer 的字符串形式，避免 enum 让 JSON 不可读。
# 信号默认 medium——它们是"复盘提示"，没有强到可以直接判 FAIL。
# ---------------------------------------------------------------------------
SEVERITY_HIGH = "high"
SEVERITY_MEDIUM = "medium"
SEVERITY_INFO = "info"

# ---------------------------------------------------------------------------
# 阈值常量（**根因层**）。调整这些值前必须重跑
# tests/test_trace_signal_analyzer.py 里的正/反向断言：反向断言保护
# examples/runtime_debug 真实 spec 不被误伤。
# ---------------------------------------------------------------------------

# 一次工具响应被认为"大"的字符阈值。runtime_debug demo 工具的 content 通常
# < 600 字符；2000 已经是日志型/堆栈型 dump 的典型起点，不会误伤正常 evidence
# 列表。这是字符串化后的长度，不是 token 数——本模块拒绝引入 tokenizer 依赖。
_LARGE_RESPONSE_CHAR_THRESHOLD = 2000

# 截断标记的常见模式：JSON 字段（``truncated: true`` / ``is_truncated``）+
# 文本省略（连续三个以上点 + "more" 字样）。这里只匹配 deterministic 形态，
# 不做语义判断；新加模式必须同步在 tests 里加正/反向断言。
_TRUNCATION_MARKERS = (
    "...(truncated)",
    "...truncated",
    "[truncated]",
    "<truncated>",
)
_TRUNCATION_FIELD_KEYS = ("truncated", "is_truncated", "was_truncated")

# 重复调用阈值：同一 (tool_name, arguments) 出现 ≥2 次即视为"重复"。
# 比 TranscriptAnalyzer 的"连续两次"更严格，因为参数也要相同——这能
# 排除"同一工具不同 trace_id 多次调用"的合法分析场景。
_REPEATED_CALL_MIN_OCCURRENCES = 2

# when_not_to_use 关键词最小长度。短词（如 "do" / "use" / "the"）会和
# 任何 prompt 撞，必须过滤。3 字符并不是真实 NLP 阈值，只是排除最常见
# 噪声；真实词法应由 LLM judge 完成。
_KEYWORD_MIN_LENGTH = 4

# when_not_to_use 关键词停用词。这些词在 ToolSpec 描述里高频出现但不携带
# 场景信息，必须排除以免假阳性。和 ToolDesignAuditor._OVERLAP_STOPWORDS
# 思路一致，但这里只在 when_not_to_use 关键词提取里用，不与 audit 共享。
_WHEN_NOT_KEYWORD_STOPWORDS = frozenset(
    {
        "use",
        "this",
        "that",
        "with",
        "for",
        "from",
        "the",
        "and",
        "not",
        "you",
        "are",
        "should",
        "tool",
        "call",
        "when",
        "task",
        "user",
        "data",
        "info",
        "info.",
        "result",
        "step",
        "case",
        "first",
        "before",
        "after",
        "between",
        "within",
    }
)


def _tokenize(text: str) -> list[str]:
    """把自由文本切成小写单词列表。

    用 ``\\w+`` 而不是 split：避免标点、连字符干扰；不去 stem，因为我们要
    deterministic 而不是 fuzzy。
    """

    return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z_0-9]+", text or "")]


def _extract_when_not_keywords(when_not_to_use: str) -> set[str]:
    """从 ``when_not_to_use`` 文本里提取信号词。

    过滤逻辑：长度 ≥ ``_KEYWORD_MIN_LENGTH`` 且不在停用词集合里。这是非常
    保守的词袋启发式——本模块明确**不**做语义识别，宁可漏报也不要误报。
    """

    tokens = _tokenize(when_not_to_use)
    return {
        token
        for token in tokens
        if len(token) >= _KEYWORD_MIN_LENGTH and token not in _WHEN_NOT_KEYWORD_STOPWORDS
    }


def _is_response_large(content: Any) -> bool:
    """启发式：响应是否"大"。

    用 JSON dump 字符长度近似；不是 token 数，但对 deterministic 工具足够。
    JSON dump 失败时回退 ``str(content)``，保证不抛异常打断分析。
    """

    if content is None:
        return False
    try:
        text = json.dumps(content, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001 - 损坏 content 也不能让分析器整体失败。
        text = str(content)
    return len(text) > _LARGE_RESPONSE_CHAR_THRESHOLD


def _has_truncation_marker(content: Any) -> bool:
    """检测响应中是否带截断标记。

    两条路径：
    - 顶层 dict 中带 ``truncated`` 等字段为 True；
    - JSON 序列化文本中包含明确的 ``...(truncated)`` 等标记。

    不识别 ``…``（U+2026 单字符省略号），因为它常被工具用于"友好显示"
    并非真截断；要求显式英文标记，避免误伤。
    """

    if isinstance(content, dict):
        for key in _TRUNCATION_FIELD_KEYS:
            if bool(content.get(key)):
                return True
    try:
        text = json.dumps(content, ensure_ascii=False, default=str)
    except Exception:  # noqa: BLE001
        text = str(content)
    return any(marker in text for marker in _TRUNCATION_MARKERS)


def _content_field_present(content: Any, field: str) -> bool:
    """判断 content 是否真正提供了某个 required field。

    "提供"的最低标准：key 存在且值不是 None / 空字符串 / 空列表 / 空 dict。
    这避免工具用 ``"evidence": []`` / ``"next_action": ""`` 蒙混过关。
    """

    if not isinstance(content, dict):
        return False
    if field not in content:
        return False
    value = content[field]
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    if isinstance(value, (list, dict)) and len(value) == 0:
        return False
    return True


# ---------------------------------------------------------------------------
# 公共 API：核心分析器
# ---------------------------------------------------------------------------


class TraceSignalAnalyzer:
    """从 raw run 证据派生 trace-derived 信号的分析器。

    构造参数 ``tools_by_name`` 是 "name → ToolSpec" 与 "namespace.name → ToolSpec"
    的合并映射。EvalRunner 在调用前就已经把工具列表索引好，避免 analyzer 反复
    线性扫 ToolSpec 列表。

    **线程安全**：所有方法纯函数，可重入；analyzer 自身不持有可变状态。

    **错误传播策略**：单条 signal 计算抛异常时，**只**跳过该条 signal 并附带
    一个 ``signal_extraction_error`` info 信号说明"哪条规则失败"。这是为了
    保护"复盘"语义——不能因为一条规则 bug 就让整份 diagnosis.json 漏掉
    其他真实可疑信号。
    """

    def __init__(self, tools_by_name: dict[str, ToolSpec] | None = None):
        self._tools = tools_by_name or {}

    def analyze_eval(
        self,
        *,
        eval_id: str,
        user_prompt: str,
        tool_calls: list[dict[str, Any]],
        tool_responses: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """对一条 eval 的 raw 调用/响应序列派生 trace 信号。

        参数：
        - ``eval_id``：用于 evidence_refs 拼装；不影响信号判定。
        - ``user_prompt``：从 EvalSpec 透传，用于 when_not_to_use 关键词匹配。
        - ``tool_calls`` / ``tool_responses``：来自 ``AgentRunResult`` 或从
          磁盘 ``tool_calls.jsonl`` / ``tool_responses.jsonl`` 读出来的列表。

        返回：信号列表。每条信号字段契约（**新字段只增不删**）：
        - ``signal_type`` (str)：信号类别枚举字符串；
        - ``severity`` (str)：``high`` / ``medium`` / ``info``；
        - ``evidence_refs`` (list[str])：指向 raw artifact 的可 grep 锚点；
        - ``related_tool`` (str | None)：与信号最相关的工具名（短名）；
        - ``related_eval`` (str)：触发信号的 eval id；
        - ``why_it_matters`` (str)：中文学习型解释；
        - ``suggested_fix`` (str)：可行动建议。
        """

        signals: list[dict[str, Any]] = []
        # 顺序无关（每条信号自带 evidence_refs），但保持 deterministic：
        # 先 contract 类（按响应顺序），再行为模式类。
        signals.extend(
            self._contract_compliance_signals(eval_id, tool_responses)
        )
        signals.extend(self._repeated_call_signals(eval_id, tool_calls))
        signals.extend(
            self._when_not_to_use_signals(eval_id, user_prompt, tool_calls)
        )
        return signals

    # ------------------------------------------------------------------ contract
    def _contract_compliance_signals(
        self, eval_id: str, tool_responses: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """contract 维度：tool 是否兑现自己的 ``output_contract``。

        三类信号：
        - ``tool_result_no_evidence``：``output_contract.required_fields`` 含
          ``evidence`` 但 content 没给（或给了空列表）；
        - ``tool_result_missing_next_action``：required_fields 含 ``next_action``
          但 content 没给；
        - ``large_or_truncated_tool_response_without_guidance``：响应大或带
          截断标记，但 content 没有 ``next_action``，且 ``token_policy`` 也
          没声明 ``truncation_guidance``。

        为什么把这三个放一起：它们都来自"工具自报契约 vs 工具实际响应"
        的对比，应在同一遍循环里处理，避免重复展开 tool_responses。
        """

        out: list[dict[str, Any]] = []
        for response in tool_responses:
            tool_name = str(response.get("tool_name") or "<unknown>")
            call_id = str(response.get("call_id") or "<unknown>")
            payload = response.get("response") or {}
            content = payload.get("content") if isinstance(payload, dict) else None

            tool_spec = self._lookup_tool(tool_name)
            output_contract = tool_spec.output_contract if tool_spec else {}
            required_fields = list(output_contract.get("required_fields") or [])

            # tool 返回 success=false 已由 TranscriptAnalyzer 归因为 tool_error；
            # 这里只看成功响应的 contract 兑现。
            if isinstance(payload, dict) and payload.get("success") is False:
                continue

            if "evidence" in required_fields and not _content_field_present(content, "evidence"):
                out.append(
                    {
                        "signal_type": "tool_result_no_evidence",
                        "severity": SEVERITY_HIGH,
                        "evidence_refs": [
                            f"tool_responses.jsonl#call_id={call_id} tool_name={tool_name}",
                            f"tools.yaml#name={tool_name} output_contract.required_fields=evidence",
                        ],
                        "related_tool": tool_name,
                        "related_eval": eval_id,
                        "why_it_matters": (
                            f"工具 `{tool_name}` 在 output_contract 中声明会返回 evidence，但本次"
                            "响应里 evidence 字段缺失或为空。Agent 拿不到可引用的证据 id，"
                            "下游 RuleJudge 的 must_use_evidence 规则也会失败；"
                            "**这是工具实现/契约不一致**，不是 Agent 选错工具。"
                        ),
                        "suggested_fix": (
                            "打开工具实现，确保正常路径下 content.evidence 至少返回一条带 id "
                            "的 evidence；如果该场景下确实没有 evidence，请在 tools.yaml 的 "
                            "output_contract.required_fields 中删除 `evidence`，"
                            "并同步 README 工具描述。"
                        ),
                    }
                )

            if "next_action" in required_fields and not _content_field_present(
                content, "next_action"
            ):
                out.append(
                    {
                        "signal_type": "tool_result_missing_next_action",
                        "severity": SEVERITY_MEDIUM,
                        "evidence_refs": [
                            f"tool_responses.jsonl#call_id={call_id} tool_name={tool_name}",
                            (
                                f"tools.yaml#name={tool_name} "
                                "output_contract.required_fields=next_action"
                            ),
                        ],
                        "related_tool": tool_name,
                        "related_eval": eval_id,
                        "why_it_matters": (
                            f"工具 `{tool_name}` 在 output_contract 中声明会返回 next_action，"
                            "但本次响应缺失。Agent 失去显式的下一步指引，可能在没有"
                            "新信息的情况下重复调用同一个工具或自由发挥。"
                        ),
                        "suggested_fix": (
                            "在工具实现中按 Anthropic *Writing effective tools for agents* 的建议"
                            "始终返回 next_action；空场景可以返回 "
                            "next_action='no further action needed' 而不是省略字段。"
                        ),
                    }
                )

            if (_is_response_large(content) or _has_truncation_marker(content)) and not (
                _content_field_present(content, "next_action")
                or (output_contract and output_contract.get("truncation_guidance"))
                or (tool_spec and tool_spec.token_policy.get("truncation_guidance"))
            ):
                out.append(
                    {
                        "signal_type": "large_or_truncated_tool_response_without_guidance",
                        "severity": SEVERITY_MEDIUM,
                        "evidence_refs": [
                            f"tool_responses.jsonl#call_id={call_id} tool_name={tool_name}",
                            f"tools.yaml#name={tool_name} token_policy.truncation_guidance=missing",
                        ],
                        "related_tool": tool_name,
                        "related_eval": eval_id,
                        "why_it_matters": (
                            f"工具 `{tool_name}` 返回了大型或截断响应，但既未提供 next_action，"
                            "工具契约也没有 truncation_guidance。真实 Agent 会被迫在不完整"
                            "信息上下决定，或反复重试，token/latency 都会被吃掉。"
                        ),
                        "suggested_fix": (
                            "为该工具补两件事之一：(a) 在响应里加 next_action 指明"
                            "如何下一步收窄；(b) 在 tools.yaml 的 token_policy 中配置"
                            "truncation_guidance（例如 'narrow by event_id range'），"
                            "让 Agent 显式知道如何分页/过滤。"
                        ),
                    }
                )
        return out

    # ------------------------------------------------------------------ pattern
    def _repeated_call_signals(
        self, eval_id: str, tool_calls: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """模式维度：(tool_name, arguments) 重复 ≥ ``_REPEATED_CALL_MIN_OCCURRENCES`` 次。

        与 TranscriptAnalyzer 的 ``redundant_tool_calls``（连续相同工具）不同：
        本信号要求**参数相同**——这能更精准识别"用相同入参重试"的退化。
        合法的"同一工具不同 trace_id"分析场景因此不会被误伤。
        """

        out: list[dict[str, Any]] = []
        seen: dict[tuple[str, str], list[str]] = {}
        for call in tool_calls:
            tool_name = str(call.get("tool_name") or "<unknown>")
            args = call.get("arguments") or {}
            try:
                args_key = json.dumps(args, ensure_ascii=False, sort_keys=True, default=str)
            except Exception:  # noqa: BLE001
                args_key = str(args)
            seen.setdefault((tool_name, args_key), []).append(
                str(call.get("call_id") or "<unknown>")
            )
        for (tool_name, _args_key), call_ids in seen.items():
            if len(call_ids) < _REPEATED_CALL_MIN_OCCURRENCES:
                continue
            out.append(
                {
                    "signal_type": "repeated_low_value_tool_call",
                    "severity": SEVERITY_MEDIUM,
                    "evidence_refs": [
                        f"tool_calls.jsonl#eval_id={eval_id} tool_name={tool_name} "
                        f"call_ids=[{','.join(call_ids)}]",
                    ],
                    "related_tool": tool_name,
                    "related_eval": eval_id,
                    "why_it_matters": (
                        f"工具 `{tool_name}` 用同一组参数被调用 {len(call_ids)} 次。"
                        "在 deterministic 工具上同参重试不会带来新信息——这通常是"
                        "工具响应没给 next_action、Agent 不知道如何收窄，或是 prompt "
                        "里没说清『调过就别再调』。token / latency 都会被白白吃掉。"
                    ),
                    "suggested_fix": (
                        f"先看 `{tool_name}` 的响应是否有 next_action / 明确的失败原因；"
                        "若没有，就在工具实现里补；若有但 Agent 仍重试，就在 prompt 里"
                        "加 'do not repeat the same tool call with identical arguments' "
                        "并考虑提升工具响应的信息密度。"
                    ),
                }
            )
        return out

    def _when_not_to_use_signals(
        self,
        eval_id: str,
        user_prompt: str,
        tool_calls: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """when_not_to_use 维度：调用了"声明禁用"的工具。

        deterministic 词袋启发式：
        - 从工具的 ``when_not_to_use`` 提取 ≥4 字母关键词（去停用词）；
        - 与 eval 的 ``user_prompt`` 词集取交集；
        - **至少 2 个关键词同时命中**才触发——避免单词撞车假阳性
          （例如 "checkpoint" 同时出现在多个工具的 when_not_to_use 里）。

        这是 deterministic 的反面教材式信号：能稳定指出"工具已经写明
        本场景别用"，但识别"用同义词改写禁用场景"仍需 LLM judge。
        """

        out: list[dict[str, Any]] = []
        prompt_tokens = set(_tokenize(user_prompt))
        called_tools: dict[str, str] = {}
        for call in tool_calls:
            name = str(call.get("tool_name") or "")
            if name and name not in called_tools:
                called_tools[name] = str(call.get("call_id") or "<unknown>")

        for tool_name, call_id in called_tools.items():
            tool_spec = self._lookup_tool(tool_name)
            if tool_spec is None or not tool_spec.when_not_to_use:
                continue
            keywords = _extract_when_not_keywords(tool_spec.when_not_to_use)
            hits = keywords & prompt_tokens
            if len(hits) < 2:
                continue
            sample = sorted(hits)[:4]
            out.append(
                {
                    "signal_type": "tool_selected_in_when_not_to_use_context",
                    "severity": SEVERITY_HIGH,
                    "evidence_refs": [
                        f"tool_calls.jsonl#call_id={call_id} tool_name={tool_name}",
                        f"tools.yaml#name={tool_name} when_not_to_use",
                        f"evals.yaml#id={eval_id} user_prompt",
                    ],
                    "related_tool": tool_name,
                    "related_eval": eval_id,
                    "why_it_matters": (
                        f"工具 `{tool_name}` 的 when_not_to_use 明确提到 "
                        f"{sample}，而本条 eval 的 user_prompt 同时命中了这些关键词。"
                        "这是 deterministic 词袋启发式：很可能 Agent 进入了工具自己"
                        "声明的禁用场景。**这不是语义证明**，需要回 raw transcript "
                        "确认；但作为复盘起点价值高。"
                    ),
                    "suggested_fix": (
                        "看 transcript.jsonl 中 Agent 选用该工具的上下文：(a) 如果"
                        "确实是误用，请检查工具 description / when_to_use 是否同时"
                        "鼓励了这个场景（边界写矛盾）；(b) 如果场景实际合法，请把"
                        "when_not_to_use 写得更精确——避免和合法场景关键词重叠。"
                    ),
                }
            )
        return out

    # ------------------------------------------------------------------ helpers
    def _lookup_tool(self, tool_name: str) -> ToolSpec | None:
        """同时按短名 / qualified name 查找 ToolSpec。

        EvalRunner 已经把两种 key 都塞进 ``tools_by_name``；这里只是简单
        优先短名，再 fallback qualified——避免 mock_replay_adapter 用短名
        而 tools.yaml 里有 namespace 时漏匹配。
        """

        if not tool_name:
            return None
        if tool_name in self._tools:
            return self._tools[tool_name]
        # 短名 fallback：扫一遍找同名（O(n) 但工具数极少）。
        for spec in self._tools.values():
            if spec.name == tool_name:
                return spec
        return None


# ---------------------------------------------------------------------------
# 磁盘 helper：从 run 目录复盘信号
# ---------------------------------------------------------------------------


def analyze_run_dir(
    run_dir: str | Path,
    *,
    tools: list[ToolSpec],
    user_prompts_by_eval: dict[str, str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """从一个已经写好的 run 目录复盘 trace 信号。

    架构边界：
    - **负责**：读取 ``tool_calls.jsonl`` / ``tool_responses.jsonl``，按 eval_id
      分组，调用 :class:`TraceSignalAnalyzer.analyze_eval`，返回
      ``{eval_id: [signal, ...]}``。
    - **不负责**：执行任何工具、修改原 artifact、调用 judge。

    为什么独立出来：未来 ``analyze-artifacts`` CLI（v0.2 backlog，本轮**不**
    实现）可以直接复用本函数；测试也可以用本函数验证"从磁盘 replay"
    与"in-memory 直接分析"得到等价结果。

    ``user_prompts_by_eval`` 为可选参数：磁盘上没有 EvalSpec 原文，调用方
    若希望触发 ``tool_selected_in_when_not_to_use_context`` 必须显式传入；
    否则只覆盖 contract / 重复调用类信号。
    """

    run_dir = Path(run_dir)
    tools_by_name: dict[str, ToolSpec] = {}
    for tool in tools:
        tools_by_name[tool.name] = tool
        if tool.qualified_name and tool.qualified_name != tool.name:
            tools_by_name[tool.qualified_name] = tool

    calls = _read_jsonl(run_dir / "tool_calls.jsonl")
    responses = _read_jsonl(run_dir / "tool_responses.jsonl")

    by_eval_calls: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        by_eval_calls.setdefault(str(call.get("eval_id") or ""), []).append(call)
    by_eval_responses: dict[str, list[dict[str, Any]]] = {}
    for response in responses:
        by_eval_responses.setdefault(str(response.get("eval_id") or ""), []).append(response)

    analyzer = TraceSignalAnalyzer(tools_by_name)
    out: dict[str, list[dict[str, Any]]] = {}
    eval_ids = set(by_eval_calls) | set(by_eval_responses)
    for eval_id in eval_ids:
        if not eval_id:
            continue
        prompt = (user_prompts_by_eval or {}).get(eval_id, "")
        out[eval_id] = analyzer.analyze_eval(
            eval_id=eval_id,
            user_prompt=prompt,
            tool_calls=by_eval_calls.get(eval_id, []),
            tool_responses=by_eval_responses.get(eval_id, []),
        )
    return out


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    """容错 JSONL 读取：单行损坏不让整份分析失败。

    用 ``json.loads`` 逐行解析，损坏行写入 stderr 由调用方决定如何处理。
    本模块不直接 print，避免污染测试输出；调用方可以包一层日志。
    """

    if not path.exists():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:  # noqa: BLE001 - 单行损坏不影响其他行复盘。
            continue
    return out
