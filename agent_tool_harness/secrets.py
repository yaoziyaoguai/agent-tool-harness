"""Secret source abstraction —— 显式 env file / os.environ / mapping 解析。

本模块负责什么
==============
为 LLM provider config 提供统一的 secret 读取层：
1. SecretSource Protocol —— 统一的 get(name) -> str | None 接口
2. EnvFileSecretSource —— 从显式 .env 文件读取（不自动加载）
3. OsEnvSecretSource —— 从 os.environ 读取（需 --allow-os-env）
4. MappingSecretSource —— 测试用内存 dict

本模块**不**负责什么
====================
- 不自动 load_dotenv()
- 不默认读取 os.environ
- 不执行 shell expansion / command substitution
- 不把 key 打印到 stdout / stderr / log
- 不支持 inline api_key

为什么需要 EnvFileSecretSource
-----------------------------
1. 第三方转接 API 的 key/url/model 需要安全存放
2. .env 文件可以加入 .gitignore，避免进 git
3. 显式 --env-file 路径让用户明确知道哪个文件被读取
4. CI 中可以传不同的 --env-file 切换环境

为什么 OsEnvSecretSource 默认不启用
----------------------------------
1. 宿主 shell 环境变量可能跨项目泄漏
2. 需要 --allow-os-env 显式 opt-in
3. 只给高级用户或 CI pipeline 使用
"""

from __future__ import annotations

import os as _os
from pathlib import Path as _Path
from typing import Protocol, runtime_checkable

# ---------------------------------------------------------------------------
# SecretSource Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class SecretSource(Protocol):
    """统一的 secret 读取接口。

    get(name) → 返回 secret 值或 None（不存在 / 为空均返回 None）。
    不抛异常——缺失时返回 None，由调用方决定如何处理。
    """

    def get(self, name: str) -> str | None: ...


# ---------------------------------------------------------------------------
# EnvFileSecretSource
# ---------------------------------------------------------------------------


class EnvFileSecretSource:
    """从显式指定的 env 文件读取 secret。

    规则：
    - 只支持简单 KEY=VALUE 格式
    - 支持空行和 # 注释
    - 支持可选引号（单引号 / 双引号）
    - 不执行 shell expansion（$VAR / ${VAR}）
    - 不执行 command substitution（$(cmd) / `cmd`）
    - 不自动读取当前目录 .env
    - 不把 key 打印出来
    - 文件不存在时抛 FileNotFoundError
    """

    def __init__(self, path: str | _Path) -> None:
        self._path = _Path(path)
        self._values: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            raise FileNotFoundError(
                f"env file 不存在: {self._path}\n"
                "  hint: 请确认文件路径正确。如需从当前目录 .env 读取，"
                " 请显式传 --env-file ./.env"
            )
        text = self._path.read_text(encoding="utf-8")
        values: dict[str, str] = {}
        for lineno, raw in enumerate(text.splitlines(), start=1):
            line = raw.strip()
            # 空行 / 注释
            if not line or line.startswith("#"):
                continue
            # 解析 KEY=VALUE
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip()
            if not key:
                continue
            # 去掉可选引号
            value = _strip_quotes(value)
            # 拒绝 shell expansion 和 command substitution
            if "$(" in value or "`" in value:
                raise ValueError(
                    f"{self._path}:{lineno}: command substitution 不支持。"
                    " env file 中不能使用 $(cmd) 或 `cmd`。"
                )
            if "${" in value or (value.count("$") > 0 and value != "$"):
                raise ValueError(
                    f"{self._path}:{lineno}: shell expansion 不支持。"
                    " env file 中不能使用 $VAR 或 ${VAR}。"
                )
            values[key] = value
        self._values = values

    def get(self, name: str) -> str | None:
        v = self._values.get(name)
        if v is None or v == "":
            return None
        return v

    @property
    def path(self) -> _Path:
        return self._path

    def __repr__(self) -> str:
        return f"EnvFileSecretSource(path={self._path!r})"


def _strip_quotes(value: str) -> str:
    """去掉首尾匹配的引号（单引号或双引号）。"""
    if len(value) >= 2:
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            return value[1:-1]
    return value


# ---------------------------------------------------------------------------
# OsEnvSecretSource
# ---------------------------------------------------------------------------


class OsEnvSecretSource:
    """从 os.environ 读取 secret。

    只能在用户显式 --allow-os-env 时使用。默认真实调用不使用。
    """

    def get(self, name: str) -> str | None:
        v = _os.environ.get(name)
        if v is None or v == "":
            return None
        return v

    def __repr__(self) -> str:
        return "OsEnvSecretSource()"


# ---------------------------------------------------------------------------
# MappingSecretSource
# ---------------------------------------------------------------------------


class MappingSecretSource:
    """测试用：从内存 dict 读取 secret，不依赖真实环境变量。"""

    def __init__(self, mapping: dict[str, str] | None = None) -> None:
        self._mapping: dict[str, str] = dict(mapping or {})

    def get(self, name: str) -> str | None:
        v = self._mapping.get(name)
        if v is None or v == "":
            return None
        return v

    def __repr__(self) -> str:
        return f"MappingSecretSource(keys={sorted(self._mapping.keys())!r})"
