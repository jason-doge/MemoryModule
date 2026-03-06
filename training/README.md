# 训练模块

本目录包含记忆管理模型与记忆整理模型的训练流程，基于 Qwen/Qwen3-1.7B 进行 LoRA/QLoRA 微调。

## 环境要求

- Python >= 3.10
- PyTorch >= 2.2（与 CUDA 版本匹配）
- transformers >= 4.51.0（Qwen3 需此版本以上）
- peft, datasets, accelerate, bitsandbytes, tensorboard, pyyaml

安装训练依赖：

```bash
pip install -e ".[train]"
# 或
pip install transformers>=4.51.0 datasets peft accelerate bitsandbytes tensorboard pyyaml
```

## 数据准备

1. **Teacher Rollout**（需配置 `llm_config.json` 与 API）：
   ```bash
   python -m training.data.build_teacher_rollouts \
     --data-dir data/final_label \
     --output training/outputs/teacher_rollouts.jsonl \
     --max-files 10
   ```

2. **SFT 数据集**：
   ```bash
   python -m training.data.build_sft_dataset \
     --rollout training/outputs/teacher_rollouts.jsonl \
     --output-dir training/outputs
   ```

3. **划分 train/val/test**：
   ```bash
   python -m training.data.split_dataset --input training/outputs/maintainer_sft.jsonl --output-dir training/outputs
   python -m training.data.split_dataset --input training/outputs/consolidator_sft.jsonl --output-dir training/outputs
   ```

## 训练

```bash
# 记忆管理模型
python -m training.train_sft --config training/configs/maintainer_sft.yaml

# 记忆整理模型
python -m training.train_sft --config training/configs/consolidator_sft.yaml
```

或使用启动脚本：

```bash
bash training/launch_autodl.sh maintainer
bash training/launch_autodl.sh consolidator
```

## AutoDL 部署

1. 选择镜像：PyTorch 2.2+ / CUDA 12.x
2. 安装依赖：`pip install -e ".[train]"`
3. 准备数据：按上述步骤生成 `training/outputs/maintainer_train.jsonl` 等
4. 启动训练：`bash training/launch_autodl.sh maintainer`
5. 显存建议：24GB 用 bf16+LoRA；16GB 用 4bit QLoRA（修改 config 中 `load_in_4bit: true`）

## 评估

```bash
python -m training.eval.offline_eval \
  --model-path training/outputs/maintainer_final \
  --test-data training/outputs/maintainer_test.jsonl \
  --task maintainer
```

## 目录结构

```
training/
├── configs/          # 训练配置
├── data/             # 数据构建与划分
├── models/           # 模型加载与 LoRA
├── utils/            # 配置、checkpoint、日志
├── eval/             # 离线评估与 replay 评估
├── train_sft.py      # SFT 主入口
├── launch_autodl.sh  # AutoDL 启动脚本
└── reward.py         # 奖励/评判（第二阶段 RL 用）
```
