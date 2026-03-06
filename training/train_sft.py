"""
共享 SFT 训练入口，通过 task=maintainer|consolidator 切换。

用法:
  python -m training.train_sft --config training/configs/maintainer_sft.yaml
  python -m training.train_sft --config training/configs/consolidator_sft.yaml
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import argparse
from typing import Any, Dict, List, Optional

import torch
from datasets import Dataset
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    DataCollatorForSeq2Seq,
    HfArgumentParser,
    Trainer,
    TrainingArguments,
)
from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training

from training.utils.config import load_training_config
from training.utils.seed import set_seed
from training.utils.logging import setup_logging


def load_jsonl(path: Path) -> List[Dict]:
    samples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            samples.append(json.loads(line))
    return samples


def messages_to_prompt_and_response(messages: List[Dict], tokenizer) -> tuple[str, str]:
    """将 messages 转为 (prompt, response) 用于 causal LM 训练。"""
    prompt_parts = []
    response = ""
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            prompt_parts.append(f"<|im_start|>system\n{content}<|im_end|>")
        elif role == "user":
            prompt_parts.append(f"<|im_start|>user\n{content}<|im_end|>")
        elif role == "assistant":
            prompt_parts.append(f"<|im_start|>assistant\n")
            response = content
            break
    prompt = "\n".join(prompt_parts)
    return prompt, response


def build_dataset(
    data_path: Path,
    tokenizer,
    max_length: int = 2048,
) -> List[Dict[str, Any]]:
    """从 JSONL 构建训练样本，返回 [{input_ids, labels, ...}]。"""
    samples = load_jsonl(data_path)
    out = []
    for s in samples:
        messages = s.get("messages", [])
        if not messages:
            continue
        prompt, response = messages_to_prompt_and_response(messages, tokenizer)
        full_text = prompt + response + (tokenizer.eos_token or "")
        enc = tokenizer(
            full_text,
            truncation=True,
            max_length=max_length,
            padding=False,
            return_tensors=None,
        )
        input_ids = enc["input_ids"]
        # labels: -100 对 prompt 部分，response 部分保留
        prompt_enc = tokenizer(
            prompt,
            truncation=True,
            max_length=max_length,
            padding=False,
            return_tensors=None,
        )
        prompt_len = len(prompt_enc["input_ids"])
        labels = [-100] * prompt_len + input_ids[prompt_len:]
        if len(labels) < len(input_ids):
            labels += [-100] * (len(input_ids) - len(labels))
        elif len(labels) > len(input_ids):
            labels = labels[: len(input_ids)]
        out.append({
            "input_ids": input_ids,
            "labels": labels,
            "attention_mask": [1] * len(input_ids),
        })
    return out


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=str, default="training/configs/maintainer_sft.yaml")
    parser.add_argument("--resume-from-checkpoint", type=str, default=None)
    parser.add_argument("--train-data", type=str, default=None, help="Override train_data path (e.g. for smoke test)")
    args = parser.parse_args()
    cfg = load_training_config(Path(args.config))
    if args.train_data:
        cfg["train_data"] = args.train_data
    set_seed(cfg.get("seed", 42))

    output_dir = Path(cfg["output_dir"])
    output_dir.mkdir(parents=True, exist_ok=True)
    setup_logging(output_dir / "train.log")

    model_name = cfg.get("model_name", "Qwen/Qwen3-1.7B")
    use_lora = cfg.get("use_lora", True)
    load_in_4bit = cfg.get("load_in_4bit", False)
    max_length = cfg.get("max_length", 2048)

    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True,
    )
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        trust_remote_code=True,
        torch_dtype=torch.bfloat16 if not load_in_4bit else None,
        load_in_4bit=load_in_4bit,
        device_map="auto",
    )

    if load_in_4bit:
        model = prepare_model_for_kbit_training(model)

    if use_lora:
        lora_cfg = cfg.get("lora", {})
        peft_config = LoraConfig(
            r=lora_cfg.get("r", 8),
            lora_alpha=lora_cfg.get("lora_alpha", 16),
            target_modules=lora_cfg.get("target_modules", ["q_proj", "v_proj"]),
            lora_dropout=lora_cfg.get("lora_dropout", 0.05),
            bias="none",
            task_type="CAUSAL_LM",
        )
        model = get_peft_model(model, peft_config)
        model.print_trainable_parameters()

    train_path = Path(cfg["train_data"])
    if not train_path.exists():
        raise FileNotFoundError(f"Train data not found: {train_path}")
    train_samples = build_dataset(train_path, tokenizer, max_length)

    val_path = cfg.get("val_data")
    eval_dataset = None
    if val_path and Path(val_path).exists():
        eval_samples = build_dataset(Path(val_path), tokenizer, max_length)
        eval_dataset = eval_samples

    data_collator = DataCollatorForSeq2Seq(
        tokenizer=tokenizer,
        padding=True,
        max_length=max_length,
        return_tensors="pt",
        label_pad_token_id=-100,
    )

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        per_device_train_batch_size=cfg.get("per_device_train_batch_size", 1),
        per_device_eval_batch_size=cfg.get("per_device_eval_batch_size", 1),
        gradient_accumulation_steps=cfg.get("gradient_accumulation_steps", 8),
        learning_rate=cfg.get("learning_rate", 2e-5),
        num_train_epochs=cfg.get("num_train_epochs", 3),
        max_steps=cfg.get("max_steps", -1),
        logging_steps=cfg.get("logging_steps", 10),
        save_steps=cfg.get("save_steps", 100),
        save_total_limit=cfg.get("save_total_limit", 3),
        bf16=cfg.get("bf16", True),
        report_to=cfg.get("report_to", "tensorboard"),
        remove_unused_columns=False,
    )

    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_samples,
        eval_dataset=eval_dataset,
        data_collator=data_collator,
    )

    trainer.train(resume_from_checkpoint=args.resume_from_checkpoint)
    trainer.save_model(str(output_dir / "final"))
    tokenizer.save_pretrained(str(output_dir / "final"))


if __name__ == "__main__":
    main()
