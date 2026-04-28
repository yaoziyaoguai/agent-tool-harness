"""AnthropicCompatibleJudgeProvider 契约 + 集成测试（v1.x 第二轮 — offline）。

测试纪律说明
============
本文件钉死的边界（任何回归立即失败）：

1. **默认不联网、不读真实 key**：构造 ``AnthropicCompatibleJudgeProvider``
   时不传 transport / 不传 fixture / 不传 key → judge() 必返回脱敏
   ``error.code=disabled_live_provider`` 或 ``missing_config``，**绝不**
   静默 PASS。
2. **缺 config 必脱敏报错**：``AGENT_TOOL_HARNESS_LLM_API_KEY`` 或
   ``AGENT_TOOL_HARNESS_LLM_MODEL`` 未设置时返回 ``missing_config``，
   错误消息**不能**包含任何 key-like / base_url-like 字符串。
3. **Composite + offline_fixture 路径正常**：与 :class:`RuleJudgeProvider`
   组合后 deterministic baseline 不被覆盖、disagreement metrics 正常计数。
4. **fake_transport 错误分类全覆盖**：auth/rate_limited/network/timeout/
   bad_response/provider_error 6 类错误全部经过脱敏走 entry.error 路径，
   metrics.judge_disagreement.error 计数 +1，**不**被误计为分歧。
5. **artifact 不泄漏 secret**：完成 run 后扫描 judge_results.json /
   metrics.json / report.md，禁止出现任何 fake key / fake base_url 子串。
6. **Composite 路径不开网络**：monkeypatch ``socket.socket`` 替换抛错版后
   仍能跑通，证明所有路径都 in-process。

mock/fixture 边界
================
本文件**完全**离线：用 :class:`FakeJudgeTransport` 模拟 transport 行为；
环境变量用 ``monkeypatch.setenv`` 注入 fake key；运行时不打开 socket。
"""

from __future__ import annotations

import json

from agent_tool_harness.cli import main as cli_main
from agent_tool_harness.judges.provider import (
    ANTHROPIC_COMPATIBLE_PROVIDER_NAME,
    ERROR_AUTH,
    ERROR_BAD_RESPONSE,
    ERROR_DISABLED_LIVE,
    ERROR_MISSING_CONFIG,
    ERROR_NETWORK,
    ERROR_PROVIDER,
    ERROR_RATE_LIMITED,
    ERROR_TIMEOUT,
    AnthropicCompatibleConfig,
    AnthropicCompatibleJudgeProvider,
    FakeJudgeTransport,
)

EXAMPLE_PROJECT = "examples/runtime_debug/project.yaml"
EXAMPLE_TOOLS = "examples/runtime_debug/tools.yaml"
EXAMPLE_EVALS = "examples/runtime_debug/evals.yaml"

FAKE_KEY = "sk-fake-test-key-DO-NOT-USE-IN-PROD"
FAKE_BASE_URL = "https://fake-anthropic-compatible.example.invalid"
FAKE_MODEL = "fake-anthropic-compatible-model"


# ---------------------------------------------------------------------------
# Unit tests on the provider class directly (no CLI)
# ---------------------------------------------------------------------------


class _Case:
    """最小化伪 EvalSpec，避免依赖完整 examples/ 加载。"""

    def __init__(self, eval_id: str) -> None:
        self.id = eval_id


class _Run:
    """最小化伪 AgentRunResult；当前 provider 不读 run，占位即可。"""

    tool_calls: list = []
    tool_responses: list = []
    transcript: list = []


def test_default_no_transport_no_fixture_returns_disabled_live():
    """钉死：默认裸构造（没 transport / 没 fixture）→ disabled_live_provider。

    防回归：未来若有人为了"smoke 跑通"在裸 provider 路径偷偷返回 PASS，
    本测试立即失败——v1.x 硬约束是"绝不假成功"。
    """

    cfg = AnthropicCompatibleConfig(api_key=FAKE_KEY, model=FAKE_MODEL)
    provider = AnthropicCompatibleJudgeProvider(config=cfg)
    result = provider.judge(_Case("eval-x"), _Run())
    assert result.passed is False
    assert result.extra["error_code"] == ERROR_DISABLED_LIVE
    # 脱敏：错误 message 不能出现 fake key / fake base_url。
    assert FAKE_KEY not in result.extra["error_message"]
    assert FAKE_BASE_URL not in result.extra["error_message"]


def test_missing_config_reports_missing_config_without_secret_leak():
    """钉死：缺 api_key / model 时返回 missing_config，且不泄漏任何配置值。

    覆盖最危险的场景：用户即便不小心把 key 设成了空串、或忘了设 model，
    错误 message 也只是固定模板，不会回显他设了什么。
    """

    cfg = AnthropicCompatibleConfig(api_key=None, model=FAKE_MODEL)
    provider = AnthropicCompatibleJudgeProvider(config=cfg)
    result = provider.judge(_Case("eval-x"), _Run())
    assert result.extra["error_code"] == ERROR_MISSING_CONFIG
    assert FAKE_KEY not in result.extra["error_message"]
    # repr 也不能泄漏 key（防 logging / pytest 失败摘要泄漏）。
    cfg2 = AnthropicCompatibleConfig(
        api_key=FAKE_KEY, base_url=FAKE_BASE_URL, model=FAKE_MODEL
    )
    assert FAKE_KEY not in repr(cfg2)
    assert FAKE_BASE_URL not in repr(cfg2)


def test_offline_fixture_path_returns_advisory_without_network():
    """钉死：offline_fixture 路径直接读字典，不开 socket，advisory 字段齐全。"""

    cfg = AnthropicCompatibleConfig(api_key=FAKE_KEY, model=FAKE_MODEL)
    fixture = {
        "eval-x": {
            "passed": True,
            "rationale": "offline fixture says PASS",
            "confidence": 0.6,
            "rubric": "evidence-grounded",
        }
    }
    provider = AnthropicCompatibleJudgeProvider(
        config=cfg, offline_fixture=fixture
    )
    assert provider.mode == "offline_fixture"
    result = provider.judge(_Case("eval-x"), _Run())
    assert result.passed is True
    assert result.rationale == "offline fixture says PASS"
    assert result.confidence == 0.6
    assert result.rubric == "evidence-grounded"
    assert result.provider == ANTHROPIC_COMPATIBLE_PROVIDER_NAME
    assert result.extra["model"] == FAKE_MODEL
    assert "error_code" not in result.extra


def test_fake_transport_each_error_taxonomy_is_sanitized():
    """钉死：6 类 transport 错误全部经过脱敏走 error_code 路径。

    covers: auth / rate_limited / network / timeout / bad_response / provider_error
    每一类的 message 都不能包含 fake key / fake base_url；都不能 leak raw exception 字符串。
    """

    cfg = AnthropicCompatibleConfig(api_key=FAKE_KEY, model=FAKE_MODEL)
    for err_code in (
        ERROR_AUTH,
        ERROR_RATE_LIMITED,
        ERROR_NETWORK,
        ERROR_TIMEOUT,
        ERROR_BAD_RESPONSE,
        ERROR_PROVIDER,
    ):
        transport = FakeJudgeTransport(raise_error=err_code)
        provider = AnthropicCompatibleJudgeProvider(
            config=cfg, transport=transport
        )
        assert provider.mode == "fake_transport"
        result = provider.judge(_Case("eval-x"), _Run())
        assert result.passed is False
        assert result.extra["error_code"] == err_code
        msg = result.extra["error_message"]
        assert FAKE_KEY not in msg
        assert FAKE_BASE_URL not in msg
        # 不能直接 echo error_code 的 raw exception 字符串（已脱敏）；只允许包含
        # 固定模板里的中文/英文短语，且不出现"Traceback"等异常细节。
        assert "Traceback" not in msg


def test_fake_transport_success_returns_advisory_passed():
    """钉死：fake transport 成功返回时 provider 透传 passed/rationale 等字段。"""

    cfg = AnthropicCompatibleConfig(api_key=FAKE_KEY, model=FAKE_MODEL)
    transport = FakeJudgeTransport(
        responses={
            "eval-x": {
                "passed": True,
                "rationale": "fake transport advisory PASS",
                "confidence": 0.9,
                "rubric": "evidence-grounded",
            }
        }
    )
    provider = AnthropicCompatibleJudgeProvider(config=cfg, transport=transport)
    result = provider.judge(_Case("eval-x"), _Run())
    assert result.passed is True
    assert result.rationale == "fake transport advisory PASS"
    assert "error_code" not in result.extra


# ---------------------------------------------------------------------------
# CLI integration: anthropic_compatible_offline + Composite + smoke
# ---------------------------------------------------------------------------


def test_cli_anthropic_compatible_offline_records_disagreement(tmp_path, monkeypatch):
    """钉死：CLI anthropic_compatible_offline 路径完整闭环。

    - 注入 fake env（key/model）；
    - 用 fixture 让 advisory PASS、deterministic FAIL（bad path）；
    - 期望 deterministic baseline 不被覆盖、disagreement metrics 反映分歧、
      report 含 Disagreement summary、artifacts 不泄漏 fake key/base_url。
    """

    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_PROVIDER", "anthropic_compatible")
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_BASE_URL", FAKE_BASE_URL)
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_API_KEY", FAKE_KEY)
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_MODEL", FAKE_MODEL)

    fixture = tmp_path / "rec.yaml"
    fixture.write_text(
        "judgments:\n"
        "  runtime_input_boundary_regression:\n"
        "    passed: true\n"
        "    rationale: 'anthropic-compatible offline says PASS'\n"
        "    confidence: 0.8\n"
        "    rubric: 'evidence-grounded'\n",
        encoding="utf-8",
    )
    out = tmp_path / "ac_run"
    rc = cli_main(
        [
            "run",
            "--project", EXAMPLE_PROJECT,
            "--tools", EXAMPLE_TOOLS,
            "--evals", EXAMPLE_EVALS,
            "--out", str(out),
            "--mock-path", "bad",
            "--judge-provider", "anthropic_compatible_offline",
            "--judge-recording", str(fixture),
        ]
    )
    assert rc == 0
    judge_text = (out / "judge_results.json").read_text(encoding="utf-8")
    metrics_text = (out / "metrics.json").read_text(encoding="utf-8")
    report_text = (out / "report.md").read_text(encoding="utf-8")

    # deterministic baseline 不被覆盖。
    judge = json.loads(judge_text)
    assert all(r["passed"] is False for r in judge["results"])
    e = judge["dry_run_provider"]["results"][0]
    # Composite 包裹时 entry.provider="composite"，advisory_result 才是 anthropic。
    assert e["provider"] == "composite"
    assert e["advisory_result"]["provider"] == ANTHROPIC_COMPATIBLE_PROVIDER_NAME
    assert e["advisory_result"]["passed"] is True
    assert e["agreement"] is False  # advisory PASS vs deterministic FAIL
    # disagreement metrics 反映分歧。
    metrics = json.loads(metrics_text)
    assert metrics["judge_disagreement"]["disagree"] == 1
    assert metrics["judge_disagreement"]["disagreement_rate"] == 1.0
    # report 含 disagreement summary + advisory disclaimer。
    assert "Disagreement summary" in report_text
    assert "DO NOT change deterministic pass/fail" in report_text

    # **关键安全断言**：扫描三类 artifact 文本，禁止泄漏 fake key/base_url。
    for blob in (judge_text, metrics_text, report_text):
        assert FAKE_KEY not in blob, "API key leaked into artifact"
        assert FAKE_BASE_URL not in blob, "base_url leaked into artifact"


def test_cli_anthropic_compatible_offline_missing_key_records_error(
    tmp_path, monkeypatch
):
    """钉死：env 缺 key 时 CLI 不崩溃；entry.error.type=missing_config，且不泄漏。

    artifact 中绝不能出现 fake_base_url / fake_model（虽然没设 key，但
    AGENT_TOOL_HARNESS_LLM_BASE_URL 是设了的——脱敏要保证它也不进 artifact）。
    """

    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_PROVIDER", "anthropic_compatible")
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_BASE_URL", FAKE_BASE_URL)
    # 故意不设 AGENT_TOOL_HARNESS_LLM_API_KEY；用 monkeypatch.delenv 显式清除。
    monkeypatch.delenv("AGENT_TOOL_HARNESS_LLM_API_KEY", raising=False)
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_MODEL", FAKE_MODEL)

    fixture = tmp_path / "rec.yaml"
    fixture.write_text(
        "judgments:\n"
        "  runtime_input_boundary_regression:\n"
        "    passed: true\n",
        encoding="utf-8",
    )
    out = tmp_path / "ac_miss_key_run"
    rc = cli_main(
        [
            "run",
            "--project", EXAMPLE_PROJECT,
            "--tools", EXAMPLE_TOOLS,
            "--evals", EXAMPLE_EVALS,
            "--out", str(out),
            "--mock-path", "bad",
            "--judge-provider", "anthropic_compatible_offline",
            "--judge-recording", str(fixture),
        ]
    )
    assert rc == 0
    judge_text = (out / "judge_results.json").read_text(encoding="utf-8")
    metrics_text = (out / "metrics.json").read_text(encoding="utf-8")
    judge = json.loads(judge_text)
    e = judge["dry_run_provider"]["results"][0]
    # advisory 因缺 key 走 error 路径；composite entry.error 必现。
    assert "error" in e
    assert e["error"]["type"] == ERROR_MISSING_CONFIG
    # 错误绝不假成功：entry 不应有 ``passed`` 字段。
    assert "passed" not in e
    # metrics 把错误计入 error 桶，不计分歧。
    metrics = json.loads(metrics_text)
    assert metrics["judge_disagreement"]["error"] == 1
    assert metrics["judge_disagreement"]["disagree"] == 0
    # 安全断言：base_url 不能落到 artifact。
    assert FAKE_BASE_URL not in judge_text
    assert FAKE_BASE_URL not in metrics_text


def test_cli_anthropic_compatible_offline_does_not_open_socket(
    tmp_path, monkeypatch
):
    """钉死：anthropic_compatible_offline 全程不开网络。

    monkeypatch ``socket.socket`` 替成抛错版；只要 provider 任何一步
    动了网络，立即炸——这是 v1.x 不联网硬约束的运行时保险丝。
    """

    import socket

    class _BannedSocket:
        def __init__(self, *a, **kw):
            raise RuntimeError("network socket forbidden in offline judge path")

    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_API_KEY", FAKE_KEY)
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_MODEL", FAKE_MODEL)
    monkeypatch.setenv("AGENT_TOOL_HARNESS_LLM_BASE_URL", FAKE_BASE_URL)
    monkeypatch.setattr(socket, "socket", _BannedSocket)

    fixture = tmp_path / "rec.yaml"
    fixture.write_text(
        "judgments:\n"
        "  runtime_input_boundary_regression:\n"
        "    passed: true\n",
        encoding="utf-8",
    )
    out = tmp_path / "ac_no_net_run"
    rc = cli_main(
        [
            "run",
            "--project", EXAMPLE_PROJECT,
            "--tools", EXAMPLE_TOOLS,
            "--evals", EXAMPLE_EVALS,
            "--out", str(out),
            "--mock-path", "bad",
            "--judge-provider", "anthropic_compatible_offline",
            "--judge-recording", str(fixture),
        ]
    )
    assert rc == 0
    judge = json.loads((out / "judge_results.json").read_text(encoding="utf-8"))
    e = judge["dry_run_provider"]["results"][0]
    # 没有 entry.error 表示 advisory 成功路径走完，且没人尝试开 socket。
    assert "error" not in e, e
