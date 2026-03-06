"""
批量生成 teacher rollout 数据。

遍历 data/final_label/ 下的轨迹 JSON，对每条轨迹调用 replay_runtime.replay_trajectory，
将导出的 rollout 条目追加到 teacher_rollouts.jsonl。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# 确保项目根在 path 中
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from training.data.replay_runtime import replay_trajectory


def process_observation(observation: list[dict]) -> dict:
    """将 observation 列表合并为与 offline_running 一致的 obs 格式。"""
    obs_classified: dict[str, str] = {}
    for obs in observation:
        obs_type = obs.get("observation_type", "")
        obs_raw = obs.get("observation_raw", "")
        if obs_type in obs_classified:
            obs_classified[obs_type] += f"\n{obs_raw}"
        else:
            obs_classified[obs_type] = obs_raw
    obs_text = "\n".join(f"[{k}]\n{v}\n" for k, v in obs_classified.items())
    return {"obs_type": "tool", "obs_text": obs_text}


def main(
    data_dir: Path | None = None,
    output_path: Path | None = None,
    max_files: int | None = None,
    model_config: dict | None = None,
) -> int:
    """
    批量生成 teacher rollouts。

    Args:
        data_dir: 轨迹 JSON 目录，默认 data/final_label
        output_path: 输出 JSONL 路径，默认 training/outputs/teacher_rollouts.jsonl
        max_files: 最多处理的文件数，None 表示全部
        model_config: 传给 MemoryModule 的模型配置

    Returns:
        成功处理的轨迹数
    """
    if data_dir is None:
        data_dir = _project_root / "data" / "final_label"
    if output_path is None:
        output_path = _project_root / "training" / "outputs" / "teacher_rollouts.jsonl"

    output_path.parent.mkdir(parents=True, exist_ok=True)

    json_files = sorted(data_dir.glob("*.json"))
    # 排除带 _N 后缀的拆分文件，只保留主轨迹
    json_files = [f for f in json_files if not f.stem.rsplit("_", 1)[-1].isdigit() or "_labeled" in f.name]

    if max_files is not None:
        json_files = json_files[:max_files]

    total_entries = 0
    processed = 0

    with open(output_path, "w", encoding="utf-8") as out_f:
        for i, traj_path in enumerate(json_files):
            try:
                entries = replay_trajectory(
                    traj_path,
                    process_observation_fn=process_observation,
                    model_config=model_config or {},
                )
                for entry in entries:
                    out_f.write(json.dumps(entry, ensure_ascii=False) + "\n")
                    total_entries += 1
                processed += 1
                print(f"[{i+1}/{len(json_files)}] {traj_path.name}: {len(entries)} entries")
            except Exception as e:
                print(f"[ERROR] {traj_path.name}: {e}", file=sys.stderr)

    print(f"Done: {processed} trajectories, {total_entries} rollout entries -> {output_path}")
    return processed


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build teacher rollout dataset")
    parser.add_argument("--data-dir", type=Path, default=None, help="Trajectory JSON directory")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output JSONL path")
    parser.add_argument("--max-files", type=int, default=None, help="Max trajectory files to process")
    args = parser.parse_args()
    main(
        data_dir=args.data_dir,
        output_path=args.output,
        max_files=args.max_files,
    )
