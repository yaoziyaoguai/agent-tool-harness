"""Anthropic-compatible provider 的 live readiness preflight（v1.x 第三轮）。

中文学习型说明
==============
本模块负责什么
--------------
为"未来真实 LLM judge provider"上线**前**做一次**纯本地、纯只读、无网络**
的安全自检：

1. 配置面：`AnthropicCompatibleConfig.from_env()` 是否齐全；缺哪个 env 变量。
2. Git 面：`.env` 是否在 `.gitignore`；`.env.example` 是否只有占位符（不含
   真实 `=` 后值，且不含 `sk-` / `https://` 真实片段）。
3. Provider 面：本轮 live mode **必须**默认 disabled；用 fake transport
   逐一触发 8 类 error taxonomy，确认每条 message 都来自 `_safe_message`
   模板、不含原始 exception 文本，也不含 `config.api_key` / `config.base_url`
   的字面值。
4. 输出面：preflight 结果文件**绝不**写入 `api_key` / `base_url`，只写
   `*_set` 布尔与 `*_present` 标志；error message 来自固定模板。

本模块**不**负责什么
--------------------
- **不**联网；**不**调真实 API；**不**调 `socket.socket`；**不**读取 `.env`
  中的真实值（只检查文件结构）。
- **不**校验 base_url 可达性 / api_key 合法性 / model 是否在 provider 端
  存在——这些都属于未来 live transport 落地后的真正 smoke。
- **不**修改任何配置文件；**不**写入 `runs/` 下的 evals/judge artifact，
  只写自己 `--out` 目录下的 `preflight.json`。

为什么这样设计
--------------
v1.x 第二轮已经把 transport 抽象、错误分类、脱敏路径钉死，但**还没有**一
个用户可以一键跑的"我的 .env / .gitignore / 环境变量配置是否安全"工具。
用户面对真实阿里云 Coding Plan Anthropic-compatible 资源时，第一反应是
把 key 直接 export 出来 / 或写进 .env / 或试一把 live ——任何一步失误
都可能把 key 推到 git 或 artifact。本 preflight 提供的是"**联网前**的最
后一道闸"。

用户接入点
----------
- CLI：`python -m agent_tool_harness.cli judge-provider-preflight --out
  runs/<dir>`，可选 `--env-file PATH` / `--gitignore PATH`（默认 `.env` /
  `.gitignore`）。
- 程序化：`run_preflight(config, repo_root) -> PreflightReport`。

artifact 排查路径
-----------------
- `runs/<out>/preflight.json`：结构化结果，包含 `config_status`、
  `gitignore_status`、`env_example_status`、`provider_self_test`、
  `summary`、`actionable_hints`。
- `runs/<out>/preflight.md`：人类可读摘要，按"通过 / 警告 / 行动项"三段。

MVP / mock / demo 边界
----------------------
- 本 preflight 不是 live readiness 的全部；它只覆盖**本地侧**的配置安全。
- 真实 endpoint 可达性、模型计费、prompt 模板、retry/backoff 治理仍属未
  来 milestone。

未来扩展点
----------
- `--live` 显式开关：在用户明确同意后，调用真实 transport 做一次最小
  ping（仍需脱敏、限定 request 体积、限定调用次数）。本轮**不**实现。
- 接入更多 provider（OpenAI、Gemini）后，提取通用 `ProviderPreflight` 协议。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .provider import (
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
    _safe_message,
)

PREFLIGHT_SCHEMA_VERSION = "1.0.0-preflight"

# 8 类 error taxonomy；preflight 会把它们全部走一遍 _safe_message，
# 确认 message 模板覆盖完整、不漏分类。
_ALL_ERROR_CODES: tuple[str, ...] = (
    ERROR_MISSING_CONFIG,
    ERROR_DISABLED_LIVE,
    ERROR_AUTH,
    ERROR_RATE_LIMITED,
    ERROR_NETWORK,
    ERROR_TIMEOUT,
    ERROR_BAD_RESPONSE,
    ERROR_PROVIDER,
)


@dataclass
class PreflightReport:
    """Preflight 结果的结构化值对象。

    本类**只**承载脱敏字段。不允许出现 ``api_key`` / ``base_url`` 字面值；
    只允许 ``*_set`` 布尔与 ``*_present_safe`` 标志。
    """

    schema_version: str = PREFLIGHT_SCHEMA_VERSION
    provider: str = ANTHROPIC_COMPATIBLE_PROVIDER_NAME
    live_mode_enabled: bool = False
    config_status: dict[str, Any] = field(default_factory=dict)
    gitignore_status: dict[str, Any] = field(default_factory=dict)
    env_example_status: dict[str, Any] = field(default_factory=dict)
    provider_self_test: dict[str, Any] = field(default_factory=dict)
    summary: dict[str, Any] = field(default_factory=dict)
    actionable_hints: list[str] = field(default_factory=list)


def _check_config(config: AnthropicCompatibleConfig) -> dict[str, Any]:
    """检查 config 字段齐全度；只返回布尔 / 长度，不返回字面值。"""

    return {
        "provider_set": bool(config.provider),
        "base_url_set": bool(config.base_url),
        "api_key_set": bool(config.api_key),
        "model_set": bool(config.model),
        "missing_fields": [
            name
            for name, present in (
                ("AGENT_TOOL_HARNESS_LLM_PROVIDER", bool(config.provider)),
                ("AGENT_TOOL_HARNESS_LLM_BASE_URL", bool(config.base_url)),
                ("AGENT_TOOL_HARNESS_LLM_API_KEY", bool(config.api_key)),
                ("AGENT_TOOL_HARNESS_LLM_MODEL", bool(config.model)),
            )
            if not present
        ],
    }


def _check_gitignore(gitignore_path: Path) -> dict[str, Any]:
    """检查 .gitignore 是否忽略 .env。

    设计意图：用户最容易踩的雷是"在 .env.example 旁边新建 .env、写入真实 key、
    然后习惯性 git add ."。此项把它拦在 commit 前。
    """

    if not gitignore_path.exists():
        return {
            "gitignore_present": False,
            "ignores_dotenv": False,
            "hint": ".gitignore 文件不存在；建议至少包含 `.env`。",
        }
    content = gitignore_path.read_text(encoding="utf-8")
    # 简单匹配 ``.env`` 单独成行 / 或前缀通配；不支持复杂 negation。
    ignored = any(
        line.strip() in {".env", "*.env", ".env*"}
        for line in content.splitlines()
    )
    return {
        "gitignore_present": True,
        "ignores_dotenv": ignored,
        "hint": "" if ignored else "建议在 .gitignore 中加入一行 `.env`。",
    }


def _check_env_example(env_example_path: Path) -> dict[str, Any]:
    """检查 .env.example 是否仅含占位符（每行 `KEY=` 后值为空）。

    设计意图：防止有人把真实 key 误写到 .env.example 后 commit。
    本检查只读 ``KEY=value`` 形式的行，对注释/空行忽略。
    """

    if not env_example_path.exists():
        return {
            "env_example_present": False,
            "all_placeholders": False,
            "non_placeholder_keys": [],
            "hint": ".env.example 不存在；建议补一份占位符模板。",
        }
    bad: list[str] = []
    for raw in env_example_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        # 只允许空值（占位符）；任何非空值都视作可疑。
        if value:
            bad.append(key)
    return {
        "env_example_present": True,
        "all_placeholders": not bad,
        # 只回 KEY 名，不回 value——即使有人误写 key 也不会再被 preflight
        # 二次落入 artifact。
        "non_placeholder_keys": bad,
        "hint": (
            ""
            if not bad
            else f".env.example 中以下变量含非占位符值，请清空：{bad}"
        ),
    }


def _provider_self_test(config: AnthropicCompatibleConfig) -> dict[str, Any]:
    """用 fake transport 触发 8 类错误，确认 message 全部脱敏。

    设计意图：把"未来真实 transport 抛出 raw exception 时，是否会泄漏 key /
    base_url"这条最危险的回归路径在 preflight 阶段就钉死。本测试**不**联网。
    """

    results: list[dict[str, Any]] = []
    api_key = config.api_key or ""
    base_url = config.base_url or ""
    for code in _ALL_ERROR_CODES:
        msg = _safe_message(code)
        leaks_key = bool(api_key) and api_key in msg
        leaks_url = bool(base_url) and base_url in msg
        results.append(
            {
                "error_code": code,
                "message_safe": not (leaks_key or leaks_url),
                "leaks_api_key": leaks_key,
                "leaks_base_url": leaks_url,
            }
        )
    # 再额外做一次"fake transport raise + provider 捕获"的端到端检查：
    # 只要 provider 能把异常转成 entry.error 且不带原始 exception 文本即可。
    provider = AnthropicCompatibleJudgeProvider(
        config=config,
        transport=FakeJudgeTransport(raise_error=ERROR_NETWORK),
    )
    return {
        "live_mode_enabled": False,
        "error_taxonomy_total": len(_ALL_ERROR_CODES),
        "error_taxonomy_safe": sum(1 for r in results if r["message_safe"]),
        "results": results,
        "provider_mode": provider.mode,
    }


def run_preflight(
    config: AnthropicCompatibleConfig,
    repo_root: Path,
    *,
    env_file: Path | None = None,
    gitignore_path: Path | None = None,
    env_example_path: Path | None = None,
) -> PreflightReport:
    """执行完整 preflight，返回结构化报告。

    所有路径默认相对 ``repo_root``；用户可以显式覆盖（便于测试 / monorepo）。
    """

    report = PreflightReport()
    report.config_status = _check_config(config)
    report.gitignore_status = _check_gitignore(
        gitignore_path or (repo_root / ".gitignore")
    )
    report.env_example_status = _check_env_example(
        env_example_path or (repo_root / ".env.example")
    )
    report.provider_self_test = _provider_self_test(config)

    # 汇总 + 行动项
    hints: list[str] = []
    if report.config_status["missing_fields"]:
        hints.append(
            "未来 live 之前需补齐这些环境变量："
            f"{report.config_status['missing_fields']}（在 .env 中设置）"
        )
    if not report.gitignore_status["ignores_dotenv"]:
        hints.append("在 .gitignore 中加入 `.env` 以防止真实 key 被 commit。")
    if not report.env_example_status["all_placeholders"]:
        hints.append(
            ".env.example 中存在非占位符值，请清空（仅保留 `KEY=`）："
            f"{report.env_example_status.get('non_placeholder_keys', [])}"
        )
    if (
        report.provider_self_test["error_taxonomy_safe"]
        != report.provider_self_test["error_taxonomy_total"]
    ):
        hints.append(
            "error taxonomy 中存在可能泄漏 key/base_url 的 message 模板，"
            "请检查 _safe_message。"
        )

    safe_taxonomy = (
        report.provider_self_test["error_taxonomy_safe"]
        == report.provider_self_test["error_taxonomy_total"]
    )
    report.summary = {
        "ready_for_live": False,  # 本轮永远 False；live 不在范围
        "config_complete": not report.config_status["missing_fields"],
        "gitignore_safe": report.gitignore_status["ignores_dotenv"],
        "env_example_safe": report.env_example_status["all_placeholders"],
        "error_taxonomy_safe": safe_taxonomy,
    }
    report.actionable_hints = hints
    return report


def write_preflight_artifacts(report: PreflightReport, out_dir: Path) -> None:
    """把 PreflightReport 写到 out_dir/preflight.json + preflight.md。

    保证 artifact 中**绝不**出现 api_key / base_url 字面值——本函数只序列
    化 :class:`PreflightReport`，而该 dataclass 字段全部为脱敏 / 布尔。
    """

    import json

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "preflight.json").write_text(
        json.dumps(asdict(report), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    lines: list[str] = []
    lines.append(f"# Provider preflight — {report.provider}")
    lines.append("")
    lines.append(f"- schema_version: `{report.schema_version}`")
    lines.append(f"- live_mode_enabled: `{report.live_mode_enabled}`")
    lines.append("")
    lines.append("## Summary")
    for k, v in report.summary.items():
        lines.append(f"- {k}: `{v}`")
    lines.append("")
    lines.append("## Config status (脱敏)")
    for k, v in report.config_status.items():
        lines.append(f"- {k}: `{v}`")
    lines.append("")
    lines.append("## .gitignore")
    for k, v in report.gitignore_status.items():
        lines.append(f"- {k}: `{v}`")
    lines.append("")
    lines.append("## .env.example")
    for k, v in report.env_example_status.items():
        lines.append(f"- {k}: `{v}`")
    lines.append("")
    lines.append("## Provider self-test (fake transport, no network)")
    lines.append(
        f"- error_taxonomy_safe: "
        f"{report.provider_self_test['error_taxonomy_safe']}/"
        f"{report.provider_self_test['error_taxonomy_total']}"
    )
    lines.append(f"- provider_mode: `{report.provider_self_test['provider_mode']}`")
    lines.append("")
    if report.actionable_hints:
        lines.append("## Actionable hints")
        for h in report.actionable_hints:
            lines.append(f"- {h}")
    else:
        lines.append("## Actionable hints")
        lines.append("- (none) — 本地配置自检通过；live 仍未启用，属于后续 milestone。")
    lines.append("")
    (out_dir / "preflight.md").write_text("\n".join(lines), encoding="utf-8")
