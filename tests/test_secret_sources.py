"""Secret source 测试。

测试纪律：
- 零网络依赖
- 不读取真实 .env 文件（使用 tempfile）
- 不读取 os.environ
- MappingSecretSource 不依赖真实环境变量
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from agent_tool_harness.secrets import (
    EnvFileSecretSource,
    MappingSecretSource,
    OsEnvSecretSource,
    SecretSource,
)

# ---------------------------------------------------------------------------
# 1. EnvFileSecretSource — basic KEY=VALUE
# ---------------------------------------------------------------------------


def test_env_file_reads_key_value():
    """EnvFileSecretSource 正确读取 KEY=VALUE。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / ".env"
        f.write_text("MY_KEY=my-value\nOTHER_KEY=other-value\n")
        src = EnvFileSecretSource(str(f))
        assert src.get("MY_KEY") == "my-value"
        assert src.get("OTHER_KEY") == "other-value"
        assert src.get("NONEXISTENT") is None


# ---------------------------------------------------------------------------
# 2. EnvFileSecretSource — comments and empty lines
# ---------------------------------------------------------------------------


def test_env_file_skips_comments_and_empty_lines():
    """EnvFileSecretSource 跳过注释和空行。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / ".env"
        f.write_text(
            "# This is a comment\n"
            "\n"
            "  # indented comment\n"
            "KEY=value\n"
            "\n"
            "OTHER=other-value\n"
        )
        src = EnvFileSecretSource(str(f))
        assert src.get("KEY") == "value"
        assert src.get("OTHER") == "other-value"
        assert src.get("# This is a comment") is None


# ---------------------------------------------------------------------------
# 3. EnvFileSecretSource — quotes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected",
    [
        ('KEY="double-quoted"', "double-quoted"),
        ("KEY='single-quoted'", "single-quoted"),
        ("KEY=unquoted", "unquoted"),
        ("KEY=\"mixed'quote\"", "mixed'quote"),
    ],
)
def test_env_file_strips_quotes(raw, expected):
    """EnvFileSecretSource 正确去掉首尾匹配引号。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / ".env"
        f.write_text(raw + "\n")
        src = EnvFileSecretSource(str(f))
        assert src.get("KEY") == expected


# ---------------------------------------------------------------------------
# 4. EnvFileSecretSource — no shell expansion
# ---------------------------------------------------------------------------


def test_env_file_rejects_command_substitution():
    """EnvFileSecretSource 拒绝 $(cmd)。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / ".env"
        f.write_text("KEY=$(echo hello)\n")
        with pytest.raises(ValueError, match="command substitution"):
            EnvFileSecretSource(str(f))


def test_env_file_rejects_backtick():
    """EnvFileSecretSource 拒绝 `cmd`。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / ".env"
        f.write_text("KEY=`echo hello`\n")
        with pytest.raises(ValueError, match="command substitution"):
            EnvFileSecretSource(str(f))


def test_env_file_rejects_shell_expansion():
    """EnvFileSecretSource 拒绝 ${VAR}。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / ".env"
        f.write_text("KEY=${HOME}/path\n")
        with pytest.raises(ValueError, match="shell expansion"):
            EnvFileSecretSource(str(f))


# ---------------------------------------------------------------------------
# 5. EnvFileSecretSource — file not found
# ---------------------------------------------------------------------------


def test_env_file_not_found():
    """EnvFileSecretSource 文件不存在时抛 FileNotFoundError。"""
    with pytest.raises(FileNotFoundError, match="env file 不存在"):
        EnvFileSecretSource("/nonexistent/.env")


# ---------------------------------------------------------------------------
# 6. EnvFileSecretSource — does not auto-read .env
# ---------------------------------------------------------------------------


def test_env_file_does_not_auto_read_dotenv():
    """EnvFileSecretSource 不会自动读取当前目录 .env。"""
    # 必须显式传路径，没有默认路径
    import inspect
    sig = inspect.signature(EnvFileSecretSource.__init__)
    params = list(sig.parameters.values())
    # path 是第一个参数（after self），没有默认值
    assert params[1].name in ("path",)
    assert params[1].default is inspect.Parameter.empty


# ---------------------------------------------------------------------------
# 7. EnvFileSecretSource — repr does not leak values
# ---------------------------------------------------------------------------


def test_env_file_repr_does_not_leak_values():
    """EnvFileSecretSource repr 不显示 key 值。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / ".env"
        f.write_text("SECRET=sk-deadbeef\n")
        src = EnvFileSecretSource(str(f))
        r = repr(src)
        assert "sk-deadbeef" not in r
        assert str(f) in r


# ---------------------------------------------------------------------------
# 8. MappingSecretSource
# ---------------------------------------------------------------------------


def test_mapping_secret_source_returns_values():
    """MappingSecretSource 返回 dict 中存储的值。"""
    src = MappingSecretSource({"A": "1", "B": "2"})
    assert src.get("A") == "1"
    assert src.get("B") == "2"
    assert src.get("C") is None


def test_mapping_secret_source_empty_value_is_none():
    """MappingSecretSource 空字符串返回 None。"""
    src = MappingSecretSource({"A": ""})
    assert src.get("A") is None


def test_mapping_secret_source_none_value_is_none():
    """MappingSecretSource None 值返回 None。"""
    src = MappingSecretSource({"A": None})  # type: ignore[dict-item]
    assert src.get("A") is None


# ---------------------------------------------------------------------------
# 9. SecretSource Protocol
# ---------------------------------------------------------------------------


def test_mapping_secret_source_conforms_to_protocol():
    """MappingSecretSource 符合 SecretSource Protocol。"""
    src = MappingSecretSource({"A": "1"})
    assert isinstance(src, SecretSource)


def test_env_file_secret_source_conforms_to_protocol():
    """EnvFileSecretSource 符合 SecretSource Protocol。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / ".env"
        f.write_text("A=1\n")
        src = EnvFileSecretSource(str(f))
        assert isinstance(src, SecretSource)


# ---------------------------------------------------------------------------
# 10. OsEnvSecretSource
# ---------------------------------------------------------------------------


def test_os_env_secret_source_reads_os_environ(monkeypatch):
    """OsEnvSecretSource 从 os.environ 读取。"""
    monkeypatch.setenv("TEST_SECRET", "real-value")
    src = OsEnvSecretSource()
    assert src.get("TEST_SECRET") == "real-value"
    assert src.get("NONEXISTENT") is None


def test_os_env_secret_source_empty_value_is_none(monkeypatch):
    """OsEnvSecretSource 空值返回 None。"""
    monkeypatch.setenv("TEST_EMPTY", "")
    src = OsEnvSecretSource()
    assert src.get("TEST_EMPTY") is None
