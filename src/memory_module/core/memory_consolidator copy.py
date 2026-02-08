from typing import List, Dict, Tuple, Callable, Optional, Any, Union
from . import prompt
from .model import ChatModel
import json

class MemoryConsolidator:
    """记忆整理模型：生成高质量上下文"""
    def __init__(
            self,
            model: str = "gpt-4",
            temperature: Optional[float] = None,
            top_p: Optional[int] = None,
            max_tokens: Optional[int] = None,
            step_id: int = 0,
        ):
        self.model = ChatModel(
            model=model,
            system_prompt="你是一名渗透测试记忆管理专家，负责精选渗透测试记忆库。",
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
        self.prompt = prompt.consolidator_prompt
        self.step_id = step_id

    def __repr__(self) -> str:
        return f"<MemoryConsolidator(model={self.model})>"
    
    def consolidate(
        self,
        pentest_info,
        retrieved_memories,
    ) -> Dict[str, Any]:
        """
        输入当前上下文，返回记忆维护决策
        """

        dict_obj = pentest_info.copy()
        format_retrieved_memories = []
        for m in retrieved_memories:
            mem_dict = {
                "mem_id": "mem_" + str(m["id"]),
                "content": m["raw_content"],
                "context": m["metadata"]["context"],
            }
            format_retrieved_memories.append(mem_dict)
        
        dict_obj["retrieved_memories"] = format_retrieved_memories
        dict_obj["step_id"] = self.step_id

        while True:
            try:
                results, _ = self.model.chat(
                    self.prompt.format(INPUT_JSON=json.dumps(dict_obj, ensure_ascii=False))
                )
                results = json.loads(results)
                break
            except Exception as e:
                print(f"Error: {e}")
                continue

        return results