"""Eval 候选生成模块。

生成器只产出 candidate，不直接覆盖正式 evals.yaml。正式转正需要 EvalQualityAuditor
和人工 review，避免把弱题或“请调用某工具”的作弊题放进回归集。
"""
