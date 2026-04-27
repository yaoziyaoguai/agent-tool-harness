"""Agent adapter 层。

adapter 决定 Agent 如何产生 tool call。MVP 使用 MockReplayAdapter 生成可复现 good/bad
路径，未来真实 OpenAI/Anthropic adapter 也应输出同样的 transcript/tool_calls 证据。
"""
