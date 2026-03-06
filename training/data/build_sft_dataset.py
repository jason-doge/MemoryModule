"""
从 teacher_rollouts.jsonl 生成 maintainer 与 consolidator 的 SFT 数据集。

每条样本格式为 messages 结构，兼容 HuggingFace SFT 训练。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

# 使用项目根目录的 prompt 模板
import sys
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from memory_module.utils import prompt as prompt_module


def _format_maintainer_input(context: Dict, obs: Dict, retrieved_memories: List[Dict]) -> str:
    """构造 maintainer 的 INPUT_JSON。"""
    data = {
        "context": context,
        "obs": obs,
        "retrieved_memories": [
            {
                "mem_id": m.get("mem_id"),
                "mem_type": m.get("mem_type"),
                "mem_content": m.get("mem_content"),
                "context": m.get("context"),
                "key": m.get("key"),
            }
            for m in retrieved_memories
        ],
    }
    return json.dumps(data, ensure_ascii=False)


def _format_consolidator_input(context: Dict, obs: Dict, retrieved_memories: List[Dict]) -> str:
    """构造 consolidator 的 INPUT_JSON。"""
    data = {
        "context": context,
        "obs": obs,
        "retrieved_memories": [
            {
                "mem_id": m.get("mem_id"),
                "mem_type": m.get("mem_type"),
                "mem_content": m.get("mem_content"),
                "context": m.get("context"),
                "key": m.get("key"),
            }
            for m in retrieved_memories
        ],
    }
    return json.dumps(data, ensure_ascii=False)


def build_maintainer_sft_samples(rollout_entries: List[Dict]) -> List[Dict[str, Any]]:
    """从 rollout 中提取 maintainer 样本。"""
    samples = []
    template = prompt_module.maintainer_prompt_policy
    for entry in rollout_entries:
        if entry.get("task") != "maintainer":
            continue
        context = entry.get("context", {})
        obs = entry.get("obs", {})
        retrieved = entry.get("retrieved_memories", [])
        teacher_output = entry.get("teacher_output", [])
        if not teacher_output:
            continue
        input_json = _format_maintainer_input(context, obs, retrieved)
        user_content = template.replace("{INPUT_JSON}", input_json)
        target = json.dumps({"decisions": teacher_output}, ensure_ascii=False)
        samples.append({
            "messages": [
                {"role": "system", "content": "你是一名渗透测试记忆管理专家，负责维护渗透测试记忆库。"},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": target},
            ],
            "trajectory_id": entry.get("trajectory_id", ""),
            "step_number": entry.get("step_number", 0),
            "label": entry.get("label", ""),
        })
    return samples


def build_consolidator_sft_samples(rollout_entries: List[Dict]) -> List[Dict[str, Any]]:
    """从 rollout 中提取 consolidator 样本。"""
    samples = []
    template = prompt_module.consolidator_prompt_policy
    for entry in rollout_entries:
        if entry.get("task") != "consolidator":
            continue
        context = entry.get("context", {})
        obs = entry.get("obs", {})
        retrieved = entry.get("retrieved_memories", [])
        teacher_output = entry.get("teacher_output", {})
        if not isinstance(teacher_output, dict) or "memories" not in teacher_output:
            continue
        input_json = _format_consolidator_input(context, obs, retrieved)
        user_content = template.replace("{INPUT_JSON}", input_json)
        target = json.dumps(teacher_output, ensure_ascii=False)
        samples.append({
            "messages": [
                {"role": "system", "content": "你是一名渗透测试记忆管理专家，负责精选渗透测试记忆库。"},
                {"role": "user", "content": user_content},
                {"role": "assistant", "content": target},
            ],
            "trajectory_id": entry.get("trajectory_id", ""),
            "step_number": entry.get("step_number", 0),
            "label": entry.get("label", ""),
        })
    return samples


def build_sft_datasets(
    rollout_path: Path,
    output_dir: Path,
) -> None:
    """
    从 teacher_rollouts.jsonl 生成 maintainer_sft.jsonl 与 consolidator_sft.jsonl。
    """
    entries: List[Dict] = []
    with open(rollout_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            entries.append(json.loads(line))

    maintainer_samples = build_maintainer_sft_samples(entries)
    consolidator_samples = build_consolidator_sft_samples(entries)

    output_dir.mkdir(parents=True, exist_ok=True)
    for name, samples in [("maintainer_sft", maintainer_samples), ("consolidator_sft", consolidator_samples)]:
        out_path = output_dir / f"{name}.jsonl"
        with open(out_path, "w", encoding="utf-8") as f:
            for s in samples:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        print(f"Wrote {len(samples)} samples to {out_path}")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollout", type=Path, default=Path("training/outputs/teacher_rollouts.jsonl"))
    parser.add_argument("--output-dir", type=Path, default=Path("training/outputs"))
    args = parser.parse_args()
    build_sft_datasets(args.rollout, args.output_dir)
