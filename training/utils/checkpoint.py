"""
Checkpoint 保存与恢复。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional


def get_latest_checkpoint(run_dir: Path) -> Optional[Path]:
    """返回 run_dir 下最新的 checkpoint-* 目录。"""
    if not run_dir.exists():
        return None
    checkpoints = [d for d in run_dir.iterdir() if d.is_dir() and d.name.startswith("checkpoint-")]
    if not checkpoints:
        return None
    return max(checkpoints, key=lambda d: int(d.name.split("-")[-1]) if d.name.split("-")[-1].isdigit() else 0)


def save_adapter_only(model, output_dir: Path) -> None:
    """仅保存 LoRA adapter 权重。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    model.save_pretrained(output_dir)
