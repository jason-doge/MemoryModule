"""
按 trajectory 划分 train/val/test，避免同轨迹泄漏。
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import List, Tuple


def get_trajectory_ids(samples: List[dict]) -> List[str]:
    """从样本中提取不重复的 trajectory_id。"""
    ids = list({s.get("trajectory_id", "") for s in samples if s.get("trajectory_id")})
    return ids


def split_by_trajectory(
    samples: List[dict],
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seed: int = 42,
) -> Tuple[List[dict], List[dict], List[dict]]:
    """
    按 trajectory_id 划分，确保同一轨迹不会同时出现在 train 和 val/test 中。

    Returns:
        (train_samples, val_samples, test_samples)
    """
    trajectory_ids = get_trajectory_ids(samples)
    if not trajectory_ids:
        # 无 trajectory_id 时退化为随机划分
        random.shuffle(samples)
        n = len(samples)
        n_val = max(1, int(n * val_ratio))
        n_test = max(1, int(n * test_ratio))
        n_train = n - n_val - n_test
        return samples[:n_train], samples[n_train:n_train + n_val], samples[n_train + n_val:]

    rng = random.Random(seed)
    rng.shuffle(trajectory_ids)
    n = len(trajectory_ids)
    n_val = max(1, int(n * val_ratio))
    n_test = max(1, int(n * test_ratio))
    n_train = n - n_val - n_test

    val_ids = set(trajectory_ids[:n_val])
    test_ids = set(trajectory_ids[n_val:n_val + n_test])
    train_ids = set(trajectory_ids[n_val + n_test:])

    train_samples = [s for s in samples if s.get("trajectory_id", "") in train_ids]
    val_samples = [s for s in samples if s.get("trajectory_id", "") in val_ids]
    test_samples = [s for s in samples if s.get("trajectory_id", "") in test_ids]

    return train_samples, val_samples, test_samples


def split_and_save(
    input_path: Path,
    output_dir: Path,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seed: int = 42,
) -> None:
    """
    读取 JSONL，按 trajectory 划分，写入 train/val/test。
    """
    samples = []
    with open(input_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            samples.append(json.loads(line))

    train, val, test = split_by_trajectory(samples, val_ratio, test_ratio, seed)
    stem = input_path.stem.replace("_sft", "")
    output_dir.mkdir(parents=True, exist_ok=True)

    for split_name, split_samples in [("train", train), ("val", val), ("test", test)]:
        out_path = output_dir / f"{stem}_{split_name}.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for s in split_samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        print(f"Wrote {len(split_samples)} samples to {out_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="maintainer_sft.jsonl 或 consolidator_sft.jsonl")
    parser.add_argument("--output-dir", type=Path, default=Path("training/outputs"))
    parser.add_argument("--val-ratio", type=float, default=0.1)
    parser.add_argument("--test-ratio", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    split_and_save(args.input, args.output_dir, args.val_ratio, args.test_ratio, args.seed)
