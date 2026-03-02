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
        self.prompt_summarize = prompt.maintainer_prompt_summarize
        self.prompt_update = prompt.maintainer_prompt_update
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
            "retrieved_memories": [
                {
                    "mem_id": mem["mem_id"],
                    "mem_type": mem["mem_type"],
                    "mem_content": mem["mem_content"],
                    "context": mem["context"],
                    "key": mem["key"],
                } for mem in retrieved_memories
            ],
        }
        # 使用决策模型生成操作建议
        prompt_text = self.prompt_policy.format(
            INPUT_JSON=json.dumps(data, ensure_ascii=False),
        )
        try:
            decisions, completion = self.policy_model.chat(prompt_text, json_mode=True)
            print("[maintainer]" + "*" * 50)
            print(completion.choices[0].message.content)
            print("[maintainer]" + "*" * 50)
            decisions = decisions.get("decisions", "N/A")
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
        print("base_action: " + action)
        key = decision.get("key", {
            "mark_key": False,
            "key_type": None,
            "key_level": 0,
        })
        policy_reason = decision.get("reason", "")
        mem_ids = []
        if action == "S1_SUMMARIZE_ADD":
            # 构造数据
            data = {
                "context": context,
                "obs": obs,
            }
            # 使用内容模型生成记忆摘要
            prompt_text = self.prompt_summarize.format(
                INPUT_JSON=json.dumps(data, ensure_ascii=False),
            )
            try:
                reply_dict, completion = self.general_model.chat(prompt_text, json_mode=True)
                print(f"Generated summary: {completion.choices[0].message.content}")
            except Exception as e:
                print(f"Error in content model: {e}")
                return []
            overall_summary = reply_dict.get("overall_summary", "").strip()
            segments = reply_dict.get("segments", [])
            further_explanation = {
                "policy": {
                    "reason": policy_reason,
                },
                "content": {
                    "overall_summary": overall_summary,
                    "segments": [
                        {
                            "type": segment.get("type", "").strip(),
                            "reason": segment.get("reason", "").strip(),
                        } for segment in segments
                    ]
                }
            }
            processed_segments = [
                {
                    "type": segment.get("type", "").strip(),
                    "content": segment.get("content", "").strip(),
                } for segment in segments
            ]
            content = json.dumps({
                "overall_summary": overall_summary,
                "segments": processed_segments,
            }, ensure_ascii=False)
            mem_id = self.memory_bank.s1_summarize_add(
                obs_id=obs_id,
                content=content,
                context=context,
                key=key,
                explanation=further_explanation,
            )
            # for segment in segments:
            #     try:
            #         type = segment.get("type", "").strip().upper()
            #         content = segment.get("content", "").strip()
            #         reason = segment.get("reason", "").strip()
            #         further_explanation = {
            #             "policy": {
            #                 "reason": policy_reason,
            #             },
            #             "content": {
            #                 "overall_summary": overall_summary,
            #                 "reason": reason,
            #             }
            #         }
            #         if type == "SUMMARY":
            #             mem_id = self.memory_bank.s1_summarize_add(
            #                 obs_id=obs_id,
            #                 content=content,
            #                 context=context,
            #                 key=key,
            #                 further_explanation=further_explanation,
            #             )
            #             mem_ids.append(mem_id)
            #         elif type == "RAW":
            #             mem_id = self.memory_bank.s2_raw_add(
            #                 obs_id=obs_id,
            #                 content=content,
            #                 context=context,
            #                 key=key,
            #                 further_explanation=further_explanation,
            #             )
            #             mem_ids.append(mem_id)
            #         else:
            #             raise ValueError(f"Unknown type: {type}")
            #     except Exception as e:
            #         print(f"Error in content model (segment loop): {e}")
            return mem_id
        elif action == "S2_RAW_ADD":
            # 将obs转换为JSON字符串
            obs_text = json.dumps(obs, ensure_ascii=False)
            further_explanation = {
                "policy": {
                    "reason": policy_reason,
                },
            }
            mem_id = self.memory_bank.s2_raw_add(
                obs_id=obs_id,
                content=obs_text,
                context=context,
                key=key,
                explanation=further_explanation,
            )
            return mem_id
        elif action == "S3_UPDATE_REPLACE":
            old_memories = []
            for memory in decision["s3_update"]:
                old_memories.append({
                    "mem_id": memory["mem_id"],
                    "mem_content": memory["mem_content"],
                    "mem_type": memory["mem_type"],
                })
            # 构造数据
            data = {
                "context": context,
                "obs_text": obs,
                "target_memories": old_memories,
            }
            # 使用内容模型生成记忆摘要
            prompt_text = self.prompt_update.format(
                INPUT_JSON=json.dumps(data, ensure_ascii=False),
            )
            try:
                reply_dict, completion = self.general_model.chat(prompt_text, json_mode=True)
                print(f"Generated summary: {completion.choices[0].message.content}")
                summary = reply_dict.get("merged_memory", "N/A")
                if summary == "N/A":
                    raise ValueError("Content model didn't return 'summary' field.")
            except Exception as e:
                print(f"Error in content model: {e}")
                return []
            # 检查模型输入输出的old_memories是否一致
            input_old_memory_ids = [mem["mem_id"] for mem in decision["s3_update"]]
            output_old_memory_ids = reply_dict.get("replaced_ids", [])
            for input_id in input_old_memory_ids:
                if input_id not in output_old_memory_ids:
                    print(f"Warning: memory {input_id} not found in output.")
            for output_id in output_old_memory_ids:
                if output_id not in input_old_memory_ids:
                    print(f"Warning: memory {output_id} not found in input.")
            # 保存到记忆库
            further_explanation = {
                "policy": {
                    "reason": policy_reason,
                },
                "content": {
                    "merge_type": reply_dict.get("merge_type", ""),
                    "improvement": reply_dict.get("improvement", ""),
                    "replaced_ids": reply_dict.get("replaced_ids", []),
                }
            }
            mem_id = self.memory_bank.s3_update_replace(
                obs_id=obs_id,
                content=summary,
                context=context,
                key=key,
                mem_ids=input_old_memory_ids,
                explanation=further_explanation,
            )
            return mem_id
        elif action == "S4_DISCARD":
            return None
        else:
            print(f"Invalid action: {action}")
            return None