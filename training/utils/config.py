"""
配置解析：合并 base + task 配置。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml


def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def merge_dict(base: Dict, override: Dict) -> Dict:
    """递归合并，override 覆盖 base。"""
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = merge_dict(out[k], v)
        else:
            out[k] = v
    return out


def load_training_config(config_path: Path, base_path: Path | None = None) -> Dict[str, Any]:
    """
    加载训练配置，自动合并 base 配置。
    """
    config_dir = config_path.parent
    if base_path is None:
        base_path = config_dir / "base.yaml"
    base = load_yaml(base_path) if base_path.exists() else {}
    task = load_yaml(config_path)
    return merge_dict(base, task)
