"""``agent_tool_harness.feedback`` —— 内部试用反馈 intake guard。

中文学习型说明
==============
本子包**不**调真实 LLM、**不**联网、**不**读 .env、**不**调用任何
外部服务、**不**自动修改反馈文件。它只做一件事：

> 给定一条 internal trial feedback record（dict），按
> [`docs/FEEDBACK_TRIAGE_WORKFLOW.md`](../docs/FEEDBACK_TRIAGE_WORKFLOW.md)
> §2 决策表的契约**校验**它是否：
> 1. 字段完整（必填字段都填了）；
> 2. 不含真实 secret / Authorization / 完整请求响应；
> 3. 内部纪律一致（synthetic 不算真实反馈、security 必须走 security-blocker、
>    v3.0 candidate 必须解释 offline gap、final_triage_decision 在 allowlist）；
> 4. 是否计入"真实反馈"3 份门槛。

**为什么是子包级 guard，不做 CLI 子命令**
- 加 CLI 会触发 ``tests/test_docs_cli_*.py`` 的 snippet/schema drift
  约束，scope 在本轮（v2.x 文档治理 + 反馈纪律）会失控；
- 当前 maintainer 收到反馈是**手动**追加到
  ``INTERNAL_TRIAL_FEEDBACK_SUMMARY.md`` + DOGFOODING_LOG，validator
  作为 ``python -c`` 或测试桩调用足矣；
- 未来如果反馈量起来（≥10 份），再加 ``cli feedback-validate`` 子命令。

**为什么 validator 不能调用 LLM 或读取 secrets**
- 反馈本身可能含敏感数据（虽然模板和 IM 已多次警告），让 validator
  把反馈喂给真实 LLM = 把潜在 leak 主动外泄；
- validator 是**纪律边界**，不是智能助手。所有判定都是确定性规则。

**用户项目自定义入口**
本模块**不**暴露用户项目自定义入口——它是 maintainer-side 的纪律
guard，不在试用者的 7 步路径里。

**如何通过 artifacts 查问题**
本模块**不产出** run-level artifact。它只返回结构化校验结果：
- ``ok`` (bool)：是否通过全部 hard rule；
- ``errors`` (list[str])：硬错误（必须修），如缺必填字段、含真实 secret、
  违反纪律一致性；
- ``warnings`` (list[str])：软提示（建议修但不阻塞），如缺 reproduction；
- ``counts_toward_real_feedback`` (bool)：是否计入 3 份 v3.0 门槛；
- ``suggested_triage`` (str | None)：根据规则推断的分类，仅供参考。

**MVP / mock / demo 边界**
- 当前是 MVP：固定 16 个必填字段 + 7 条规则。**不**做语义分析、**不**做
  自动修复、**不**做交互；
- demo 边界：``validate_feedback_dict`` 可以独立调用，**不**依赖 yaml/
  filesystem，方便测试与 review；
- 未来扩展点：(a) 加 yaml 文件读取入口；(b) 接 CLI；(c) 加更多硬规则
  （如 reproduction 必须含 artifact path）；(d) 接 ``ROADMAP.md`` 的
  v3.0 backlog 自动追加（**仍不**实现 v3.0 能力本身）。
"""

from .validator import (
    ALLOWED_TRIAGE_DECISIONS,
    REQUIRED_FIELDS,
    ValidationResult,
    validate_feedback_dict,
)

__all__ = [
    "REQUIRED_FIELDS",
    "ALLOWED_TRIAGE_DECISIONS",
    "ValidationResult",
    "validate_feedback_dict",
]
