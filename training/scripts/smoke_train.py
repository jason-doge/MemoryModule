"""
冒烟测试：用极小数据验证训练链路可运行。

用法（需先 pip install -e ".[train]"）:
  cd 项目根目录
  python -m training.scripts.smoke_train
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 生成 5 条最小 maintainer 样本
_MIN_SAMPLES = [
    {
        "messages": [
            {"role": "system", "content": "你是一名渗透测试记忆管理专家。"},
            {"role": "user", "content": '{"context":{"phase":"recon","subgoal":"scan ports"},"obs":{"obs_text":"nmap output"},"retrieved_memories":[]}\n请输出JSON决策。'},
            {"role": "assistant", "content": '{"decisions":[{"base_action":"S1_SUMMARIZE_ADD","mark_key":true,"key_type":"PORT","key_level":2,"s3_update":[],"reason":"Port scan result."}]}'},
        ],
        "trajectory_id": "smoke_1",
        "step_number": 0,
    }
] * 5


def main():
    out_dir = _project_root / "training" / "outputs" / "smoke"
    out_dir.mkdir(parents=True, exist_ok=True)
    smoke_path = out_dir / "smoke_maintainer.jsonl"
    with open(smoke_path, "w", encoding="utf-8") as f:
        for s in _MIN_SAMPLES:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    # 使用最小 config 覆盖
    cfg_path = out_dir / "smoke_config.yaml"
    cfg_path.write_text(f"""
model_name: Qwen/Qwen3-1.7B
use_lora: true
load_in_4bit: true
max_length: 512
train_data: "{smoke_path.as_posix()}"
val_data: null
output_dir: "{(out_dir / "checkpoints").as_posix()}"
per_device_train_batch_size: 1
gradient_accumulation_steps: 2
num_train_epochs: 1
max_steps: 2
save_steps: 1
logging_steps: 1
bf16: true
""", encoding="utf-8")

    from training.utils.config import load_training_config
    from training.train_sft import main as train_main
    # 注入 config 路径
    sys.argv = ["train_sft", "--config", str(cfg_path)]
    train_main()


if __name__ == "__main__":
    main()
