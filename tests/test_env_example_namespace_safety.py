"""Tests pinning .env.example as a v2.x live readiness 安全模板。

中文学习型说明
==============
本测试模块**不**调真实 LLM，**不**联网，**不**读 .env 真实值；它只对
``.env.example`` 做静态字符串检查，目的是把"模板未来不能漂"的若干
**不可逆安全约束**钉死，包括：

1. **命名空间隔离**：本项目**只**接受 ``AGENT_TOOL_HARNESS_LLM_*`` 4
   个变量名；任何把 ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` /
   ``MODEL_NAME`` 写成"项目应该读"的左值都会被本测试视为合并失败——因为
   那会让用户为别的项目（如 IDE 插件、其它 Agent 框架）设的 key 在
   本项目意外生效，破坏 budget / 跨项目隔离 / no-leak 边界。
2. **占位符纪律**：4 个 ``AGENT_TOOL_HARNESS_LLM_*=`` 行右侧必须为空，
   绝不能在模板里写出疑似真实 key（``sk-`` 开头）/ 真实 https URL /
   形如 base64 长字符串。这条由 ``judge-provider-preflight`` 的
   ``env_example_safe`` 也在跑，本测试做第二层冗余防御。
3. **模型名仅作为字符串字面量出现**：模板可以**列出**阿里云 Coding
   Plan Anthropic-compatible 网关已知模型名（如 ``qwen3-coder-next``）
   作为人类参考；但不允许出现"项目代码会内置 allowlist"的暗示，因为
   v2.x 主线**不**做 model 路由 / model 准入控制，这些都属 v3.0+。
4. **opt-in 关键词存在**：模板必须显式提到双标志契约
   （``--live`` + ``--confirm-i-have-real-key``）和 no-leak 5 条
   纪律的关键名词，确保即使用户跳过 README 也能从模板自身读到红线。

为什么不直接 import 项目代码做 dynamic 检查？
- 本测试故意只做**纯文本 / 静态**校验，避免把测试 hook 进真实 provider
  factory；那会把"未来 v3.0 才接的 live executor"测试入口提前曝光。
- 测试**不**写入任何 artifact，**不**生成 .env，**不**调 preflight
  CLI——是为了保持 v2.x "0 联网 / 0 真实 key" 的全局不变量。

未来扩展点（**不**在本测试里实现）：
- v3.0 真接 live executor 时，新增的网络层 contract test 应该放在
  ``tests/test_live_anthropic_transport.py`` 旁边，**不要**塞进本文件。
- 如果未来支持除阿里云外的其它 Anthropic-compatible 网关，模板里继续
  追加新模型名即可；本测试**不**锁定模型名 allowlist。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_EXAMPLE = REPO_ROOT / ".env.example"

CANONICAL_KEYS = (
    "AGENT_TOOL_HARNESS_LLM_PROVIDER",
    "AGENT_TOOL_HARNESS_LLM_BASE_URL",
    "AGENT_TOOL_HARNESS_LLM_API_KEY",
    "AGENT_TOOL_HARNESS_LLM_MODEL",
)


def _read_env_example() -> str:
    assert ENV_EXAMPLE.is_file(), f"{ENV_EXAMPLE} 必须存在（v2.x release gate）"
    return ENV_EXAMPLE.read_text(encoding="utf-8")


def _assignment_lines(text: str) -> list[str]:
    """返回所有 ``KEY=VALUE`` 形式的赋值行（忽略注释行）。"""
    out: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            out.append(stripped)
    return out


def test_canonical_namespace_keys_present_with_empty_value():
    """4 个项目 canonical key 必须出现，且右值必须为空（占位符）。

    这条失败说明：要么有人删了某个 canonical key（preflight 会漏检），
    要么有人把真实 key 写进了模板（leak，立刻 release-blocking）。
    """
    text = _read_env_example()
    assignments = _assignment_lines(text)
    keys_with_value = {line.split("=", 1)[0]: line.split("=", 1)[1] for line in assignments}
    for key in CANONICAL_KEYS:
        assert key in keys_with_value, f"{key} 必须以占位符形式出现在 .env.example"
        value = keys_with_value[key].strip()
        assert value == "", (
            f"{key} 右值必须为空占位符；当前 .env.example 出现疑似真实值，"
            f"这是 release-blocking 的 leak。"
        )


def test_no_alternate_namespace_assignment_lines():
    """不允许 .env.example 出现"项目应该读"的非 canonical 命名赋值行。

    模拟边界：维护者出于"方便"在模板里加一行
    ``ANTHROPIC_API_KEY=`` —— 这会让真心想做隔离的用户**误以为**本项目
    会读它，从而把别的项目 key 用到这里。本测试要在这种漂移合并前就
    把它拦下来。

    注意：模板的注释里**可以**提到 ``ANTHROPIC_API_KEY`` 名字（用来解释
    为什么我们故意不用它），但不能出现成赋值行。
    """
    text = _read_env_example()
    assignments = _assignment_lines(text)
    forbidden = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "MODEL_NAME", "REVIEW_MODEL_NAME"}
    for line in assignments:
        key = line.split("=", 1)[0]
        assert key not in forbidden, (
            f"模板出现非 canonical 命名空间的赋值行 {key!r}；"
            "本项目故意只读 AGENT_TOOL_HARNESS_LLM_* 4 个变量，"
            "把通用名加成赋值行会破坏跨项目隔离。"
        )
        assert key.startswith("AGENT_TOOL_HARNESS_LLM_"), (
            f"非 canonical 命名空间赋值行 {key!r} 出现在 .env.example，"
            "请改写到注释，或用 AGENT_TOOL_HARNESS_LLM_ 前缀。"
        )


def test_no_real_key_or_url_shape_in_template():
    """绝不允许模板出现疑似真实 key / 真实 https endpoint 字面量。

    模拟边界：维护者贴了一份"测试用的"短 key（如 ``sk-...``）以为不要紧；
    或贴了一段真实 base_url（``https://dashscope.aliyuncs.com/...``）。
    这两类都是 v2.x release-blocking leak，必须立刻拦下来。
    """
    text = _read_env_example()
    forbidden_patterns = (
        # 真实 key 常见前缀（任何 SDK 风格的 prefix 一律拒绝）
        re.compile(r"\bsk-[A-Za-z0-9]{8,}"),
        re.compile(r"\bsk_[A-Za-z0-9]{8,}"),
        # 真实 https endpoint：模板里的 example 必须用 .example.com 兜底
        re.compile(r"https://[A-Za-z0-9.-]+\.aliyuncs\.com"),
        re.compile(r"https://api\.anthropic\.com"),
        re.compile(r"https://api\.openai\.com"),
    )
    for pattern in forbidden_patterns:
        match = pattern.search(text)
        assert match is None, (
            f".env.example 出现疑似真实 key/url 字面量：{match.group(0) if match else ''!r}；"
            "请改用 ``.example.com`` 占位符或仅在注释里描述。"
        )


def test_optin_and_no_leak_keywords_present():
    """模板必须显式提到双标志 opt-in 与 no-leak 5 条纪律。

    模拟边界：维护者**只**改了 4 个变量名，忘了把"必须 --live +
    --confirm-i-have-real-key 才进 live"和"绝不写 key/Authorization/
    完整 prompt/完整 response 进 artifact"这两条用户在终端能直接看到
    的红线写进模板。如果模板自身没有这些关键词，README 哪怕写得再清楚
    也会被复制 .env.example 的人漏看。
    """
    text = _read_env_example()
    required_keywords = (
        "--live",
        "--confirm-i-have-real-key",
        "Authorization",
        "api_key",
        "base_url",
        "budget",
        "anthropic_compatible",
    )
    for kw in required_keywords:
        assert kw in text, (
            f".env.example 缺少关键安全关键词 {kw!r}；如果模板不把它写在用户面前，"
            "用户就会跳过 README 直接误用 live。"
        )


def test_aliyun_model_names_listed_as_strings_only():
    """阿里云 Coding Plan 已知模型名应作为人类参考列出（仅字符串字面量）。

    这条的目的**不**是锁定 allowlist——本项目主线 v2.x 不做 model 准入
    控制；而是确认模板里**至少有 1-2 个模型名**作为 example，让用户填
    ``AGENT_TOOL_HARNESS_LLM_MODEL`` 时不需要去翻别的文档。
    未来加新网关 / 删旧模型直接改模板即可，本测试不会因此红。
    """
    text = _read_env_example()
    sample_models = (
        "qwen3-coder-next",
        "qwen3-coder-plus",
        "glm-5",
    )
    hits = sum(1 for m in sample_models if m in text)
    assert hits >= 2, (
        ".env.example 注释中至少要列出 2 个常见 Anthropic-compatible 模型名作为参考，"
        f"当前只匹配到 {hits} 个，用户填 AGENT_TOOL_HARNESS_LLM_MODEL 时会无所适从。"
    )
