"""JudgeProvider 抽象骨架（v1.1 第一项受控启动）。

本模块负责什么
==============
为未来可插拔 judge（deterministic RuleJudge / dry-run mock LLM judge / 历史
record replay judge / 真实 LLM judge）定义一个**最小契约**：调用方只看
``JudgeProvider.judge(case, run) -> ProviderJudgeResult``，不再关心底层是
substring 规则还是 LLM rationale。

本模块**不**负责什么
====================
- **不调用任何外部 LLM / 网络 / 密钥 / 付费 API**。本轮所有 provider 都是
  in-process、deterministic、零副作用——dry-run / record-only 是硬约束。
- **不替代 RuleJudge**。``RuleJudgeProvider`` 是把现有 :class:`RuleJudge`
  包一层适配，deterministic baseline 完全不变。EvalRunner 默认仍然用
  RuleJudge；本模块**不**改 EvalRunner、**不**改 ``judge_results.json``
  schema、**不**让 mock 结果覆盖 deterministic pass/fail。
- **不做 prompt / rubric / cost / 隐私脱敏**。这些属真实 LLM judge 接入时
  再做（v1.1 后续轮 / v1.2 backlog）。

为什么这样设计
==============
v1.0 已经把 deterministic anti-decoy / evidence grounding 做到了 deterministic
范围内能达到的语义天花板。再往上必须接真实 LLM judge——但**直接接外部 API**
会引入密钥管理、费用、隐私、网络抖动一堆问题。因此 v1.1 先做"契约和抽象"：
让未来真实 LLM judge 落地时，EvalRunner 只需要换一个 provider 实现，不需要
改任何调用方；同时保证现在所有 provider 都 deterministic + offline，便于在
CI 中跑 contract test。

未来扩展点（仅备忘，本轮不实现）
================================
- ``OpenAIJudgeProvider`` / ``AnthropicJudgeProvider``：真实 LLM 调用，
  接收 prompt / rubric / model / temperature；落实密钥与成本治理。
- ``CompositeJudgeProvider``：并列跑多个 provider，把 deterministic baseline
  作为底线、LLM judge 作为 advisory 写入 ``judge_results.json``。
- ``judge_results.json`` schema 升级：每条 check 增加 ``provider`` /
  ``mode`` / ``rationale`` / ``confidence`` / ``rubric`` 字段，
  ``schema_version`` 由当前对外契约 bump 一档。

artifacts 排查路径
==================
本轮**不**改写任何 artifact。如果未来某个 provider 走异常路径，建议在
``judge_results.json::results[].checks[]`` 增加 ``provider_error`` 字段，
而**不是**只改 ``report.md``——避免"只改 report 不改底层证据"反模式。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from agent_tool_harness.agents.agent_adapter_base import AgentRunResult
from agent_tool_harness.config.eval_spec import EvalSpec
from agent_tool_harness.judges.rule_judge import JudgeResult, RuleJudge

PROVIDER_SCHEMA_VERSION = "1.1.0-skeleton"
"""provider 契约的 schema 版本。

- ``1.1.0-skeleton``：仅暴露 Protocol + RuleJudgeProvider + RecordedJudgeProvider，
  EvalRunner 仍直接用 RuleJudge，judge_results.json schema 未变。
- 后续接 LLM judge 时按 SemVer 演进；任何不兼容字段变化必须 bump major。
"""


@dataclass
class ProviderJudgeResult:
    """provider 返回的标准结果包装。

    ``inner`` 仍然是 v1.0 的 :class:`JudgeResult`，保留 deterministic 字段；
    其他字段是 provider 元信息（mode / rationale / confidence / rubric），
    本轮**仅**在 contract test 中被读取，**不**写入 ``judge_results.json``。

    设计意图：如果未来 EvalRunner 决定写入这些字段，只需在
    :func:`JudgeResult.to_dict` 之外再 merge ``metadata()`` 的输出，
    不必改本数据类。
    """

    inner: JudgeResult
    provider: str
    mode: str = "deterministic"
    rationale: str | None = None
    confidence: float | None = None
    rubric: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def eval_id(self) -> str:
        return self.inner.eval_id

    @property
    def passed(self) -> bool:
        return self.inner.passed

    def metadata(self) -> dict[str, Any]:
        """provider 元信息（不含 deterministic checks）。

        EvalRunner 未来若要把 LLM judge 结果写进 ``judge_results.json``，
        建议在每条 check 上挂这个 metadata，**不要**覆盖 ``inner.checks``
        ——deterministic baseline 永远是 ground truth。
        """

        return {
            "provider": self.provider,
            "mode": self.mode,
            "schema_version": PROVIDER_SCHEMA_VERSION,
            "rationale": self.rationale,
            "confidence": self.confidence,
            "rubric": self.rubric,
            **self.extra,
        }


class JudgeProvider(Protocol):
    """v1.1 judge provider 契约。

    实现方必须 deterministic 或显式声明 ``mode != "deterministic"``；
    必须在 ``provider`` 字段写自己的稳定标识；必须能在没有网络 / 密钥的
    环境下被调用（CI / 离线复盘）。如果未来真实 LLM provider 落地，
    它的 ``judge`` 实现仍要在没有 API key 时给出**可行动错误**而不是
    静默返回 PASS。
    """

    name: str
    mode: str

    def judge(self, case: EvalSpec, run: AgentRunResult) -> ProviderJudgeResult:
        ...


class RuleJudgeProvider:
    """把 v1.0 :class:`RuleJudge` 包成 provider。

    本类负责什么
    ------------
    透传 RuleJudge 的 deterministic 判定结果，保证 EvalRunner 默认行为
    100% 不变（mode=``deterministic``）。

    本类**不**负责什么
    ------------------
    不做语义判断、不修改 RuleJudge 的判定逻辑、不增加任何额外检查；
    任何想"在 deterministic 之上叠加 LLM 意见"的需求都属未来
    ``CompositeJudgeProvider``。
    """

    name = "rule"
    mode = "deterministic"

    def __init__(self, judge: RuleJudge | None = None) -> None:
        self._judge = judge or RuleJudge()

    def judge(self, case: EvalSpec, run: AgentRunResult) -> ProviderJudgeResult:
        inner = self._judge.judge(case, run)
        return ProviderJudgeResult(inner=inner, provider=self.name, mode=self.mode)


class RecordedJudgeProvider:
    """从离线 fixture 读取 judge 结果的 provider（dry-run / record-only）。

    本类负责什么
    ------------
    用预先录制的 ``recordings`` dict（``eval_id -> {passed, rationale,
    confidence, rubric}``）模拟"未来 LLM judge 看了 trajectory 之后会
    给什么结论"。**绝**不调用任何外部服务、**绝**不读取磁盘以外的来源。

    本类**不**负责什么
    ------------------
    - 不替代 deterministic 判定。``inner`` 字段会用一个 deterministic
      ``JudgeResult`` 占位（passed 由 recording 决定，但 ``checks`` 仅
      包含一条 ``recorded_judge`` 占位说明，**不**伪装成 RuleJudge 的
      产物）。
    - 不允许 recording 缺失就静默 PASS：如果某个 ``eval_id`` 不在
      recordings 中，会抛出 :class:`MissingRecordingError`，由调用方
      决定是 fail-fast 还是降级到 RuleJudge——"吞异常假成功"是反模式。

    扩展点
    ------
    未来真实 LLM judge 落地后，可以让 ``OpenAIJudgeProvider`` 在 dry-run
    模式下输出与本类相同 shape 的 ``ProviderJudgeResult``，方便 CI 在
    "不调真实 API"的情况下跑回归。
    """

    name = "recorded"
    mode = "dry_run"

    def __init__(self, recordings: dict[str, dict[str, Any]]) -> None:
        # 浅拷贝以避免外部 mutate 改变本 provider 行为；fixture 字段不深嵌
        # 不需要 deepcopy。
        self._recordings = dict(recordings)

    def judge(self, case: EvalSpec, run: AgentRunResult) -> ProviderJudgeResult:
        if case.id not in self._recordings:
            raise MissingRecordingError(
                f"RecordedJudgeProvider has no recording for eval_id={case.id!r}; "
                "either add a recording fixture or fall back to RuleJudgeProvider."
            )
        rec = self._recordings[case.id]
        passed = bool(rec.get("passed", False))
        # 占位 JudgeResult：明确标记 rule.type=recorded_judge，便于调用方
        # 识别这条不是 deterministic check；不要伪装成 RuleJudge 真实规则。
        from agent_tool_harness.judges.rule_judge import RuleCheckResult

        placeholder_check = RuleCheckResult(
            rule={"type": "recorded_judge", "provider": self.name},
            passed=passed,
            message=str(rec.get("rationale", "recorded dry-run judgment")),
        )
        inner = JudgeResult(eval_id=case.id, passed=passed, checks=[placeholder_check])
        return ProviderJudgeResult(
            inner=inner,
            provider=self.name,
            mode=self.mode,
            rationale=rec.get("rationale"),
            confidence=rec.get("confidence"),
            rubric=rec.get("rubric"),
        )


class MissingRecordingError(KeyError):
    """``RecordedJudgeProvider`` 找不到对应 eval_id 的 recording。

    设计意图：这是**可行动错误**，不是 PASS——避免"recording 缺失 → 静默
    通过"成为新的吞异常假成功路径。调用方应当 catch 它并决定 fail-fast
    或降级，而**不**应该在 provider 内部假成功。
    """


class CompositeJudgeProvider:
    """组合 deterministic baseline + advisory provider 的复合 provider（v1.x）。

    本类负责什么
    ------------
    把 deterministic :class:`RuleJudgeProvider`（ground truth）与一个
    advisory :class:`JudgeProvider`（当前实战只会是 :class:`RecordedJudgeProvider`，
    未来可能是真实 LLM provider 的 dry-run 模式）**并列**调用，把两份结果都
    序列化到返回的 ``ProviderJudgeResult.extra`` 里，附带一个布尔
    ``agreement`` 字段标记两者 PASS/FAIL 是否一致——这是 v1.x 让用户在
    不调真实模型的前提下就能拿到"deterministic vs advisory 分歧率"信号的
    最小路径。

    本类**不**负责什么
    ------------------
    - **不**让 advisory 覆盖 deterministic baseline。``inner`` 字段始终是
      deterministic :class:`JudgeResult`；调用方（EvalRunner）拿到的
      ``ProviderJudgeResult.passed`` 也是 deterministic PASS/FAIL。advisory
      意见只能作为"旁路 metadata"消费，不能改写 ``judge_results.json::
      results[].passed``——这是 v1.0 deterministic baseline 永远是 ground
      truth 的政治红线。
    - **不**调用任何外部 LLM / 网络 / 密钥。Composite 自身不开 socket；
      只要传入的两个 sub-provider 都 deterministic + offline，Composite
      也就 deterministic + offline——这一点由契约测试用 monkeypatch 替换
      ``socket.socket`` 钉死。
    - **不**在 advisory provider 抛 :class:`MissingRecordingError` 时静默
      成 PASS。Composite 会把异常**透传**给上层，让 EvalRunner 的
      ``_invoke_dry_run_provider`` 走结构化 ``error`` 路径，而不是把
      "advisory 缺失"伪装成"advisory PASS"。

    用户项目自定义入口
    ------------------
    - CLI: ``agent-tool-harness run --judge-provider composite
      --judge-recording PATH``。
    - Python: 直接构造 ``CompositeJudgeProvider(RuleJudgeProvider(),
      RecordedJudgeProvider({...}))`` 并传给 ``EvalRunner(dry_run_provider=...)``。

    artifacts 排查路径
    ------------------
    - ``judge_results.json::dry_run_provider.results[]``：每条 entry 含
      ``provider="composite" / mode="composite" / passed=<deterministic> /
      agrees_with_deterministic=true / advisory_result={...} /
      deterministic_result={...} / agreement=<bool>``；
      ``rationale/confidence/rubric`` 透传自 advisory；
    - ``metrics.json::judge_disagreement``：聚合分歧率（在 EvalRunner 中
      根据 dry_run_provider.results 计算）；
    - ``report.md → ## Dry-run JudgeProvider (advisory only)`` 段会显式
      渲染分歧条目，并保留 "DO NOT change deterministic pass/fail"
      免责声明。

    未来扩展点
    ----------
    - 把 ``RecordedJudgeProvider`` 换成真实 LLM provider 的 dry-run 模式
      （``OpenAIJudgeProvider``、阿里云 Anthropic-compatible provider 等），
      Composite 不需要任何改动。
    - 支持多 advisory（list 形式）：聚合"多模型 majority vote vs deterministic"
      分歧率——属于 v1.x 后续轮次。
    """

    name = "composite"
    mode = "composite"

    def __init__(
        self,
        deterministic: RuleJudgeProvider,
        advisory: JudgeProvider,
    ) -> None:
        # 显式参数命名让调用现场一眼看出谁是 ground truth；不允许位置参数颠倒。
        self._deterministic = deterministic
        self._advisory = advisory

    def judge(self, case: EvalSpec, run: AgentRunResult) -> ProviderJudgeResult:
        det_result = self._deterministic.judge(case, run)
        # advisory 抛 MissingRecordingError / 其他异常都直接透传，由 EvalRunner
        # 的 _invoke_dry_run_provider 走结构化 error 路径，**不**在这里吞异常。
        adv_result = self._advisory.judge(case, run)
        agreement = bool(det_result.passed) == bool(adv_result.passed)
        # extra 中 advisory_result / deterministic_result 仅含**已落到 artifact
        # 的字段**（passed + provider/mode + 可选 rationale 等），不夹带原始
        # JudgeResult 对象——避免 dataclass 直接进 json.dumps 出错，也防止
        # 把 RuleJudge 的 checks 列表泄漏到 advisory 视图（语义会被误读）。
        return ProviderJudgeResult(
            inner=det_result.inner,
            provider=self.name,
            mode=self.mode,
            rationale=adv_result.rationale,
            confidence=adv_result.confidence,
            rubric=adv_result.rubric,
            extra={
                "agreement": agreement,
                "deterministic_result": {
                    "provider": det_result.provider,
                    "mode": det_result.mode,
                    "passed": det_result.passed,
                },
                "advisory_result": {
                    "provider": adv_result.provider,
                    "mode": adv_result.mode,
                    "passed": adv_result.passed,
                    "rationale": adv_result.rationale,
                    "confidence": adv_result.confidence,
                    "rubric": adv_result.rubric,
                },
            },
        )
