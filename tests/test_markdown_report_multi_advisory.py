"""v1.5 第二轮契约测试：MarkdownReport multi-advisory 可读性渲染。

本测试模块负责什么
==================
钉住 v1.5 第二轮 ``_render_dry_run_provider`` 多 advisory 可读性扩展：

1. **多 advisory 一致**：所有 advisory passed=True → report 主行
   majority_passed=True + votes 计数；每条 advisory 单独缩进展开
   provider/passed/rationale/confidence；
2. **多 advisory 分歧**：1 pass + 1 fail → majority_passed=None (inconclusive)
   仍展开两条 sub-bullet；deterministic baseline 仍是唯一 pass/fail；
3. **advisory 失败（含 error_code）**：error_code/error_message + 固定
   suggested_fix 出现在 report 中；不允许 silent pass；
4. **未识别 error_code**：fallback 通用 hint；不崩；
5. **secret 不进 report**：fake key/url 字面量在任何 multi-advisory rendering
   分支都不会出现在 report.md（防回归扫描）；
6. **默认 RuleJudge 路径不退化**：未启用 dry-run provider 时 ``Dry-run
   JudgeProvider`` 段不渲染（v1.0 字节兼容）。

本模块**不**负责什么
====================
- 不真实联网；所有 advisory 用 dataclass-style dict 直接喂渲染函数；
- 不验证 EvalRunner 写入逻辑——已由 ``test_eval_runner_judge_provider.py``
  与 ``test_composite_multi_advisory.py`` 覆盖。
"""

from __future__ import annotations

from agent_tool_harness.reports.markdown_report import (
    _ADVISORY_SUGGESTED_FIX,
    MarkdownReport,
)


def _judge_results_with_advisories(
    advisories: list[dict],
    *,
    deterministic_passed: bool,
    majority_passed: bool | None,
    vote_distribution: dict,
) -> dict:
    """构造一份合法的 ``judge_results.json::dry_run_provider`` 多 advisory 数据。

    深思熟虑：本 helper **不**调用任何 provider；只是手工拼出渲染函数依赖
    的字段子集。这样一来，本模块的测试只盯渲染层契约，与 provider 真实
    业务解耦，能更精准定位 bug 来源。
    """

    return {
        "dry_run_provider": {
            "results": [
                {
                    "eval_id": "demo_eval",
                    "provider": "composite",
                    "mode": "composite",
                    "deterministic_passed": deterministic_passed,
                    "passed": deterministic_passed,
                    "agrees_with_deterministic": True,
                    "majority_passed": majority_passed,
                    "vote_distribution": vote_distribution,
                    "advisory_results": advisories,
                }
            ],
            "schema_version": "1.1.0-skeleton",
        },
    }


def _render(judge_results: dict) -> str:
    rep = MarkdownReport()
    return "\n".join(rep._render_dry_run_provider(judge_results))


def test_multi_advisory_consensus_renders_each_advisory():
    advisories = [
        {
            "provider": "recorded",
            "mode": "dry_run",
            "passed": True,
            "rationale": "advisory A says pass",
            "confidence": 0.9,
        },
        {
            "provider": "anthropic_compatible",
            "mode": "fake_transport",
            "passed": True,
            "rationale": "advisory B says pass",
            "confidence": 0.8,
        },
    ]
    text = _render(
        _judge_results_with_advisories(
            advisories,
            deterministic_passed=True,
            majority_passed=True,
            vote_distribution={"pass": 2, "fail": 0, "error": 0, "total": 2},
        )
    )
    assert "majority_passed=True" in text
    assert "votes pass=2 fail=0 error=0 total=2" in text
    # 每条 advisory 都展开 sub-bullet
    assert "advisory [recorded/dry_run]" in text
    assert "advisory [anthropic_compatible/fake_transport]" in text
    assert "rationale=advisory A says pass" in text
    assert "rationale=advisory B says pass" in text
    # 顶部 disclaimer 必须强调 deterministic 不被覆盖
    assert "DO NOT change deterministic" in text


def test_multi_advisory_disagreement_renders_inconclusive():
    advisories = [
        {"provider": "recorded", "mode": "dry_run", "passed": True, "confidence": 0.7},
        {"provider": "recorded", "mode": "dry_run", "passed": False, "confidence": 0.6},
    ]
    text = _render(
        _judge_results_with_advisories(
            advisories,
            deterministic_passed=False,
            majority_passed=None,
            vote_distribution={"pass": 1, "fail": 1, "error": 0, "total": 2},
        )
    )
    assert "majority_passed=None" in text  # inconclusive
    # deterministic 行仍展示自己的 False
    assert "deterministic_passed=False" in text
    assert "passed=True" in text
    assert "passed=False" in text


def test_multi_advisory_error_renders_suggested_fix():
    """错误 advisory 必须有 error_code + suggested_fix；不允许 silent pass。"""

    advisories = [
        {"provider": "recorded", "mode": "dry_run", "passed": True, "confidence": 0.5},
        {
            "provider": "recorded",
            "mode": "dry_run",
            "error_code": "missing_recording",
            "error_message": "demo_eval 缺 judgment 录音",
        },
    ]
    text = _render(
        _judge_results_with_advisories(
            advisories,
            deterministic_passed=True,
            majority_passed=True,
            vote_distribution={"pass": 1, "fail": 0, "error": 1, "total": 2},
        )
    )
    assert "error: missing_recording" in text
    assert "demo_eval 缺 judgment 录音" in text
    # suggested_fix 来自固定表
    assert _ADVISORY_SUGGESTED_FIX["missing_recording"] in text


def test_multi_advisory_unknown_error_code_uses_fallback_hint():
    advisories = [
        {
            "provider": "recorded",
            "mode": "dry_run",
            "error_code": "totally_new_error",
            "error_message": "msg",
        },
    ]
    text = _render(
        _judge_results_with_advisories(
            advisories,
            deterministic_passed=True,
            majority_passed=None,
            vote_distribution={"pass": 0, "fail": 0, "error": 1, "total": 1},
        )
    )
    assert "totally_new_error" in text
    # fallback hint 关键句应出现
    assert "judge_results.json" in text
    assert "不要回填真实 key/url" in text


def test_multi_advisory_does_not_leak_keylike_strings():
    """fake-key / fake-url 即便混入 rationale/error_message 也只能逐字展示，
    不能被代码额外加工进 hint；本测试钉死渲染层不会泄漏额外字面量。"""

    fake_key = "sk-fake-key-must-not-leak-elsewhere"
    fake_url = "https://fake-leak-host.local/v1"
    advisories = [
        {
            "provider": "recorded",
            "mode": "dry_run",
            "error_code": "auth_error",
            "error_message": f"upstream said {fake_key}",
        },
    ]
    text = _render(
        _judge_results_with_advisories(
            advisories,
            deterministic_passed=True,
            majority_passed=None,
            vote_distribution={"pass": 0, "fail": 0, "error": 1, "total": 1},
        )
    )
    # 渲染必须保留 error_message 原文；但渲染函数本身不能再注入新 url/key 字面量
    assert text.count(fake_key) == 1
    assert fake_url not in text


def test_default_no_dry_run_provider_segment():
    """v1.0 字节兼容回归：未设 dry_run_provider 字段 → 渲染返回空 list。"""

    rep = MarkdownReport()
    out = rep._render_dry_run_provider({})
    assert out == []
    out2 = rep._render_dry_run_provider({"dry_run_provider": {"results": []}})
    assert out2 == []
