"""跨 artifact 一致性 + 反泄漏审计（v1.7 第二项）。

中文学习型说明
==============
本文件**钉死**的边界
--------------------
1. **同一次 run 产出的所有 JSON artifact 必须有 ``schema_version`` 顶层
   字段**——这是下游消费者升级时的唯一信号；
2. **没有任何 artifact（JSON / md / jsonl）允许出现 sk- 形态 key 字面、
   ``Authorization`` header 字面、``Bearer `` token 字面**——v1.6
   judge prompt auditor 已经按 prompt 维度脱敏；本测试在 artifact 维度
   横向钉死，防止 v1.7+ 加新 artifact 时遗漏；
3. **``llm_cost.json`` 的 ``estimated_cost_usd`` 必须为 null 且
   ``estimated_cost_note`` 必须包含 advisory-only 措辞**——防止有人
   悄悄接价格表把 cost 当真实账单宣传（v1.6 硬约束）；
4. **``preflight.json`` 在没真实 key 的 CI 默认场景必须
   ``ready_for_live=false``**——防止有人误把默认值翻成 true 让用户
   以为已接通真实 LLM。

本文件**不**负责什么
--------------------
- 不验证 artifact 字段语义正确性（每个产生器自己有单测）；
- 不替代 ``test_subcommand_artifact_contract.py`` 的"文件名集合"契约；
- 不验证 markdown 视觉渲染。

防回归价值
----------
真实可能的 bug：
- v1.7 加新 artifact 时忘了写 schema_version → 下游消费者无法判断版本；
- 有人把 raw API key / Authorization header dump 进 transcript 或
  judge_results.json（live 路径很容易踩到）；
- 有人偷偷给 llm_cost.json 接了价格表又忘了改 advisory-only 措辞；
- 有人把 preflight 默认值翻成"成功"伪装通过。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from agent_tool_harness.cli import main as cli_main

REPO_ROOT = Path(__file__).resolve().parent.parent
EX = REPO_ROOT / "examples" / "runtime_debug"

# 模拟 OpenAI / Anthropic key 形态（含 sk-ant-）+ Authorization header 字面。
# 这些 pattern 故意宽松——宁可 false positive 让维护者解释，
# 也不能 false negative 让真实 key 漏出去。
KEY_LIKE = re.compile(r"sk-[A-Za-z0-9_\-]{16,}|sk-ant-[A-Za-z0-9_\-]{8,}")
AUTH_HEADER = re.compile(r"\bAuthorization:\s*Bearer\s+\S{8,}", re.IGNORECASE)
BEARER_LITERAL = re.compile(r"\bBearer\s+[A-Za-z0-9_\-\.]{16,}")


def _scan_for_secrets(path: Path) -> list[str]:
    """扫描单个文件是否含真实 key / Authorization header / Bearer token 字面。"""
    text = path.read_text(encoding="utf-8", errors="replace")
    hits: list[str] = []
    for label, pat in (("KEY_LIKE", KEY_LIKE),
                       ("AUTH_HEADER", AUTH_HEADER),
                       ("BEARER", BEARER_LITERAL)):
        for m in pat.finditer(text):
            hits.append(f"{label}: {m.group(0)[:24]}...")
    return hits


@pytest.fixture
def smoke_run(tmp_path: Path) -> Path:
    """用 runtime_debug bad path 跑一次 run，产出 v1.6 全套 artifact 用于扫描。"""
    out = tmp_path / "run-bad"
    rc = cli_main([
        "run",
        "--project", str(EX / "project.yaml"),
        "--tools", str(EX / "tools.yaml"),
        "--evals", str(EX / "evals.yaml"),
        "--out", str(out),
        "--mock-path", "bad",
    ])
    assert rc == 0
    return out


def test_all_run_json_artifacts_have_schema_version(smoke_run: Path):
    """所有 .json artifact 必须有顶层 schema_version 字段。"""
    missing: list[str] = []
    for p in sorted(smoke_run.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        if "schema_version" not in data:
            missing.append(p.name)
    assert not missing, (
        f"artifacts missing schema_version: {missing}; "
        "下游消费者无法判断版本兼容性。"
    )


def test_no_secrets_leak_in_any_artifact(smoke_run: Path):
    """任何 artifact 文件不能包含真实 key / Authorization header / Bearer token 字面。"""
    leaks: dict[str, list[str]] = {}
    for p in smoke_run.iterdir():
        if not p.is_file():
            continue
        hits = _scan_for_secrets(p)
        if hits:
            leaks[p.name] = hits
    assert not leaks, (
        f"secret-like strings leaked into artifacts: {leaks}; "
        "v1.6/v1.7 安全闸门要求所有 artifact 维度 0 泄漏。"
    )


def test_llm_cost_advisory_only_contract_holds(smoke_run: Path):
    """llm_cost.json estimated_cost_usd 必须 null + 措辞必须 advisory-only。"""
    cost = json.loads((smoke_run / "llm_cost.json").read_text(encoding="utf-8"))
    assert cost.get("estimated_cost_usd") is None, (
        "v1.6 estimated_cost_usd 永远是 null；如要接真实价格表请走 v1.7+ 设计评审。"
    )
    note = cost.get("estimated_cost_note", "")
    assert "advisory-only" in note, (
        "estimated_cost_note 必须显式声明 advisory-only，禁止把 cost 当真实账单宣传。"
    )
    # totals 必须存在且各字段是非负整数（防止有人把 None 当 0 蒙过去）。
    totals = cost.get("totals", {})
    for k in ("advisory_count", "tokens_in", "tokens_out",
              "retry_count_total", "error_count"):
        v = totals.get(k)
        assert isinstance(v, int) and v >= 0, (
            f"totals.{k} 必须是非负整数，实际 {v!r}"
        )


def test_preflight_default_is_not_ready_for_live(tmp_path: Path):
    """无真实 key 的默认 CI 场景下，preflight.ready_for_live 必须为 false。

    防止有人误把默认值翻成 true 让用户以为接通了真实 LLM。
    """
    out = tmp_path / "preflight"
    rc = cli_main(["judge-provider-preflight", "--out", str(out)])
    # preflight 设计上即使 not ready 也返回 0（advisory），不应在 CI 中断。
    assert rc == 0
    pre = json.loads((out / "preflight.json").read_text(encoding="utf-8"))
    summary = pre.get("summary", {})
    assert summary.get("ready_for_live") is False, (
        "默认 CI 场景没有真实 key，summary.ready_for_live 必须 false；"
        "翻成 true 会误导用户以为已经接通真实 LLM。"
    )
