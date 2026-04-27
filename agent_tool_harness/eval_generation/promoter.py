"""候选 eval 转正（promote）流程。

架构边界：
- 负责把 ``eval_candidates.yaml`` 中**已经被人工标注 review_status="accepted" 且
  runnable=true** 的候选搬运到正式 evals.yaml 片段；这一步是"人工 review →
  机械搬运"的最后一公里，**不**做 LLM 评审、**不**自动改 prompt、**不**改 judge
  规则。
- 负责拒绝写覆盖：默认禁止覆盖任何已有文件，必须显式 ``--force``。这是为了
  保护用户手写的正式 evals.yaml，避免一条命令把审核成果冲掉。
- 负责输出可行动的 skip reason：被跳过的候选必须解释"为什么跳"（review_status
  不对、runnable=false、缺 initial_context、缺 verifiable_outcome、缺 expected
  root cause、judge 规则空等），方便审核者补齐再跑一次。
- **不**做 audit-evals：promote 出来的文件由用户/CI 用 ``audit-evals`` 自己跑
  一遍，确保转正后字段能通过 EvalQualityAuditor。promoter 只做搬运，不复制 audit
  逻辑，避免审计标准两处分叉。

用户项目自定义入口：
- 输入文件可以是 ``eval_candidates: [...]`` 也可以直接是 list root（与 loader
  对 evals.yaml 的容忍策略保持一致）。
- 候选条目里可保留任何额外字段（例如 review_notes、source、difficulty）；
  promote 后**整体保留**，不丢字段——便于审核痕迹一直随 eval 走到正式 suite。

如何通过 artifacts 查问题：
- promoter 输出文件顶层会带 ``schema_version`` 与 ``promote_summary``：
  ``promote_summary.promoted`` 列出被搬运的 eval id；
  ``promote_summary.skipped`` 列出 ``{id, reason}``，让 CI / 审核者一眼看出哪些
  候选还差什么。
- promoter 不写 transcript / tool_calls / tool_responses；它运行在"运行时之外"。

未来扩展点（仅 ROADMAP，不在本轮实现）：
- 可加 ``--needs-review`` 状态过滤；
- 可结合真实 issue tracker 自动同步 review 状态；
- 可加 LLM Reviewer 作为 second-pass，但与 deterministic check 并列，不替换。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agent_tool_harness.artifact_schema import make_run_metadata, stamp_artifact


@dataclass
class PromoteResult:
    """一次 promote 的结果摘要。

    promoted / skipped 都是面向人类审核者的，便于在 CLI 输出和测试断言里直接消费。
    """

    promoted: list[dict[str, Any]]
    skipped: list[dict[str, str]]
    out_path: Path


class CandidatePromoter:
    """把 review 通过的候选搬运成正式 evals.yaml。

    约束（与文档/测试硬契约）：
    - 必须 ``review_status == "accepted"``（大小写不敏感，去空格）；
    - 必须 ``runnable`` 为 True；
    - 必须有非空 ``initial_context`` 和非空 ``verifiable_outcome``；
    - ``verifiable_outcome.expected_root_cause`` 不能是空字符串；
    - ``judge.rules`` 至少一条。
    任何一条不满足的候选都进入 skipped，**不**写进输出文件——这是把"审核闭环"
    的责任留在审核者身上，框架不替审核者做主。
    """

    def promote(
        self,
        candidates_path: str | Path,
        out_path: str | Path,
        *,
        force: bool = False,
    ) -> PromoteResult:
        candidates_file = Path(candidates_path)
        out_file = Path(out_path)
        if not candidates_file.exists():
            raise FileNotFoundError(f"candidates file does not exist: {candidates_file}")
        if out_file.exists() and not force:
            # 默认禁止覆盖：保护用户手写正式 evals.yaml。要求显式 ``--force`` 才允许。
            raise FileExistsError(
                f"refusing to overwrite existing file: {out_file}; "
                "如需覆盖请显式传 --force（请先确认目标不是手写正式 evals.yaml）"
            )

        candidates = self._load_candidates(candidates_file)
        promoted: list[dict[str, Any]] = []
        skipped: list[dict[str, str]] = []
        for index, candidate in enumerate(candidates):
            cid = str(candidate.get("id") or f"<index_{index}>")
            reason = self._reject_reason(candidate)
            if reason is None:
                # 整体搬运：保留所有审核痕迹字段（review_status/review_notes/
                # difficulty/source 等），只剥掉 promoter 内部的临时字段（目前没有）。
                promoted.append(dict(candidate))
            else:
                skipped.append({"id": cid, "reason": reason})

        out_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "evals": promoted,
            "promote_summary": {
                "promoted_ids": [str(item.get("id")) for item in promoted],
                "skipped": skipped,
                "input_path": str(candidates_file),
            },
        }
        stamped = stamp_artifact(
            payload,
            run_metadata=make_run_metadata(
                eval_count=len(promoted),
                extra={"command": "promote-evals"},
            ),
        )
        with out_file.open("w", encoding="utf-8") as fh:
            yaml.safe_dump(stamped, fh, allow_unicode=True, sort_keys=False)
        return PromoteResult(promoted=promoted, skipped=skipped, out_path=out_file)

    # ------------------------------------------------------------------
    # 私有：装载与判定
    # ------------------------------------------------------------------

    def _load_candidates(self, path: Path) -> list[dict[str, Any]]:
        """读取候选文件并归一化为 list[dict]。

        容忍两种 root：
        - mapping 含 ``eval_candidates: [...]``（CandidateWriter 写出来的格式）；
        - 直接是 list（用户手工调整后的简化格式）。
        与 loader.load_evals 对 evals.yaml 的容忍策略保持一致。
        """

        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        if isinstance(data, list):
            raw = data
        elif isinstance(data, dict):
            raw = data.get("eval_candidates", data.get("evals", []))
        else:
            raise ValueError(f"candidates file root must be mapping or list: {path}")
        if not isinstance(raw, list):
            raise ValueError("candidates must be a list")
        results: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, dict):
                results.append(item)
        return results

    def _reject_reason(self, candidate: dict[str, Any]) -> str | None:
        """返回拒绝原因；如果可以 promote 则返回 None。

        拒绝原因都是**可行动的**——告诉审核者下一步要补什么，不只是"reject"。
        """

        status = str(candidate.get("review_status", "")).strip().lower()
        if status != "accepted":
            return (
                f"review_status={status!r} (需要 'accepted'；先把 review_notes 处理掉"
                "再把 review_status 改成 accepted)"
            )
        if not bool(candidate.get("runnable", False)):
            return (
                "runnable=false（候选需要先补齐 initial_context 等让 audit 判 runnable=true）"
            )
        initial_context = candidate.get("initial_context") or {}
        if not isinstance(initial_context, dict) or not initial_context:
            return "initial_context 为空（请补真实用户上下文/fixture）"
        outcome = candidate.get("verifiable_outcome") or {}
        if not isinstance(outcome, dict) or not outcome:
            return "verifiable_outcome 为空（请补可验证根因/证据）"
        if not str(outcome.get("expected_root_cause", "")).strip():
            return "verifiable_outcome.expected_root_cause 为空（RuleJudge 无法判定）"
        judge = candidate.get("judge") or {}
        rules = judge.get("rules") if isinstance(judge, dict) else None
        if not isinstance(rules, list) or not rules:
            return "judge.rules 为空（请至少配置一条 must_use_evidence 等语义规则）"
        return None
