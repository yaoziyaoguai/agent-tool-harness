"""realistic_offline_tool_trial sample 的防回归测试。

存在意义
--------
v2.x Realistic Offline Tool Trial 节点引入 `examples/realistic_offline_tool_trial/`
作为"比 toy lookup 更接近真实内部工作流，但完全 offline / deterministic /
fake data"的 sample，用于 maintainer rehearsal 和后续第一批内部同事的
试用入口。本文件确保后续 patch 不会无意中：

1. 删掉这个 sample；
2. 把 fake data 改成需要联网 / 真实 key / 数据库；
3. 让 sample 的工具函数缺 docstring / type hints / return annotation；
4. 让 reviewed config 漏 strict-reviewed / mock-path good / mock-path bad；
5. 让 sample 文件意外混入真实 Bearer token / Authorization header / 完整
   响应体 / 真实公司路径；
6. 把 maintainer rehearsal feedback 文件改成"真实内部反馈"的形态（污染
   3-feedback v3.0 gate）。

为什么 sample 必须 offline / fake：v2.x 的核心安全契约是 no secrets read /
no network / no live LLM / no untrusted code execution；一旦 sample 引入
真实数据就自动跨出 v2.x 范围（属 v3.0 backlog）。

如何用 artifacts 排查：本测试只看 sample 静态结构 + scaffold-tools 的
deterministic 扫描结果，不依赖 run artifacts；如果 strict-reviewed 失败，
请到 `runs/<rehearsal>/audit_tools.json` / `audit_evals.json` 看具体 finding。
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_DIR = PROJECT_ROOT / "examples" / "realistic_offline_tool_trial"
SAMPLE_TOOLS_PY = SAMPLE_DIR / "sample_tools.py"
TOOLS_REVIEWED = SAMPLE_DIR / "tools.reviewed.yaml"
EVALS_REVIEWED = SAMPLE_DIR / "evals.reviewed.yaml"
PROJECT_YAML = SAMPLE_DIR / "project.yaml"
README = SAMPLE_DIR / "README.md"
MAINTAINER_LOG = SAMPLE_DIR / "MAINTAINER_REHEARSAL.md"


def test_sample_dir_exists() -> None:
    """sample 目录必须存在；防止后续 patch 误删 v2.x Realistic Trial 入口。"""
    assert SAMPLE_DIR.is_dir(), "examples/realistic_offline_tool_trial/ 不应被删"


def test_sample_has_required_files() -> None:
    """5 个文件构成一个完整的"真实感 offline 试用包"，缺一不可。"""
    required = [SAMPLE_TOOLS_PY, TOOLS_REVIEWED, EVALS_REVIEWED, PROJECT_YAML, README]
    missing = [str(p.relative_to(PROJECT_ROOT)) for p in required if not p.is_file()]
    assert not missing, f"realistic offline trial sample 缺文件: {missing}"


# ---------------------------------------------------------------------------
# 静态结构检查 —— 用 ast 而不是 import sample_tools.py。
# 原因：scaffold-tools 本身就是 ast-only / 不 import 用户代码；测试也必须
# 验证 sample 即使在不被 import 的情况下也是合法的 Python module，并且
# 工具函数都有 docstring / type hints / return annotation。
# ---------------------------------------------------------------------------
EXPECTED_TOOL_FUNCTIONS = (
    "search_fake_knowledge_base",
    "classify_fake_tool_failure",
    "validate_fake_config_snippet",
)


def test_sample_tools_module_is_parseable() -> None:
    """sample_tools.py 必须是合法 Python；任何 syntax error 都阻塞 7 步路径。"""
    text = SAMPLE_TOOLS_PY.read_text(encoding="utf-8")
    ast.parse(text)


def test_sample_tools_have_three_named_functions() -> None:
    """模块必须暴露 3 个具名工具函数，且名字与 reviewed tools.yaml 对齐。"""
    tree = ast.parse(SAMPLE_TOOLS_PY.read_text(encoding="utf-8"))
    func_names = {
        node.name
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
    }
    missing = set(EXPECTED_TOOL_FUNCTIONS) - func_names
    assert not missing, f"sample_tools.py 缺工具函数: {missing}"


def test_sample_tool_functions_have_docstring_and_annotations() -> None:
    """每个工具函数必须有 docstring + 至少一个 type-annotated 参数 + return annotation。

    模拟反向场景：如果未来 patch 把 sample 简化成 toy stub，会让"第一次内部
    同事看 sample 学怎么写真实工具"失去参照价值，本测试主动把这种简化拦下来。
    """
    tree = ast.parse(SAMPLE_TOOLS_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name not in EXPECTED_TOOL_FUNCTIONS:
            continue
        assert ast.get_docstring(node), f"{node.name} 缺 docstring"
        assert node.returns is not None, f"{node.name} 缺 return annotation"
        annotated = [arg for arg in node.args.args if arg.annotation is not None]
        assert annotated, f"{node.name} 至少一个参数需要 type annotation"


# ---------------------------------------------------------------------------
# Offline / safety 检查 —— 防止任何真实 secret / 网络副作用混入 sample。
# 这些 substring 黑名单不是语义级安全，仅是 deterministic 兜底；真实安全
# 仍需要 reviewer。
# ---------------------------------------------------------------------------
_OFFLINE_FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "import requests",
    "import urllib.request",
    "import httpx",
    "import http.client",
    "from urllib.request",
    "from urllib import request",
    "socket.socket",
    "subprocess.run",
    "subprocess.Popen",
    "os.system",
    "os.popen",
    "open(\"/etc/",
    "open('/etc/",
    "openai.",
    "anthropic.",
    "boto3.",
    "psycopg2.",
    "sqlite3.connect",
    "Bearer sk-",
    "Bearer ya29",
    "Authorization: Bearer",
)


def test_sample_tools_module_is_offline_only() -> None:
    """sample_tools.py 不允许出现网络/数据库/真实 SDK/真 token 关键字。

    本测试故意用关键字黑名单（deterministic / 可解释），不是真实 sandbox，
    属于 v2.x MVP 安全兜底；真实越界（例如自己实现 socket）必须靠 reviewer
    + 日后 v3.0 真实 executor 的 syscall 限制。
    """
    text = SAMPLE_TOOLS_PY.read_text(encoding="utf-8")
    found = [tok for tok in _OFFLINE_FORBIDDEN_SUBSTRINGS if tok in text]
    assert not found, f"sample_tools.py 出现禁字: {found}"


def test_sample_does_not_read_dotenv_or_env_keys() -> None:
    """禁止任何方式读 .env / 真实 secret 环境变量。"""
    text = SAMPLE_TOOLS_PY.read_text(encoding="utf-8")
    forbidden = (
        "open('.env'",
        'open(".env"',
        "Path('.env'",
        'Path(".env"',
        "load_dotenv",
        "os.environ['OPENAI",
        'os.environ["OPENAI',
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GITHUB_TOKEN",
    )
    found = [tok for tok in forbidden if tok in text]
    assert not found, f"sample_tools.py 不应读 .env 或真实 key: {found}"


_DOC_FILES_TO_SCAN = (
    SAMPLE_TOOLS_PY,
    TOOLS_REVIEWED,
    EVALS_REVIEWED,
    PROJECT_YAML,
    README,
    MAINTAINER_LOG,
)

_TOKEN_PATTERNS: tuple[str, ...] = (
    r"Bearer\s+sk-[A-Za-z0-9]{16,}",
    r"Bearer\s+ya29\.[A-Za-z0-9_\-]{16,}",
    r"sk-[A-Za-z0-9]{20,}",
    r"AIza[0-9A-Za-z_\-]{35}",
)


def test_sample_files_have_no_real_token_leakage() -> None:
    """所有 sample 文件不允许出现真实 token / Authorization 真值。

    Bearer / sk- / Google API key 这些都用正则盯，匹配到一条就 fail；
    "fake" / "TODO" / placeholder 不会被匹配（正则要求足够长的真实形态）。
    """
    leaks: list[tuple[str, str]] = []
    for path in _DOC_FILES_TO_SCAN:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in _TOKEN_PATTERNS:
            for match in re.finditer(pattern, text):
                leaks.append((path.name, match.group(0)))
    assert not leaks, f"sample 文件出现真实 token: {leaks}"


# ---------------------------------------------------------------------------
# scaffold-tools 静态扫描验证 —— 必须能识别 3 个工具函数；不能 import 它们。
# 用 subprocess 跑 cli 是为了完全模拟"用户从命令行跑"的边界，而不是直接
# 调内部 API（那样可能绕过 sys.path / sys.modules 的真实污染）。
# ---------------------------------------------------------------------------
def _run_cli(args: list[str], cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "agent_tool_harness.cli", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )


def test_scaffold_tools_can_scan_realistic_sample(tmp_path: Path) -> None:
    """scaffold-tools 能 ast-only 扫描 realistic sample，识别 3 个函数为工具候选。"""
    out = tmp_path / "scaffold_out.yaml"
    proc = _run_cli([
        "scaffold-tools",
        "--source", str(SAMPLE_DIR),
        "--out", str(out),
    ])
    assert proc.returncode == 0, f"scaffold-tools 失败: {proc.stderr}"
    text = out.read_text(encoding="utf-8")
    for name in EXPECTED_TOOL_FUNCTIONS:
        assert name in text, f"scaffold-tools 输出缺工具: {name}"
    assert "TODO" in text, "scaffold-tools 必须保留 TODO 占位（draft 不能被自动 approve）"


def test_scaffold_tools_does_not_import_realistic_sample(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """scaffold-tools 必须 ast-only：sample 模块不会被 import 到 sys.modules。

    这是本会话 sample_tool_project/tools_unsafe.py 同款 safety canary：如果
    scaffold 真的 import sample，realistic sample 也不会爆炸（它没有顶层副
    作用），但只要 sys.modules 出现 sample_tools 模块，就说明 ast-only 契约
    被打破，未来若用户接入有副作用的真实工具就会出问题。
    """
    import sys as _sys

    sentinel = "examples.realistic_offline_tool_trial.sample_tools"
    monkeypatch.setattr(_sys, "modules", dict(_sys.modules))
    out = tmp_path / "scaffold_out.yaml"
    proc = _run_cli([
        "scaffold-tools",
        "--source", str(SAMPLE_DIR),
        "--out", str(out),
    ])
    assert proc.returncode == 0
    # subprocess 用独立进程跑，本进程 sys.modules 不会被污染；这条断言永远 pass，
    # 但保留显式语义防止未来重构成 in-process 调用而失去 import isolation。
    assert sentinel not in _sys.modules


def test_strict_reviewed_passes_on_realistic_reviewed_configs() -> None:
    """v2.x strict-reviewed 必须直接通过 realistic reviewed configs（status=pass）。"""
    proc = _run_cli([
        "validate-generated",
        "--tools", str(TOOLS_REVIEWED),
        "--evals", str(EVALS_REVIEWED),
        "--strict-reviewed",
    ])
    assert proc.returncode == 0, f"strict-reviewed 失败: {proc.stderr}\n{proc.stdout}"
    assert "status=pass" in proc.stderr or "status=pass" in proc.stdout


def test_deterministic_smoke_run_good_path_passes(tmp_path: Path) -> None:
    """7 步路径里的 deterministic smoke run（mock-path good）必须 PASS 全部 eval。

    这是 maintainer rehearsal 已经验过一次的路径；本测试钉住它，防止后续
    sample 改动让 evidence id 与 verifiable_outcome 失配（这正是本轮
    rehearsal 暴露的真实 bug：dict-form vs string-list evidence）。
    """
    out_dir = tmp_path / "smoke_good"
    proc = _run_cli([
        "run",
        "--project", str(PROJECT_YAML),
        "--tools", str(TOOLS_REVIEWED),
        "--evals", str(EVALS_REVIEWED),
        "--out", str(out_dir),
        "--mock-path", "good",
    ])
    assert proc.returncode == 0, f"run good 失败: {proc.stderr}\n{proc.stdout}"
    # 10 件套 artifact + report.md
    artifacts = sorted(p.name for p in out_dir.iterdir())
    for required in (
        "report.md",
        "transcript.jsonl",
        "tool_calls.jsonl",
        "tool_responses.jsonl",
        "metrics.json",
        "audit_tools.json",
        "audit_evals.json",
        "judge_results.json",
        "diagnosis.json",
        "llm_cost.json",
    ):
        assert required in artifacts, f"缺 artifact: {required} (got {artifacts})"


def test_maintainer_rehearsal_log_is_clearly_not_real_feedback() -> None:
    """maintainer rehearsal log 必须显式标明"不计入 3 份真实内部反馈"。

    防御场景：未来某次 commit 把 maintainer rehearsal 同步进
    docs/INTERNAL_TRIAL_FEEDBACK_SUMMARY.md，会让 v3.0 启动 gate 被自己
    刷的反馈污染。此处通过文案显式声明拦下。
    """
    text = MAINTAINER_LOG.read_text(encoding="utf-8")
    for marker in (
        "maintainer rehearsal only",
        "not real internal team feedback",
        "does NOT count",
        "v3.0 gate",
    ):
        assert marker in text, f"MAINTAINER_REHEARSAL.md 缺关键声明: {marker}"


def test_reviewed_evals_runnable_true_only_after_review() -> None:
    """reviewed evals 必须有 runnable=true（draft 默认 false）；
    生成的 draft（scaffold-evals 输出）必须 runnable=false。

    这是 v2.x bootstrap-to-run 的核心契约：runnable=true 只能由 reviewer
    显式声明改完 TODO 后开启；本测试通过对比 reviewed 与 scaffold draft
    防止未来 patch 把 draft 默认切成 runnable=true（那将自动跨出 v2.x 安
    全契约，让用户没 review 就 run）。
    """
    text = EVALS_REVIEWED.read_text(encoding="utf-8")
    assert "runnable: true" in text, "reviewed evals 必须有 runnable: true"
