from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class RunRecorder:
    """一次 run 的证据写入器。

    架构边界：
    - 负责把 transcript、tool_calls、tool_responses 和 JSON artifacts 写入磁盘。
    - 不负责判断好坏，也不负责改变 Agent 行为。
    - 所有 runner、adapter、judge 共享这一层，保证 bug 发生后能从文件复盘真实事件链路。

    为什么这样拆：
    如果只看最终回答，Agent 可能“猜对”或自评通过。recorder 强制保留 raw transcript 和
    工具调用/返回，让 judge 和人工 review 都能追溯每一步证据。

    记录约束：
    - transcript.jsonl 是面向人类复盘的事件流，包含 user/assistant/tool 视角。
    - tool_calls.jsonl 是 Agent 发出的结构化调用，必须保留原始参数。
    - tool_responses.jsonl 是确定性系统返回的结构化证据，judge 应优先读取这里。
    - metrics/report 是派生物，不能替代前三个 raw artifacts。
    """

    JSONL_FILES = ["transcript.jsonl", "tool_calls.jsonl", "tool_responses.jsonl"]

    def __init__(self, out_dir: str | Path):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._call_counter = 0
        for filename in self.JSONL_FILES:
            (self.out_dir / filename).write_text("", encoding="utf-8")

    def next_call_id(self, eval_id: str) -> str:
        self._call_counter += 1
        return f"{eval_id}-call-{self._call_counter:03d}"

    def record_transcript(self, eval_id: str, event: dict[str, Any]) -> None:
        """记录一条 transcript 事件。

        调用方负责传入 role/type/content 等业务字段；recorder 只补 timestamp/eval_id。
        这样可以保持 adapter 灵活，同时保证所有 transcript 行都有统一索引字段。
        """

        payload = {
            "timestamp": self._now(),
            "eval_id": eval_id,
            **event,
        }
        self._append_jsonl("transcript.jsonl", payload)

    def record_tool_call(self, call: dict[str, Any]) -> None:
        """记录 Agent 发出的工具调用。

        这里刻意不清洗 arguments，因为错误参数本身就是重要证据。
        """

        payload = {"timestamp": self._now(), **call}
        self._append_jsonl("tool_calls.jsonl", payload)

    def record_tool_response(self, response: dict[str, Any]) -> None:
        """记录工具返回。

        工具异常也要以 success=false 写入，而不是只抛异常退出；否则无法复盘工具返回阶段。
        """

        payload = {"timestamp": self._now(), **response}
        self._append_jsonl("tool_responses.jsonl", payload)

    def write_json(self, filename: str, data: dict[str, Any] | list[Any]) -> Path:
        path = self.out_dir / filename
        with path.open("w", encoding="utf-8") as file:
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.write("\n")
        return path

    def write_text(self, filename: str, content: str) -> Path:
        path = self.out_dir / filename
        path.write_text(content, encoding="utf-8")
        return path

    def read_jsonl(self, filename: str) -> list[dict[str, Any]]:
        path = self.out_dir / filename
        if not path.exists():
            return []
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows

    def _append_jsonl(self, filename: str, payload: dict[str, Any]) -> None:
        with (self.out_dir / filename).open("a", encoding="utf-8") as file:
            json.dump(payload, file, ensure_ascii=False)
            file.write("\n")

    def _now(self) -> str:
        return datetime.now(UTC).isoformat()
