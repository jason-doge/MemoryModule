"""
统一 tokenizer 与 model 加载，支持 Qwen3-1.7B、LoRA、4bit/8bit。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig


def load_tokenizer(
    model_name_or_path: str,
    trust_remote_code: bool = True,
) -> "AutoTokenizer":
    from transformers import AutoTokenizer
    return AutoTokenizer.from_pretrained(
        model_name_or_path,
        trust_remote_code=trust_remote_code,
    )


def load_model_and_tokenizer(
    model_name_or_path: str,
    use_4bit: bool = False,
    use_8bit: bool = False,
    bf16: bool = True,
    trust_remote_code: bool = True,
    device_map: Optional[str] = "auto",
) -> Tuple[Any, "AutoTokenizer"]:
    """
    加载 Qwen3 模型与 tokenizer。
    支持 4bit/8bit 量化以节省显存。
    """
    tokenizer = load_tokenizer(model_name_or_path, trust_remote_code)

    quantization_config = None
    if use_4bit:
        quantization_config = BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16 if bf16 else torch.float16,
        )
    elif use_8bit:
        quantization_config = BitsAndBytesConfig(
            load_in_8bit=True,
        )

    model = AutoModelForCausalLM.from_pretrained(
        model_name_or_path,
        quantization_config=quantization_config,
        torch_dtype=torch.bfloat16 if bf16 and not quantization_config else None,
        device_map=device_map,
        trust_remote_code=trust_remote_code,
    )

    return model, tokenizer
