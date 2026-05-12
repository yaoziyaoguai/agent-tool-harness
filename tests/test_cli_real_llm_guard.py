"""CLI --judge-provider llm 安全门控测试。

测试纪律：
- 所有测试零网络依赖
- 不读取 .env / os.environ
- 不调用真实 LLM
- 使用 _build_parser 验证 argparse 层
- 使用 _run_core_flow 验证运行时层
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from agent_tool_harness.cli import _build_parser, _run_core_flow
from agent_tool_harness.config.loader import load_evals, load_tools

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _load_knowledge_search_fixtures():
    base = Path("examples/knowledge_search")
    tools = load_tools(str(base / "tools.yaml"))
    evals = load_evals(str(base / "evals.yaml"))
    return tools, evals


# ---------------------------------------------------------------------------
# 1. argparse: --judge-provider llm is valid
# ---------------------------------------------------------------------------


def test_judge_provider_llm_is_valid_choice():
    """--judge-provider llm 在 argparse 层是合法选项。"""
    parser = _build_parser()
    args = parser.parse_args([
        "run",
        "--project", "p.yaml",
        "--tools", "t.yaml",
        "--evals", "e.yaml",
        "--out", "out",
        "--core-flow",
        "--judge-provider", "llm",
        "--live",
        "--confirm-i-have-real-key",
        "--llm-config", "providers.yaml",
        "--llm-provider", "openai-native",
    ])
    assert args.judge_provider == "llm"
    assert args.live is True
    assert args.confirm_i_have_real_key is True
    assert args.llm_config == "providers.yaml"
    assert args.llm_provider == "openai-native"


# ---------------------------------------------------------------------------
# 2. argparse: --judge-provider llm without core-flow is parsed (runtime error)
# ---------------------------------------------------------------------------


def test_judge_provider_llm_without_core_flow_parsed():
    """--judge-provider llm 不配合 --core-flow 在 argparse 层通过（运行时拒绝）。"""
    parser = _build_parser()
    args = parser.parse_args([
        "run",
        "--project", "p.yaml",
        "--tools", "t.yaml",
        "--evals", "e.yaml",
        "--out", "out",
        "--judge-provider", "llm",
    ])
    assert args.judge_provider == "llm"


# ---------------------------------------------------------------------------
# 3. --judge-provider llm requires --live --confirm-i-have-real-key --llm-config --llm-provider
# ---------------------------------------------------------------------------


def test_llm_without_dual_flags_rejected():
    """--judge-provider llm 缺双标志 → exit 2。"""
    tools, evals = _load_knowledge_search_fixtures()
    with tempfile.TemporaryDirectory() as tmpdir:
        exit_code = _run_core_flow(
            tools=tools,
            evals=evals[:1],
            out=tmpdir,
            mock_path="good",
            judge_provider="llm",
            # 未传 live + confirm_i_have_real_key + llm_config + llm_provider
        )
        assert exit_code == 2


def test_llm_without_llm_config_rejected():
    """--judge-provider llm 缺 --llm-config → exit 2（在 _run 层拦截）。"""
    tools, evals = _load_knowledge_search_fixtures()
    with tempfile.TemporaryDirectory() as tmpdir:
        exit_code = _run_core_flow(
            tools=tools,
            evals=evals[:1],
            out=tmpdir,
            mock_path="good",
            judge_provider="llm",
            live=True,
            confirm_i_have_real_key=True,
            # 未传 llm_config
        )
        assert exit_code == 2


def test_llm_without_llm_provider_rejected():
    """--judge-provider llm 缺 --llm-provider → exit 2。"""
    tools, evals = _load_knowledge_search_fixtures()
    with tempfile.TemporaryDirectory() as tmpdir:
        exit_code = _run_core_flow(
            tools=tools,
            evals=evals[:1],
            out=tmpdir,
            mock_path="good",
            judge_provider="llm",
            live=True,
            confirm_i_have_real_key=True,
            llm_config="providers.yaml",
            # 未传 llm_provider
        )
        assert exit_code == 2


# ---------------------------------------------------------------------------
# 4. --live without --confirm-i-have-real-key rejected
# ---------------------------------------------------------------------------


def test_live_only_without_confirm_rejected_in_run():
    """_run 层：--live 单独存在时 --judge-provider llm 被拒。"""
    tools, evals = _load_knowledge_search_fixtures()
    with tempfile.TemporaryDirectory() as tmpdir:
        exit_code = _run_core_flow(
            tools=tools,
            evals=evals[:1],
            out=tmpdir,
            mock_path="good",
            judge_provider="llm",
            live=True,
            confirm_i_have_real_key=False,
            llm_config="providers.yaml",
            llm_provider="openai-native",
        )
        assert exit_code == 2


# ---------------------------------------------------------------------------
# 5. --live / --confirm-i-have-real-key without --judge-provider llm rejected
# ---------------------------------------------------------------------------


def test_live_flags_without_llm_judge_provider_rejected():
    """_run_core_flow 层：使用 fake judge 传 live flag 被拒。"""
    tools, evals = _load_knowledge_search_fixtures()
    with tempfile.TemporaryDirectory() as tmpdir:
        exit_code = _run_core_flow(
            tools=tools,
            evals=evals[:1],
            out=tmpdir,
            mock_path="good",
            judge_provider="fake",
            live=True,
            confirm_i_have_real_key=True,
        )
        assert exit_code == 2


# ---------------------------------------------------------------------------
# 6. nonexistent config file → exit 2
# ---------------------------------------------------------------------------


def test_llm_nonexistent_config_exits_2():
    """不存在的 --llm-config → exit 2（factory 层 FileNotFoundError）。"""
    tools, evals = _load_knowledge_search_fixtures()
    with tempfile.TemporaryDirectory() as tmpdir:
        exit_code = _run_core_flow(
            tools=tools,
            evals=evals[:1],
            out=tmpdir,
            mock_path="good",
            judge_provider="llm",
            live=True,
            confirm_i_have_real_key=True,
            llm_config="/nonexistent/providers.yaml",
            llm_provider="openai-native",
        )
        assert exit_code == 2


# ---------------------------------------------------------------------------
# 7. --core-flow without --judge-provider still works (backward compat)
# ---------------------------------------------------------------------------


def test_core_flow_without_judge_provider_still_works():
    """--core-flow 不传 --judge-provider 仍正常运行。"""
    tools, evals = _load_knowledge_search_fixtures()
    with tempfile.TemporaryDirectory() as tmpdir:
        exit_code = _run_core_flow(
            tools=tools,
            evals=evals[:1],
            out=tmpdir,
            mock_path="good",
        )
        assert exit_code == 0
        assert (Path(tmpdir) / "report.md").exists()


# ---------------------------------------------------------------------------
# 8. --judge-provider llm with non-core-flow rejected by _run
# ---------------------------------------------------------------------------


def test_llm_judge_outside_core_flow_rejected():
    """_run 层：--judge-provider llm 不配合 --core-flow → exit 2。"""
    from agent_tool_harness.cli import _run

    tools, evals = _load_knowledge_search_fixtures()
    with tempfile.TemporaryDirectory() as tmpdir:
        exit_code = _run(
            project_path="examples/knowledge_search/project.yaml",
            tools_path="examples/knowledge_search/tools.yaml",
            evals_path="examples/knowledge_search/evals.yaml",
            out=tmpdir,
            mock_path="good",
            judge_provider="llm",
            core_flow=False,
        )
        assert exit_code == 2


# ---------------------------------------------------------------------------
# 9. argparse: --env-file and --allow-os-env flags
# ---------------------------------------------------------------------------


def test_env_file_flag_accepted():
    """--env-file 在 argparse 层是合法选项。"""
    parser = _build_parser()
    args = parser.parse_args([
        "run",
        "--project", "p.yaml",
        "--tools", "t.yaml",
        "--evals", "e.yaml",
        "--out", "out",
        "--core-flow",
        "--judge-provider", "llm",
        "--live",
        "--confirm-i-have-real-key",
        "--llm-config", "providers.yaml",
        "--llm-provider", "openai-native",
        "--env-file", "./.env",
    ])
    assert args.env_file == "./.env"
    assert args.allow_os_env is False


def test_allow_os_env_flag_accepted():
    """--allow-os-env 在 argparse 层是合法选项。"""
    parser = _build_parser()
    args = parser.parse_args([
        "run",
        "--project", "p.yaml",
        "--tools", "t.yaml",
        "--evals", "e.yaml",
        "--out", "out",
        "--core-flow",
        "--judge-provider", "llm",
        "--live",
        "--confirm-i-have-real-key",
        "--llm-config", "providers.yaml",
        "--llm-provider", "openai-native",
        "--allow-os-env",
    ])
    assert args.allow_os_env is True
    assert args.env_file is None


# ---------------------------------------------------------------------------
# 10. --judge-provider llm without --env-file or --allow-os-env → rejected
# ---------------------------------------------------------------------------


def test_llm_without_secret_source_rejected():
    """--judge-provider llm 没有 --env-file / --allow-os-env → exit 2。"""
    tools, evals = _load_knowledge_search_fixtures()
    with tempfile.TemporaryDirectory() as tmpdir:
        exit_code = _run_core_flow(
            tools=tools,
            evals=evals[:1],
            out=tmpdir,
            mock_path="good",
            judge_provider="llm",
            live=True,
            confirm_i_have_real_key=True,
            llm_config="providers.yaml",
            llm_provider="openai-native",
            # 未传 env_file / allow_os_env
        )
        assert exit_code == 2


# ---------------------------------------------------------------------------
# 11. dry-run does not require --env-file
# ---------------------------------------------------------------------------


def test_dry_run_provider_does_not_require_env_file():
    """dry-run 不读取 --env-file，不校验 secret source。"""
    parser = _build_parser()
    args = parser.parse_args([
        "run",
        "--project", "p.yaml",
        "--tools", "t.yaml",
        "--evals", "e.yaml",
        "--out", "out",
        "--dry-run-provider",
        "--llm-config", "examples/llm_providers.example.yaml",
    ])
    assert args.dry_run_provider is True
    assert args.env_file is None
    assert args.allow_os_env is False
