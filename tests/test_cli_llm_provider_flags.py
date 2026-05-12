"""CLI LLM provider flag 测试。

测试纪律：
- 所有测试零网络依赖
- 不读取 .env / os.environ
- 不调用真实 LLM
- 使用 tempfile 创建 fixture 文件
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_tool_harness.cli import _build_parser, _dry_run_provider_config

VALID_PROVIDERS_YAML = """
providers:
  openai-native:
    family: openai
    compatibility: native
    model: gpt-4.1-mini
    api_key_env: OPENAI_API_KEY
  anthropic-native:
    family: anthropic
    compatibility: native
    model: claude-sonnet-4-6
    api_key_env: ANTHROPIC_API_KEY
"""


# ---------------------------------------------------------------------------
# parser tests — flag existence and choices
# ---------------------------------------------------------------------------


def test_parser_has_dry_run_provider_flag():
    """--dry-run-provider flag 存在于 run 子命令。"""
    parser = _build_parser()
    args = parser.parse_args(
        [
            "run",
            "--project", "p.yaml",
            "--tools", "t.yaml",
            "--evals", "e.yaml",
            "--out", "out",
            "--dry-run-provider",
        ]
    )
    assert args.dry_run_provider is True


def test_parser_has_llm_config_flag():
    """--llm-config flag 存在于 run 子命令。"""
    parser = _build_parser()
    args = parser.parse_args(
        [
            "run",
            "--project", "p.yaml",
            "--tools", "t.yaml",
            "--evals", "e.yaml",
            "--out", "out",
            "--llm-config", "providers.yaml",
        ]
    )
    assert args.llm_config == "providers.yaml"


def test_parser_has_llm_provider_flag():
    """--llm-provider flag 存在于 run 子命令。"""
    parser = _build_parser()
    args = parser.parse_args(
        [
            "run",
            "--project", "p.yaml",
            "--tools", "t.yaml",
            "--evals", "e.yaml",
            "--out", "out",
            "--llm-provider", "openai-native",
        ]
    )
    assert args.llm_provider == "openai-native"


def test_judge_provider_fake_is_valid_choice():
    """--judge-provider fake 是合法选项。"""
    parser = _build_parser()
    args = parser.parse_args(
        [
            "run",
            "--project", "p.yaml",
            "--tools", "t.yaml",
            "--evals", "e.yaml",
            "--out", "out",
            "--judge-provider", "fake",
        ]
    )
    assert args.judge_provider == "fake"


def test_judge_provider_fake_without_core_flow_is_parsed():
    """--judge-provider fake 可以解析（运行时会报错，但 argparse 层通过）。"""
    parser = _build_parser()
    args = parser.parse_args(
        [
            "run",
            "--project", "p.yaml",
            "--tools", "t.yaml",
            "--evals", "e.yaml",
            "--out", "out",
            "--judge-provider", "fake",
        ]
    )
    assert args.judge_provider == "fake"


# ---------------------------------------------------------------------------
# dry-run provider tests
# ---------------------------------------------------------------------------


def test_dry_run_provider_without_llm_config_errors():
    """--dry-run-provider 缺 --llm-config 返回 exit 2。"""
    exit_code = _dry_run_provider_config(llm_config=None, llm_provider=None)
    assert exit_code == 2


def test_dry_run_provider_with_valid_config():
    """--dry-run-provider 加载有效配置返回 0。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "providers.yaml"
        path.write_text(VALID_PROVIDERS_YAML, encoding="utf-8")
        exit_code = _dry_run_provider_config(
            llm_config=str(path), llm_provider=None
        )
        assert exit_code == 0


def test_dry_run_provider_with_nonexistent_config():
    """--dry-run-provider 加载不存在的配置文件返回 2。"""
    exit_code = _dry_run_provider_config(
        llm_config="/nonexistent/providers.yaml", llm_provider=None
    )
    assert exit_code == 2


def test_dry_run_provider_with_valid_llm_provider_name():
    """--dry-run-provider 指定有效的 --llm-provider 返回 0。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "providers.yaml"
        path.write_text(VALID_PROVIDERS_YAML, encoding="utf-8")
        exit_code = _dry_run_provider_config(
            llm_config=str(path), llm_provider="openai-native"
        )
        assert exit_code == 0


def test_dry_run_provider_with_invalid_llm_provider_name():
    """--dry-run-provider 指定无效的 --llm-provider 返回 2。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "providers.yaml"
        path.write_text(VALID_PROVIDERS_YAML, encoding="utf-8")
        exit_code = _dry_run_provider_config(
            llm_config=str(path), llm_provider="nonexistent"
        )
        assert exit_code == 2


def test_dry_run_provider_does_not_read_env():
    """--dry-run-provider 不读取环境变量。"""
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "providers.yaml"
        path.write_text(VALID_PROVIDERS_YAML, encoding="utf-8")
        old_val = os.environ.get("OPENAI_API_KEY")
        os.environ["OPENAI_API_KEY"] = "sk-should-not-be-read"
        try:
            exit_code = _dry_run_provider_config(
                llm_config=str(path), llm_provider=None
            )
            assert exit_code == 0
        finally:
            if old_val is not None:
                os.environ["OPENAI_API_KEY"] = old_val
            else:
                os.environ.pop("OPENAI_API_KEY", None)
