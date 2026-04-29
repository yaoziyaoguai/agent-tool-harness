"""validate-generated —— v2.x bootstrap chain hardening。

定位
----
把 scaffold-tools / scaffold-evals / scaffold-fixtures 三步生成的 draft
配置当作一个**整体**做轻量交叉校验，告诉内部小团队：

- 三份文件是否都是合法 YAML？
- 是否还是 draft（含披露 + scaffold_status: draft）？
- evals 引用的 tool name 在 tools 里都存在吗？
- 有多少 TODO 字段还没填？
- runnable=true 的 eval 是否还残留 TODO？（最危险：reviewer 把 runnable
  改了 true 但忘清 TODO，就会被 EvalRunner 跑出 misleading 结果）
- fixtures 目录是否每个 tool 都有占位文件？

而**不**重复 audit-tools / audit-evals 的字段级 finding——那两条命令
仍然是真实 ToolSpec/EvalSpec quality audit 的入口；本模块的定位是
**"一眼看出 bootstrap chain 是否健康 + 还差几步能进入正式 eval"**。

不负责
------
- **不**执行任何工具；
- **不**联网 / 不调真实 LLM / 不读 .env；
- **不**做 ToolSpec/EvalSpec 字段级 audit（那是 audit-tools/audit-evals
  的职责）；
- **不**做语义级判断（when_to_use 是否合理 / decoy 检测）；
- **不**自动修 TODO（这是反 hack 硬约束：scaffold 不能伪造业务答案）。

输出契约
--------
返回一个 ValidateGeneratedReport（dataclass），含：
- status: "pass" / "warning" / "fail"
- issues: list[Issue]，每条 Issue 含 severity(error/warning/info)/code/file/message
- counts: TODO 计数 / draft eval 计数 / orphan tool 计数 等

CLI 退出码：
- 0 = pass / warning（draft 还没 review 完，不是 fail）
- 2 = fail（含 broken reference / invalid yaml / missing required file 等
  会让 reviewer 拿到错误结论的硬错误）

为什么 warning vs fail 这样分
-----------------------------
draft 里残留 TODO 是**预期状态**——reviewer 还没填完——不应该 fail，
否则用户每次跑 validate 都看到红色一片，无法区分"还在 review"和
"真坏掉了"。但 broken reference / invalid yaml / runnable=true 但还有
TODO 这种"会让下游 run 写出 misleading PASS/FAIL"的状况必须 fail。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Issue:
    """单条校验问题。

    severity: error / warning / info
    code: 稳定字符串（用于测试断言 + 用户 grep）
    file: 相对哪个文件，便于 reviewer 直接打开
    message: 给人看的一句话，必须可行动
    """

    severity: str
    code: str
    file: str
    message: str


@dataclass
class ValidateGeneratedReport:
    """validate-generated 命令的总报告。

    status 三态：pass / warning / fail。CLI 把 fail → exit 2；其它 → exit 0。
    """

    status: str
    tools_yaml: str
    evals_yaml: str
    fixtures_dir: str | None
    issues: list[Issue] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    def to_json(self) -> str:
        """用 dataclasses.asdict 序列化，保证字段顺序稳定，便于测试用 in/equals 断言。"""
        return json.dumps(
            {
                "status": self.status,
                "tools_yaml": self.tools_yaml,
                "evals_yaml": self.evals_yaml,
                "fixtures_dir": self.fixtures_dir,
                "counts": self.counts,
                "issues": [asdict(i) for i in self.issues],
            },
            ensure_ascii=False,
            indent=2,
        )


# 5 行披露行的关键短语；与 scaffold/from_python_ast.py 和 scaffold/from_tools_yaml.py
# 中的 _DRAFT_HEADER_LINES / _EVAL_DRAFT_HEADER_LINES 保持同构。
_TOOLS_DISCLOSURE_PHRASES = ("generated draft", "review required", "does not execute")
_EVALS_DISCLOSURE_PHRASES = (
    "generated draft",
    "review required",
    "does not execute tools",
)
_FIXTURES_DISCLOSURE_PHRASES = ("example only", "not real tool output")

# TODO 占位的可识别正则（scaffold 写出来的形态）。匹配 TODO_xxx / TODO(reviewer):
# / TODO（reviewer）等；设计原则：宁可多匹配（warning）也不漏匹配（漏匹配会
# 让 reviewer 以为已经填完）。
_TODO_PATTERN = re.compile(r"TODO[_\(（]")


def _safe_load_yaml(path: Path) -> tuple[Any | None, Issue | None]:
    """读取 + 解析 yaml；解析失败返回明确 fail Issue（**不**抛异常）。"""
    if not path.exists():
        return None, Issue(
            severity="error",
            code="file_missing",
            file=str(path),
            message=f"required file not found: {path}",
        )
    try:
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        return None, Issue(
            severity="error",
            code="invalid_yaml",
            file=str(path),
            message=f"YAML parse failed: {exc}",
        )
    return (data, text), None


def _check_disclosure(text: str, phrases: tuple[str, ...], file_label: str) -> list[Issue]:
    """披露行缺失 → warning（draft 失去溯源标记，但不阻断）。"""
    missing = [p for p in phrases if p not in text]
    if not missing:
        return []
    return [
        Issue(
            severity="warning",
            code="disclosure_missing",
            file=file_label,
            message=(
                f"draft disclosure phrases missing: {missing}. "
                "若文件已被 reviewer 整理为正式配置，请把 scaffold 元数据从顶部移除"
                "并在团队 wiki 记录 review approver。"
            ),
        )
    ]


def _count_todos(text: str) -> int:
    """统计 TODO 占位次数（用于报告 + warning 信号）。"""
    return len(_TODO_PATTERN.findall(text))


def validate_generated(
    tools_yaml: Path | str,
    evals_yaml: Path | str,
    fixtures_dir: Path | str | None = None,
) -> ValidateGeneratedReport:
    """主入口：交叉校验 bootstrap chain 三件套。

    完全 deterministic / offline：只做 yaml.safe_load + 文本扫描 + 文件
    存在性检查；不 import 用户代码、不联网、不读 .env。
    """
    tp = Path(tools_yaml)
    ep = Path(evals_yaml)
    fp = Path(fixtures_dir) if fixtures_dir else None

    issues: list[Issue] = []
    counts: dict[str, int] = {
        "todo_in_tools": 0,
        "todo_in_evals": 0,
        "todo_in_fixtures": 0,
        "tools_count": 0,
        "evals_count": 0,
        "draft_evals_count": 0,
        "runnable_evals_count": 0,
        "fixture_files_count": 0,
        "missing_fixture_count": 0,
        "broken_tool_refs": 0,
    }

    # ---- 1. tools.yaml ----
    loaded, err = _safe_load_yaml(tp)
    tool_names: set[str] = set()
    if err:
        issues.append(err)
    else:
        data, text = loaded  # type: ignore[misc]
        issues += _check_disclosure(text, _TOOLS_DISCLOSURE_PHRASES, str(tp))
        counts["todo_in_tools"] = _count_todos(text)
        tools_list = data.get("tools", []) if isinstance(data, dict) else data
        if not isinstance(tools_list, list):
            issues.append(
                Issue(
                    "error", "tools_root_invalid", str(tp),
                    "tools.yaml root must be `tools: [...]` mapping or a list",
                )
            )
        else:
            for t in tools_list:
                if isinstance(t, dict) and isinstance(t.get("name"), str) and t["name"]:
                    tool_names.add(t["name"])
            counts["tools_count"] = len(tool_names)

    # ---- 2. evals.yaml ----
    loaded, err = _safe_load_yaml(ep)
    if err:
        issues.append(err)
    else:
        data, text = loaded  # type: ignore[misc]
        issues += _check_disclosure(text, _EVALS_DISCLOSURE_PHRASES, str(ep))
        counts["todo_in_evals"] = _count_todos(text)
        evals_list = data.get("evals", []) if isinstance(data, dict) else data
        if not isinstance(evals_list, list):
            issues.append(
                Issue(
                    "error", "evals_root_invalid", str(ep),
                    "evals.yaml root must be `evals: [...]` mapping or a list",
                )
            )
        else:
            counts["evals_count"] = len(evals_list)
            for ev in evals_list:
                if not isinstance(ev, dict):
                    continue
                ev_id = str(ev.get("id", "<no-id>"))
                runnable = ev.get("runnable", True)
                meta = ev.get("metadata") or {}
                is_draft = (
                    isinstance(meta, dict)
                    and meta.get("scaffold_status") == "draft"
                ) or runnable is False
                if is_draft:
                    counts["draft_evals_count"] += 1
                if runnable is True:
                    counts["runnable_evals_count"] += 1
                # 交叉引用：required_tools 必须在 tools.yaml 里存在。
                etb = ev.get("expected_tool_behavior") or {}
                req_tools = etb.get("required_tools") if isinstance(etb, dict) else None
                if isinstance(req_tools, list):
                    for rt in req_tools:
                        if not isinstance(rt, str):
                            continue
                        # 跳过 TODO 占位本身——TODO 警告由 todo 计数报。
                        if "TODO" in rt:
                            continue
                        if tool_names and rt not in tool_names:
                            counts["broken_tool_refs"] += 1
                            issues.append(
                                Issue(
                                    "error",
                                    "broken_tool_reference",
                                    str(ep),
                                    f"eval {ev_id!r} required_tools "
                                    f"references unknown tool {rt!r}; "
                                    "请检查 tools.yaml 是否包含该工具或修正 eval。",
                                )
                            )
                # 关键警戒：runnable=true 但仍含 TODO 占位（某字段没填完）
                # → reviewer 把 runnable 改 true 时漏看 TODO，会让 EvalRunner
                # 跑出 misleading PASS/FAIL。这是 bootstrap chain 最危险的
                # 状态，必须 error 阻断，不是 warning。
                if runnable is True:
                    raw_text = json.dumps(ev, ensure_ascii=False)
                    if _TODO_PATTERN.search(raw_text):
                        issues.append(
                            Issue(
                                "error",
                                "runnable_eval_with_todo",
                                str(ep),
                                f"eval {ev_id!r} has runnable=true but still "
                                "contains TODO placeholders; either set runnable: "
                                "false or replace all TODO_xxx with real values "
                                "before running.",
                            )
                        )

    # ---- 3. fixtures (可选) ----
    if fp is not None:
        if not fp.is_dir():
            issues.append(
                Issue(
                    "error", "fixtures_dir_missing", str(fp),
                    f"--fixtures-dir not found: {fp}",
                )
            )
        else:
            files = sorted(fp.glob("*.fixture.yaml"))
            counts["fixture_files_count"] = len(files)
            present_names = {f.name[: -len(".fixture.yaml")] for f in files}
            for f in files:
                ftext = f.read_text(encoding="utf-8")
                issues += _check_disclosure(
                    ftext, _FIXTURES_DISCLOSURE_PHRASES, str(f)
                )
                counts["todo_in_fixtures"] += _count_todos(ftext)
            # 每个 tool 应有对应 fixture（warning：reviewer 可能还没补完，
            # 不强制 error）。
            for tn in tool_names:
                if tn not in present_names:
                    counts["missing_fixture_count"] += 1
                    issues.append(
                        Issue(
                            "warning",
                            "missing_fixture",
                            str(fp),
                            f"tool {tn!r} has no <name>.fixture.yaml in "
                            f"fixtures dir; 跑 `scaffold-fixtures` 或手工补一个。",
                        )
                    )

    # ---- 4. TODO 总数 → warning（仅当 issues 里没有其它 warning/error 时也要发出）----
    todo_total = (
        counts["todo_in_tools"] + counts["todo_in_evals"] + counts["todo_in_fixtures"]
    )
    if todo_total > 0:
        issues.append(
            Issue(
                "warning",
                "draft_still_needs_review",
                str(tp),
                f"found {todo_total} TODO placeholders across draft files; "
                "reviewer must replace all TODO_xxx with real values + flip "
                "runnable: true before promoting to a real eval run.",
            )
        )

    # ---- 5. 决定 status ----
    has_error = any(i.severity == "error" for i in issues)
    has_warning = any(i.severity == "warning" for i in issues)
    if has_error:
        status = "fail"
    elif has_warning:
        status = "warning"
    else:
        status = "pass"

    return ValidateGeneratedReport(
        status=status,
        tools_yaml=str(tp),
        evals_yaml=str(ep),
        fixtures_dir=str(fp) if fp else None,
        issues=issues,
        counts=counts,
    )
