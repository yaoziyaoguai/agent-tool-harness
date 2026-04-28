"""CompositeJudgeProvider 多 advisory majority-vote 聚合契约测试（v1.3）。

中文学习型说明
==============
本文件覆盖的 v1.3 新增能力：

- ``CompositeJudgeProvider(advisory=[adv1, adv2, ...])`` 接受 advisory 列表；
- 输出 ``vote_distribution / majority_passed / advisory_results`` 聚合字段；
- ``majority_passed`` 平票或全 error 时为 ``None``，**不**被 metrics 误算成
  disagree（防吞异常假成功）；
- deterministic baseline **永远**是 ``ProviderJudgeResult.passed``，多
  advisory 聚合**只**作为 advisory metadata；
- 单 advisory 形态（向后兼容）依旧走旧 schema（``advisory_result`` 字段），
  v1.x 第一/二/三轮已落地的 19 条契约测试不会退化。

mock/fixture 边界
================
全部用 in-process 假 ``JudgeProvider``——本测试不联网、不调真实 LLM、不读
真实 key。``_FixedAdvisory`` 是带 ``passed`` 标签的最小 stub；``_ErrorAdvisory``
模拟 advisory 返回结构化 error（带 ``error_code`` 的 ``ProviderJudgeResult``），
用来钉死"error advisory 不计入投票，只计入 error 桶"这条边界。
"""

from __future__ import annotations

from typing import Any

from agent_tool_harness.judges.provider import (
    CompositeJudgeProvider,
    ProviderJudgeResult,
)
from agent_tool_harness.judges.rule_judge import JudgeResult


class _FixedDetermistic:
    """假 deterministic provider，固定 PASS/FAIL；不调 RuleJudge，避免依赖完整 EvalSpec。

    模拟边界：测试只关心 Composite 的聚合行为，不关心 RuleJudge 内部规则。
    保持 ``name="rule_judge"`` 与 ``mode="deterministic"`` 与真实 RuleJudgeProvider
    对齐，让 advisory_results 序列化字段在 reviewer 视角下没差异。
    """

    name = "rule_judge"
    mode = "deterministic"

    def __init__(self, *, passed: bool) -> None:
        self._passed = passed

    def judge(self, case, run) -> ProviderJudgeResult:  # type: ignore[no-untyped-def]
        inner = JudgeResult(eval_id="stub", passed=self._passed, checks=[])
        return ProviderJudgeResult(
            inner=inner,
            provider=self.name,
            mode=self.mode,
        )


class _FixedAdvisory:
    """最小 stub advisory：固定 ``passed`` 标签，不联网，不读 env。"""

    def __init__(self, *, passed: bool, name: str = "stub", mode: str = "stub") -> None:
        self._passed = passed
        self.name = name
        self._mode = mode

    @property
    def mode(self) -> str:
        return self._mode

    def judge(self, case, run) -> ProviderJudgeResult:  # type: ignore[no-untyped-def]
        inner = JudgeResult(eval_id="stub", passed=self._passed, checks=[])
        return ProviderJudgeResult(
            inner=inner,
            provider=self.name,
            mode=self._mode,
            rationale=f"{self.name} says passed={self._passed}",
            confidence=0.5,
        )


class _ErrorAdvisory:
    """模拟 advisory 返回结构化 error（带 ``error_code``）的 stub。

    模拟边界：v1.x 第二轮里 AnthropicCompatible 的"配置缺失 / transport 网
    络错"路径——provider **返回**带 ``error_code`` 的 ProviderJudgeResult，
    不抛异常；Composite 多 advisory 模式下应**不**计入 pass/fail 投票，
    只计入 ``vote_distribution.error``——防吞异常假成功。
    """

    def __init__(self, *, error_code: str = "network_error", name: str = "errored") -> None:
        self._error_code = error_code
        self.name = name

    @property
    def mode(self) -> str:
        return "fake_transport"

    def judge(self, case, run) -> ProviderJudgeResult:  # type: ignore[no-untyped-def]
        inner = JudgeResult(eval_id="stub", passed=False, checks=[])
        extra: dict[str, Any] = {
            "error_code": self._error_code,
            "error_message": "stub error message (sanitized)",
        }
        return ProviderJudgeResult(
            inner=inner,
            provider=self.name,
            mode=self.mode,
            extra=extra,
        )


# case / run 在 stub provider 内部完全未使用；用 None 即可。
_DUMMY_CASE = None
_DUMMY_RUN = None


def test_multi_advisory_majority_pass_majority_passed_true():
    """3 个 advisory：2 PASS / 1 FAIL → majority_passed=True；与 det FAIL 必报分歧。"""

    det = _FixedDetermistic(passed=False)
    adv = [
        _FixedAdvisory(passed=True, name="adv1"),
        _FixedAdvisory(passed=True, name="adv2"),
        _FixedAdvisory(passed=False, name="adv3"),
    ]
    composite = CompositeJudgeProvider(deterministic=det, advisory=adv)
    result = composite.judge(_DUMMY_CASE, _DUMMY_RUN)
    extra = result.extra
    assert "advisory_results" in extra
    # 单 advisory 字段在多 advisory 模式下**不**应出现，避免 reviewer 误读。
    assert "advisory_result" not in extra
    assert len(extra["advisory_results"]) == 3
    vd = extra["vote_distribution"]
    assert vd["pass"] == 2 and vd["fail"] == 1 and vd["error"] == 0 and vd["total"] == 3
    assert extra["majority_passed"] is True
    assert extra["agreement"] is False  # det FAIL vs majority PASS
    # ProviderJudgeResult.passed 必须透传 deterministic，绝不被 majority 改写。
    assert result.passed is False


def test_multi_advisory_majority_passed_agrees_with_deterministic():
    """3 advisory 全 PASS + det PASS → majority_passed=True，agreement=True。"""

    det = _FixedDetermistic(passed=True)
    adv = [_FixedAdvisory(passed=True, name=f"adv{i}") for i in range(3)]
    composite = CompositeJudgeProvider(deterministic=det, advisory=adv)
    result = composite.judge(_DUMMY_CASE, _DUMMY_RUN)
    assert result.extra["majority_passed"] is True
    assert result.extra["agreement"] is True
    assert result.passed is True


def test_multi_advisory_tie_majority_passed_none():
    """2 PASS + 2 FAIL → majority_passed=None；agreement=None；防误算 disagree。"""

    det = _FixedDetermistic(passed=True)
    adv = [
        _FixedAdvisory(passed=True, name="adv1"),
        _FixedAdvisory(passed=False, name="adv2"),
        _FixedAdvisory(passed=True, name="adv3"),
        _FixedAdvisory(passed=False, name="adv4"),
    ]
    composite = CompositeJudgeProvider(deterministic=det, advisory=adv)
    result = composite.judge(_DUMMY_CASE, _DUMMY_RUN)
    extra = result.extra
    assert extra["majority_passed"] is None
    assert extra["agreement"] is None
    vd = extra["vote_distribution"]
    assert vd["pass"] == 2 and vd["fail"] == 2 and vd["error"] == 0


def test_multi_advisory_with_one_error_does_not_count_as_vote():
    """1 PASS + 1 FAIL + 1 error → vote_distribution.error=1，pass=1，fail=1。

    error advisory **不**计入投票（防吞异常假成功）；这里 1:1 平票 → None。
    """

    det = _FixedDetermistic(passed=True)
    adv = [
        _FixedAdvisory(passed=True, name="adv1"),
        _FixedAdvisory(passed=False, name="adv2"),
        _ErrorAdvisory(error_code="rate_limited", name="adv3"),
    ]
    composite = CompositeJudgeProvider(deterministic=det, advisory=adv)
    result = composite.judge(_DUMMY_CASE, _DUMMY_RUN)
    extra = result.extra
    vd = extra["vote_distribution"]
    assert vd["pass"] == 1 and vd["fail"] == 1 and vd["error"] == 1 and vd["total"] == 3
    assert extra["majority_passed"] is None
    error_entries = [a for a in extra["advisory_results"] if "error_code" in a]
    assert len(error_entries) == 1
    assert error_entries[0]["error_code"] == "rate_limited"


def test_multi_advisory_all_error_majority_passed_none():
    """所有 advisory 都 error → majority_passed=None；不能伪造投票结果。"""

    det = _FixedDetermistic(passed=True)
    adv = [
        _ErrorAdvisory(error_code="auth_error", name="adv1"),
        _ErrorAdvisory(error_code="network_error", name="adv2"),
    ]
    composite = CompositeJudgeProvider(deterministic=det, advisory=adv)
    result = composite.judge(_DUMMY_CASE, _DUMMY_RUN)
    extra = result.extra
    vd = extra["vote_distribution"]
    assert vd["pass"] == 0 and vd["fail"] == 0 and vd["error"] == 2
    assert extra["majority_passed"] is None
    assert extra["agreement"] is None
    # 顶层 rationale/confidence/rubric 在全 error 时退化为 None；不能假装有评估意见。
    assert result.rationale is None
    assert result.confidence is None
    assert result.rubric is None


def test_multi_advisory_empty_list_raises_value_error():
    """空 advisory 列表必须立即报错——空配置很可能是 CLI 漏写，不能默默通过。"""

    import pytest

    det = _FixedDetermistic(passed=True)
    with pytest.raises(ValueError, match="至少一个 advisory"):
        CompositeJudgeProvider(deterministic=det, advisory=[])


def test_single_advisory_mode_keeps_v1x_first_round_schema():
    """传单个 advisory（非 list）走旧 schema，advisory_result 字段必须出现，
    advisory_results / majority_passed / vote_distribution 不应出现——
    保证 v1.x 第一/二/三轮已落地的 19 条契约测试不退化。
    """

    det = _FixedDetermistic(passed=True)
    adv = _FixedAdvisory(passed=False, name="adv1")
    composite = CompositeJudgeProvider(deterministic=det, advisory=adv)
    result = composite.judge(_DUMMY_CASE, _DUMMY_RUN)
    extra = result.extra
    assert "advisory_result" in extra
    assert "advisory_results" not in extra
    assert "majority_passed" not in extra
    assert "vote_distribution" not in extra
    assert extra["agreement"] is False  # det PASS vs adv FAIL
    assert result.passed is True  # det baseline 不被覆盖

