"""Artifact schema 版本与最小 run metadata。

为什么需要这个模块（架构边界）：
- 真实团队接 CI / dashboard / 内部 reviewer 时，一手要做的事情就是"我能不能稳定
  解析这个 JSON"。如果没有 ``schema_version``，任何字段调整都会让下游消费者陷入
  "字段是不是变了"的猜测；如果没有 ``generated_at`` / ``run_id`` / ``project_name``，
  跨次 run 比较时无法把 artifact 串起来。
- 这是**最小解析契约**，不是 OpenTelemetry / OpenInference / W3C trace context。
  不引入任何 SDK；不承担分布式追踪；不替代 ``docs/ARTIFACTS.md`` 中的字段说明。
- 升级策略：字段可以**只增不删**；破坏性改动必须同时升 ``ARTIFACT_SCHEMA_VERSION``
  并在 ``docs/ARTIFACTS.md`` / ``docs/ROADMAP.md`` 显式记录。下游消费者读取时应
  ``schema_version`` 配合最大允许版本做兼容判断。

模块**不**负责：
- 不强制时区/格式之外的内容（例如不签名、不 hash、不加 trace span）。
- 不对 raw artifact（transcript.jsonl / tool_calls.jsonl / tool_responses.jsonl）
  添加包装层——那三件套是事件流，每行独立，不能塞顶层字段；它们的"版本"由本
  schema_version 配合 ``docs/ARTIFACTS.md`` 描述的字段约定共同表达。
- 不替换 ``signal_quality`` 的能力边界声明。signal_quality 是"信号质量"，
  schema_version 是"解析契约版本"，两者正交。

用户项目自定义入口：
- 不需要也不应当修改 ``ARTIFACT_SCHEMA_VERSION``。如果你需要在 artifact 里塞自己
  的字段，建议放在 ``run_metadata.extra`` 这样的扩展位，框架不会消费它，但 CI
  下游可以读到。
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime
from typing import Any

# 最小解析契约版本。语义遵循 SemVer：
# - PATCH：纯字段新增 / 文档补充 / bug 修复，下游无需改动；
# - MINOR：新增字段或新增 finding 类型，下游兼容老版本仍能解析；
# - MAJOR：删字段 / 改字段语义 / 改类型，下游必须升级。
# 当前 MVP 第一版定为 1.0.0：表示 docs/ARTIFACTS.md 列出的全部字段已稳定。
ARTIFACT_SCHEMA_VERSION = "1.0.0"


def make_run_metadata(
    *,
    project_name: str | None = None,
    eval_count: int | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """生成最小 run metadata。

    字段说明：
    - ``run_id``：UUID4，便于跨 artifact 关联同一次 run；不依赖时间，避免并发
      run 撞 ID。环境变量 ``AGENT_TOOL_HARNESS_RUN_ID`` 可显式覆盖（例如 CI 把
      build id 透传进来便于回查）。
    - ``generated_at``：UTC ISO8601。统一时区避免下游误读本地时间。
    - ``project_name`` / ``eval_count``：让 artifact 在脱离上下文（例如被人转发
      到 issue tracker）时仍能自描述。
    - ``extra``：留给上层（CLI / runner / generator）补充少量自描述字段，例如
      ``source="from_tools"``、``mock_path="bad"``。**不要塞大对象**——artifact
      不是日志库。

    本函数**不**负责：
    - 不写文件；只产出 dict 由调用方塞进 artifact。
    - 不读取 git commit / hostname 等可能泄露 PII 或导致测试不稳定的环境信息。
    """

    metadata: dict[str, Any] = {
        "run_id": os.environ.get("AGENT_TOOL_HARNESS_RUN_ID") or str(uuid.uuid4()),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    if project_name is not None:
        metadata["project_name"] = project_name
    if eval_count is not None:
        metadata["eval_count"] = int(eval_count)
    if extra:
        metadata["extra"] = dict(extra)
    return metadata


def stamp_artifact(
    payload: dict[str, Any],
    *,
    run_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """给一个派生 JSON artifact 打上 schema_version 与 run_metadata 戳。

    设计选择（**根因层**）：
    - 把 ``schema_version`` 与 ``run_metadata`` 作为**新增**顶层 key 加进去，
      而不是把现有 payload 包进 ``data`` 子字段。原因：现有所有测试和 docs/
      ARTIFACTS.md 都假设字段直接出现在顶层（例如 ``audit["summary"]`` /
      ``metrics["passed"]``），包一层会立即破坏所有下游消费者，违反"只增不删"
      的升级承诺。
    - 不在 raw JSONL 里塞这两个字段——JSONL 是逐行事件流，加一行"假事件"会污染
      时序；JSONL 的版本契约由本模块的 schema_version + docs/ARTIFACTS.md 共同
      表达。

    重复打戳是幂等的：再次 ``stamp_artifact`` 会用最新值覆盖。这让重新生成同一
    artifact（例如修复后再跑）不会出现两层 schema_version。
    """

    stamped = dict(payload)
    stamped["schema_version"] = ARTIFACT_SCHEMA_VERSION
    if run_metadata is not None:
        stamped["run_metadata"] = run_metadata
    return stamped
