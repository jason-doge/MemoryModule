#!/bin/bash
# AutoDL 训练启动脚本
# 用法: bash training/launch_autodl.sh [maintainer|consolidator]
# 需在项目根目录执行

set -e
cd "$(dirname "$0")/.."
TASK="${1:-maintainer}"

echo "=== MemoryModule Training on AutoDL ==="
echo "Task: $TASK"

# 检查训练依赖
python -c "
import transformers
import peft
import torch
print(f'PyTorch: {torch.__version__}')
print(f'Transformers: {transformers.__version__}')
print(f'PEFT: {peft.__version__}')
print(f'CUDA available: {torch.cuda.is_available()}')
"

# 预缓存模型（可选，避免训练时重复下载）
# python -c "
# from transformers import AutoTokenizer, AutoModelForCausalLM
# m = 'Qwen/Qwen3-1.7B'
# AutoTokenizer.from_pretrained(m)
# AutoModelForCausalLM.from_pretrained(m, torch_dtype='auto')
# print('Model cached.')
# "

CONFIG="training/configs/${TASK}_sft.yaml"
if [ ! -f "$CONFIG" ]; then
    echo "Config not found: $CONFIG"
    exit 1
fi

echo "Starting training with config: $CONFIG"
python -m training.train_sft --config "$CONFIG"

echo "=== Training finished ==="
