from typing import *
import json
from pprint import pprint

from memory_module.utils import prompt
from memory_module.utils.model import ChatModel
from memory_module.core.memory_bank import MemoryBank
from memory_module.debug import log_entry

class MemoryMaintainer:
    """记忆维护模型：决定增删改操作"""
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
            system_prompt="你是一名渗透测试记忆管理专家，负责维护渗透测试记忆库。",
            temperature=policy_temperature,
            top_p=policy_top_p,
            max_tokens=policy_max_tokens,
        )
        self.general_model = ChatModel(
            model=general_model,
            system_prompt="你是一名渗透测试记忆管理专家，负责维护渗透测试记忆库。",
            temperature=general_temperature,
            top_p=general_top_p,
            max_tokens=general_max_tokens,
        )
        self.prompt_policy = prompt.maintainer_prompt_policy
        self.prompt_content = prompt.maintainer_prompt_content
        self.memory_bank = memory_bank
        self.step_id = step_id

    def __repr__(self) -> str:
        return f"<MemoryMaintainer(model={self.model})>"

    @log_entry
    def decide_action(
        self,
        context: Dict[str, str],
        obs: Dict,
        retrieved_memories: List[Dict],
    ) -> List[Dict]:
        """
        决策记忆管理操作
        """
        # 构造数据字典
        data = {
            "context": context,
            "obs": obs,
            "retrieved_memories": retrieved_memories,
        }
        # 使用决策模型生成操作建议
        prompt_text = self.prompt_policy.format(
            INPUT_JSON=json.dumps(data, ensure_ascii=False),
        )
        try:
            decisions, _ = self.policy_model.chat(prompt_text, json_mode=True)
            decisions = decisions.get("decisions", "N/A")
            pprint(decisions)
            if decisions == "N/A":
                raise ValueError("Policy model didn't return 'decisions' field.")
        except Exception as e:
            decisions = []
            print(f"Error in policy model: {e}")
        
        for decision in decisions:
            if decision.get("base_action", "N/A") == "S3_UPDATE_REPLACE":
                # 将s3_update列表中的mem_id改为完整的记忆条目, 并检查是否存在
                s3_update = decision.get("s3_update", [])
                try:
                    s3_update_memories = self.memory_bank.get_memories(s3_update)
                except Exception as e:
                    print(f"Error in retrieving memories: {e}")
                    decision["s3_update"] = []
                    continue
                # 检查s3_update中是否有记忆库中不存在的条目
                s3_update_memory_ids = [mem["mem_id"] for mem in s3_update_memories]
                for mem in s3_update:
                    if mem not in s3_update_memory_ids:
                        print(f"Warning: memory {mem} not found in memory bank.")
                decision["s3_update"] = s3_update_memories
        
        return decisions

    # 实际行动
    @log_entry
    def execute_action(
        self,
        decision: Dict,
        context: Dict,
        obs_id: str,
        obs: Dict,
    ) -> Optional[str]:
        """
        执行记忆管理操作
        """
        action = decision.get("base_action", "No base_action field found.")
        key = decision.get("key", {
            "mark_key": False,
            "key_type": None,
            "key_level": 0,
        })
        if action == "S1_SUMMARIZE_ADD":
            # 构造数据
            data = {
                "action": "S1_SUMMARIZE_ADD",
                "context": context,
                "obs": obs,
                "target_memories": [],
            }
            # 使用内容模型生成记忆摘要
            prompt_text = self.prompt_content.format(
                INPUT_JSON=json.dumps(data, ensure_ascii=False),
            )
            try:
                summary, completion = self.general_model.chat(prompt_text, json_mode=True)
                print(f"Generated summary: {completion.choices[0].message.content}")
                summary = summary.get("mem_content", "N/A")
                if summary == "N/A":
                    raise ValueError("Content model didn't return'summary' field.")
            except Exception as e:
                summary = ""
                print(f"Error in content model: {e}")
            # 保存到记忆库
            mem_id = self.memory_bank.s1_summarize_add(
                obs_id=obs_id,
                content=summary,
                context=context,
                key=key,
            )
            return mem_id
        elif action == "S2_RAW_ADD":
            # 将obs转换为JSON字符串
            obs_text = json.dumps(obs, ensure_ascii=False)
            self.memory_bank.s2_raw_add(
                obs_id=obs_id,
                content=obs_text,
                context=context,
                key=key,
            )
            return None
        elif action == "S3_UPDATE_REPLACE":
            # 构造数据
            data = {
                "action": "S3_UPDATE_REPLACE",
                "context": context,
                "obs_text": obs,
                "target_memories": decision["s3_update"],
            }
            # 使用内容模型生成记忆摘要
            prompt_text = self.prompt_content.format(
                INPUT_JSON=json.dumps(data, ensure_ascii=False),
            )
            try:
                summary, completion = self.general_model.chat(prompt_text, json_mode=True)
                print(f"Generated summary: {completion.choices[0].message.content}")
                summary = summary.get("mem_content", "N/A")
                if summary == "N/A":
                    raise ValueError("Content model didn't return 'summary' field.")
            except Exception as e:
                summary = ""
                print(f"Error in content model: {e}")
            # 保存到记忆库
            target_memory_ids = [mem["mem_id"] for mem in decision["s3_update"]]
            mem_id = self.memory_bank.s3_update_replace(
                obs_id=obs_id,
                content=summary,
                context=context,
                key=key,
                mem_ids=target_memory_ids,
            )
            return mem_id
        elif action == "S4_DISCARD":
            return None
        else:
            print(f"Invalid action: {action}")
            return None