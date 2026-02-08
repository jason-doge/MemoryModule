from typing import List, Dict, Tuple, Callable, Optional, Any, Union
from . import prompt
from .model import ChatModel
from .memory_bank import MemoryBank
import json

class MemoryMaintainer:
    """记忆维护模型：决定增删改操作"""
    def __init__(
            self,
            model: str = "gpt-4",
            general_model: str = "gpt-4",
            temperature: Optional[float] = None,
            top_p: Optional[int] = None,
            max_tokens: Optional[int] = None,
            step_id: int = 0,
        ):
        self.policy_model = ChatModel(
            model=model,
            system_prompt="你是一名渗透测试记忆管理专家，负责维护渗透测试记忆库。",
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
        self.general_model = ChatModel(
            model=general_model,
            system_prompt="你是一名渗透测试记忆管理专家，负责维护渗透测试记忆库。",
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
        self.prompt = prompt.maintainer_prompt
        self.step_id = step_id

    def __repr__(self) -> str:
        return f"<MemoryMaintainer(model={self.model})>"
    
    def decide_action(
        self,
        pentest_info,
        tool_outputs,
        retrieved_memories,
    ) -> Dict[str, Any]:
        """
        输入当前上下文，返回记忆维护决策
        """
        # 格式化检索到的记忆
        format_retrieved_memories = []
        for m in retrieved_memories:
            dict_obj = {
                "mem_id": "mem_" + str(m["id"]),
                "content": m["raw_content"],
                "context": m["metadata"]["context"],
            }
            format_retrieved_memories.append(dict_obj)
        
        input_json = pentest_info.copy()
        input_json.update({
            "retrieved_memories": format_retrieved_memories,
        })

        prompt_text = self.prompt.format(
            INPUT_JSON=json.dumps(input_json, ensure_ascii=False),
        )
        
        while True:
            try:
                actions, _ = self.model.chat(prompt_text)
                actions = json.loads(actions)
                break
            except json.JSONDecodeError:
                print("模型返回非JSON格式或格式不正确，请重新输入。")
                continue
        
        return actions



        # step_observation = {
        #     "step_id": self.step_id,
        #     "output": tool_outputs,
        # }
        # step_observation.update(pentest_info)

        # prompts = self.prompts.format(
        #     PENTEST_GOAL=pentest_goal,
        #     TOOL_OUTPUTS=json.dumps(step_observation, ensure_ascii=False),
        #     RELATED_MEMORY_CANDIDATES_JSON="\n".join(retrieved_memories),
        # )

        # actions, _ = self.model.chat(prompts, response_format="json_object")

        # try:
        #     actions = json.loads(actions)["decisions"]
        # except json.JSONDecodeError:
        #     actions = {"action": "none"}
        #     print(f"记忆维护模型返回非JSON格式或格式不正确，默认不操作。返回内容: {actions}")
        
        # return actions

    # 实际行动
    def execute_action(
        self,
        actions,
        pentest_info,
        tool_outputs,
        memory_bank: MemoryBank,
    ) -> None:
        """
        执行记忆维护操作: 将所需的操作划归到增删改查
        """
        
        action = actions["decision"]["base_action"].lower()
        if "summarize" in action:
            # 使用通用模型生成摘要
            general_model_prompt = """
### pentest_info
以下pentest_info对象给出了渗透测试的工具 (source_tool), 工具命令 (source_command), 工具输出 (obs_text), 当前阶段 (phase), 子目标 (subgoal), 以及状态总结 (state_summary)。
{PENTEST_INFO_JSON}

### 任务
你的任务是根据上述pentest_info生成一个简洁且信息丰富的记忆摘要，突出显示对当前渗透测试步骤的信息。确保摘要涵盖关键发现、观察结果和任何可能影响后续步骤的重要细节。请用英文写出摘要信息, 请用1~3句话 (纯文本) 表示.
Please reply in English within 1-3 sentences.
"""
            summary, _ = self.general_model.chat(
                general_model_prompt.format(
                    PENTEST_INFO_JSON=json.dumps(pentest_info, ensure_ascii=False),
                )
            )

            # 保存摘要到记忆库
            pentest_info_save = {
                "phase": pentest_info["phase"],
                "subgoal": pentest_info["subgoal"],
                "source_tool": pentest_info["obs"]["source_tool"],
                "source_command": pentest_info["obs"]["source_command"],
            }

            metadata_save = {
                "mem_type": "SUMMARY",
                "context": {
                    "phase": pentest_info["phase"],
                    "subgoal": pentest_info["subgoal"],
                },
                "status": {
                    "state": "ACTIVE",
                },
                "tool": {
                    "source_tool": pentest_info["obs"]["source_tool"],
                    "source_command": pentest_info["obs"]["source_command"],
                },
                "obs_ref": [pentest_info["obs"]["obs_id"]],
                "reason": actions["decision"]["reason"],
            }

            memory_bank.add(
                content=summary,
                pentest_info=pentest_info_save,
                metadata=metadata_save,
            )

        elif "raw" in action:
            # 保存原始输出到记忆库
            pentest_info_save = {
                "phase": pentest_info["phase"],
                "subgoal": pentest_info["subgoal"],
                "source_tool": pentest_info["obs"]["source_tool"],
                "source_command": pentest_info["obs"]["source_command"],
            }

            metadata_save = {
                "mem_type": "SUMMARY",
                "context": {
                    "phase": pentest_info["phase"],
                    "subgoal": pentest_info["subgoal"],
                },
                "status": {
                    "state": "ACTIVE",
                },
                "tool": {
                    "source_tool": pentest_info["obs"]["source_tool"],
                    "source_command": pentest_info["obs"]["source_command"],
                },
                "obs_ref": [pentest_info["obs"]["obs_id"]],
                "reason": actions["decision"]["reason"],
            }

            memory_bank.add(
                content=tool_outputs,
                pentest_info=pentest_info_save,
                metadata=metadata_save,
            )
        
        elif "update" in action:
            # 更新记忆库
            target_memory_ids = actions["decision"]["s3_update"]["target_memory_ids"]
            target_memory_ids = [int(m.split("_")[-1]) for m in target_memory_ids]

            # 取出这些记忆
            target_memories = [m for m in memory_bank.memories if m["id"] in target_memory_ids]
            # 格式化这些记忆供模型使用
            format_retrieved_memories = []
            for m in target_memories:
                dict_obj = {
                    "mem_id": "mem_" + str(m["id"]),
                    "content": m["raw_content"],
                    "context": m["metadata"]["context"],
                }
                format_retrieved_memories.append(dict_obj)
            # 使用通用模型生成更新后的内容
            general_model_prompt = """
### pentest_info
以下pentest_info对象给出了渗透测试的工具 (source_tool), 工具命令 (source_command), 工具输出 (obs_text), 当前阶段 (phase), 子目标 (subgoal), 以及状态总结 (state_summary)。
{PENTEST_INFO_JSON}

### memories_to_update
以下是记忆库中需要**合并**并**根据pentest_info更新**的记忆内容:
{MEMORIES_TO_UPDATE_JSON}

### 任务
你的任务是根据上述pentest_info**合并并更新**memories_to_update中的记忆内容, 生成一条新的记忆内容用于**取代**原有记忆内容，确保它们反映最新的观察结果和信息。请用英文写出更新后的记忆内容, 请用1~3句话 (纯文本) 表示.
Please reply in English within 1-3 sentences.
"""
            updated_content, _ = self.general_model.chat(
                general_model_prompt.format(
                    PENTEST_INFO_JSON=json.dumps(pentest_info, ensure_ascii=False),
                    MEMORIES_TO_UPDATE_JSON=json.dumps(format_retrieved_memories, ensure_ascii=False),
                )
            )
            # 保存更新后的内容到记忆库
            pentest_info_save = {
                "phase": pentest_info["phase"],
                "subgoal": pentest_info["subgoal"],
                "source_tool": pentest_info["obs"]["source_tool"],
                "source_command": pentest_info["obs"]["source_command"],
            }

            # 取出所有target_memories的obs_ref并拼接
            obs_refs = [m["metadata"]["obs_ref"] for m in target_memories]

            metadata_save = {
                "mem_type": "MERGED",
                "context": {
                    "phase": pentest_info["phase"],
                    "subgoal": pentest_info["subgoal"],
                },
                "status": {
                    "state": "ACTIVE",
                },
                "tool": {
                    "source_tool": pentest_info["obs"]["source_tool"],
                    "source_command": pentest_info["obs"]["source_command"],
                },
                "obs_ref": obs_refs.append(pentest_info["obs"]["obs_id"]),
                "reason": actions["decision"]["reason"],
            }

            memory_bank.add(
                content=updated_content,
                pentest_info=pentest_info_save,
                metadata=metadata_save,
            )

            # 然后删掉原有的记忆
            for mem in memory_bank.memories:
                if mem["id"] in target_memory_ids:
                    mem["status"]["state"] = "SUPERSDED"

        elif "discard" in action:
            print(f"Discard action: {actions['decision']['reason']}")