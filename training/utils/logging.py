"""
训练日志：JSONL + TensorBoard。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict


def log_metrics_jsonl(metrics: Dict[str, Any], path: Path) -> None:
    """追加一行 JSON 到 metrics.jsonl。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(metrics, ensure_ascii=False) + "\n")
