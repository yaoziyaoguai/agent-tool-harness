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
        advisory: JudgeProvider | list[JudgeProvider],
    ) -> None:
        # 显式参数命名让调用现场一眼看出谁是 ground truth；不允许位置参数颠倒。
        # advisory 既可以是**单个** JudgeProvider（v1.x 第一轮形态，向后兼容），
        # 也可以是 JudgeProvider 列表（v1.3 多 advisory majority-vote 形态）。
        # 内部统一存成 `_advisories: list`，并用 `_single_advisory_mode` 布尔
        # 区分输出 schema（单 advisory 仍走原 `advisory_result` 字段，避免破坏
        # 已有 artifact / 测试 / report 渲染契约）。
        self._deterministic = deterministic
        if isinstance(advisory, list):
            if not advisory:
                # 空列表是配置错误：让用户立即看到，而不是悄悄全部走 error 路径。
                raise ValueError(
                    "CompositeJudgeProvider 需要至少一个 advisory provider；"
                    "传入空列表通常意味着 CLI 配置漏写，请检查。"
                )
            self._advisories: list[JudgeProvider] = list(advisory)
            self._single_advisory_mode = False
        else:
            self._advisories = [advisory]
            self._single_advisory_mode = True

    def judge(self, case: EvalSpec, run: AgentRunResult) -> ProviderJudgeResult:
        det_result = self._deterministic.judge(case, run)
        # 逐个调用 advisory；任何 advisory 抛异常都直接透传，由 EvalRunner
        # 的 _invoke_dry_run_provider 走结构化 error 路径，**不**在这里吞异常。
        adv_results = [adv.judge(case, run) for adv in self._advisories]

        # 单 advisory 模式：保持 v1.x 第一轮 / 第二轮 / 第三轮 已有 schema 与
        # EvalRunner._invoke_dry_run_provider 的 error_code 透传契约；不引入
        # 任何新字段，避免破坏既有 artifact / 测试。
        if self._single_advisory_mode:
            adv_result = adv_results[0]
            agreement = bool(det_result.passed) == bool(adv_result.passed)
            extra: dict[str, Any] = {
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
            }
            for key in ("error_code", "error_message", "model",
                        "attempts_summary", "retry_count", "usage"):
                if key in adv_result.extra:
                    extra[key] = adv_result.extra[key]
            return ProviderJudgeResult(
                inner=det_result.inner,
                provider=self.name,
                mode=self.mode,
                rationale=adv_result.rationale,
                confidence=adv_result.confidence,
                rubric=adv_result.rubric,
                extra=extra,
            )

        # 多 advisory 模式（v1.3）：聚合 vote_distribution + majority_passed。
        # 设计原则：
        # - 每条 advisory 都序列化到 ``advisory_results[]``（脱敏字段，不夹带
        #   原始 dataclass）；
        # - 错误（带 error_code 的 advisory）**不计入** vote_distribution，
        #   单独算入 ``error`` 桶——避免"advisory 错误"被当成"advisory FAIL"
        #   投票（这是反吞异常假成功的关键路径）；
        # - majority_passed: pass 票多 → True；fail 票多 → False；平票或全
        #   error → None（None 表示无效投票，EvalRunner 会按 None 处理为
        #   "无 agreement 信号"，metrics 不会把它误算成 disagree）；
        # - agreement = (majority_passed == deterministic.passed)，None 时
        #   agreement 也为 None；
        # - rationale/confidence/rubric 取**第一个非 error advisory** 的字段
        #   作为 entry 顶层；详细多 provider rationale 完整保留在
        #   ``advisory_results[]`` 中供 reviewer 排查。
        serialized_advisories: list[dict[str, Any]] = []
        pass_count = 0
        fail_count = 0
        error_count = 0
        for adv_result in adv_results:
            adv_entry: dict[str, Any] = {
                "provider": adv_result.provider,
                "mode": adv_result.mode,
                "passed": adv_result.passed,
                "rationale": adv_result.rationale,
                "confidence": adv_result.confidence,
                "rubric": adv_result.rubric,
            }
            for key in ("error_code", "error_message", "model",
                        "attempts_summary", "retry_count", "usage"):
                if key in adv_result.extra:
                    adv_entry[key] = adv_result.extra[key]
            serialized_advisories.append(adv_entry)
            if "error_code" in adv_result.extra:
                error_count += 1
            elif adv_result.passed:
                pass_count += 1
            else:
                fail_count += 1

        if pass_count > fail_count:
            majority_passed: bool | None = True
        elif fail_count > pass_count:
            majority_passed = False
        else:
            # 平票（含全 error）→ 无效；不强行赋值，避免误导 metrics。
            majority_passed = None

        agreement_multi: bool | None
        if majority_passed is None:
            agreement_multi = None
        else:
            agreement_multi = bool(det_result.passed) == bool(majority_passed)

        # 选 rationale/confidence/rubric 顶层来源：第一个非 error advisory；
        # 全 error 时退化为空字段（EvalRunner 仍会收到结构化 entry，error 走
        # extra 中的 vote_distribution.error 计数 + provider_results 详情）。
        first_non_error = next(
            (a for a in adv_results if "error_code" not in a.extra),
            None,
        )
        rationale = first_non_error.rationale if first_non_error else None
        confidence = first_non_error.confidence if first_non_error else None
        rubric = first_non_error.rubric if first_non_error else None

        extra_multi: dict[str, Any] = {
            "agreement": agreement_multi,
            "majority_passed": majority_passed,
            "vote_distribution": {
                "pass": pass_count,
                "fail": fail_count,
                "error": error_count,
                "total": len(adv_results),
            },
            "deterministic_result": {
                "provider": det_result.provider,
                "mode": det_result.mode,
                "passed": det_result.passed,
            },
            "advisory_results": serialized_advisories,
        }
        return ProviderJudgeResult(
            inner=det_result.inner,
            provider=self.name,
            mode=self.mode,
            rationale=rationale,
            confidence=confidence,
            rubric=rubric,
            extra=extra_multi,
        )


# ---------------------------------------------------------------------------
# Anthropic-compatible JudgeProvider skeleton（v1.x 第二轮 — offline / fake transport）
# ---------------------------------------------------------------------------
#
# 本节负责什么
# ============
# 为未来接入"Anthropic Messages API 兼容"端点（典型如阿里云 Coding Plan
# 的 Anthropic-compatible 协议资源）**先把契约 / 配置 / 错误分类 / 脱敏 /
# artifact schema / 测试边界**全部钉住——但**绝不**在本轮做真实 HTTP
# 请求、**绝不**读取真实 API key、**绝不**联网、**绝不**引入新依赖。
#
# 本节**不**负责什么
# ==================
# - 不做真实 SDK 集成（``anthropic`` / ``httpx`` / ``requests`` 均**不**
#   引入）。本轮只暴露一个注入式 ``JudgeTransport`` 协议，未来真实 HTTP
#   client 落地时只换 transport 实现，provider 主体不动。
# - 不做密钥管理 / 成本治理 / 隐私脱敏 prompt 工程。本轮只确保 error
#   message **不会**回传任何 key-like / Authorization / 完整 base_url
#   query / 完整请求体响应体——这是脱敏底线。
# - 不在 deterministic 路径之外私自走任何降级。Composite + 本 provider 组合
#   时，deterministic baseline 永远是 ground truth。
#
# 为什么这样设计
# ==============
# 用户只能提供"阿里云 Coding Plan Anthropic-compatible 协议资源"，模型 /
# base_url / key 都需要从环境变量按需读取。如果不先把 transport 抽象出来，
# 后续加 HTTP client 时极容易把 key 通过 logging / traceback / response
# body 泄漏到 ``runs/`` artifacts 或 git。这里把"读 env → 校验 → 调
# transport → 分类异常 → 脱敏 → 包装成 ProviderJudgeResult"整条链路写死
# 在一个 provider 里，使得未来加 transport 实现时**所有**安全约束都在已
# 钉住的契约里。
#
# 用户项目自定义入口
# ==================
# - 环境变量：``AGENT_TOOL_HARNESS_LLM_PROVIDER=anthropic_compatible`` /
#   ``AGENT_TOOL_HARNESS_LLM_BASE_URL`` / ``AGENT_TOOL_HARNESS_LLM_API_KEY``
#   / ``AGENT_TOOL_HARNESS_LLM_MODEL``。详见仓库根 ``.env.example``。
# - Python：构造 ``AnthropicCompatibleJudgeProvider(config=..., transport=...,
#   offline_fixture=...)``，传入未来的 HTTP transport 或测试用的
#   ``FakeJudgeTransport``。
#
# artifacts 排查路径
# ==================
# - ``judge_results.json::dry_run_provider.results[].provider="anthropic_compatible"``；
# - ``mode`` 取值：``offline_fixture``（无 transport，从 fixture 读）/
#   ``fake_transport``（注入了 transport）/ 未来 ``live``（真实 HTTP，
#   **本轮不做**）；
# - 失败时 entry 含 ``error={code, message}``，``code`` 走稳定 taxonomy：
#   ``missing_config / disabled_live_provider / auth_error / rate_limited /
#   network_error / timeout / bad_response / provider_error``。
# - ``model`` 字段（如配置）会以**已脱敏**形式落到 entry。base_url 与 key
#   **绝不**落到 artifact。

ANTHROPIC_COMPATIBLE_PROVIDER_NAME = "anthropic_compatible"

# 错误分类常量。新增/重命名一定要 bump PROVIDER_SCHEMA_VERSION。
ERROR_MISSING_CONFIG = "missing_config"
ERROR_DISABLED_LIVE = "disabled_live_provider"
ERROR_AUTH = "auth_error"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_NETWORK = "network_error"
ERROR_TIMEOUT = "timeout"
ERROR_BAD_RESPONSE = "bad_response"
ERROR_PROVIDER = "provider_error"


@dataclass
class AnthropicCompatibleConfig:
    """Anthropic-compatible provider 的配置数据类。

    本类负责什么
    ------------
    把 4 个环境变量（provider/base_url/api_key/model）封装成一个**值对象**，
    并提供 :meth:`from_env` 工厂；任何想"把 env 读取写在 provider 内部"
    的诱惑都被这里拦住——provider 只接受已构造好的 config，便于单元测试
    传入 in-process 假 config 而不污染真实环境变量。

    本类**不**负责什么
    ------------------
    - 不校验 base_url 格式 / 不验证 api_key 真伪——本轮没有真实 HTTP，
      验证留给未来 transport 实现；
    - 不**在任何序列化路径**暴露 ``api_key``。本类故意**不**实现
      ``__str__`` / ``__repr__`` 之外的导出方法，且实现 ``__repr__``
      时屏蔽 ``api_key``。
    """

    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model: str | None = None

    @classmethod
    def from_env(cls, env: dict | None = None) -> AnthropicCompatibleConfig:
        import os as _os

        e = env if env is not None else _os.environ
        return cls(
            provider=e.get("AGENT_TOOL_HARNESS_LLM_PROVIDER") or None,
            base_url=e.get("AGENT_TOOL_HARNESS_LLM_BASE_URL") or None,
            api_key=e.get("AGENT_TOOL_HARNESS_LLM_API_KEY") or None,
            model=e.get("AGENT_TOOL_HARNESS_LLM_MODEL") or None,
        )

    def __repr__(self) -> str:
        # 屏蔽 api_key + base_url 的敏感片段；只暴露是否已设置。
        # 这样 logging / pytest 失败摘要也不会意外打印 secret。
        return (
            f"AnthropicCompatibleConfig(provider={self.provider!r}, "
            f"base_url_set={bool(self.base_url)}, "
            f"api_key_set={bool(self.api_key)}, model={self.model!r})"
        )


class JudgeTransport(Protocol):
    """注入式 transport 契约（本轮只接受 fake / offline transport）。

    本协议负责什么
    --------------
    把"实际发请求"这一步抽象成 ``send(request) -> response`` 一对一的纯
    函数，让 :class:`AnthropicCompatibleJudgeProvider` 完全不知道底层是
    httpx / requests / 还是 in-process fake。未来真实 HTTP 落地时只需提
    供一个新的 transport，provider 主体零改动。

    本协议**不**负责什么
    --------------------
    - 不做重试 / 限流 / 超时治理——这些属未来真实 transport 的实现细节，
      provider 只感知最终结果（成功 / 已分类异常）。
    - 不规定请求 / 响应 schema 的字节细节——本轮 provider 只读 response
      中的 ``passed / rationale / confidence / rubric`` 字段；未来真实
      Anthropic Messages 响应需要适配层把内容字段映射过来。
    """

    def send(self, request: dict) -> dict:
        ...


class FakeJudgeTransport:
    """测试 / smoke 专用的 in-process fake transport。

    本类负责什么
    ------------
    根据初始化时给的 ``responses`` 字典（``eval_id -> {passed, ...}``）
    或 ``raise_error``（错误 taxonomy slug，模拟 transport 抛出何种类别
    的异常）返回固定结果。**不**做任何网络 IO；**不**读取真实 key（构造
    时若不慎传入也会被 ``AnthropicCompatibleJudgeProvider`` 在 send
    之前的脱敏路径处理）。

    本类**不**负责什么
    ------------------
    不模拟真实 Anthropic API 的字节级语义；只提供"成功 / 失败分类"两类
    分支。真实集成测试需要等 live transport 落地后单独覆盖。
    """

    def __init__(
        self,
        responses: dict[str, dict[str, Any]] | None = None,
        raise_error: str | None = None,
    ) -> None:
        self._responses = dict(responses or {})
        self._raise_error = raise_error

    def send(self, request: dict) -> dict:
        if self._raise_error:
            # 用一个内部异常类承载错误分类；provider 会捕获并脱敏。
            raise _FakeTransportError(self._raise_error)
        eval_id = request.get("eval_id")
        if eval_id not in self._responses:
            # 模拟"transport 拿到了请求但响应里没有可解析的判定"——按
            # bad_response 分类，让 provider 走脱敏错误路径。
            raise _FakeTransportError(ERROR_BAD_RESPONSE)
        return dict(self._responses[eval_id])


class _FakeTransportError(Exception):
    """内部用：携带错误分类 slug 的 fake transport 异常。

    用户**永远**不会直接看到此类异常文本——AnthropicCompatibleJudgeProvider
    会捕获它、读取 ``error_code``、构造脱敏 message。
    """

    def __init__(self, error_code: str) -> None:
        super().__init__(error_code)
        self.error_code = error_code


# ---------------------------------------------------------------------------
# v1.4 第一项：LiveAnthropicTransport — 真实 HTTPS transport 骨架（默认 disabled）
# ---------------------------------------------------------------------------
#
# 本节负责什么
# ============
# 在 v1.x 第二轮已经钉死的 ``JudgeTransport`` Protocol 之上，提供一个**基
# 于标准库** ``http.client`` 的真实 HTTPS transport 实现骨架——为未来
# 接入阿里云 Coding Plan Anthropic-compatible endpoint 准备最小可注入
# 的 live-ready 路径。
#
# 本节**不**负责什么
# ==================
# - **不**引入 ``requests`` / ``httpx`` / ``anthropic`` 等第三方依赖；
#   严格用 ``http.client`` + ``ssl`` + ``json`` + ``urllib.parse`` 标准库；
# - **不**在测试 / smoke 中真实联网。所有 contract test 通过 ``http_factory``
#   注入 fake connection，断言 transport 把 HTTP status / 异常正确映射
#   到 8 类 error taxonomy；
# - **不**自己解析 prompt / rubric。LiveAnthropicTransport 把 ``request``
#   dict 直接序列化成 JSON body 发出去；prompt 工程留给 v1.4 第二轮；
# - **不**自己实现 retry / backoff / 限流治理；这些属于 v1.5+ 工程治理。
#
# 默认安全闸门
# ============
# ``LiveAnthropicTransport.__init__`` 接受 ``live_enabled`` /
# ``live_confirmed`` 双标志（与 ``judge-provider-preflight`` 的 CLI 双标
# 志契约一一对应），任一为 ``False`` 时 ``send()`` **直接**抛
# ``_FakeTransportError(ERROR_DISABLED_LIVE)``——绝不会进入 ``http.client``
# 任何分支。这是为了让"用户不小心构造了 LiveAnthropicTransport 但没完
# 整 opt-in"在 artifact 里**显眼**地报错，而不是默默落网。
#
# 错误分类映射
# ============
# - 401 / 403 → ``ERROR_AUTH``
# - 429 → ``ERROR_RATE_LIMITED``
# - 5xx → ``ERROR_PROVIDER``
# - ``socket.timeout`` / ``TimeoutError`` → ``ERROR_TIMEOUT``
# - ``OSError`` / ``socket.gaierror`` / ``ConnectionError`` /
#   ``http.client.HTTPException`` → ``ERROR_NETWORK``
# - 200 但 JSON 解析失败 / 缺关键字段 → ``ERROR_BAD_RESPONSE``
#
# 全部映射后**只**抛 ``_FakeTransportError``——上层 provider 已经在
# v1.x 第二轮把 ``_FakeTransportError`` 的捕获 + 脱敏路径钉死，
# Live transport 复用同一条路径，零新增证据写入面。
#
# 脱敏硬约束
# ==========
# - 永远**不**把 ``base_url`` / ``api_key`` / Authorization header 写
#   入异常 message / raise from / __cause__；只透传 error_code slug；
# - 永远**不**把 raw response body 落入 artifact——transport.send 只
#   返回经过字段提取的小 dict（``passed / rationale / confidence /
#   rubric``）；
# - 永远**不**把 raw exception repr 序列化；上层 provider 只读 ``error_code``。
#
# 未来扩展点（仅备忘）
# ====================
# - retry / backoff（指数退避 + jitter）；
# - 成本上报：每次成功调用记录 token usage 到 ``runs/<run_dir>/llm_cost.json``；
# - 流式响应支持（Anthropic Messages 的 SSE）；
# - 多 endpoint 故障转移（已通过 CompositeJudgeProvider list 形态自然
#   覆盖）。
# ---------------------------------------------------------------------------


class LiveAnthropicTransport:
    """Anthropic-compatible 真实 HTTPS transport 骨架（v1.4，默认 disabled）。

    使用方式
    --------
    1. **测试 / smoke**：传 ``http_factory`` 注入 fake connection，
       ``live_enabled=True``、``live_confirmed=True``、config 完整 →
       transport 走 fake connection 的 ``request()`` / ``getresponse()``
       路径，**不**碰真实 ``http.client.HTTPSConnection``；
    2. **真实 live（v1.4 之外）**：用户在自己环境里完整 opt-in（双标志 +
       4 个 env var）后构造 ``LiveAnthropicTransport(config,
       live_enabled=True, live_confirmed=True)``，``http_factory=None``
       时回落到 ``http.client.HTTPSConnection``——这一分支**不**在 CI /
       smoke 中执行（尽管代码已就位），完全由用户自行触发。

    本类**不**负责什么
    ------------------
    见模块级注释；这里再次强调：不引入新依赖、不在 CI 联网、不写入
    任何 secret 到 artifact / 异常 chain。
    """

    def __init__(
        self,
        config: AnthropicCompatibleConfig,
        *,
        live_enabled: bool = False,
        live_confirmed: bool = False,
        http_factory: Any = None,
        timeout_s: float | None = None,
        max_attempts: int = 1,
        base_delay_s: float = 0.5,
        max_delay_s: float = 8.0,
        retryable_error_codes: tuple[str, ...] | None = None,
        sleep_fn: Any = None,
    ) -> None:
        self._config = config
        # 双标志同时为 True 才认为 user 完整 opt-in；任一缺失 → 走
        # disabled_live_provider 错误路径。这条契约与 CLI
        # ``--live`` + ``--confirm-i-have-real-key`` 一一对应。
        self._enabled = bool(live_enabled and live_confirmed)
        # http_factory 用于注入 fake connection（contract test）。签名约定：
        # ``http_factory(host: str, port: int, timeout: float) -> conn``，
        # conn 必须有 ``request(method, path, body, headers)`` 与
        # ``getresponse() -> resp``，resp 必须有 ``status`` 与 ``read()``。
        # 默认 None 时回落到 ``http.client.HTTPSConnection``——但只有真
        # 实 live 路径会触发，CI / smoke 不会走到这里。
        self._http_factory = http_factory
        # timeout 来源优先级：显式参数 > env var > 默认 30s；硬上限 120s
        # 防"无限等"路径让用户体感更安全。
        if timeout_s is None:
            try:
                import os as _os
                env_v = _os.environ.get("AGENT_TOOL_HARNESS_LLM_REQUEST_TIMEOUT_S")
                timeout_s = float(env_v) if env_v else 30.0
            except (ValueError, TypeError):
                timeout_s = 30.0
        self._timeout_s = max(1.0, min(120.0, float(timeout_s)))
        # v1.6 第一项：retry/backoff 治理。设计边界：
        # - 默认 ``max_attempts=1`` → 无重试，与 v1.5 字节兼容；
        # - 只对**可重试**的 8 类 error_code 子集做指数退避（默认仅
        #   rate_limited / network_error / timeout）；auth_error /
        #   missing_config / disabled_live_provider / bad_response /
        #   provider_error 永远不重试——这些重试只会放大账单或泄漏；
        # - 退避公式：``min(max_delay, base_delay * 2 ** (attempt-1))``，
        #   不引入 jitter / 不引入新依赖；CI 用 ``sleep_fn`` 注入 fake
        #   clock 钉死序列；
        # - retry 决策与序列化的 ``attempts_summary`` 写入 advisory 结果
        #   ``extra`` 中（由 AnthropicCompatibleJudgeProvider 透传），方便
        #   reviewer 在 ``judge_results.json`` / ``llm_cost.json`` 排查。
        self._max_attempts = max(1, int(max_attempts))
        self._base_delay_s = max(0.0, float(base_delay_s))
        self._max_delay_s = max(self._base_delay_s, float(max_delay_s))
        self._retryable_codes = tuple(
            retryable_error_codes
            if retryable_error_codes is not None
            else (ERROR_RATE_LIMITED, ERROR_NETWORK, ERROR_TIMEOUT)
        )
        # sleep_fn 默认走 ``time.sleep``；测试 / smoke 注入 lambda 记录调用
        # 序列即可，永远不真实 sleep。
        if sleep_fn is None:
            import time as _time

            sleep_fn = _time.sleep
        self._sleep_fn = sleep_fn
        # 最近一次 send 的 attempts_summary，由 send() 写入。AnthropicCompatible
        # JudgeProvider.judge() 会在 send 返回/抛错后读取并写入 ProviderJudge
        # Result.extra；外部不要直接依赖这个属性。
        self.last_attempts_summary: list[dict] = []

    @property
    def is_live_ready(self) -> bool:
        """供调用方 / 报告显示用：本 transport 当前是否完整 opt-in。

        注意：``True`` 仅表示**有资格**调网络，**不**表示一定会调；
        ``send()`` 仍会校验 config 字段。
        """

        return self._enabled

    def send(self, request: dict) -> dict:
        """发送一次 request；可重试 error 按配置重试，其它立即抛错。

        v1.6 第一项扩展：retry/backoff 在本方法外层做 deterministic 包裹。
        每次尝试调用内部 ``_send_once()``；命中 retryable error_code →
        计算退避 → 调 ``sleep_fn`` → 进入下一次 attempt；其它 error 立刻
        抛出。最终把 attempts 序列写入 ``self.last_attempts_summary``，
        由 :class:`AnthropicCompatibleJudgeProvider` 在外层读取。

        本方法不打印 secret；任何 raw exception 都已经在 ``_send_once``
        被映射成 ``_FakeTransportError(error_code)``。
        """

        attempts: list[dict] = []
        last_exc: _FakeTransportError | None = None
        for attempt_idx in range(1, self._max_attempts + 1):
            try:
                result = self._send_once(request)
                attempts.append({"attempt": attempt_idx, "outcome": "success"})
                self.last_attempts_summary = attempts
                return result
            except _FakeTransportError as exc:
                last_exc = exc
                attempts.append(
                    {"attempt": attempt_idx, "outcome": "error", "error_code": exc.error_code}
                )
                # 不可重试 → 立即抛；或者用尽 max_attempts → 立即抛。
                if exc.error_code not in self._retryable_codes:
                    self.last_attempts_summary = attempts
                    raise
                if attempt_idx >= self._max_attempts:
                    self.last_attempts_summary = attempts
                    raise
                # 指数退避：min(max_delay, base * 2^(attempt-1))。
                delay = min(
                    self._max_delay_s,
                    self._base_delay_s * (2 ** (attempt_idx - 1)),
                )
                attempts[-1]["sleep_s"] = delay
                self._sleep_fn(delay)
        # 理论不可达；保险起见。
        self.last_attempts_summary = attempts
        if last_exc is not None:
            raise last_exc
        raise _FakeTransportError(ERROR_PROVIDER)

    def _send_once(self, request: dict) -> dict:
        """发送一次 request；任何分类错误统一抛 ``_FakeTransportError``。

        本方法不做 retry / 不做日志 / 不打印 secret；调用方 :meth:`send`
        负责重试；上层 provider 负责脱敏。
        """

        if not self._enabled:
            # 双标志未完整 opt-in → 立即拒绝；不调任何 socket / http.client。
            raise _FakeTransportError(ERROR_DISABLED_LIVE)
        if (
            not self._config.base_url
            or not self._config.api_key
            or not self._config.model
        ):
            # 完整 opt-in 但 config 不全 → missing_config；上层走脱敏路径。
            raise _FakeTransportError(ERROR_MISSING_CONFIG)

        # 解析 base_url；任何解析异常（不合法 URL）→ network 路径，避免
        # 用 raw URL 字符串构造异常 chain 泄漏。
        from urllib.parse import urlsplit
        try:
            parts = urlsplit(self._config.base_url)
            host = parts.hostname
            port = parts.port or (443 if parts.scheme == "https" else 80)
            path = parts.path or "/v1/messages"
        except Exception:
            raise _FakeTransportError(ERROR_NETWORK) from None
        if not host:
            raise _FakeTransportError(ERROR_NETWORK)

        # 构造 connection。优先用注入 factory（测试用）；否则回落 stdlib。
        # 这里**故意**用懒导入：CI 默认走 http_factory 路径，根本不需要
        # import http.client，进一步降低"测试时不小心 import 真实 client"
        # 的风险。
        try:
            if self._http_factory is not None:
                conn = self._http_factory(host, port, self._timeout_s)
            else:
                from http.client import HTTPSConnection
                conn = HTTPSConnection(host, port, timeout=self._timeout_s)
        except Exception:
            raise _FakeTransportError(ERROR_NETWORK) from None

        # 序列化请求 body：固定 JSON；headers 不写入任何 raw secret 到日志。
        # Authorization header 是必须的，但仅在 send 调用栈里短暂存在；
        # **不**写入异常 message、不写入 artifact。
        import json as _json

        try:
            body = _json.dumps(request, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError):
            raise _FakeTransportError(ERROR_BAD_RESPONSE) from None

        headers = {
            "Content-Type": "application/json",
            "X-Api-Key": self._config.api_key,
            "Anthropic-Version": "2023-06-01",
            "Accept": "application/json",
        }

        try:
            conn.request("POST", path, body=body, headers=headers)
            resp = conn.getresponse()
            status = int(getattr(resp, "status", 0))
            raw = resp.read()
        except TimeoutError:
            raise _FakeTransportError(ERROR_TIMEOUT) from None
        except OSError as exc:
            # socket.timeout 在 Py3.10+ 是 TimeoutError 的别名；老版本走
            # 这里。任何 socket 级错误一律映射为 network/timeout，**不**
            # 透传 raw exception。
            if "timed out" in str(exc).lower():
                raise _FakeTransportError(ERROR_TIMEOUT) from None
            raise _FakeTransportError(ERROR_NETWORK) from None
        except Exception:
            # http.client.HTTPException 等其它异常：归 network。
            raise _FakeTransportError(ERROR_NETWORK) from None
        finally:
            try:
                conn.close()
            except Exception:
                pass

        # HTTP 状态码映射；分类与 v1.x 第二轮 8 类 taxonomy 完全对齐。
        if status in (401, 403):
            raise _FakeTransportError(ERROR_AUTH)
        if status == 429:
            raise _FakeTransportError(ERROR_RATE_LIMITED)
        if 500 <= status < 600:
            raise _FakeTransportError(ERROR_PROVIDER)
        if status != 200:
            # 其它非 2xx 状态：归 bad_response（不暴露具体 status code 给
            # 用户，避免被 fingerprint）。
            raise _FakeTransportError(ERROR_BAD_RESPONSE)

        # 200 OK：解析 body；任何 JSON 解析 / 字段缺失都归 bad_response。
        try:
            payload = _json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, _json.JSONDecodeError):
            raise _FakeTransportError(ERROR_BAD_RESPONSE) from None
        if not isinstance(payload, dict) or "passed" not in payload:
            raise _FakeTransportError(ERROR_BAD_RESPONSE)

        # 只回传 4 个公开字段；不夹带 raw response 给上层（防泄漏 +
        # 防 schema drift）。
        return {
            "passed": bool(payload.get("passed")),
            "rationale": payload.get("rationale"),
            "confidence": payload.get("confidence"),
            "rubric": payload.get("rubric"),
        }


def _safe_message(error_code: str) -> str:
    """根据错误分类返回固定的安全提示文本（**不**含任何用户输入）。

    设计意图：拒绝把 transport 抛出的原始 message 直接 echo 出去——
    raw exception 文本经常包含 base_url、Authorization header 片段、
    完整请求体响应体。这里返回的是固定模板，永远不会泄漏 secret。
    """

    table = {
        ERROR_MISSING_CONFIG: (
            "AnthropicCompatibleJudgeProvider 缺必要配置 "
            "(AGENT_TOOL_HARNESS_LLM_API_KEY 或 _MODEL)；"
            "见 .env.example。"
        ),
        ERROR_DISABLED_LIVE: (
            "live transport 在本轮被显式禁用；本 provider 仅支持 "
            "offline_fixture 或 fake_transport 模式。"
        ),
        ERROR_AUTH: "transport 报告认证失败（auth_error，已脱敏）。",
        ERROR_RATE_LIMITED: "transport 报告被限流（rate_limited，已脱敏）。",
        ERROR_NETWORK: "transport 报告网络错误（network_error，已脱敏）。",
        ERROR_TIMEOUT: "transport 报告超时（timeout，已脱敏）。",
        ERROR_BAD_RESPONSE: "transport 返回不可解析的响应（bad_response，已脱敏）。",
        ERROR_PROVIDER: "provider 未分类错误（provider_error，已脱敏）。",
    }
    return table.get(error_code, "provider 错误（未分类，已脱敏）。")


class AnthropicCompatibleJudgeProvider:
    """Anthropic-compatible judge provider skeleton（v1.x 第二轮 — offline）。

    实战行为
    --------
    - **未注入 transport** 且 **未给 offline_fixture** → 每次 judge 返回
      ``error.code=disabled_live_provider``，绝不落入"静默 PASS"。
    - **未注入 transport** 但给了 ``offline_fixture`` → ``mode=
      offline_fixture``，按 fixture 构造 advisory result。
    - **注入了 fake transport** → ``mode=fake_transport``，调 transport，
      捕获 :class:`_FakeTransportError` 走脱敏 error 路径；transport 正常
      返回则按响应字段构造 advisory result。
    - 在以上任何路径下，若 ``config.api_key`` 或 ``config.model`` 缺失，
      **优先**返回 ``missing_config`` 错误——避免"配置缺失但 fixture 命中
      就给 PASS"成为新的吞异常假成功路径。

    本类**不**负责什么
    ------------------
    - 不做任何真实网络调用。**真实 HTTP transport 不在本轮落地范围**。
    - 不修改 deterministic baseline。返回的 ``ProviderJudgeResult.passed``
      仅作为 advisory；与 :class:`CompositeJudgeProvider` 组合时
      deterministic 仍是 ground truth。
    - 不打印 / 序列化任何 secret。错误 message 全部走 :func:`_safe_message`
      固定模板。

    未来扩展点
    ----------
    - ``LiveAnthropicTransport``：真实 HTTP client（基于 stdlib ``http.client``
      或在用户明确允许后引入轻量依赖），覆盖 auth/retry/timeout 治理；
    - prompt / rubric 的真实组装；
    - 多 advisory / 投票聚合（接入 :class:`CompositeJudgeProvider` 的 list
      形式扩展）。
    """

    name = ANTHROPIC_COMPATIBLE_PROVIDER_NAME

    def __init__(
        self,
        config: AnthropicCompatibleConfig,
        transport: JudgeTransport | None = None,
        offline_fixture: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self._config = config
        self._transport = transport
        self._offline_fixture = dict(offline_fixture or {})

    @property
    def mode(self) -> str:
        if self._transport is not None:
            return "fake_transport"
        return "offline_fixture"

    def judge(self, case: EvalSpec, run: AgentRunResult) -> ProviderJudgeResult:
        # 占位 deterministic JudgeResult：本 provider 是 advisory，inner.passed
        # 不应被消费方当成 deterministic baseline；CompositeJudgeProvider 会用
        # 真正的 RuleJudgeProvider 提供 deterministic baseline。
        from agent_tool_harness.judges.rule_judge import RuleCheckResult

        def _wrap(passed: bool, message: str, error_code: str | None = None,
                  rationale: str | None = None, confidence: float | None = None,
                  rubric: str | None = None,
                  attempts_summary: list[dict] | None = None,
                  usage: dict[str, Any] | None = None) -> ProviderJudgeResult:
            placeholder = RuleCheckResult(
                rule={"type": "anthropic_compatible_provider", "provider": self.name},
                passed=passed,
                message=message,
            )
            inner = JudgeResult(eval_id=case.id, passed=passed, checks=[placeholder])
            extra: dict[str, Any] = {"model": self._config.model}
            if error_code is not None:
                # 错误信息走脱敏模板；**绝不**夹带 raw exception / key / url。
                extra["error_code"] = error_code
                extra["error_message"] = _safe_message(error_code)
            # v1.6 第一项：把 transport.last_attempts_summary 透传到
            # advisory ``extra``。reviewer 可以在 ``judge_results.json`` 直接
            # 看到每次 attempt 的 outcome / error_code / sleep_s——这是
            # retry/backoff 治理的"证据落地"。
            if attempts_summary:
                extra["attempts_summary"] = attempts_summary
                extra["retry_count"] = max(0, len(attempts_summary) - 1)
            # v1.6 第二项：把 token usage 透传给 EvalRunner 聚合。
            # 任何缺失都不在这里 fabricate；EvalRunner 会按 cost_unknown_reason
            # 显式记录。
            if usage:
                extra["usage"] = usage
            return ProviderJudgeResult(
                inner=inner,
                provider=self.name,
                mode=self.mode,
                rationale=rationale,
                confidence=confidence,
                rubric=rubric,
                extra=extra,
            )

        # Step 1：硬性 config 校验。api_key + model 任一缺失就直接 missing_config。
        if not self._config.api_key or not self._config.model:
            return _wrap(False, _safe_message(ERROR_MISSING_CONFIG),
                         error_code=ERROR_MISSING_CONFIG)

        # Step 2：走 transport（fake）或 offline_fixture。
        if self._transport is not None:
            request = {
                "eval_id": case.id,
                "model": self._config.model,
            }
            # 提前抓 transport 上的 attempts_summary（如果属性存在），
            # 不存在则传空列表——FakeAnthropicTransport 可能没有 retry 治理。
            try:
                response = self._transport.send(request)
            except _FakeTransportError as exc:
                attempts = list(getattr(self._transport, "last_attempts_summary", []) or [])
                return _wrap(False, _safe_message(exc.error_code),
                             error_code=exc.error_code,
                             attempts_summary=attempts)
            except Exception:  # noqa: BLE001 - 防御 transport 抛出未分类异常
                attempts = list(getattr(self._transport, "last_attempts_summary", []) or [])
                # 不把 raw exception 序列化进 artifact——只落分类 + 安全模板文本。
                return _wrap(False, _safe_message(ERROR_PROVIDER),
                             error_code=ERROR_PROVIDER,
                             attempts_summary=attempts)
            if not isinstance(response, dict) or "passed" not in response:
                attempts = list(getattr(self._transport, "last_attempts_summary", []) or [])
                return _wrap(False, _safe_message(ERROR_BAD_RESPONSE),
                             error_code=ERROR_BAD_RESPONSE,
                             attempts_summary=attempts)
            attempts = list(getattr(self._transport, "last_attempts_summary", []) or [])
            usage = response.get("usage") if isinstance(response.get("usage"), dict) else None
            return _wrap(
                bool(response.get("passed")),
                str(response.get("rationale", "fake transport advisory")),
                rationale=response.get("rationale"),
                confidence=response.get("confidence"),
                rubric=response.get("rubric"),
                attempts_summary=attempts,
                usage=usage,
            )

        # offline_fixture 路径
        if case.id not in self._offline_fixture:
            return _wrap(False, _safe_message(ERROR_DISABLED_LIVE),
                         error_code=ERROR_DISABLED_LIVE)
        rec = self._offline_fixture[case.id]
        usage = rec.get("usage") if isinstance(rec.get("usage"), dict) else None
        return _wrap(
            bool(rec.get("passed", False)),
            str(rec.get("rationale", "offline fixture advisory")),
            rationale=rec.get("rationale"),
            confidence=rec.get("confidence"),
            rubric=rec.get("rubric"),
            usage=usage,
        )
