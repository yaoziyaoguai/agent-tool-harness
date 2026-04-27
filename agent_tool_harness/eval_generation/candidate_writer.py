"""候选 eval YAML 序列化。

架构边界：
- 只做序列化与最小自描述（schema_version / generated_at / warnings）。
- **不**决定候选是否转正——那是 ``CandidatePromoter`` 的职责；
- **不**重做 audit——空候选 / 缺上下文 / cheating prompt 等"质量提示"只是
  warning，不会过滤候选；写入文件后由审核者人工判断如何处理。

为什么要在写入阶段就计算 warnings：
- generate-evals 的输出是审核者的"工作清单"。如果只在 stderr 打印警告，审核者
  关掉终端就丢了；写进文件顶层 ``warnings`` 字段，能跟随候选文件被 review、被
  commit、被 PR diff 看到，形成审核闭环的一部分。
- warnings **不是失败**，CLI 退出码仍是 0；这是为了让"候选质量不足"和"配置错误"
  在退出码层面区分开。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from agent_tool_harness.artifact_schema import make_run_metadata, stamp_artifact


class CandidateWriter:
    """把候选 eval 写成 YAML，并附带最小自描述与质量 warning。

    输出文件结构（顶层 mapping）：
    - ``schema_version`` / ``run_metadata``：解析契约（详见 artifact_schema.py）；
    - ``warnings``：list[str]，质量提示；空 list 表示无可见质量风险；
    - ``eval_candidates``：list[dict]，原样保留生成器产出的候选（含 review_notes）。
    """

    def write(self, candidates: list[dict[str, Any]], out_path: str | Path) -> Path:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        warnings = self.collect_warnings(candidates)
        payload = {
            "warnings": warnings,
            "eval_candidates": candidates,
        }
        stamped = stamp_artifact(
            payload,
            run_metadata=make_run_metadata(
                eval_count=len(candidates),
                extra={"command": "generate-evals"},
            ),
        )
        with path.open("w", encoding="utf-8") as file:
            yaml.safe_dump(stamped, file, allow_unicode=True, sort_keys=False)
        return path

    # ------------------------------------------------------------------
    # warnings 计算
    # ------------------------------------------------------------------

    # 与 EvalQualityAuditor.realism.cheating_prompt 同步的轻量启发式。这里**故意**
    # 复制几条最常见的短语，而不是 import auditor——审计与生成解耦能让两边演进
    # 更自由；如果将来需要统一，再抽到 ``audit/cheating_signals.py``。
    _CHEATING_SIGNALS = (
        "please call",
        "please use",
        "call the ",
        "use the ",
        "invoke the ",
        "请调用",
        "请使用",
        "使用工具",
    )

    def collect_warnings(self, candidates: list[dict[str, Any]]) -> list[str]:
        """从候选列表派生质量 warning。

        返回中文一行的可行动提示；不重复同类 warning。
        本方法**不**修改 candidates，纯读。
        """

        warnings: list[str] = []
        if not candidates:
            warnings.append(
                "empty_input: 没有生成任何候选；请确认 tools.yaml/tests 路径包含足够"
                "信号（工具描述、when_to_use、test docstring 等）。"
            )
            return warnings

        unrunnable = [c for c in candidates if not bool(c.get("runnable"))]
        if len(unrunnable) == len(candidates):
            warnings.append(
                "all_unrunnable: 全部候选 runnable=false；通常意味着工具/测试缺少 "
                "fixture/initial_context；请按每条候选的 review_notes 补齐再 promote。"
            )

        no_notes = [
            c
            for c in candidates
            if not isinstance(c.get("review_notes"), list) or not c.get("review_notes")
        ]
        if no_notes:
            warnings.append(
                f"missing_review_notes: {len(no_notes)} 条候选没有 review_notes；"
                "审核者将拿到无说明的候选，请检查生成器是否被改弱。"
            )

        # missing_context > 1 视为"缺上下文较多"，不是"完全没救"。
        many_missing = [
            c
            for c in candidates
            if isinstance(c.get("missing_context"), list) and len(c["missing_context"]) > 1
        ]
        if many_missing:
            ids = ", ".join(str(c.get("id")) for c in many_missing[:3])
            warnings.append(
                f"high_missing_context: {len(many_missing)} 条候选 missing_context 多于 1 项"
                f"（前 3 条：{ids}）；优先为这些候选补 fixture / expected_root_cause。"
            )

        cheating_ids: list[str] = []
        for c in candidates:
            prompt = str(c.get("user_prompt", "")).lower()
            if any(sig in prompt for sig in self._CHEATING_SIGNALS):
                cheating_ids.append(str(c.get("id")))
        if cheating_ids:
            sample = ", ".join(cheating_ids[:3])
            warnings.append(
                f"cheating_prompt_suspect: {len(cheating_ids)} 条候选 user_prompt 出现"
                f'"call/use/请调用/请使用/使用工具" 等动词（前 3 条：{sample}）；'
                "请改写成纯用户目标，避免泄露调用路径。"
            )

        return warnings
