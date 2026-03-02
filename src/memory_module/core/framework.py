from openai import OpenAI
import json
from typing import *
from pathlib import Path
from ulid import ULID
from datetime import datetime
import math

from memory_module.core.memory_bank import MemoryBank
from memory_module.core.memory_maintainer import MemoryMaintainer
from memory_module.core.memory_consolidator import MemoryConsolidator
from memory_module.utils.model import ChatModel, EmbeddingModel
from memory_module.utils.count_tokens import count_tokens
from memory_module.debug import log_entry


class MemoryModule:
    @log_entry
    def __init__(
        self,
        chat_model: str = "deepseek-chat",
        maintainer_model_policy: str = "deepseek-chat",
        maintainer_model_content: str = "deepseek-chat",
        consolidator_model_policy: str = "deepseek-chat",
        consolidator_model_content: str = "deepseek-chat",
        rag_summary_model: str = "deepseek-chat",
        embedding_model: str = "qwen-text-embedding-v4",
        top_k_0: int = 20,
        top_k_1: int = 50,
        top_k_2: Optional[int] = None,
        step_id: int = 0,
        session_id: Optional[str] = None,
        data_dir: str = "data",
        log_dir: str = "log",
    ):
        self.embedding_model = embedding_model
        self.rag_summary_model = rag_summary_model
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

    @staticmethod
    @log_entry
    def _slice_by_threshold(numbers, threshold, func=lambda x: x):
        """
        将列表从左到右划分为多个切片，每个切片的和不大于 threshold。
        如果单个数字大于 threshold，则它自己成为一个组。

        Args:
            numbers: 数字列表
            threshold: 阈值
            func: 函数，用于计算数字的大小

        Returns:
            切片列表，每个切片是一个子列表
        """
        if not numbers:
            return []

        slices = []
        current_slice = []
        current_sum = 0

        for num in numbers:
            print(func(num), end=" ")
            if func(num) > threshold:
                # 如果当前切片非空，先保存当前累积的切片
                if current_slice:
                    slices.append(current_slice)
                    current_slice = []
                    current_sum = 0

                # 该数字单独成为一个组
                slices.append([num])
            else:
                # 正常情况：检查加入后是否会超过阈值
                if current_sum + func(num) > threshold:
                    # 保存当前切片，开启新切片
                    slices.append(current_slice)
                    current_slice = [num]
                    current_sum = func(num)
                else:
                    # 加入当前切片
                    current_slice.append(num)
                    current_sum += func(num)
        print()

        # 别忘了最后一个切片
        if current_slice:
            slices.append(current_slice)

        return slices

    @log_entry
    def process_step(
        self,
        context: Dict,
        obses: List[Dict] | Dict,
    ):
        """
        处理新的步骤，更新记忆库
        """
        if isinstance(obses, dict):
            obses = [obses]

        segmented_obses = []

        max_tokens_for_raw_text = min(
            0.5 * self.memory_maintainer.general_model.max_context_tokens,
            0.5 * self.memory_maintainer.policy_model.max_context_tokens,
            0.5 * self.memory_consolidator.general_model.max_context_tokens,
            0.5 * self.memory_consolidator.policy_model.max_context_tokens,
            0.5 * self.memory_bank.rag_summary_model.max_context_tokens,
        )
        for obs in obses:
            obs_text_token_number = count_tokens(obs["obs_text"])
            string_length = len(obs["obs_text"])
            if obs_text_token_number > max_tokens_for_raw_text:
                # 每一段取 max_tokens_for_raw_text 长的片段, 片段之间重叠约 1000 个字
                segment_length = int(max_tokens_for_raw_text / obs_text_token_number * string_length)
                overlap = 1000
                if segment_length <= overlap:
                    overlap = segment_length / 10
                    if overlap % 2 != 0:
                        overlap += 1
                segment_count = math.ceil(string_length / (segment_length - overlap))
                for i in range(segment_count):
                    # 为防止最后一段过短, 最后两段平均分
                    if i < segment_count - 2:
                        segment_start = i * (segment_length - overlap)
                        segment_end = segment_start + segment_length
                    elif i == segment_count - 2:
                        segment_start = i * (segment_length - overlap)
                        segment_end = int((segment_start + string_length) / 2) + overlap / 2
                    else:
                        segment_start = int(((i - 1) * (segment_length - overlap) + string_length) / 2) - overlap / 2
                        segment_end = string_length
                    segmented_obses.append({
                        "obs_type": obs["obs_type"],
                        "obs_text": obs["obs_text"][segment_start : segment_end],
                    })
            else:
                segmented_obses.append(obs)
        obses = segmented_obses

        self.memory_bank.new_step(context=context)
        filtered_memories_total = []
        consolidate_memory_dict_total = {
            "recent_progress": [],
            "prior_related_attempts": [],
            "unexplored_entry_points": [],
        }
        intermediate_results = []
        for obs in obses:
            retrieved_memories_1, retrieved_memories_2, decisions, filtered_memories, consolidate_memory_dict \
                = self.process_observation(context=context, obs=obs)
            filtered_memories_total.extend(filtered_memories)
            consolidate_memory_dict_total["recent_progress"].extend(consolidate_memory_dict["recent_progress"])
            consolidate_memory_dict_total["prior_related_attempts"].extend(consolidate_memory_dict["prior_related_attempts"])
            consolidate_memory_dict_total["unexplored_entry_points"].extend(consolidate_memory_dict["unexplored_entry_points"])
            intermediate_results.append({
                "retrieved_memories_1": retrieved_memories_1,
                "retrieved_memories_2": retrieved_memories_2,
                "decisions": decisions,
                "filtered_memories": filtered_memories,
                "consolidate_memory_dict": consolidate_memory_dict,
            })

        self._step_id += 1
        self.memory_bank.step_id = self._step_id
        self.memory_maintainer.step_id = self._step_id
        self.memory_consolidator.step_id = self._step_id

        to_string_dict = {
            "distilled_summary": consolidate_memory_dict_total
        }
        try:
            consolidate_memory_text = json.dumps(to_string_dict, ensure_ascii=False)
        except Exception as e:
            try:
                consolidate_memory_text = json.dumps(to_string_dict)
            except Exception as e:
                consolidate_memory_text = str(to_string_dict)

        return intermediate_results, consolidate_memory_dict_total, consolidate_memory_text

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

        # 获取obs的token数
        obs_token_number = count_tokens(obs["obs_text"])

        # 检索相关记忆
        retrieved_memories_1, query_text, vector = self.memory_bank.retrieve(
            obs=obs,
            context=context,
            top_k_for_0=self.top_k_0,
            top_k_for_1=self.top_k_1,
            top_k_for_2=self.top_k_2,
        )
        retrieved_memory_ids_1 = [pair[0] for pair in retrieved_memories_1]
        retrieved_memories_1 = self.memory_bank.get_memories(
            mem_ids=retrieved_memory_ids_1,
            mode="middle",
        )

        retrieved_memories_1_slices = self._slice_by_threshold(
            numbers=retrieved_memories_1,
            threshold=0.8 * self.memory_maintainer.policy_model.max_context_tokens - obs_token_number,
            func=lambda x: x["token_number"],
        )
        if not retrieved_memories_1_slices:
            retrieved_memories_1_slices = [[]]
        decisions_total = []
        for retrieved_memories_1_slice in retrieved_memories_1_slices:
            # 决定记忆维护操作
            decisions = self.memory_maintainer.decide_action(
                context=context,
                obs=obs,
                retrieved_memories=retrieved_memories_1_slice,
            )
            decisions_total.extend(decisions)

            # 执行记忆维护操作
            for decision in decisions:
                mem_ids = self.memory_maintainer.execute_action(
                    decision=decision,
                    context=context,
                    obs_id=obs_id,
                    obs=obs,
                )

        # 再次检索相关记忆
        retrieved_memories_2, _, _ = self.memory_bank.retrieve(
            obs=obs,
            context=context,
            top_k_for_0=self.top_k_0,
            top_k_for_1=self.top_k_1,
            top_k_for_2=self.top_k_2,
            query_text=query_text,
            vector=vector,
        )
        retrieved_memory_ids_2 = [pair[0] for pair in retrieved_memories_2]
        retrieved_memories_2 = self.memory_bank.get_memories(
            mem_ids=retrieved_memory_ids_2,
            mode="middle",
        )

        retrieved_memories_2_slices = self._slice_by_threshold(
            numbers=retrieved_memories_2,
            threshold=0.8 * self.memory_consolidator.policy_model.max_context_tokens - obs_token_number,
            func=lambda x: x["token_number"],
        )
        if not retrieved_memories_2_slices:
            retrieved_memories_2_slices = [[]]
        filtered_memories_total = []
        for retrieved_memories_2_slice in retrieved_memories_2_slices:
            # 筛选记忆
            filtered_memories = self.memory_consolidator.filter_memory(
                context=context,
                obs=obs,
                retrieved_memories=retrieved_memories_2_slice,
            )
            filtered_memories_total.extend(filtered_memories)

        filtered_memories_slices = self._slice_by_threshold(
            numbers=filtered_memories_total,
            threshold=0.8 * self.memory_consolidator.general_model.max_context_tokens - obs_token_number,
            func=lambda x: x["token_number"],
        )
        consolidate_memory_dict = {
            "recent_progress": [],
            "prior_related_attempts": [],
            "unexplored_entry_points": [],
        }
        for filtered_memories_slice in filtered_memories_slices:
            # 整理记忆
            subset_of_consolidate_memory_dict = self.memory_consolidator.format_memory(
                context=context,
                obs=obs,
                selected_memories=filtered_memories_slice,
            )
            try:
                consolidate_memory_dict["recent_progress"].extend(subset_of_consolidate_memory_dict["distilled_summary"]["recent_progress"])
                consolidate_memory_dict["prior_related_attempts"].extend(subset_of_consolidate_memory_dict["distilled_summary"]["prior_related_attempts"])
                consolidate_memory_dict["unexplored_entry_points"].extend(subset_of_consolidate_memory_dict["distilled_summary"]["unexplored_entry_points"])
            except Exception as e:
                print(f"Error: failed to extend consolidate_memory_dict:{e}")

        return retrieved_memories_1, retrieved_memories_2, decisions_total, filtered_memories_total, consolidate_memory_dict
