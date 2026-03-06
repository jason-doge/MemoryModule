"""
离线评估入口：加载 checkpoint，在 val/test 集上推理并计算指标。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel

from training.eval.metrics import compute_maintainer_metrics, compute_consolidator_metrics


def load_model_for_eval(
    base_model: str,
    adapter_path: Optional[Path] = None,
    device: str = "cuda",
) -> tuple:
    tokenizer = AutoTokenizer.from_pretrained(
        adapter_path or base_model,
        trust_remote_code=True,
    )
    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        torch_dtype=torch.bfloat16,
        device_map=device,
        trust_remote_code=True,
    )
    if adapter_path and (adapter_path / "adapter_config.json").exists():
        model = PeftModel.from_pretrained(model, str(adapter_path))
    model.eval()
    return model, tokenizer


def load_jsonl(path: Path) -> List[Dict]:
    samples = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            samples.append(json.loads(line))
    return samples


def extract_prompt_from_messages(messages: List[Dict]) -> str:
    """构造推理时的 prompt（不含 assistant 回复）。"""
    parts = []
    for msg in messages:
        role = msg.get("role", "")
        content = msg.get("content", "")
        if role == "system":
            parts.append(f"<|im_start|>system\n{content}<|im_end|>")
        elif role == "user":
            parts.append(f"<|im_start|>user\n{content}<|im_end|>")
        elif role == "assistant":
            parts.append("<|im_start|>assistant\n")
            break
    return "\n".join(parts)


def run_offline_eval(
    data_path: Path,
    model,
    tokenizer,
    task: str = "maintainer",
    max_new_tokens: int = 512,
    batch_size: int = 1,
) -> Dict[str, float]:
    """
    在指定数据上运行离线评估。
    task: "maintainer" | "consolidator"
    """
    samples = load_jsonl(data_path)
    predictions = []
    references = []
    for s in samples:
        messages = s.get("messages", [])
        if not messages:
            continue
        prompt = extract_prompt_from_messages(messages)
        enc = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=2048,
        ).to(model.device)
        with torch.no_grad():
            out = model.generate(
                **enc,
                max_new_tokens=max_new_tokens,
                do_sample=False,
                pad_token_id=tokenizer.pad_token_id or tokenizer.eos_token_id,
            )
        pred_text = tokenizer.decode(
            out[0][enc["input_ids"].shape[1]:],
            skip_special_tokens=True,
        ).strip()
        predictions.append(pred_text)
        for m in messages:
            if m.get("role") == "assistant":
                ref_text = m.get("content", "")
                try:
                    references.append(json.loads(ref_text))
                except json.JSONDecodeError:
                    references.append({})
                break
        else:
            references.append({})

    if task == "maintainer":
        return compute_maintainer_metrics(predictions, references)
    return compute_consolidator_metrics(predictions, references)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True, help="val 或 test JSONL 路径")
    parser.add_argument("--base-model", type=str, default="Qwen/Qwen3-1.7B")
    parser.add_argument("--adapter", type=Path, default=None, help="LoRA adapter 路径")
    parser.add_argument("--task", choices=["maintainer", "consolidator"], default="maintainer")
    parser.add_argument("--output", type=Path, default=None, help="指标 JSON 输出路径")
    args = parser.parse_args()

    model, tokenizer = load_model_for_eval(args.base_model, args.adapter)
    metrics = run_offline_eval(args.data, model, tokenizer, task=args.task)
    print(json.dumps(metrics, indent=2, ensure_ascii=False))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(metrics, f, indent=2, ensure_ascii=False)
        print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()
