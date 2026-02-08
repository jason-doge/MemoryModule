from typing import *
import json

from memory_module.utils import prompt
from memory_module.utils.model import ChatModel
from memory_module.core.memory_bank import MemoryBank
from memory_module.debug import log_entry

class MemoryConsolidator:
    """记忆整理模型：生成高质量上下文"""
    @log_entry
    def __init__(
            self,
            memory_bank: MemoryBank,
            step_id: int = 0,
            policy_model: str = "gpt-4",
            general_model: str = "gpt-4",
            policy_temperature: Optional[float] = None,
            general_temperature: Optional[float] = None,
            policy_top_p: Optional[int] = None,
            general_top_p: Optional[int] = None,
            policy_max_tokens: Optional[int] = None,
            general_max_tokens: Optional[int] = None,
        ):
        self.policy_model = ChatModel(
            model=policy_model,
            system_prompt="你是一名渗透测试记忆管理专家，负责精选渗透测试记忆库。",
            temperature=policy_temperature,
            top_p=policy_top_p,
            max_tokens=policy_max_tokens,
        )
        self.general_model = ChatModel(
            model=general_model,
            system_prompt="你是一名渗透测试记忆管理专家，负责整理渗透测试记忆库。",
            temperature=general_temperature,
            top_p=general_top_p,
            max_tokens=general_max_tokens,
        )
        self.prompt_policy = prompt.consolidator_prompt_policy
        self.prompt_content = prompt.consolidator_prompt_content
        self.memory_bank = memory_bank
        self.step_id = step_id

    def __repr__(self) -> str:
        return f"<MemoryConsolidator(model={self.model})>"
    
    # 筛选记忆条目
    @log_entry
    def filter_memory(
        self,
        context: Dict,
        obs: Dict,
        retrieved_memories: List[Dict],
    ) -> List[Dict]:
        """
        筛选记忆条目
        """
        # 构造数据, 传入策略模型
        data = {
            "context": context,
            "obs": obs,
            "retrieved_memories": retrieved_memories,
        }
        retrieved_memories_ids = [mem["mem_id"] for mem in retrieved_memories]
        # 策略模型生成筛选结果
        prompt_text = self.prompt_policy.format(
            INPUT_JSON=json.dumps(data, ensure_ascii=False)
        )
        return_memories, completion = self.policy_model.chat(prompt_text, json_mode=True)
        print(f"Filtered: {completion.choices[0].message.content}")

        return_memory_ids = [mem["mem_id"] for mem in return_memories["memories"]]

        # 检查两个条件: (1) 是否严格等同于retrieved_memories, (2) 是否在记忆库中
        # (1.1) return_memory_ids 是 retrieved_memores 的子集
        for return_memory_id in return_memory_ids:
            if return_memory_id not in retrieved_memories_ids:
                print(f"Warning: {return_memory_id} is in return_memory_ids but not in retrieved_memories_ids, and will be removed")
                return_memory_ids.remove(return_memory_id)
        # (1.2) retrieved_memories_ids 是 return_memory_ids 的子集
        for retrieved_memory_id in retrieved_memories_ids:
            if retrieved_memory_id not in return_memory_ids:
                print(f"Warning: {retrieved_memory_id} is in retrieved_memories_ids but not in return_memory_ids")

        # (2) 检查是否在记忆库中
        # 将return_memories转换为完整的记忆条目
        try:
            return_complete_memories = self.memory_bank.get_memories(return_memory_ids)
        except Exception as e:
            print(f"Error: {e}")
            return_complete_memories = []
        # 检查是否在记忆库中
        for return_memory_id in return_memory_ids:
            if return_memory_id not in [mem["mem_id"] for mem in return_complete_memories]:
                print(f"Warning: {return_memory_id} is not in return_complete_memories, and will be removed")
                return_memory_ids.remove(return_memory_id)

        # 选择mem["selected"]为True的记忆条目
        selected_memory_ids = [mem["mem_id"] for mem in return_memories["memories"] if mem["selected"] and mem["mem_id"] in return_memory_ids]
        selected_memories = [mem for mem in return_complete_memories if mem["mem_id"] in selected_memory_ids]

        return selected_memories

    # 整理记忆条目, 生成格式化的文本
    @log_entry
    def format_memory(
        self,
        context: Dict,
        obs: Any,
        selected_memories: List[Dict],
    ) -> tuple[dict, str]:
        """
        整理记忆条目, 生成格式化的文本
        """
        # 构造数据, 传入整理模型
        data = {
            "context": context,
            "obs": obs,
            "selected_memories": selected_memories,
        }
        prompt_text = self.prompt_content.format(
            INPUT_JSON=json.dumps(data, ensure_ascii=False)
        )
        return_dict, completion = self.general_model.chat(prompt_text, json_mode=True)
        print(f"Formatted: {completion.choices[0].message.content}")
        return_text = json.dumps(return_dict, ensure_ascii=False)
        return return_dict, return_text
        
        



        
