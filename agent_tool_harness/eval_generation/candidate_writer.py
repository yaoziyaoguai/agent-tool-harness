from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class CandidateWriter:
    """把候选 eval 写成 YAML。

    该类只做序列化，不决定候选是否转正。这样可以把生成和审核分开。
    """

    def write(self, candidates: list[dict[str, Any]], out_path: str | Path) -> Path:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as file:
            yaml.safe_dump(
                {"eval_candidates": candidates},
                file,
                allow_unicode=True,
                sort_keys=False,
            )
        return path
