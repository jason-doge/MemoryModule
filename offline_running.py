import json
from typing import *
from pathlib import Path
from datetime import datetime

from memory_module import MemoryModule
from memory_module.debug import log_entry

def truncate_observation(obs_raw: str, max_length: int = 2000) -> str:
    """截断过长的观测数据，优先保留关键信息"""
    if len(obs_raw) <= max_length:
        return obs_raw

    # 优先保留：错误信息、URL、关键提示
    lines = obs_raw.split('\n')
    important_lines = []
    normal_lines = []

    for idx, line in enumerate(lines):
        line_lower = line.lower()
        if any(keyword in line_lower for keyword in [
            "error", "exception", "traceback", "http://", "https://",
            "flag", "filter", "block", "can't use", "payload", "xss"
        ]):
            important_lines.append([idx, "line" + str(idx + 1) + ":" + line])
        else:
            normal_lines.append([idx, "line" + str(idx + 1) + ":" + line])

    # 先保留重要行，再补充普通行直到达到长度限制
    result_lines = important_lines[:]
    remaining = max_length - sum(len(l[1]) + 1 for l in result_lines)

    for line in normal_lines:
        if remaining <= 0:
            break
        if len(line) + 1 <= remaining:
            result_lines.append(line)
            remaining -= len(line) + 1
        else:
            result_lines.append(line[:remaining] + "...")
            break

    # 根据行号排序
    result_lines = sorted(result_lines, key=lambda x: x[0])

    # 合并成字符串
    result = '\n'.join([line[1] for line in result_lines])
    if len(result) < len(obs_raw):
        result += f"\n... [truncated, original length: {len(obs_raw)}]"

    return result


# 处理单个 observation
def process_observation(observation):
    """处理 observation，返回字符串"""
    # 归类的obs
    obs_classified = {}
    for obs in observation:
        obs_type = obs.get("observation_type", "")
        obs_raw = obs.get("observation_raw", "")
        if obs_type in obs_classified:
            obs_classified[obs_type] += f"\n{obs_raw}"
        else:
            obs_classified[obs_type] = obs_raw
    return obs_classified

# 遍历./data/final_label下的所有json文件
cwd = Path.cwd()
data_dir = cwd / "data" / "final_label"
for file in data_dir.glob("*.json"):
    print('=' * 50)
    print(file)
    memory_module = MemoryModule(
        chat_model="deepseek-chat",
        maintainer_model_policy="deepseek-chat",
        maintainer_model_content="deepseek-chat",
        consolidator_model_policy="deepseek-chat",
        consolidator_model_content="deepseek-chat",
        embedding_model="text-embedding-v4",
        step_id=0,
        session_id=None,
    )
    with open(file, "r", encoding="utf-8") as f:
        data = json.load(f)

    for step in data["steps"]:
        context = {
            "phase": step["phase"],
            "subgoal": step["subgoal"],
            "state_summary": step["state_summary"],
            "source_tool": "python",
            "source_command": step["code"],
        }
        obses = process_observation(step["observation"])
        # 获取obses的键值对
        obses = [{"obs_type": key, "obs_text": value} for key, value in obses.items()]
        intermediate_results, consolidate_memory_dict, consolidate_memory_text = memory_module.process_step(context=context, obses=obses)

        log_file_step = Path.cwd() / "log" / f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}" / f"{file}_{step['step_number']}.json"
        # 创建文件夹
        log_file_step.parent.mkdir(parents=True, exist_ok=True)

        with open(log_file_step, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "step": step["step_number"],
                    "observation": obses,
                    "intermediate_results": intermediate_results,
                    "consolidate_memory_dict": consolidate_memory_dict,
                },
                f,
                indent=4,
                ensure_ascii=False,
            )

    break