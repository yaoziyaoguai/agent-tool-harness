"""scaffold-evals / scaffold-fixtures —— v2.x 内部试用 bootstrap 第二轮。

定位
----
当用户用 `scaffold-tools` 生成了 draft `tools.yaml` 后，下一步还需要
**至少一条 smoke eval** + **每个工具一个 mock fixture 占位**，才能跑通
`run --mock-path good/bad`。完全手写这两份文件，对第一次接入的内部团队来
说仍然是高门槛。本模块提供两个 deterministic / offline-first 的 scaffold
命令，把"机械可推断"的部分自动化，"业务语义"部分留 TODO 给 reviewer。

职责
----
- `scaffold_evals_yaml(tools_yaml, out, force)`：为 tools.yaml 中的每个
  工具生成 1 条最小 smoke eval 草稿（**只**做存在性 / shape 检查，**不**
  假装知道业务正确答案）；
- `scaffold_fixtures_dir(tools_yaml, out_dir, force)`：为每个工具生成
  一个 mock fixture 占位文件（含 example-only / not real tool output 披露）。

不负责的事（**重要边界**）
--------------------------
- **不**执行任何工具；
- **不**联网 / 不调真实 LLM；
- **不**读取 .env；
- **不**读 tools.yaml 之外的源码（不会被 docstring / 注解的 secrets 污染）；
- **不**自动 promote draft 到正式 evals.yaml；
- **不**伪造业务正确答案——所有 `expected_root_cause` / `verifiable_outcome`
  / mock fixture 内容都写 `TODO(reviewer):` 占位，让 reviewer 必须思考填什么。

为什么 eval scaffold 不能假装知道业务答案
----------------------------------------
eval 的核心价值是"业务上 PASS/FAIL 的判定标准"。这个标准必须由懂业务的
工具作者人工填写。如果 scaffold 自动写 `expected_root_cause: input_boundary`
之类的真实业务判断，reviewer 容易把它当 production-grade 跳过 review，
导致后续所有 run 的 PASS/FAIL 都不可信。本模块写的所有业务字段都是
`TODO_xxx` + 行内注释，故意"跑不起来"，强制 reviewer 把 TODO 全清理掉
才能用 `audit-evals` 验证 + 用 `run` 跑。

未来扩展点（v3.0 backlog，本轮不做）
------------------------------------
- 从真实 transcript 抓 mock fixture 内容（需要先有真实运行历史）；
- LLM 协助写 `success_criteria` 自然语言（需要 live LLM）；
- 与 from_transcripts eval 生成串联。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

# 与 scaffold-tools 的披露段保持同构，但措辞针对 evals 语境调整。
# 修改这些字符串需要同步更新 tests/test_scaffold_evals_and_fixtures.py。
_EVAL_DRAFT_HEADER_LINES: tuple[str, ...] = (
    "# generated draft —— 由 `agent-tool-harness scaffold-evals` 静态生成；",
    "# review required —— 所有 TODO 字段必须由懂业务的 reviewer 补完后才能用于正式 run；",
    "# does not execute tools —— 仅读 tools.yaml 元数据；绝不调工具、不联网、不读 .env；",
    "# does not call live provider —— scaffold 完全 deterministic / offline；不调真实 LLM；",
    "# deterministic/offline starter only —— 仅作 smoke 起点，未经 audit-evals 不要直接用于评估。",
)

_FIXTURE_HEADER_LINES: tuple[str, ...] = (
    "# example only —— 由 `agent-tool-harness scaffold-fixtures` 自动生成的占位；",
    "# review required —— 内容是占位字典，不是真实工具响应；reviewer 必须替换成真实样例；",
    "# not real tool output —— scaffold 不调用任何工具，无法获得真实 schema；",
    "# generated without executing tool —— 完全 deterministic / offline 文件 IO；",
)


def _load_tools_list(tools_yaml: Path) -> list[dict[str, Any]]:
    """读取 tools.yaml（draft 或正式），返回 tools list。

    支持顶层 `tools: [...]` mapping 或裸 list root，与 ConfigLoader 兼容；
    但**不**走 ConfigLoader——loader 会把缺字段当 ConfigError 抛掉，而我们
    本来就在处理 draft（满 yaml 都是 TODO 字符串），需要更宽松的读取。
    """
    if not tools_yaml.exists():
        raise FileNotFoundError(f"--tools 必须指向已存在的 yaml 文件: {tools_yaml}")
    data = yaml.safe_load(tools_yaml.read_text(encoding="utf-8")) or {}
    if isinstance(data, dict):
        items = data.get("tools", [])
    else:
        items = data
    if not isinstance(items, list):
        raise ValueError(
            f"tools.yaml root 必须是 list 或含 'tools:' 的 mapping: {tools_yaml}"
        )
    out: list[dict[str, Any]] = []
    for it in items:
        if isinstance(it, dict) and isinstance(it.get("name"), str) and it["name"]:
            out.append(it)
    return out


def _safe_eval_id(tool_name: str) -> str:
    """把 tool name 映射成稳定 eval id，避免 TODO 占位 id 撞名。"""
    cleaned = "".join(c if c.isalnum() or c in "_-" else "_" for c in tool_name)
    return f"smoke_{cleaned}_TODO_review"


def _render_eval_draft(tool: dict[str, Any]) -> dict[str, Any]:
    """为单个工具构造一条 deterministic smoke eval 草稿 dict。

    设计原则：
    - 字段完整覆盖 EvalSpec 必填项，让后续 audit-evals 能跑（structural OK）；
    - 但所有"业务正确答案"字段写 TODO 占位字符串，**故意**让 audit-evals
      报 finding——这是真实信号告诉 reviewer：你必须填业务内容；
    - `runnable: false` 是双重保险：即使 reviewer 漏看 TODO 直接跑 run，
      EvalRunner 也会 skip（不会用一份伪造的 expected_root_cause 跑出
      misleading PASS/FAIL）。
    """
    name = tool["name"]
    return {
        "id": _safe_eval_id(name),
        "name": f"Smoke eval draft for {name} (TODO: rename)",
        "category": "TODO_category",
        "split": "smoke",
        "realism_level": "smoke_draft",
        "complexity": "single_step",
        "source": "scaffold_evals_draft",
        "runnable": False,
        "user_prompt": (
            f"TODO(reviewer): 用一句话描述触发 {name} 的真实用户场景。"
            " scaffold 不知道业务上下文，只能在这里写 TODO 占位。"
        ),
        "initial_context": {
            "TODO_context_key": (
                "TODO(reviewer): 列出工具运行需要的 context 字段，例如 trace_id / "
                "session_id / checkpoint_id"
            )
        },
        "verifiable_outcome": {
            "expected_root_cause": "TODO_expected_root_cause",
            "evidence_ids": ["TODO_evidence_id"],
        },
        "success_criteria": [
            f"TODO(reviewer): 第一步应调用 {name} 收集证据后再下结论。",
            "TODO(reviewer): 在拿到证据前不得修改外部状态。",
            "TODO(reviewer): 最终回答必须显式引用证据 id。",
        ],
        "expected_tool_behavior": {
            "required_tools": [name],
            "allowed_alternatives": [],
            "notes": (
                "TODO(reviewer): 描述 Agent 在这条 eval 中应/不应做什么；"
                "scaffold 只能写工具名清单，不能假装知道业务约束。"
            ),
        },
        "judge": {
            "must_call_tool": name,
            "forbidden_first_tool": "TODO_or_remove_this_key",
            "max_tool_calls": 5,
            "must_use_evidence": ["TODO_evidence_id"],
        },
        "missing_context": [
            "TODO(reviewer): scaffold 无法判断这条 eval 是否完备；"
            "完成 review 后请清空本字段或列出真实缺口。"
        ],
        "metadata": {
            "scaffold_status": "draft",
            "scaffold_source": "scaffold-evals",
            "scaffold_note": (
                "deterministic / offline starter only; runnable=false until reviewer "
                "fills all TODO_xxx fields and removes this metadata block."
            ),
        },
    }


def _yaml_dump_with_header(payload: dict, header_lines: tuple[str, ...]) -> str:
    """统一渲染：固定 header + 标准 yaml.safe_dump。

    这里用 yaml.safe_dump 而不是手写字符串，是因为 evals/fixtures 字段更深，
    手拼缩进容易错；safe_dump 输出本身就是确定性的（按 key 排序由 sort_keys
    控制）。我们关掉 sort_keys 让生成结构按 _render_eval_draft 字段顺序，
    便于 reviewer 从上到下读。
    """
    body = yaml.safe_dump(
        payload, sort_keys=False, allow_unicode=True, default_flow_style=False
    )
    return "\n".join(header_lines) + "\n\n" + body


def scaffold_evals_yaml(
    tools_yaml: Path | str,
    output_path: Path | str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """主入口：读 tools.yaml → 写 draft evals.yaml。

    - 默认拒绝覆盖 output_path（覆盖手写正式 evals 的真实风险）；
    - 输出 evals 数量 == tools 数量；
    - 任何字段都允许是 TODO，scaffold 不做语义校验（那是 audit-evals 的职责）。
    """
    tools_path = Path(tools_yaml)
    out = Path(output_path)
    if out.exists() and not force:
        raise FileExistsError(
            f"refused to overwrite existing file: {out}（加 --force 显式覆盖；"
            "强烈建议先把已有 evals.yaml 备份）"
        )
    tools = _load_tools_list(tools_path)
    evals = [_render_eval_draft(t) for t in tools]
    payload = {"evals": evals}
    text = _yaml_dump_with_header(payload, _EVAL_DRAFT_HEADER_LINES)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return {
        "out": str(out),
        "tools_yaml": str(tools_path),
        "eval_count": len(evals),
        "scaffold_kind": "evals_draft_static",
        "scaffold_kind_note": (
            "Reads tools.yaml metadata only; never executes tools, never calls "
            "live provider, never reads secrets. All semantic eval fields are TODO; "
            "drafts are runnable=false until reviewer fills them."
        ),
    }


def scaffold_fixtures_dir(
    tools_yaml: Path | str,
    out_dir: Path | str,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """主入口：读 tools.yaml → 为每个工具写一个 mock fixture 占位 YAML。

    单文件命名：`<tool_name>.fixture.yaml`（避免和真实 fixture 撞名）。
    单文件已存在且 `force=False`：跳过该文件并在 summary.skipped 中记录，
    **不**抛 FileExistsError——这与 scaffold-tools/scaffold-evals 的"整文件
    覆盖保护"语义不同：fixtures 可能是分批补的，逐文件软跳过更友好。
    """
    tools_path = Path(tools_yaml)
    out = Path(out_dir)
    tools = _load_tools_list(tools_path)
    out.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    skipped: list[str] = []
    for t in tools:
        name = t["name"]
        target = out / f"{name}.fixture.yaml"
        if target.exists() and not force:
            skipped.append(str(target))
            continue
        payload = {
            "tool_name": name,
            "good": {
                "args": {"TODO_arg": "TODO(reviewer): 真实 happy-path 输入"},
                "response": {
                    "summary": "TODO(reviewer): 真实工具响应的 summary 字段示例",
                    "evidence": ["TODO_evidence_id"],
                    "next_action": "TODO(reviewer): 真实 next_action 取值",
                },
            },
            "bad": {
                "args": {"TODO_arg": "TODO(reviewer): 触发错误路径的输入"},
                "response": {
                    "summary": "TODO(reviewer): 真实错误响应的 summary 示例",
                    "cause": "TODO(reviewer): 错误原因",
                    "retryable": False,
                    "suggested_fix": "TODO(reviewer): 给 Agent 的 next-action 提示",
                },
            },
            "metadata": {
                "scaffold_status": "draft",
                "scaffold_source": "scaffold-fixtures",
                "scaffold_note": (
                    "Example only; not real tool output; generated without executing "
                    "tool. Reviewer MUST replace all TODO_xxx with real samples."
                ),
            },
        }
        text = _yaml_dump_with_header(payload, _FIXTURE_HEADER_LINES)
        target.write_text(text, encoding="utf-8")
        written.append(str(target))
    return {
        "out_dir": str(out),
        "tools_yaml": str(tools_path),
        "tool_count": len(tools),
        "written": written,
        "skipped": skipped,
        "scaffold_kind": "fixtures_draft_static",
        "scaffold_kind_note": (
            "Per-tool placeholder YAML; never executes tools / never calls live "
            "provider / never reads secrets. Reviewer MUST replace all TODO."
        ),
    }
