"""Agent Tool Harness.

不运行 Agent 的 Agent 工具评估闭环：

Import (trace JSON) → Inspect (deterministic rules) → Evaluate (pass/fail)
→ Advise (LLM judge, opt-in) → Report (Markdown + JSON artifacts)。

核心原则：
- 外部 runner 产生 trace，harness 导入并评测（不运行 Agent）
- RuleFinding（确定性规则）决定 passed；JudgeFinding（LLM）仅 advisory
- ReviewDecision 必须人工显式创建
- 用户项目差异通过 project.yaml / tools.yaml / evals.yaml 注入
"""

__all__ = ["__version__"]

__version__ = "3.3.1"
