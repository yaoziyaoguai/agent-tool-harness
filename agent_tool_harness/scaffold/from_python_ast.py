"""static AST-only tool scaffold —— v2.x patch / 内部试用 bootstrap MVP。

本模块只做"机械可推断"的事：用 Python 标准库 `ast` 解析用户项目源码，
抽取顶层函数（默认排除以 `_` 开头的私有函数）的 name / docstring /
位置参数 / 类型注解 / 返回类型注解，写出 draft `tools.yaml`。

为什么用 `ast` 而不是 `import`：
- import 会执行模块顶层代码，可能触发联网 / 读 .env / 调真实 LLM /
  注册副作用；
- ast 只读 source，**绝不**执行任何用户代码，是 v2.x patch 范围里
  唯一安全的离线 bootstrap 方式。

为什么不用 `inspect.signature`：
- 必须先 import 才能拿到 signature；
- 而我们不允许 import；
- ast.FunctionDef.args 已经能拿到所需信息。

不负责的事（明确划清边界，避免读者误以为这是"自动接入"工具）：
- **不**判断函数是否真的"是"工具（用户必须 review draft 后删除噪音）；
- **不**推断 input_schema 的语义校验（type hint 只能给出 type，不能给
  出 enum / required / 默认值约束意图）；
- **不**推断 output_contract、token_policy、side_effects、when_to_use、
  when_not_to_use——这些字段必须由工具作者人工补充，draft 里写 TODO
  占位；
- **不**自动 audit；
- **不**自动 promote 到 evals。

如何用 artifacts 查问题：
- 生成的 draft `tools.yaml` 顶部固定写 `# generated draft / review required
  / does not execute tools / does not read secrets / not production-approved`
  + 每个 tool 写 `metadata.scaffold_source: <相对路径>:<行号>`；
- 任何字段被推断成 TODO 时，draft 里都会带 `# TODO(reviewer):` 注释说明
  原因，方便 reviewer 一眼定位需要补什么。

MVP 边界 / 未来扩展点：
- 当前只扫顶层 `def`，**不**扫 class method（v3.0 backlog：可选支持
  `--include-class-methods`）；
- 当前不识别 `@tool` decorator——遇到任何 decorator 都按候选处理，
  让 reviewer 决定（v3.0 可加 `--decorator <name>` 过滤）；
- 当前不读 docstring 里的 args/returns 段做 schema 推断（v3.0 可接
  google/numpy 风格 docstring 解析）。
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Draft 文件头：固定 5 行声明 + 1 行版本/来源指针，tests pin 这些字面值。
# 修改这些字符串需要同步更新 tests/test_scaffold_tools.py，避免悄悄削弱披露。
_DRAFT_HEADER_LINES: tuple[str, ...] = (
    "# generated draft —— 由 `agent-tool-harness scaffold-tools` 静态生成；",
    "# review required —— 所有 TODO 字段必须由工具作者人工补充后才能用于正式 run；",
    "# does not execute tools —— 仅 ast 静态扫描，绝不 import / 调 shell / 联网；",
    "# does not read secrets —— 不读取 .env / 不读取真实 key / 不调真实 LLM；",
    "# not production-approved —— 未经过 audit-tools / human review 不要直接用于评估。",
)

# 把 Python ast 注解节点扁平化成"人类可读类型字符串"。
# 仅做最小可读化；任何复杂泛型 fallback 到 ast.unparse。
def _annotation_to_str(node: ast.AST | None) -> str:
    """把 ast 注解节点转成 docstring/YAML 可读的类型字符串。

    设计思路：保持机械翻译，**不**尝试做语义推断（例如把 `Optional[str]`
    转成 `nullable: true`）——那是 schema 推断，不是字符串映射，超出本
    MVP 范围。任何无法识别的复杂注解直接 fallback 到 `ast.unparse(node)`。
    """
    if node is None:
        return "TODO_unannotated"
    try:
        return ast.unparse(node)
    except Exception:
        return "TODO_unannotated"


@dataclass(frozen=True)
class ScaffoldedParam:
    """单个候选工具参数的最小描述。

    `annotation` 为 `"TODO_unannotated"` 表示用户函数没写类型注解——这是
    真实信号（"可能是隐式 dict 入参"），让 reviewer 决定 input_schema
    要不要补 string/object/...。
    """

    name: str
    annotation: str
    has_default: bool


@dataclass(frozen=True)
class ScaffoldedTool:
    """从一个 Python 函数 ast 节点抽出来的候选工具描述。

    `source_path` 是相对扫描根目录的路径；`line` 是 def 行号。它们一起
    成为生成 YAML 时的 `metadata.scaffold_source`，让 reviewer 能秒级
    跳回源码。
    """

    name: str
    docstring: str | None
    params: tuple[ScaffoldedParam, ...]
    return_annotation: str
    source_path: str
    line: int
    decorators: tuple[str, ...] = field(default_factory=tuple)


def scan_python_module(
    source_text: str, source_path: str = "<unknown>"
) -> list[ScaffoldedTool]:
    """对单份 Python 源代码做 ast 扫描，返回候选工具列表。

    只扫**顶层** `def`（不进入 class）；忽略以 `_` 开头的私有函数。
    遇到语法错误抛 `SyntaxError` 让上层决定如何展示——上层 CLI 会把它
    转成 actionable 错误而不是 traceback。

    为什么要把"扫单文件"和"遍历目录 + 写 YAML"拆开：
    - scan_python_module 是纯函数，方便单测；
    - 目录遍历涉及 IO + 跳过规则，单独一层。
    """
    tree = ast.parse(source_text, filename=source_path)
    tools: list[ScaffoldedTool] = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        if node.name.startswith("_"):
            continue
        params: list[ScaffoldedParam] = []
        defaults_count = len(node.args.defaults)
        positional_total = len(node.args.args)
        first_default_idx = positional_total - defaults_count
        for idx, arg in enumerate(node.args.args):
            if arg.arg == "self":
                continue
            params.append(
                ScaffoldedParam(
                    name=arg.arg,
                    annotation=_annotation_to_str(arg.annotation),
                    has_default=idx >= first_default_idx,
                )
            )
        decorators = tuple(_annotation_to_str(d) for d in node.decorator_list)
        tools.append(
            ScaffoldedTool(
                name=node.name,
                docstring=ast.get_docstring(node),
                params=tuple(params),
                return_annotation=_annotation_to_str(node.returns),
                source_path=source_path,
                line=node.lineno,
                decorators=decorators,
            )
        )
    return tools


def _scan_directory(source_dir: Path) -> list[ScaffoldedTool]:
    """遍历目录下所有 .py 文件做 ast 扫描。

    跳过规则（v2.x patch MVP）：
    - 跳过 `__pycache__` / `.venv` / `.git` / 任何 `tests/` 子树（避免
      把测试桩当工具）；
    - 跳过以 `.` / `_` 开头的目录；
    - 单文件 SyntaxError 不中止整个扫描，只跳过该文件并打印 stderr 警告。
    """
    import sys

    skip_dirs = {"__pycache__", ".venv", ".git", "tests", "test", ".pytest_cache",
                 ".mypy_cache", ".ruff_cache", "node_modules", "build", "dist"}
    results: list[ScaffoldedTool] = []
    for py_path in sorted(source_dir.rglob("*.py")):
        rel_parts = py_path.relative_to(source_dir).parts
        if any(p in skip_dirs or p.startswith(".") or p.startswith("_") for p in rel_parts[:-1]):
            continue
        rel_str = str(py_path.relative_to(source_dir))
        try:
            text = py_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            print(f"warning: skip {rel_str}: {exc}", file=sys.stderr)
            continue
        try:
            results.extend(scan_python_module(text, source_path=rel_str))
        except SyntaxError as exc:
            print(
                f"warning: skip {rel_str}: SyntaxError at line {exc.lineno}",
                file=sys.stderr,
            )
            continue
    return results


def _yaml_quote(value: str) -> str:
    """最小 YAML safe-quote：把字符串包成单引号块，转义内部单引号。

    我们**故意不**引入 PyYAML 写出——为了保持零新增依赖，且 draft 的可读性
    比"完美 YAML 序列化"更重要（reviewer 必须能直接看懂改）。
    """
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _render_tool(tool: ScaffoldedTool) -> list[str]:
    """把一个 ScaffoldedTool 渲染成 YAML 行列表。

    渲染原则：
    - 任何静态可推断的字段直接写值；
    - 任何**需要业务语义**的字段写 `TODO(reviewer): ...` 注释 + 占位
      值，绝不伪造；
    - 行内注释中文，方便内部团队 review。
    """
    lines: list[str] = []
    desc = (tool.docstring or "").strip().splitlines()[0] if tool.docstring else ""
    lines.append(f"  - name: {tool.name}")
    lines.append("    namespace: TODO_namespace  # TODO(reviewer): 选一个稳定的命名空间，例如 team.subdomain")  # noqa: E501
    lines.append("    version: '0.1'")
    if desc:
        lines.append(f"    description: {_yaml_quote(desc)}")
    else:
        lines.append("    description: TODO_description  # TODO(reviewer): 一句话描述工具能做什么")
    lines.append("    when_to_use: TODO_when_to_use  # TODO(reviewer): 在什么场景下 Agent 应优先选这个工具")  # noqa: E501
    lines.append("    when_not_to_use: TODO_when_not_to_use  # TODO(reviewer): 哪些场景应避免使用，避免诱导 Agent 误用")  # noqa: E501
    lines.append("    input_schema:")
    lines.append("      type: object")
    if tool.params:
        required = [p.name for p in tool.params if not p.has_default]
        if required:
            lines.append(f"      required: [{', '.join(required)}]")
        lines.append("      properties:")
        for param in tool.params:
            lines.append(f"        {param.name}:")
            lines.append(f"          type: TODO_type  # static annotation: {param.annotation}")
            lines.append(f"          description: TODO(reviewer): 描述参数 {param.name} 的用途")
    else:
        lines.append("      properties: {}  # TODO(reviewer): 函数无显式参数；可能是隐式 kwargs，请人工确认")  # noqa: E501
    lines.append("    output_contract:")
    lines.append(f"      required_fields: TODO_required_fields  # static return annotation: {tool.return_annotation}")  # noqa: E501
    lines.append("      # TODO(reviewer): 列出工具响应必须包含的字段，例如 [summary, evidence, next_action]")  # noqa: E501
    lines.append("    token_policy:")
    lines.append("      max_output_tokens: TODO_int  # TODO(reviewer): 上限 token，避免响应膨胀")
    lines.append("      actionable_errors: TODO_bool  # TODO(reviewer): 错误响应是否包含 suggested_fix")  # noqa: E501
    lines.append("    side_effects:")
    lines.append("      destructive: TODO_bool  # TODO(reviewer): 是否会修改外部状态")
    lines.append("      open_world_access: TODO_bool  # TODO(reviewer): 是否会访问外部网络或不可控资源")  # noqa: E501
    lines.append("    executor:")
    lines.append("      type: python")
    lines.append(f"      path: {tool.source_path}")
    lines.append(f"      function: {tool.name}")
    lines.append("    metadata:")
    lines.append(f"      scaffold_source: {tool.source_path}:{tool.line}")
    if tool.decorators:
        lines.append(f"      scaffold_decorators: [{', '.join(tool.decorators)}]")
    lines.append("      scaffold_status: draft  # 必须经过 human review + audit-tools 才能正式使用")
    return lines


def _render_yaml(tools: list[ScaffoldedTool], source_dir: Path) -> str:
    """组装完整 draft YAML 文本（含固定文件头）。"""
    out: list[str] = list(_DRAFT_HEADER_LINES)
    out.append(f"# scaffold_source_dir: {source_dir}")
    out.append(f"# scaffold_tool_count: {len(tools)}")
    out.append("")
    if not tools:
        out.append("tools: []")
        out.append("# 没有抽取到任何候选工具——可能 source 目录下没有 .py，或都是私有函数 (_xxx)。")
        out.append("# 请确认 --source 指向的是工具实现根目录，而不是 tests/ 或文档目录。")
        return "\n".join(out) + "\n"
    out.append("tools:")
    for tool in tools:
        out.extend(_render_tool(tool))
    return "\n".join(out) + "\n"


def scaffold_tools_yaml(
    source_dir: Path | str,
    output_path: Path | str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """主入口：扫描 source_dir，把 draft tools.yaml 写到 output_path。

    返回一个 summary dict，方便 CLI 打印 `wrote ...` 与 tool 计数。

    `force=False` 时如 output_path 已存在则抛 `FileExistsError`——这是
    安全契约，避免覆盖手写正式 tools.yaml。CLI 把这条异常映射为
    actionable error 信息，与 `promote-evals` 的覆盖保护完全一致。
    """
    src = Path(source_dir).resolve()
    out = Path(output_path)
    if not src.exists() or not src.is_dir():
        raise FileNotFoundError(f"--source 必须指向一个存在的目录: {src}")
    if out.exists() and not force:
        raise FileExistsError(
            f"refused to overwrite existing file: {out}（加 --force 显式覆盖；"
            "强烈建议先把已有 tools.yaml 备份）"
        )
    tools = _scan_directory(src)
    yaml_text = _render_yaml(tools, src)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml_text, encoding="utf-8")
    return {
        "out": str(out),
        "tool_count": len(tools),
        "source_dir": str(src),
        "scaffold_kind": "python_ast_static",
        "scaffold_kind_note": (
            "Static AST scan only; never imports / executes user code; "
            "never reads .env; never calls real LLM. All semantic fields are TODO."
        ),
    }
