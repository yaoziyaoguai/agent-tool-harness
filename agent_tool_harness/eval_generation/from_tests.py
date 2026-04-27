from __future__ import annotations

import ast
from pathlib import Path
from typing import Any


class FromTestsGenerator:
    """从 pytest 测试扫描 eval candidate。

    架构边界：
    - 只抽取 test 函数名、docstring、xfail reason 和 regression 命名线索。
    - 不尝试猜测完整 fixture；无法构造 initial_context 时必须标记 runnable=false。
    - 不执行测试文件，避免扫描阶段产生副作用。

    扩展点：
    - 后续可读取测试 fixture、snapshot 或失败 transcript 来补全 runnable eval。

    测试纪律：
    - 从测试生成的候选默认不可运行，因为单元测试名并不等于真实用户上下文。
    - xfail reason 只作为候选元数据，不代表 harness 可以放宽正式 eval 判定。
    """

    def generate(self, tests_path: str | Path) -> list[dict[str, Any]]:
        root = Path(tests_path)
        files = [root] if root.is_file() else sorted(root.rglob("test_*.py"))
        candidates: list[dict[str, Any]] = []
        for file_path in files:
            candidates.extend(self._from_file(file_path, root))
        return candidates

    def _from_file(self, file_path: Path, root: Path) -> list[dict[str, Any]]:
        tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
        cases = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                xfail_reason = self._xfail_reason(node)
                is_regression = "regression" in node.name.lower()
                rel = file_path.relative_to(root) if root.is_dir() else file_path.name
                doc = ast.get_docstring(node) or ""
                cases.append(
                    {
                        "id": f"candidate_from_test_{file_path.stem}_{node.name}",
                        "name": node.name.replace("_", " "),
                        "category": "regression" if is_regression else "test_derived",
                        "split": "regression" if is_regression else "training",
                        "realism_level": "regression" if is_regression else "synthetic_realistic",
                        "complexity": "unknown",
                        "source": "generated_from_tests",
                        "user_prompt": self._prompt_from_test_name(node.name, doc),
                        "initial_context": {},
                        "verifiable_outcome": {
                            "test_file": str(rel),
                            "test_function": node.name,
                            "xfail_reason": xfail_reason,
                        },
                        "success_criteria": [
                            "候选来自测试语义，转正前必须补充真实用户上下文和可验证证据。"
                        ],
                        "expected_tool_behavior": {
                            "notes": "从测试静态信息无法可靠推断工具调用路径。"
                        },
                        "judge": {"rules": []},
                        "runnable": False,
                        "missing_context": ["initial_context", "expected_tool_behavior"],
                    }
                )
        return cases

    def _prompt_from_test_name(self, name: str, doc: str) -> str:
        if doc:
            return doc.strip().splitlines()[0]
        phrase = name.removeprefix("test_").replace("_", " ")
        return f"请把这个回归测试场景转化为真实用户问题：{phrase}"

    def _xfail_reason(self, node: ast.FunctionDef) -> str:
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            name = self._decorator_name(decorator.func)
            if name.endswith("xfail"):
                for keyword in decorator.keywords:
                    if keyword.arg == "reason" and isinstance(keyword.value, ast.Constant):
                        return str(keyword.value.value)
        return ""

    def _decorator_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            return f"{self._decorator_name(node.value)}.{node.attr}"
        return ""
