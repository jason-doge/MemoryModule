from openai import OpenAI
import json
from typing import *
from pathlib import Path
from ulid import ULID
from datetime import datetime

from memory_module.core.memory_bank import MemoryBank
from memory_module.core.memory_maintainer import MemoryMaintainer
from memory_module.core.memory_consolidator import MemoryConsolidator
from memory_module.utils.model import ChatModel, EmbeddingModel
from memory_module.debug import log_entry

class MemoryModule:
    @log_entry
    def __init__(
        self,
        chat_model: str = "qwen-max",
        maintainer_model_policy: str = "qwen-max",
        maintainer_model_content: str = "qwen-max",
        consolidator_model_policy: str = "qwen-max",
        consolidator_model_content: str = "qwen-max",
        embedding_model: str = "text-embedding-v4",
        top_k_0: int = 20,
        top_k_1: int = 50,
        top_k_2: Optional[int] = None,
        step_id: int = 0,
        session_id: Optional[str] = None,
        data_dir: str = "data",
        log_dir: str = "log",
    ):
        self.embedding_model = embedding_model
        self.top_k_0 = top_k_0
        self.top_k_1 = top_k_1
        self.top_k_2 = top_k_2

        # 在 data 和 log 里面创建两个带时间的文件夹
        self.data_dir = Path(data_dir) / datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_dir = Path(log_dir) / datetime.now().strftime("%Y%m%d_%H%M%S")
        if not self.data_dir.exists():
            self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.log_dir.exists():
            self.log_dir.mkdir(parents=True, exist_ok=True)

        # 在当前目录创建一个session.json用于保存session存储的数据库位置
        session_file = Path.cwd() / "session.json"
        session_data = {}
        if session_file.exists():
            with open(session_file, "r", encoding="utf-8") as f:
                try:
                    session_data = json.load(f)
                except Exception as e:
                    session_data = {}
        if session_id is None:
            session_id = f"session_{ULID()}"
        if session_id not in session_data:
            self.memory_bank = MemoryBank(step_id=step_id)
            session_data.update({str(session_id): str(self.memory_bank.db_dir)})
            with open(session_file, "w", encoding="utf-8") as f:
                json.dump(session_data, f)
        else:
            self.memory_bank = MemoryBank(db_dir=session_data[str(session_id)])
        self.session_id = session_id

        self.chat_model = ChatModel(model=chat_model)
        self.memory_maintainer = MemoryMaintainer(
            memory_bank=self.memory_bank,
            step_id=step_id,
            policy_model=maintainer_model_policy,
            general_model=maintainer_model_content,
        )
        self.memory_consolidator = MemoryConsolidator(
            memory_bank=self.memory_bank,
            step_id=step_id,
            policy_model=consolidator_model_policy,
            general_model=consolidator_model_content,
        )
        self._step_id = step_id

    def __repr__(self) -> str:
        return f"<MemoryModule with {len(self.memory_bank)} items>"

    @property
    def step_id(self) -> int:
        return self._step_id

    @step_id.setter
    def step_id(self, value: int) -> None:
        self._step_id = value
        self.memory_bank.step_id = value
        self.memory_maintainer.step_id = value
        self.memory_consolidator.step_id = value

    @log_entry
    def process_step(
        self,
        context: Dict,
        obses: List[Dict] | Dict,
    ):
        """
        处理新的步骤，更新记忆库
        """
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        # 这里还缺一个处理过长输出的过程
        # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        if isinstance(obses, dict):
            obses = [obses]
        self.memory_bank.new_step(context=context)
        filtered_memories_total = []
        intermediate_results = []
        for obs in obses:
            retrieved_memories_1, retrieved_memories_2, decisions, filtered_memories = self.process_observation(context=context, obs=obs)
            filtered_memories_total.extend(filtered_memories)
            intermediate_results.append({
                "retrieved_memories_1": retrieved_memories_1,
                "retrieved_memories_2": retrieved_memories_2,
                "decisions": decisions,
                "filtered_memories": filtered_memories,
            })
        # 整理记忆
        consolidate_memory_dict, consolidate_memory_text = self.memory_consolidator.format_memory(
            context=context,
            obs=obses,
            selected_memories=filtered_memories_total,
        )

        self._step_id += 1
        self.memory_bank.step_id = self._step_id
        self.memory_maintainer.step_id = self._step_id
        self.memory_consolidator.step_id = self._step_id

        return intermediate_results, consolidate_memory_dict, consolidate_memory_text

    @log_entry
    def process_observation(
        self,
        context: Dict,
        obs: Dict,
    ):
        """
        处理新的观察结果，更新记忆库
        """
        # 以session_id_步骤_时间.txt 保存到data目录下
        obs_source_file_name = f"{self.session_id}_{self.step_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        obs_source_file_path = self.data_dir / obs_source_file_name
        with open(obs_source_file_path, "w", encoding="utf-8") as f:
            f.write(f"[{obs['obs_type']}]\n")
            f.write(obs["obs_text"])

        # 获取obs_id
        obs_id = self.memory_bank.new_observation(
            obs_type=obs["obs_type"],
            source_tool=context["source_tool"],
            source_command=context["source_command"],
            obs_source=str(obs_source_file_path),
        )

        # 检索相关记忆
        retrieved_memories_1 = self.memory_bank.retrieve(
            obs=obs,
            context=context,
            top_k_for_0=self.top_k_0,
            top_k_for_1=self.top_k_1,
            top_k_for_2=self.top_k_2,
        )
        retrieved_memories_1 = [pair[0] for pair in retrieved_memories_1]
        retrieved_memories_1 = self.memory_bank.get_memories(
            mem_ids=retrieved_memories_1,
        )

        # 决定记忆维护操作
        decisions = self.memory_maintainer.decide_action(
            context=context,
            obs=obs,
            retrieved_memories=retrieved_memories_1,
        )
        
        # 执行记忆维护操作
        for decision in decisions:
            mem_id = self.memory_maintainer.execute_action(
                decision=decision,
                context=context,
                obs_id=obs_id,
                obs=obs,
            )

        # 再次检索相关记忆
        retrieved_memories_2 = self.memory_bank.retrieve(
            obs=obs,
            context=context,
            top_k_for_0=self.top_k_0,
            top_k_for_1=self.top_k_1,
            top_k_for_2=self.top_k_2,
        )
        retrieved_memories_2 = [pair[0] for pair in retrieved_memories_1]
        retrieved_memories_2 = self.memory_bank.get_memories(
            mem_ids=retrieved_memories_2,
        )
    
        # 筛选记忆
        filtered_memories = self.memory_consolidator.filter_memory(
            context=context,
            obs=obs,
            retrieved_memories=retrieved_memories_2,
        )

        return retrieved_memories_1, retrieved_memories_2, decisions, filtered_memories
