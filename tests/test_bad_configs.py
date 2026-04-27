"""坏配置 fixtures 行为锁定测试。

为什么需要这组测试：`examples/bad_configs/` 目录是给真实接入者的对照表，
**它的价值取决于框架对每个坏文件给出的错误信息是否稳定且可行动**。
这组测试既验证 loader/audit/CLI 能识别这些错误，又同时锁住了 fixtures
内容本身——如果谁不小心把 fixture 改“好”了，这里会立刻红。

测试纪律：
- 不允许通过删测试或放宽断言来追求绿；如要修改 fixture 内容，必须同时
  调整断言并解释如何让真实用户更容易识别错误。
- 不在这里复测 `tests/test_cli_errors.py` 已覆盖的“通用 CLI hint 文案”。
  本文件聚焦：(a) 坏 fixture 文件本身仍然坏；(b) ToolRegistry/audit 等
  loader 之外的边界仍然能正确响应。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_tool_harness.audit.eval_quality_auditor import EvalQualityAuditor
from agent_tool_harness.audit.tool_design_auditor import ToolDesignAuditor
from agent_tool_harness.cli import main
from agent_tool_harness.config.loader import ConfigError, load_evals, load_tools
from agent_tool_harness.tools.registry import ToolRegistry, ToolRegistryError

BAD = Path(__file__).resolve().parent.parent / "examples" / "bad_configs"


def test_bad_configs_directory_has_readme():
    """README 是这组 fixture 的“说明书”，缺了真实接入者就找不到对照表。"""

    assert (BAD / "README.md").exists()


def test_tools_empty_loads_but_cli_warns(tmp_path, capsys):
    """`tools: []` 是合法占位；loader 必须接受，但 CLI 必须在 stderr 提示空状态，
    避免用户误以为审计真的通过。"""

    tools = load_tools(BAD / "tools_empty.yaml")
    assert tools == []

    rc = main(
        [
            "audit-tools",
            "--tools",
            str(BAD / "tools_empty.yaml"),
            "--out",
            str(tmp_path / "out"),
        ]
    )
    err = capsys.readouterr().err
    assert rc == 0
    assert "empty" in err and "tools" in err


def test_evals_empty_loads_but_cli_warns(tmp_path, capsys):
    """`evals: []` 同样是合法占位，audit-evals 时必须打印空状态 warning。"""

    evals = load_evals(BAD / "evals_empty.yaml")
    assert evals == []

    rc = main(
        [
            "audit-evals",
            "--evals",
            str(BAD / "evals_empty.yaml"),
            "--out",
            str(tmp_path / "out"),
        ]
    )
    err = capsys.readouterr().err
    assert rc == 0
    assert "empty" in err and "evals" in err


def test_tools_scalar_root_raises_config_error():
    """顶层是字符串时，loader 必须明确拒绝，而不是悄悄变成空列表。"""

    with pytest.raises(ConfigError) as exc:
        load_tools(BAD / "tools_scalar_root.yaml")
    assert "mapping or list" in str(exc.value)


def test_tools_bad_entry_raises_config_error():
    """`tools[0]` 不是 mapping 时，loader 必须报到具体下标，方便用户定位行号。"""

    with pytest.raises(ConfigError) as exc:
        load_tools(BAD / "tools_bad_entry.yaml")
    assert "tools[0]" in str(exc.value)


def test_tools_duplicate_qualified_name_blocks_runner(tmp_path):
    """两个工具拥有相同 qualified name 时，ToolRegistry 必须直接拒绝构造；
    EvalRunner 也必须把这个失败保全成 artifact，而不是让 run 静默成功。

    注：CLI 不直接遇到这条 raise——runner 会拦下并转成 judge_results 中的
    `tool_registry_initialization_failed`。下面同时锁住这两层契约。"""

    tools = load_tools(BAD / "tools_duplicate_qualified.yaml")
    with pytest.raises(ToolRegistryError):
        ToolRegistry(tools)

    rc = main(
        [
            "run",
            "--project",
            "examples/runtime_debug/project.yaml",
            "--tools",
            str(BAD / "tools_duplicate_qualified.yaml"),
            "--evals",
            "examples/runtime_debug/evals.yaml",
            "--out",
            str(tmp_path / "out"),
            "--mock-path",
            "good",
        ]
    )
    assert rc == 0  # runner 把失败保全成 artifact，不向 CLI 抛
    judge_path = tmp_path / "out" / "judge_results.json"
    assert judge_path.exists()
    text = judge_path.read_text(encoding="utf-8")
    assert "tool_registry_initialization_failed" in text


def test_evals_duplicate_id_raises_config_error():
    """重复 eval.id 会让 run/judge artifact 互相覆盖，loader 必须拒收。"""

    with pytest.raises(ConfigError) as exc:
        load_evals(BAD / "evals_duplicate_id.yaml")
    assert "unique" in str(exc.value) or "duplicate" in str(exc.value).lower()


def test_tool_missing_optional_fields_surfaces_audit_findings():
    """缺 when_to_use / output_contract / token_policy 不应让 loader 失败，
    但 ToolDesignAuditor 必须给出对应 finding——否则真实用户会误以为这些字段可有可无。"""

    tools = load_tools(BAD / "tool_missing_optional_fields.yaml")
    assert len(tools) == 1

    result = ToolDesignAuditor().audit(tools)
    findings = result["tools"][0]["findings"]
    rule_ids = {f["rule_id"] for f in findings}

    assert any("when_to_use" in r for r in rule_ids), rule_ids
    assert any("output_contract" in r for r in rule_ids), rule_ids


def test_eval_missing_outcome_marks_eval_not_runnable():
    """缺 verifiable_outcome / initial_context 的 eval 不能进入正式 tool-use eval；
    auditor 必须把它标 runnable=false 并给出 high-severity finding。"""

    evals = load_evals(BAD / "eval_missing_outcome.yaml")
    assert len(evals) == 1

    audit = EvalQualityAuditor().audit(evals)
    assert evals[0].id in audit["summary"]["not_runnable"]

    finding_ids = {f["rule_id"] for f in audit["evals"][0]["findings"]}
    assert any("verifiability" in r or "fixture" in r for r in finding_ids), finding_ids
