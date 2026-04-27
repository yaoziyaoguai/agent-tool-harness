"""Agent Tool Harness.

这个包提供一个最小但可运行的 Agent 工具评估闭环：

Audit -> Generate -> Audit Evals -> Run -> Record -> Judge -> Diagnose -> Report。

框架只处理“工具契约、eval 质量、真实调用证据和诊断报告”，不把任何用户项目的
业务逻辑写进核心包。用户项目差异必须通过 project.yaml、tools.yaml、evals.yaml、
adapter、executor 或 judge 注入。
"""

__all__ = ["__version__"]

__version__ = "0.1.0"
