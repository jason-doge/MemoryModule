"""
轨迹回放与 teacher rollout 导出

复用现有 MemoryModule 回放 data/final_label 中的标注轨迹，
导出每步的 context、obs、retrieved_memories、teacher_outputs，
供后续 SFT 数据集构建使用。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from memory_module import MemoryModule


def process_observation_from_step(observation: List[Dict]) -> Dict[str, str]:
    """将 trajectory 中的 observation 转为 MemoryModule 期望的 obs 格式。"""
    obs_classified: Dict[str, str] = {}
    for obs in observation:
        obs_type = obs.get("observation_type", "")
        obs_raw = obs.get("observation_raw", "")
        if obs_type in obs_classified:
            obs_classified[obs_type] += f"\n{obs_raw}"
        else:
            obs_classified[obs_type] = obs_raw
    parts = [f"[{k}]\n{v}\n" for k, v in obs_classified.items()]
    return {
        "obs_type": "tool",
        "obs_text": "\n".join(parts),
    }


def replay_trajectory(
    trajectory_path: Path,
    output_path: Optional[Path] = None,
    memory_module_kwargs: Optional[Dict[str, Any]] = None,
    max_steps: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """
    回放单条轨迹，收集 teacher rollout 数据。

    Args:
        trajectory_path: 轨迹 JSON 文件路径
        output_path: 若提供，将 rollout 写入该路径（JSONL）
        memory_module_kwargs: 传给 MemoryModule 的额外参数
        max_steps: 最大处理步数，None 表示不限制

    Returns:
        rollout 条目列表，每项包含 task、trajectory_id、step_number、obs_index、
        context、obs、retrieved_memories、teacher_output、label 等
    """
    with open(trajectory_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    trajectory_id = trajectory_path.stem
    steps = data.get("steps", [])
    if max_steps is not None:
        steps = steps[:max_steps]

    kwargs = memory_module_kwargs or {}
    rollout_capture: List[Dict] = []
    mm = MemoryModule(
        step_id=0,
        session_id=None,
        rollout_capture=rollout_capture,
        **kwargs,
    )

    for step in steps:
        len_before = len(rollout_capture)
        context = {
            "phase": step.get("phase", ""),
            "subgoal": step.get("subgoal", ""),
            "state_summary": step.get("state_summary") or "",
            "source_tool": "python",
            "source_command": step.get("code", ""),
        }
        obses = process_observation_from_step(step.get("observation", []))
        obses_list = [obses] if isinstance(obses, dict) else obses

        for obs_idx, obs in enumerate(obses_list):
            mm.process_step(context=context, obses=obs)

        # 为本步新增的 rollout 条目补充 trajectory_id、step_number、label
        step_number = step.get("step_number", 0)
        label = step.get("label", "")
        label_rationale = step.get("label_rationale", "")
        for entry in rollout_capture[len_before:]:
            entry["trajectory_id"] = trajectory_id
            entry["step_number"] = step_number
            entry["label"] = label
            entry["label_rationale"] = label_rationale

    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            for entry in rollout_capture:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    return rollout_capture
