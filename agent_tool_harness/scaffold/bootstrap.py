"""user-friendly bootstrap orchestrator：把 4 步收束成一条命令。

为什么需要这个模块（v2.x User-Friendly Bootstrap Flow）
------------------------------------------------------
内部用户第一次接入 agent-tool-harness 时，要先后执行：

1. scaffold-tools  → 写 draft tools.yaml
2. scaffold-evals  → 读 tools.yaml 写 draft evals.yaml
3. scaffold-fixtures → 读 tools.yaml 在目录里写 fixture 占位
4. validate-generated → 交叉校验三件套

4 条命令、4 个 --tools / --evals / --out / --out-dir 参数排列组合，
新人极易迷路（"我现在生成到第几步了？" / "fixtures 该指向哪个目录？"）。
本模块把这 4 步串成一个原子操作，并写出 reviewer 直接能读的
``REVIEW_CHECKLIST.md`` + ``validation_summary.json``。

边界（v2.x patch / 不是 v3.0 executor）
---------------------------------------
- **绝不** import / exec 用户源码（继承 scaffold 子包不变量）；
- **绝不**联网 / **绝不**调真实 LLM / **绝不**读 ``.env``；
- **绝不**自动 approve（即使 validation_summary 是 pass，仍标 draft）；
- **绝不**伪造业务正确答案——所有需要业务语义的字段仍是 ``TODO_xxx``；
- 默认拒绝覆盖已存在 ``--out``（需显式 ``--force``，避免误冲掉
  reviewer 已经手动改过的 reviewed config）。

何处接入
--------
- CLI 入口：``python -m agent_tool_harness.cli bootstrap --source <dir>
  --out <bootstrap_dir>``；
- Python API：``bootstrap_user_project(source, out_dir)`` 返回
  :class:`BootstrapReport`。

artifact 排查路径
-----------------
- ``<out>/tools.generated.yaml`` / ``<out>/evals.generated.yaml`` /
  ``<out>/fixtures/`` 来自现有 scaffold 子模块（同一份契约）；
- ``<out>/validation_summary.json`` = ``ValidateGeneratedReport.to_json()``
  原样落盘，便于 CI/script 抓 status；
- ``<out>/REVIEW_CHECKLIST.md`` 是写给 reviewer 看的人类可读版，包含
  TODO 数 / runnable 数 / broken_ref 数 / 下一步建议命令 / v3.0 不会
  做什么的明示。

未来扩展点（v3.0 backlog，本轮**不做**）
---------------------------------------
- 接 MCP ``tools/list`` 自动发现；
- 真实 LLM 帮 reviewer 起草 ``when_to_use``；
- Web UI review 流；
- 自动跑 ``audit-tools`` / ``audit-evals``（目前留给用户决定时机，
  避免在 bootstrap 阶段产生 misleading PASS/FAIL）。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agent_tool_harness.scaffold.from_python_ast import scaffold_tools_yaml
from agent_tool_harness.scaffold.from_tools_yaml import (
    scaffold_evals_yaml,
    scaffold_fixtures_dir,
)
from agent_tool_harness.scaffold.validate_generated import (
    ValidateGeneratedReport,
    validate_generated,
)

# REVIEW_CHECKLIST.md 模板里这些固定短语会被回归测试钉住，**不能**随意删改。
# 变更前请同步 tests/test_user_friendly_bootstrap.py 中的 _CHECKLIST_PHRASES。
_CHECKLIST_REQUIRED_PHRASES = (
    "generated draft",
    "review required",
    "TODO",
    "strict-reviewed",
    "no secrets",
    "v3.0",
    "doctor",
    "First Tool Suitability",
    "mockable",
    "deterministic eval",
)


@dataclass
class BootstrapReport:
    """:func:`bootstrap_user_project` 的结构化结果。

    字段
    ----
    out_dir : 实际落盘目录（绝对路径，便于 CI 拼后续命令）。
    tools_yaml / evals_yaml : draft 文件路径。
    fixtures_dir : fixtures 输出目录。
    validation : 来自 :func:`validate_generated` 的结构化报告（draft mode；
                 reviewed strict 校验留给 reviewer 改完后自己跑）。
    next_steps : 给 reviewer 的下一步命令字符串列表（用于 stdout 也写入
                 REVIEW_CHECKLIST）。
    written_files : 本次写入的所有文件相对路径，便于做 diff/审计。
    """

    out_dir: Path
    tools_yaml: Path
    evals_yaml: Path
    fixtures_dir: Path
    validation: ValidateGeneratedReport
    next_steps: list[str] = field(default_factory=list)
    written_files: list[str] = field(default_factory=list)

    def to_json_safe(self) -> dict[str, Any]:
        """转换成 JSON-safe dict，便于 CLI 打印 / CI 抓字段。"""
        return {
            "out_dir": str(self.out_dir),
            "tools_yaml": str(self.tools_yaml),
            "evals_yaml": str(self.evals_yaml),
            "fixtures_dir": str(self.fixtures_dir),
            "validation_status": self.validation.status,
            "validation_counts": dict(self.validation.counts),
            "validation_issue_codes": [i.code for i in self.validation.issues],
            "next_steps": list(self.next_steps),
            "written_files": list(self.written_files),
        }


def _build_review_checklist(report: BootstrapReport) -> str:
    """生成 REVIEW_CHECKLIST.md 内容。

    设计原则：
    - 不夸大能力：明确说"这是 draft / 不是 approved config"；
    - 给可复制粘贴的下一步命令（含 ``validate-generated --strict-reviewed``
      和 ``run --mock-path good``），不让 reviewer 自己拼路径；
    - 给"不要 paste 到 prompt / issue / artifact"的安全提醒（真实 API
      key / Authorization / 完整请求体 / 完整响应体）。
    """
    v = report.validation
    counts = v.counts
    lines: list[str] = [
        "# Bootstrap Review Checklist",
        "",
        "> ⚠️ 本目录下的 `tools.generated.yaml` / `evals.generated.yaml` / "
        "`fixtures/` 都是 **generated draft / review required**，不是 approved config。",
        "> reviewer 必须人工 review 后才能进入 deterministic run。",
        "",
        "## 1. 当前 validation 状态",
        "",
        f"- status: **{v.status}**",
        f"- TODO 占位总数: tools={counts.get('todo_in_tools', 0)}, "
        f"evals={counts.get('todo_in_evals', 0)}, "
        f"fixtures={counts.get('todo_in_fixtures', 0)}",
        f"- runnable evals: {counts.get('runnable_evals_count', 0)}",
        f"- broken tool references: {counts.get('broken_tool_refs', 0)}",
        f"- missing fixture files: {counts.get('missing_fixture_count', 0)}",
        "",
        "## 2. reviewer 必须做什么",
        "",
        "- [ ] 把 `tools.generated.yaml` 中所有 `TODO_xxx` 替换为真实业务值",
        "      （`when_to_use` / `output_contract` / `token_policy` /",
        "      `side_effects` 等需要业务语义，scaffold 不会瞎猜）。",
        "- [ ] 把 `evals.generated.yaml` 中 `runnable: false` 改成 `true`",
        "      **前**先把 `verifiable_outcome.expected_*` / `judge.rules` 等",
        "      占位填成真实业务期望（runnable=true + 残留 TODO 是最危险情",
        "      景，会被 strict 校验 fail 拦下）。",
        "- [ ] 检查 `fixtures/` 下每个 `<tool>.fixture.yaml`：当前内容只是",
        "      example only，**不是真实 tool 输出**；如果你的工作流需要",
        "      replay-mode（v3.0 backlog），届时由你自己提供真实样例。",
        "",
        "## 3. 下一步可复制命令",
        "",
        "```bash",
        "# strict 校验（reviewer 声称改完 TODO 后跑；TODO 残留 / 无 runnable",
        "# 都会 fail）",
    ]
    for cmd in report.next_steps:
        lines.append(cmd)
    lines += [
        "```",
        "",
        "## 4. 安全 / 边界提醒",
        "",
        "- 本 bootstrap 命令**不**执行你的工具代码（仅 ast 静态扫描）；",
        "  **不**联网；**不**读 `.env`；**不**调真实 LLM。",
        "- **不要**把真实 API key / Authorization header / 完整请求体 / 完整",
        "  响应体粘进 prompt / issue / artifact / 反馈渠道。",
        "- 当前仍属 v2.x patch；MCP / Web UI / 真实 LLM Judge / HTTP·Shell",
        "  executor / 企业级平台能力都是 **v3.0** backlog，本轮 **no secrets",
        "  read / no live LLM**。",
        "- 内部真实反馈不足 3 份之前不讨论 v3.0；先把 v2.x bootstrap UX +",
        "  deterministic smoke 跑顺。",
        "",
        "## 5. 一键 doctor 检查（reviewer 改完后随时跑）",
        "",
        "```bash",
        f"python -m agent_tool_harness.cli validate-generated \\\n"
        f"  --bootstrap-dir {report.out_dir}",
        f"python -m agent_tool_harness.cli validate-generated \\\n"
        f"  --bootstrap-dir {report.out_dir} --strict-reviewed",
        "```",
        "",
        "## 6. First Tool Suitability Checklist（v2.x Real Trial Readiness）",
        "",
        "如果这是你第一次拿\"自己项目里的真实小工具\"接入 agent-tool-harness，",
        "请先确认目标工具满足以下条件——满足越多，试用失败成本越低；",
        "强烈不推荐第一轮就接整个项目 / 真实外部 API / 数据库 / 真实 key 工具。",
        "",
        "- [ ] 单一工具（不是工具链）",
        "- [ ] 输入参数简单（≤ 3 个，类型可在 yaml 里写明）",
        "- [ ] 不需要真实 secret / API key / Authorization header",
        "- [ ] 不需要联网（offline-first 是 v2.x 的核心契约）",
        "- [ ] 输出可以被 mock / fixture 表达（mockable / example only 即可）",
        "- [ ] 可以写出 2–3 条 deterministic eval（rule-based judge 能验证）",
        "- [ ] 不会执行危险副作用（删数据 / 发邮件 / 调外部支付等）",
        "- [ ] 不需要真实用户数据 / PII",
        "- [ ] 不属于 MCP / HTTP / Shell executor 场景（这些都是 **v3.0** backlog）",
        "- [ ] 不需要 live LLM judge（v3.0 backlog）",
        "",
        "若上面任何一条无法满足：详细参见 `docs/REAL_TRIAL_CANDIDATE.md`",
        "里\"不推荐作为第一个试用工具\"的清单，挑下一个候选再试。",
        "",
        "_本 checklist 由 `bootstrap` 命令自动生成，根据 `validation_summary.json`",
        "_即时填字段；如需修改文案请改 `agent_tool_harness/scaffold/bootstrap.py`._",
        "",
    ]
    return "\n".join(lines)


def bootstrap_user_project(
    source: str | Path,
    out_dir: str | Path,
    *,
    force: bool = False,
) -> BootstrapReport:
    """主入口：把 scaffold-tools / -evals / -fixtures / validate-generated
    收束成一次原子调用。

    参数
    ----
    source : 用户项目源码目录（scaffold-tools 的 ``--source``）。仅做 ast
             静态扫描；如果路径不存在或里面没有可识别 tool，会通过 scaffold
             子模块抛 ConfigError / FileNotFoundError，不假成功。
    out_dir : bootstrap 输出目录。默认 **不允许**已存在；``force=True``
              才会清空重建（便于 reviewer 改完后再重新 bootstrap 而不互相
              污染）。这是反误覆盖的硬约束。
    force : 显式覆盖开关。

    返回
    ----
    :class:`BootstrapReport` —— 即使 validation_status 是 fail / warning
    也照常返回（draft 状态本来就不要求 pass）。CLI 入口决定要不要把
    fail 翻成 exit code 2。
    """
    out = Path(out_dir)
    if out.exists():
        if not force:
            raise FileExistsError(
                f"bootstrap out dir already exists: {out}; "
                "pass --force to overwrite (will rm -rf the whole dir)"
            )
        # force=True 时整目录重建，避免上一次 bootstrap 残留与本次混在一起。
        shutil.rmtree(out)
    out.mkdir(parents=True)

    tools_yaml = out / "tools.generated.yaml"
    evals_yaml = out / "evals.generated.yaml"
    fixtures_dir = out / "fixtures"

    # 步骤 1：scaffold-tools。失败由上层抛 ConfigError，CLI 会给 actionable msg。
    scaffold_tools_yaml(str(source), str(tools_yaml), force=force)
    # 步骤 2：scaffold-evals。
    scaffold_evals_yaml(str(tools_yaml), str(evals_yaml), force=force)
    # 步骤 3：scaffold-fixtures（目录可能已经被父目录 mkdir 创建过了）。
    scaffold_fixtures_dir(str(tools_yaml), str(fixtures_dir), force=force)
    # 步骤 4：validate-generated（draft mode；strict 留给 reviewer 改完跑）。
    validation = validate_generated(
        tools_yaml, evals_yaml, fixtures_dir, strict_reviewed=False
    )

    # 落盘 validation_summary.json（机器可读）。
    summary_path = out / "validation_summary.json"
    summary_path.write_text(validation.to_json() + "\n", encoding="utf-8")

    next_steps = [
        "python -m agent_tool_harness.cli validate-generated \\",
        f"  --tools {tools_yaml} \\",
        f"  --evals {evals_yaml} \\",
        f"  --fixtures-dir {fixtures_dir} \\",
        "  --strict-reviewed",
        "",
        "# reviewer 改完后跑一次 deterministic smoke run（mock 桩）：",
        "python -m agent_tool_harness.cli run \\",
        "  --project <your_project.yaml> \\",
        f"  --tools {tools_yaml} \\",
        f"  --evals {evals_yaml} \\",
        "  --out runs/bootstrap-smoke --mock-path good",
    ]

    report = BootstrapReport(
        out_dir=out.resolve(),
        tools_yaml=tools_yaml.resolve(),
        evals_yaml=evals_yaml.resolve(),
        fixtures_dir=fixtures_dir.resolve(),
        validation=validation,
        next_steps=next_steps,
        written_files=sorted(
            str(p.relative_to(out))
            for p in out.rglob("*")
            if p.is_file()
        ),
    )

    # 落盘 REVIEW_CHECKLIST.md（人类可读）。在 written_files 之后写避免漏列自身。
    checklist_path = out / "REVIEW_CHECKLIST.md"
    checklist_path.write_text(_build_review_checklist(report), encoding="utf-8")
    report.written_files.append("REVIEW_CHECKLIST.md")

    return report


__all__ = ["BootstrapReport", "bootstrap_user_project"]


# 把固定短语对外暴露，方便回归测试 import 同一份常量（避免文档 drift 测试
# 用魔术字符串，写错就一起错）。
bootstrap_user_project.checklist_required_phrases = (  # type: ignore[attr-defined]
    _CHECKLIST_REQUIRED_PHRASES
)
