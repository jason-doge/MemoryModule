"""
LoRA / QLoRA 配置
"""

from __future__ import annotations

from typing import List, Optional

from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training


def get_lora_config(
    r: int = 8,
    lora_alpha: int = 16,
    lora_dropout: float = 0.05,
    target_modules: Optional[List[str]] = None,
    bias: str = "none",
    task_type: str = "CAUSAL_LM",
) -> LoraConfig:
    if target_modules is None:
        target_modules = ["q_proj", "v_proj"]
    return LoraConfig(
        r=r,
        lora_alpha=lora_alpha,
        lora_dropout=lora_dropout,
        target_modules=target_modules,
        bias=bias,
        task_type=task_type,
    )


def apply_lora(model, lora_config: LoraConfig, use_4bit_or_8bit: bool = False):
    """对模型应用 LoRA。若已量化，先 prepare_model_for_kbit_training。"""
    if use_4bit_or_8bit:
        model = prepare_model_for_kbit_training(model)
    return get_peft_model(model, lora_config)
