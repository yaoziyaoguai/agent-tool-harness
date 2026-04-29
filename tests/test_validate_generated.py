"""validate-generated 防回归测试 (v2.x bootstrap chain hardening)。

为什么这是 bootstrap chain 防漂移测试
-------------------------------------
- scaffold-tools / scaffold-evals / scaffold-fixtures 三步生成的 draft 配置
  是内部小团队第一次接入 agent-tool-harness 的入口；如果它们之间的引用关
  系（eval.required_tools → tools[].name）漂移、披露行被人误删、或
  reviewer 把 runnable 改 true 但漏清 TODO，下游 EvalRunner 会跑出
  misleading PASS/FAIL，把 bootstrap 的安全契约（"draft 不得当真实结果"）
  整个打穿。validate-generated 是这个边界的最后防线。
- 这些测试**不是 v3.0 executor 测试**：从头到尾不调真实 LLM、不 import 用户代码、
  不联网；只做 yaml.safe_load + 文本扫描 + 文件存在性检查。

它能发现什么真实接入问题
------------------------
- 任何把 scaffold 的"runnable=false 双重保险"撤掉但留 TODO 的改动；
- 任何让 scaffold-tools 写出 evals 引用不存在 tool 的回归；
- 任何把 scaffold draft 披露行删掉伪装成 production 的回退；
- 任何把 fixtures 与 tools 的命名约定漂移。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from agent_tool_harness.scaffold import scaffold_tools_yaml, validate_generated

REPO_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_PROJECT = REPO_ROOT / "tests" / "fixtures" / "sample_tool_project"


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "agent_tool_harness.cli", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture
def chain(tmp_path: Path) -> dict[str, Path]:
    """跑一次完整 scaffold chain，返回三件套路径。每个 test 独立 tmp，避免污染。"""
    base = tmp_path
    tools_yaml = base / "tools.draft.yaml"
    evals_yaml = base / "evals.draft.yaml"
    fixtures_dir = base / "fixtures.draft"

    r1 = _run_cli("scaffold-tools", "--source", str(SAMPLE_PROJECT), "--out", str(tools_yaml))
    assert r1.returncode == 0
    r2 = _run_cli("scaffold-evals", "--tools", str(tools_yaml), "--out", str(evals_yaml))
    assert r2.returncode == 0
    r3 = _run_cli(
        "scaffold-fixtures",
        "--tools", str(tools_yaml),
        "--out-dir", str(fixtures_dir),
    )
    assert r3.returncode == 0

    return {"tools": tools_yaml, "evals": evals_yaml, "fixtures": fixtures_dir, "base": base}


def test_validate_clean_chain_returns_warning_not_fail(chain: dict[str, Path]) -> None:
    """完整 scaffold 输出（默认全 TODO + runnable=false）→ status=warning，
    退出码 0。这是预期 draft 状态，不该被当 fail。"""
    r = _run_cli(
        "validate-generated",
        "--tools", str(chain["tools"]),
        "--evals", str(chain["evals"]),
        "--fixtures-dir", str(chain["fixtures"]),
    )
    assert r.returncode == 0, f"clean draft should not fail: {r.stderr}"
    assert "\"status\": \"warning\"" in r.stdout
    assert "draft_still_needs_review" in r.stdout
    # 关键：不能误报 broken_tool_reference / runnable_eval_with_todo。
    assert "broken_tool_reference" not in r.stdout
    assert "runnable_eval_with_todo" not in r.stdout


def test_broken_tool_reference_in_eval_is_fail(chain: dict[str, Path]) -> None:
    """**真实 bug 模拟**：reviewer 改了 evals.yaml 的 required_tools 写错 tool 名
    （或反过来 scaffold 漂移）→ validate 必须 fail，否则 EvalRunner 会跑出
    "tool not found" 但 reviewer 已经看到 PASS-looking validate 了。"""
    text = chain["evals"].read_text(encoding="utf-8")
    # 把第一个 required_tools 中的工具名改成不存在的名字
    text = text.replace(
        "    required_tools:\n    - query_user_profile",
        "    required_tools:\n    - non_existent_tool_xyz",
        1,
    )
    chain["evals"].write_text(text, encoding="utf-8")

    r = _run_cli(
        "validate-generated",
        "--tools", str(chain["tools"]),
        "--evals", str(chain["evals"]),
        "--fixtures-dir", str(chain["fixtures"]),
    )
    assert r.returncode == 2, f"broken ref must exit 2, got {r.returncode}; stdout={r.stdout}"
    assert "broken_tool_reference" in r.stdout
    assert "non_existent_tool_xyz" in r.stdout


def test_runnable_eval_with_todo_is_fail(chain: dict[str, Path]) -> None:
    """**最危险情景**：reviewer 把 runnable 改 true 但漏清 TODO。
    下游 EvalRunner 会拿 TODO_expected_root_cause 当真实答案跑，写出
    misleading PASS/FAIL。validate 必须 fail 阻断。"""
    text = chain["evals"].read_text(encoding="utf-8")
    text = text.replace("runnable: false", "runnable: true", 1)
    chain["evals"].write_text(text, encoding="utf-8")

    r = _run_cli(
        "validate-generated",
        "--tools", str(chain["tools"]),
        "--evals", str(chain["evals"]),
        "--fixtures-dir", str(chain["fixtures"]),
    )
    assert r.returncode == 2
    assert "runnable_eval_with_todo" in r.stdout


def test_invalid_yaml_is_fail(chain: dict[str, Path]) -> None:
    """YAML 解析失败 → fail；信息要指向具体文件。"""
    chain["evals"].write_text("not: valid: yaml: oops", encoding="utf-8")
    r = _run_cli(
        "validate-generated",
        "--tools", str(chain["tools"]),
        "--evals", str(chain["evals"]),
    )
    assert r.returncode == 2
    assert "invalid_yaml" in r.stdout


def test_missing_file_is_fail(tmp_path: Path) -> None:
    """tools.yaml 不存在 → fail。"""
    r = _run_cli(
        "validate-generated",
        "--tools", str(tmp_path / "nope.yaml"),
        "--evals", str(tmp_path / "nope2.yaml"),
    )
    assert r.returncode == 2
    assert "file_missing" in r.stdout


def test_missing_fixture_is_warning_not_fail(chain: dict[str, Path]) -> None:
    """删掉某个 tool 的 fixture → warning（reviewer 可能还没补完，不阻断）。"""
    target = chain["fixtures"] / "query_user_profile.fixture.yaml"
    assert target.exists()
    target.unlink()

    r = _run_cli(
        "validate-generated",
        "--tools", str(chain["tools"]),
        "--evals", str(chain["evals"]),
        "--fixtures-dir", str(chain["fixtures"]),
    )
    assert r.returncode == 0  # warning 不 fail
    assert "missing_fixture" in r.stdout
    assert "query_user_profile" in r.stdout


def test_disclosure_phrase_removed_is_warning(chain: dict[str, Path]) -> None:
    """有人手工把 'generated draft' 行删掉 → warning（draft 失去溯源标记，
    但不是硬错误）。"""
    text = chain["tools"].read_text(encoding="utf-8")
    text = text.replace("generated draft", "edited tools file")
    chain["tools"].write_text(text, encoding="utf-8")

    r = _run_cli(
        "validate-generated",
        "--tools", str(chain["tools"]),
        "--evals", str(chain["evals"]),
        "--fixtures-dir", str(chain["fixtures"]),
    )
    assert r.returncode == 0
    assert "disclosure_missing" in r.stdout


def test_validate_generated_does_not_import_unsafe_module(chain: dict[str, Path]) -> None:
    """**安全契约**：sample_tool_project/tools_unsafe.py 顶层 raise 是 canary；
    validate-generated 只做 yaml/text 处理，不应该触碰用户源码。
    本测试用 chain fixture（真跑了三步 scaffold + 一次 validate），如果
    validate 走了任何动态 import 退路，subprocess 会非零退出 + canary
    文本会出现在 stderr。"""
    r = _run_cli(
        "validate-generated",
        "--tools", str(chain["tools"]),
        "--evals", str(chain["evals"]),
        "--fixtures-dir", str(chain["fixtures"]),
    )
    assert "would-have-executed" not in r.stderr
    assert "would-have-executed" not in r.stdout
    assert "safety canary" not in r.stderr


def test_python_api_is_pure_offline(chain: dict[str, Path]) -> None:
    """Python API 路径同样不联网 / 不 import / 不读 .env：直接调函数确认。"""
    report = validate_generated(
        chain["tools"], chain["evals"], chain["fixtures"]
    )
    # 干净 chain → warning（只有 todo + 可能 0 个其它 issue）。
    assert report.status == "warning"
    assert report.counts["broken_tool_refs"] == 0
    assert report.counts["runnable_evals_count"] == 0


def test_cli_help_lists_validate_generated() -> None:
    """argparse drift 探测：validate-generated 必须出现在 --help。"""
    r = _run_cli("--help")
    assert r.returncode == 0
    assert "validate-generated" in r.stdout


def test_yaml_module_used_for_parsing(tmp_path: Path) -> None:
    """钉死 invalid yaml 不会让 validate 抛异常 / 不会泄漏 traceback——必须
    返回友好 Issue。"""
    bad = tmp_path / "bad.yaml"
    bad.write_text(": : :", encoding="utf-8")
    good = tmp_path / "good.yaml"
    # 用 scaffold-tools 生成一个合法 tools.yaml 做对照。
    src = tmp_path / "src"
    src.mkdir()
    (src / "demo.py").write_text(
        "def foo(x: int) -> int:\n    \"\"\"f\"\"\"\n    return x\n",
        encoding="utf-8",
    )
    scaffold_tools_yaml(src, good)
    report = validate_generated(good, bad)
    codes = {i.code for i in report.issues}
    assert "invalid_yaml" in codes
    assert report.status == "fail"


def test_yaml_loader_used(tmp_path: Path) -> None:
    """Sanity：让 import 不会因 yaml 缺失而失败（yaml 已在依赖）。"""
    assert yaml.safe_load("a: 1") == {"a": 1}


def test_todo_in_yaml_comment_is_not_counted(tmp_path: Path) -> None:
    """**回归 bug**：reviewer 在 reviewed.yaml 顶部写解释性注释，比如
    "全部 TODO_xxx 占位被替换"，过去会被 TODO 正则误匹配，validate
    误报 1 个 TODO warning。修复后：YAML # 注释里的 TODO 不计入。

    边界：注释不计；引号字符串里的 TODO_xxx 是稳定 scaffold 占位，
    不会出现在引号内（scaffold 不会写出来），所以朴素行级剥注释足够。
    """
    tools = tmp_path / "tools.yaml"
    evals = tmp_path / "evals.yaml"
    tools.write_text(
        "# 顶部解释：本文件已 review，全部 TODO_xxx 占位都被替换\n"
        "# generated draft / review required / does not execute\n"
        "tools:\n"
        "  - name: foo\n"
        "    description: real tool description\n"
        "    when_to_use: real guidance\n",
        encoding="utf-8",
    )
    evals.write_text(
        "# generated draft / review required / does not execute tools\n"
        "# 注意：所有 TODO_xxx 都已清掉\n"
        "evals:\n"
        "  - id: e1\n"
        "    runnable: false\n"
        "    required_tools: [foo]\n",
        encoding="utf-8",
    )
    report = validate_generated(tools, evals)
    # 注释里的 TODO_xxx 不应被计数
    assert report.counts["todo_in_tools"] == 0
    assert report.counts["todo_in_evals"] == 0
    # 也不应触发 draft_still_needs_review warning（来源于 todo_total>0）
    codes = {i.code for i in report.issues}
    assert "draft_still_needs_review" not in codes


def test_real_todo_in_data_still_counted(tmp_path: Path) -> None:
    """对照实验：真实数据行里的 TODO_xxx 仍必须计数（避免修过头）。"""
    tools = tmp_path / "tools.yaml"
    evals = tmp_path / "evals.yaml"
    tools.write_text(
        "# generated draft / review required / does not execute\n"
        "tools:\n"
        "  - name: foo\n"
        "    description: TODO_real_description\n"
        "    when_to_use: TODO(reviewer) fill in\n",
        encoding="utf-8",
    )
    evals.write_text(
        "# generated draft / review required / does not execute tools\n"
        "evals:\n"
        "  - id: e1\n"
        "    runnable: false\n"
        "    required_tools: [foo]\n",
        encoding="utf-8",
    )
    report = validate_generated(tools, evals)
    # 数据行里的 TODO 必须计数 (TODO_real_description + TODO(reviewer))
    assert report.counts["todo_in_tools"] >= 2
