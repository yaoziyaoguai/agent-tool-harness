"""Signal quality 标签。

这个模块**不是**一个评分器，而是一个**自我披露机制**。它用一个稳定的字符串告诉报告
读者：当前这次 run 的 PASS/FAIL 信号到底来自什么质量等级的来源。

为什么需要它（架构边界）：
- Anthropic 的 *Writing effective tools for agents* 主张 evaluation 必须由真实 LLM
  agentic loop 驱动；当前 MVP 仍然只用 MockReplayAdapter，把 eval 自带的
  ``expected_tool_behavior.required_tools`` 反向回放。这导致 RuleJudge 的“通过”在结构
  上是必然的，没有携带工具好不好用的信号。
- 我们不想悄悄把这种 PASS 当作真实信号呈现给真实团队。所以 EvalRunner 会把 adapter
  声明的 ``SIGNAL_QUALITY`` 写进 ``metrics.json``，MarkdownReport 会在报告顶部渲染
  显著的能力边界 banner。

这个模块**不**负责：
- 自动判断 adapter 的真实质量。adapter 必须显式声明自己的 SIGNAL_QUALITY。
- 把任何字符串映射成评分。这里只是离散标签 + 人类可读说明。
- 拦截或修复信号质量低的 run。它只做披露，不做判断。

用户项目自定义入口：
- 真实的 OpenAI/Anthropic adapter 落地后，应在 adapter 类上把
  ``SIGNAL_QUALITY = REAL_AGENT`` 显式标出；如果 adapter 走的是历史 transcript 重放
  （未来的 TranscriptReplayAdapter），应使用 ``RECORDED_TRAJECTORY``。

如何通过 artifacts 查问题：
- 看 ``metrics.json`` 的 ``signal_quality`` 字段；
- 看 ``report.md`` 顶部的 banner；
- 看 ``transcript.jsonl`` 的 ``runner_start`` 事件 metadata。

未来扩展点：
- 可加更细的等级（比如区分“真实 LLM + 真实工具”和“真实 LLM + mock 工具”）。
- 可加 per-eval 的 signal_quality 覆盖，区别 sanity 题和真实题。
"""

from __future__ import annotations

# 当前 MVP 的默认等级：
# MockReplayAdapter 直接读取 eval 的期望并回放，judge 几乎必然通过；
# 这个标签明确告诉报告读者：PASS/FAIL 不能被解读为“工具是否真的对 Agent 好用”。
TAUTOLOGICAL_REPLAY = "tautological_replay"

# 给未来 deterministic 但不直接照抄 eval 期望的 adapter 留的等级：
# 例如基于规则、状态机或 transcript 模式生成的 trajectory，仍非真实模型推理。
RULE_DETERMINISTIC = "rule_deterministic"

# 当历史 transcript 回放 adapter 接入后使用：来自真实历史，但不是当前模型的实时决策。
RECORDED_TRAJECTORY = "recorded_trajectory"

# 真实模型 adapter 接入后使用：trajectory 来自当前 LLM 的 agentic loop。
REAL_AGENT = "real_agent"

# adapter 未声明等级时的兜底；报告会按“需谨慎对待”渲染。
UNKNOWN = "unknown"


# 每个等级的人类可读说明，会被写入 metrics.json 和 report.md，
# 让真实团队不需要回到源码也能理解信号边界。
DESCRIPTIONS: dict[str, str] = {
    TAUTOLOGICAL_REPLAY: (
        "MockReplayAdapter reproduces the eval's own expected_tool_behavior; "
        "PASS/FAIL is structurally guaranteed and does NOT measure real Agent capability. "
        "中文：当前为 MVP mock replay，PASS 不代表工具好用，FAIL 不代表工具差。"
    ),
    RULE_DETERMINISTIC: (
        "Adapter emits deterministic rule-driven trajectories without LLM reasoning; "
        "results reflect rule design, not Agent intelligence."
    ),
    RECORDED_TRAJECTORY: (
        "Trajectory replayed from a previously recorded transcript; "
        "useful for regression but not a fresh Agent decision."
    ),
    REAL_AGENT: (
        "Trajectory came from a real LLM agentic loop calling the configured tools."
    ),
    UNKNOWN: (
        "Adapter did not declare SIGNAL_QUALITY; treat results with caution. "
        "中文：adapter 未显式声明信号质量，结果不可作为评估依据。"
    ),
}


def describe(level: str) -> str:
    """返回信号质量等级对应的人类可读说明。

    未知等级返回 UNKNOWN 的说明，而不是抛错；这是因为我们更希望报告里出现一条
    “未知 adapter，请谨慎”的 banner，而不是因为字符串拼错让整次 run 报告生成失败。
    """

    return DESCRIPTIONS.get(level, DESCRIPTIONS[UNKNOWN])
