import os
from pathlib import Path
from typing import *
from datetime import datetime
import json
from pprint import pprint
import sys


import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
import sqlite3
import numpy as np
from ulid import ULID

from memory_module.utils.model import EmbeddingModel
from memory_module.utils.model import ChatModel
from memory_module.utils.prompt import rag_prompt
from memory_module.utils.count_tokens import count_tokens
from memory_module.debug import log_entry

# 一个也不算太正式的正式方案: 使用ChromaDB管理向量数据库, 使用sqlite管理元数据

class MemoryBank:
    """向量记忆库: RAG + 记忆操作"""
    @log_entry
    def __init__(
        self,
        step_id: int = 0,
        db_dir: Optional[str] = None,
        embedding_model: str = "qwen-text-embedding-v4",
        rag_summary_model: str = "qwen-max",
    ):
        # 一个表示已存入记忆条目个数的计数器
        self.count = 0
        self.step_id = step_id
        self.embedding_model = EmbeddingModel(model=embedding_model)
        self.rag_summary_model = ChatModel(model=rag_summary_model, max_tokens=8192)

        if db_dir is None:
            db_dir = f"database/{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}"
            self.db_dir = Path.cwd() / db_dir
            # 检查 db_dir 是否存在, 不存在则创建, 注意有可能database这一层级就不存在, 需要创建
            if not self.db_dir.exists():
                self.db_dir.mkdir(parents=True, exist_ok=True)
        else:
            self.db_dir = Path(db_dir)
            if not self.db_dir.exists():
                self.db_dir.mkdir(parents=True, exist_ok=True)

        # 我需要两个 db 文件: chroma 和 sqlite
        self.sqlite_file = os.path.join(self.db_dir, f"sqlite.db")
        self.chroma_file = os.path.join(self.db_dir, f"chroma")

        # SQLite
        self.sqlite_conn = sqlite3.connect(self.sqlite_file)
        self.sqlite_cursor = self.sqlite_conn.cursor()

        # 在 SQLite 中创建表
        # 1. 步骤表：渗透测试执行上下文
        # step_id: 步骤ID
        # phase: 渗透测试执行阶段
        # subgoal: 渗透测试目标
        # state_summary: 渗透测试执行状态
        # created_at:
        self.sqlite_cursor.execute("""
                CREATE TABLE IF NOT EXISTS steps (
                    step_id INTEGER PRIMARY KEY,
                    phase TEXT NOT NULL,
                    subgoal TEXT NOT NULL,
                    state_summary TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

        # 2. 观测表：原始输出元数据（obs_text不存于此，仅存引用）
        # obs_id: 观测ID
        # step_id: 步骤ID
        # obs_type: 观测类型: 观测的来源, 比如stdout, stderr, screen_output等
        # source_tool: 工具
        # source_command: 调用工具的命令
        # obs_source: 工具输出原文的文件地址
        # created_at: 创建时间
        self.sqlite_cursor.execute("""
                CREATE TABLE IF NOT EXISTS observations (
                    obs_id TEXT PRIMARY KEY,
                    step_id INTEGER NOT NULL,
                    obs_type TEXT NOT NULL,
                    source_tool TEXT,
                    source_command TEXT,
                    obs_source TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

        # 3. 记忆表：核心记忆条目（内容存向量库，此处仅元数据）
        # mem_id: 记忆ID
        # mem_type: 观测类型: 观测的来源, 比如stdout, stderr, screen_output等
        # phase: 渗透测试执行阶段
        # subgoal: 渗透测试目标
        # state_summary: 渗透测试执行状态
        # source_tool: 源工具
        # source_command: 调用工具的命令
        # mark_key: 关键记忆标志
        # key_type: 关键记忆标志类型
        # key_level: 关键记忆标志级别
        # further_explanation: 记忆维护中间步骤的所有解释性文字, 以JSON存储
        # token_number: 该记忆占用的token数的估计
        # created_at_step_id: 创建时步骤ID
        # updated_at_step_id: 更新时步骤ID
        # superseded_by: 被替换的记忆ID
        # current_obs_id: 当前关联的观测ID
        # status: 状态 (ACTIVE表示有效, SUPERSEDED表示被替代)
        # created_at: 创建时间
        self.sqlite_cursor.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    mem_id TEXT PRIMARY KEY,
                    mem_type TEXT NOT NULL,
                    content TEXT,
                    phase TEXT,
                    subgoal TEXT,
                    state_summary TEXT,
                    source_tool TEXT,
                    source_command TEXT,
                    mark_key INTEGER DEFAULT 0,
                    key_type TEXT,
                    key_level INTEGER DEFAULT 0,
                    further_explanation TEXT,
                    token_number INTEGER DEFAULT 0,
                    created_at_step_id INTEGER NOT NULL,
                    updated_at_step_id INTEGER NOT NULL,
                    superseded_by TEXT,
                    current_obs_id TEXT NOT NULL,
                    status TEXT DEFAULT 'ACTIVE',
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
        
        # 4. 观测-记忆关联表：记录多对多关系
        # obs_id: 观测ID
        # mem_id: 记忆ID
        # created_at: 创建时间
        self.sqlite_cursor.execute("""
            CREATE TABLE IF NOT EXISTS obs_memory_links (
                obs_id TEXT NOT NULL,
                mem_id TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (obs_id, mem_id)
            )
        """)
        
        self.sqlite_conn.commit()

        # 在 Chroma 中建表
        self.chroma_client = chromadb.PersistentClient(path=self.chroma_file)
        self.chroma_collection = self.chroma_client.get_or_create_collection(
            name="memories",
            embedding_function=None,
            configuration={"hnsw": {"space": "cosine"}},
        )

    def __repr__(self):
        return f"<MemoryBank: {self.count} memories>"

    def __len__(self):
        return self.count

    @staticmethod
    @log_entry
    def _generate_id(prefix: str = "mem") -> str:
        """生成 ULID 格式的 ID: prefix_01HV8J3K..."""
        return f"{prefix}_{ULID()}"

    # 处理新的step
    @log_entry
    def new_step(
        self,
        context: Dict[str, Any],
    ) -> None:
        """
        处理新的step
        适用于：渗透测试执行阶段，记录执行上下文
        """
        phase = context.get("phase", "")
        subgoal = context.get("subgoal", "")
        state_summary = context.get("state_summary", "")
        self.sqlite_cursor.execute("""
            INSERT INTO steps (step_id, phase, subgoal, state_summary)
            VALUES (?,?,?,?)
        """, (self.step_id, phase, subgoal, state_summary))
        self.sqlite_conn.commit()
    
    # 处理新的观测
    @log_entry
    def new_observation(
        self,
        obs_type: str,
        source_tool: str,
        source_command: str,
        obs_source: str,
    ) -> str:
        """
        处理新的观测
        适用于：原始输出元数据

        Args:
            obs_type: 观测类型
            source_tool: 观测来源工具
            source_command: 观测来源命令
            obs_source: 将观测存储在哪个文件中
        
        Returns:
            obs_id: 新创建的观测ID
        """
        obs_id = self._generate_id(prefix="obs")
        self.sqlite_cursor.execute("""
            INSERT INTO observations (obs_id, step_id, obs_type, source_tool, source_command, obs_source)
            VALUES (?,?,?,?,?,?)
        """, (obs_id, self.step_id, obs_type, source_tool, source_command, obs_source))
        self.sqlite_conn.commit()
        return obs_id

    @staticmethod
    @log_entry
    def _count_memory_tokens(
            content: str,
            context: Dict[str, Any],
            key: Dict[str, Any],
    ):
        data_dict = {
            "content": content,
            "context": context,
            "key": key,
        }
        data_dict = json.dumps(data_dict, ensure_ascii=False)
        return count_tokens(data_dict)
    
    # S1_SUMMARIZE_ADD: 摘要后添加新记忆
    @log_entry
    def s1_summarize_add(
        self,
        obs_id: str,
        content: str,
        context: Dict[str, Any],
        key: Dict[str, Any],
        explanation: Optional[Dict] = None,
    ) -> str:
        """
        S1_SUMMARIZE_ADD: 摘要后添加新记忆
        适用于：扫描结果、枚举列表等结构化信息，提取要点后存储
        
        Returns:
            mem_id: 新创建的记忆ID
        """
        mem_id = self._generate_id()
        mem_type = "SUMMARY"

        # 1. 向量化
        # 将context和content合并为一个文本
        extended_content = context.copy()
        extended_content.update({"content": content})
        vector = None
        try:
            extended_content_json = json.dumps(extended_content, ensure_ascii=False)
            vector = self.embedding_model.embedding(extended_content_json)
        except Exception as e:
            try:
                extended_content_json = json.dumps(extended_content)
                vector = self.embedding_model.embedding(extended_content_json)
            except Exception as e:
                print(f"Failed to vectorize content at step {self.step_id}: {e}")
                return None
        
        # 2. 向量库存储
        # 向量库中存储向量
        print(vector[:5])
        self.chroma_collection.add(
            ids=[mem_id],
            documents=[content],
            embeddings=[vector],
        )

        # 3. 向 SQLite 中插入记忆条目
        if not explanation:
            explanation = {}
        further_explanation = json.dumps(explanation, ensure_ascii=False)
        token_number = self._count_memory_tokens(content, context, key)
        # 检查 key 参数
        if not key.get("mark_key", False):
            key["key_type"] = None
            key["key_level"] = 0
        self.sqlite_cursor.execute("""
            INSERT INTO memories (mem_id, mem_type, content, phase, subgoal, state_summary, source_tool, source_command, mark_key, key_type, key_level, further_explanation, token_number, created_at_step_id, updated_at_step_id, superseded_by, current_obs_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (mem_id, mem_type, content, context.get("phase", ""), context.get("subgoal", ""), context.get("state_summary", ""), context.get("source_tool", ""), context.get("source_command", ""), int(key.get("mark_key", False)), key.get("key_type", ""), key.get("key_level", 0), further_explanation, token_number, self.step_id, self.step_id, None, obs_id))
        self.sqlite_conn.commit()

        # 4. 关联表插入
        self.sqlite_cursor.execute("""
            INSERT INTO obs_memory_links (obs_id, mem_id)
            VALUES (?,?)
        """, (obs_id, mem_id))
        self.sqlite_conn.commit()

        self.count += 1
        return mem_id
    
    # S2_RAW_ADD：将原始观察内容存储为记忆条目
    @log_entry
    def s2_raw_add(
        self,
        obs_id: str,
        content: str,
        context: Dict[str, Any],
        key: Dict[str, Any],
        explanation: Optional[Dict] = None,
    ) -> str:
        """
        S2_RAW_ADD：将原始观察内容存储为记忆条目
        适用于：原始输出元数据
        
        Returns:
            mem_id: 新创建的记忆ID
        """
        mem_id = self._generate_id()
        mem_type = "RAW"

        # 1. 向量化
        # 将context和content合并为一个文本
        extended_content = context.copy()
        extended_content.update({"content": content})
        vector = None
        try:
            extended_content_json = json.dumps(extended_content, ensure_ascii=False)
            vector = self.embedding_model.embedding(extended_content_json)
        except Exception as e:
            try:
                extended_content_json = json.dumps(extended_content)
                vector = self.embedding_model.embedding(extended_content_json)
            except Exception as e:
                print(f"Failed to vectorize content at step {self.step_id}: {e}")
                return None
        # 2. 向量库存储
        # 向量库中存储向量
        print(vector[:5])
        self.chroma_collection.add(
            ids=[mem_id],
            documents=[content],
            embeddings=[vector],
        )

        # 3. 向 SQLite 中插入记忆条目
        if not explanation:
            explanation = {}
        further_explanation = json.dumps(explanation, ensure_ascii=False)
        token_number = self._count_memory_tokens(content, context, key)
        # 检查 key 参数
        if not key.get("mark_key", False):
            key["key_type"] = None
            key["key_level"] = 0
        self.sqlite_cursor.execute("""
            INSERT INTO memories (mem_id, mem_type, content, phase, subgoal, state_summary, source_tool, source_command, mark_key, key_type, key_level, further_explanation, token_number, created_at_step_id, updated_at_step_id, superseded_by, current_obs_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (mem_id, mem_type, content, context.get("phase", ""), context.get("subgoal", ""), context.get("state_summary", ""), context.get("source_tool", ""), context.get("source_command", ""), int(key.get("mark_key", False)), key.get("key_type", ""), key.get("key_level", 0), further_explanation, token_number, self.step_id, self.step_id, None, obs_id))
        self.sqlite_conn.commit()

        # 4. 关联表插入
        self.sqlite_cursor.execute("""
            INSERT INTO obs_memory_links (obs_id, mem_id)
            VALUES (?,?)
        """, (obs_id, mem_id))
        self.sqlite_conn.commit()

        self.count += 1
        return mem_id
    
    # S3_UPDATE_REPLACE：更新记忆条目
    @log_entry
    def s3_update_replace(
        self,
        obs_id: str,
        content: str,
        context: Dict[str, Any],
        key: Dict[str, Any],
        mem_ids: List[str],
        explanation: Optional[Dict] = None,
    ) -> str | None:
        """
        S3_UPDATE_REPLACE：更新记忆条目
        适用于：更新记忆条目
        
        Returns:
            mem_id: 新创建的记忆ID
        """
        mem_id = self._generate_id()
        mem_type = "MERGED"

        # 1. 向量化
        # 将context和content合并为一个文本
        extended_content = context.copy()
        extended_content.update({"content": content})
        vector = None
        try:
            extended_content_json = json.dumps(extended_content, ensure_ascii=False)
            vector = self.embedding_model.embedding(extended_content_json)
        except Exception as e:
            try:
                extended_content_json = json.dumps(extended_content)
                vector = self.embedding_model.embedding(extended_content_json)
            except Exception as e:
                print(f"Failed to vectorize content at step {self.step_id}: {e}")
                return None
        # 2. 向量库存储
        # 向量库中存储向量
        print(vector[:5])
        self.chroma_collection.add(
            ids=[mem_id],
            documents=[content],
            embeddings=[vector],
        )

        # 3. 向 SQLite 中插入记忆条目
        if not explanation:
            explanation = {}
        further_explanation = json.dumps(explanation, ensure_ascii=False)
        token_number = self._count_memory_tokens(content, context, key)
        # 检查 key 参数
        if not key.get("mark_key", False):
            key["key_type"] = None
            key["key_level"] = 0
        self.sqlite_cursor.execute("""
            INSERT INTO memories (mem_id, mem_type, content, phase, subgoal, state_summary, source_tool, source_command, mark_key, key_type, key_level, further_explanation, token_number, created_at_step_id, updated_at_step_id, superseded_by, current_obs_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (mem_id, mem_type, content, context.get("phase", ""), context.get("subgoal", ""), context.get("state_summary", ""), context.get("source_tool", ""), context.get("source_command", ""), int(key.get("mark_key", False)), key.get("key_type", ""), key.get("key_level", 0), further_explanation, token_number, self.step_id, self.step_id, None, obs_id))
        self.sqlite_conn.commit()

        # 4. 替代原有记忆条目
        # 修改updated_at_step_id, superseded_by, status
        self.sqlite_cursor.execute("""
            UPDATE memories
            SET updated_at_step_id = ?, superseded_by = ?, status = 'SUPERSEDED'
            WHERE mem_id IN ({})
        """.format(",".join(["?"] * len(mem_ids))), (self.step_id, mem_id) + tuple(mem_ids))
        self.sqlite_conn.commit()

        # 5. 关联表插入: 当前观察 + 被更新记忆的obs_id 合并算入关联的 obs
        # 先看被更新记忆关联的obs_id有哪些
        self.sqlite_cursor.execute("""
            SELECT obs_id FROM obs_memory_links WHERE mem_id IN ({})
        """.format(",".join(["?"] * len(mem_ids))), tuple(mem_ids))
        obs_ids = [row[0] for row in self.sqlite_cursor.fetchall()]
        # 再插入新的关联
        data = [(old_obs_id, mem_id) for old_obs_id in obs_ids]
        data.append((obs_id, mem_id))
        self.sqlite_cursor.executemany("""
            INSERT INTO obs_memory_links (obs_id, mem_id)
            VALUES (?, ?)
        """, data)
        self.sqlite_conn.commit()

        self.count = self.count - len(mem_ids) + 1
        return mem_id
    
    # 检索记忆条目
    @log_entry
    def retrieve(
        self,
        obs: Dict,
        context: Dict[str, Any],
        top_k_for_0: int = 20,
        top_k_for_1: int = 50,
        top_k_for_2: Optional[int] = None,
        query_text: Optional[str] = None,
        vector: Optional[List] = None,
    ):
        """
        根据相似度检索记忆条目
        
        Returns:
            memories: 匹配记忆条目列表
        """
        if query_text is None and vector is None:
            # 0. 构建结构化查询
            # 将context和obs合并为一个文本
            extended_content = context.copy()
            extended_content.update({"obs": obs})
            try:
                extended_content_json = json.dumps(extended_content, ensure_ascii=False)
            except Exception as e:
                try:
                    extended_content_json = json.dumps(extended_content)
                except Exception as e:
                    print(f"Failed to vectorize content at step {self.step_id}: {e}")
                    return None, None, None

            approximate_max_tokens = max(int(self.embedding_model.max_context_tokens / 1000) * 1000, 1000)

            prompt = rag_prompt.format(INPUT_JSON=extended_content_json, MAX_TOKENS=approximate_max_tokens)

            try:
                query_text, _ = self.rag_summary_model.chat(prompt, max_tokens=approximate_max_tokens)
            except Exception as e:
                print(f"Failed to generate query text at step {self.step_id}: {e}")
                return None, None, None

        if vector is None:
            # 1. 向量化
            try:
                vector = self.embedding_model.embedding(query_text)
            except Exception as e:
                print(f"Failed to vectorize content at step {self.step_id}: {e}")
                return None, None, None

        # 2. 从 sqlite 中检索 ACTIVE 记忆条目
        self.sqlite_cursor.execute("""
            SELECT mem_id, key_level
            FROM memories
            WHERE status = 'ACTIVE'
        """)
        active_memories = self.sqlite_cursor.fetchall()
        active_memories = [(row[0], row[1]) for row in active_memories]
        # active_memories_dict = {row[0]: {
        #     "mem_id": row[0],
        #     "mem_type": row[1],
        #     "mem_content": row[2],
        #     "context": {
        #         "phase": row[3],
        #         "subgoal": row[4],
        #         "state_summary": row[5],
        #         "source_tool": row[6],
        #         "source_command": row[7],
        #     },
        #     "key": {
        #         "mark_key": bool(row[8]),
        #         "key_type": row[9],
        #         "key_level": row[10],
        #     },
        # } for row in active_memories}

        # 如果没有任何活跃记忆，直接返回空列表
        if not active_memories:
            return [], query_text, vector

        # 3. 从 Chroma 中检索记忆条目
        results = []
        
        # 3.1 检索 key_level=0 的记忆条目
        key_level_0_memory_ids = [row[0] for row in active_memories if row[1] == 0]
        if key_level_0_memory_ids:  # 修复：只有当列表非空时才查询
            actual_top_k_0 = min(top_k_for_0, len(key_level_0_memory_ids))  # 修复：防止n_results超过实际数量
            try:
                key_level_0_results = self.chroma_collection.query(
                    query_embeddings=[vector],
                    n_results=actual_top_k_0,
                    ids=key_level_0_memory_ids,
                    include=["distances"],
                )
                key_level_0_results = list(zip(key_level_0_results["ids"][0], key_level_0_results["distances"][0]))
                results.extend(key_level_0_results)
            except Exception as e:
                print(f"[Warning] Failed to query key_level=0 memories: {e}")

        # 3.2 检索 key_level=1 的记忆条目
        key_level_1_memory_ids = [row[0] for row in active_memories if row[1] == 1]
        if key_level_1_memory_ids:  # 修复：只有当列表非空时才查询
            actual_top_k_1 = min(top_k_for_1, len(key_level_1_memory_ids))  # 修复：防止n_results超过实际数量
            try:
                key_level_1_results = self.chroma_collection.query(
                    query_embeddings=[vector],
                    n_results=actual_top_k_1,
                    ids=key_level_1_memory_ids,
                    include=["distances"],
                )
                key_level_1_results = list(zip(key_level_1_results["ids"][0], key_level_1_results["distances"][0]))
                results.extend(key_level_1_results)
            except Exception as e:
                print(f"[Warning] Failed to query key_level=1 memories: {e}")

        # 3.3 检索 key_level=2 的记忆条目
        key_level_2_memory_ids = [row[0] for row in active_memories if row[1] == 2]
        if key_level_2_memory_ids:  # 修复：只有当列表非空时才查询
            top_k_for_2 = top_k_for_2 if top_k_for_2 else len(key_level_2_memory_ids)
            actual_top_k_2 = min(top_k_for_2, len(key_level_2_memory_ids))  # 修复：防止n_results超过实际数量
            try:
                key_level_2_results = self.chroma_collection.query(
                    query_embeddings=[vector],
                    n_results=actual_top_k_2,
                    ids=key_level_2_memory_ids,
                    include=["distances"],
                )
                key_level_2_results = list(zip(key_level_2_results["ids"][0], key_level_2_results["distances"][0]))
                results.extend(key_level_2_results)
            except Exception as e:
                print(f"[Warning] Failed to query key_level=2 memories: {e}")

        pprint(results)

        return results, query_text, vector
    
    # 取出记忆条目
    @log_entry
    def get_memories(
        self,
        mem_ids: List[str] | str,
        mode: str = "simple",
    ) -> List[Dict]:
        """
        根据记忆条目ID取出完整记忆条目 (不包括status, provenance等控制信息)
        Args:
            mode: 模式,
                simple表示取出(mem_id, mem_type, mem_content, context, key)
                middle表示取出(mem_id, mem_type, mem_content, context, key, further_explanation, token_number)
                verbose表示取出(mem_id, mem_type, mem_content, context, key, further_explanation, token_number, satus, provenance)

        Returns:
            memories: 记忆条目列表
        """
        if isinstance(mem_ids, str):
            mem_ids = [mem_ids]
        if not mem_ids:
            return []
        if mode == "simple":
            self.sqlite_cursor.execute("""
                SELECT mem_id, mem_type, content, phase, subgoal, state_summary, source_tool, source_command, mark_key, key_type, key_level
                FROM memories
                WHERE mem_id IN ({}) AND status = 'ACTIVE'
            """.format(",".join(["?"] * len(mem_ids))), tuple(mem_ids))
            memories = self.sqlite_cursor.fetchall()
            memory_list = [{
                "mem_id": row[0],
                "mem_type": row[1],
                "mem_content": row[2],
                "context": {
                    "phase": row[3],
                    "subgoal": row[4],
                    "state_summary": row[5],
                    "source_tool": row[6],
                    "source_command": row[7],
                },
                "key": {
                    "mark_key": bool(row[8]),
                    "key_type": row[9],
                    "key_level": row[10],
                },
            } for row in memories]
        elif mode == "middle":
            self.sqlite_cursor.execute("""
                SELECT mem_id, mem_type, content, phase, subgoal, state_summary, source_tool, source_command, mark_key, key_type, key_level, further_explanation, token_number
                FROM memories
                WHERE mem_id IN ({}) AND status = 'ACTIVE'
            """.format(",".join(["?"] * len(mem_ids))), tuple(mem_ids))
            memories = self.sqlite_cursor.fetchall()
            memory_list = [{
                "mem_id": row[0],
                "mem_type": row[1],
                "mem_content": row[2],
                "context": {
                    "phase": row[3],
                    "subgoal": row[4],
                    "state_summary": row[5],
                    "source_tool": row[6],
                    "source_command": row[7],
                },
                "key": {
                    "mark_key": bool(row[8]),
                    "key_type": row[9],
                    "key_level": row[10],
                },
                "further_explanation": json.loads(row[11]) if row[11] else None,
                "token_number": row[12],
            } for row in memories]
        elif mode == "verbose":
            # provenance的格式:
            # - created_at_step
            # - updated_at_step
            # - created_at: 创建时间
            # - obs_refs: 所有关联的obs
            # - supersedes_mem_ids: 被这个条目替代的条目id的列表
            self.sqlite_cursor.execute("""
                SELECT mem_id, mem_type, content, phase, subgoal, state_summary, source_tool, source_command, mark_key, key_type, key_level, further_explanation, token_number, status, created_at_step_id, updated_at_step_id, created_at, current_obs_id
                FROM memories
                WHERE mem_id IN ({})
            """.format(",".join(["?"] * len(mem_ids))), tuple(mem_ids))
            memories = self.sqlite_cursor.fetchall()
            memory_list = [{
                "mem_id": row[0],
                "mem_type": row[1],
                "mem_content": row[2],
                "context": {
                    "phase": row[3],
                    "subgoal": row[4],
                    "state_summary": row[5],
                    "source_tool": row[6],
                    "source_command": row[7],
                },
                "key": {
                    "mark_key": bool(row[8]),
                    "key_type": row[9],
                    "key_level": row[10],
                },
                "further_explanation": json.loads(row[11]) if row[11] else None,
                "token_number": row[12],
                "status": row[13],
                "provenance": {
                    "created_at_step": row[14],
                    "updated_at_step": row[15],
                    "created_at": row[16],
                    "current_obs_id": row[17],
                },
            } for row in memories]
            for memory in memory_list:
                # obs_refs需要用obs_memory_links表查出来
                self.sqlite_cursor.execute("""
                    SELECT obs_id FROM obs_memory_links WHERE mem_id = ?
                """, (memory["mem_id"],))
                memory["provenance"]["obs_refs"] = [row[0] for row in self.sqlite_cursor.fetchall()]
                # supersedes_mem_ids需要用memories表的superseded_by字段反向查找
                self.sqlite_cursor.execute("""
                    SELECT mem_id FROM memories WHERE superseded_by = ?
                """, (memory["mem_id"],))
                memory["provenance"]["supersedes_mem_ids"] = [row[0] for row in self.sqlite_cursor.fetchall()]
        else:
            raise ValueError("Invalid mode")
        # 按 mem_ids 顺序返回，保持 retrieve() 的排序
        mem_by_id = {m["mem_id"]: m for m in memory_list}
        return [mem_by_id[mid] for mid in mem_ids if mid in mem_by_id]
    
    # 检查输入的一系列mem_ids是否存在于数据库中
    @log_entry
    def check_mem_ids(
        self,
        mem_ids: List[str],
    ) -> List[bool]:
        """
        检查输入的一系列mem_ids是否存在于数据库中
        适用于：检查输入的一系列mem_ids是否存在于数据库中
        
        Returns:
            exist_flags: 存在与否的列表
        """
        if not mem_ids:
            return []
        self.sqlite_cursor.execute("""
            SELECT mem_id FROM memories WHERE mem_id IN ({})
        """.format(",".join(["?"] * len(mem_ids))), tuple(mem_ids))
        exist_mem_ids = [row[0] for row in self.sqlite_cursor.fetchall()]
        exist_flags = [mem_id in exist_mem_ids for mem_id in mem_ids]
        return exist_flags


class MemoryDebugger:
    def __init__(self, db_dir: str):
        self.db_path = Path(db_dir)
        self.sqlite_file = self.db_path / "sqlite.db"
        self.chroma_dir = self.db_path / "chroma"

        if not self.sqlite_file.exists():
            print(f"Error: {self.sqlite_file} not found")
            sys.exit(1)

        self.conn = sqlite3.connect(self.sqlite_file)
        self.cursor = self.conn.cursor()

        self.chroma_collection = None
        if chromadb and self.chroma_dir.exists():
            try:
                client = chromadb.PersistentClient(path=str(self.chroma_dir))
                self.chroma_collection = client.get_collection(name="memories")
                print(f"Loaded: {db_dir}")
            except Exception as e:
                print(f"Chroma load failed: {e}")
        else:
            print(f"SQLite only: {db_dir}")

    def close(self):
        self.conn.close()

    def sql(self, query: str):
        """执行SQL，长文本字段放最后"""
        try:
            self.cursor.execute(query)
            if query.strip().upper().startswith(("SELECT", "PRAGMA")):
                rows = self.cursor.fetchall()
                if not rows:
                    print("(empty)")
                    return

                # 获取列名并识别长文本字段（放最后）
                col_names = [desc[0] for desc in self.cursor.description]
                long_keywords = ['content', 'doc', 'text', 'source', 'explanation', 'summary', 'command', 'subgoal']

                short_indices = []
                long_indices = []
                for i, name in enumerate(col_names):
                    if any(kw in name.lower() for kw in long_keywords):
                        long_indices.append(i)
                    else:
                        short_indices.append(i)

                # 逐行打印
                for row_idx, row in enumerate(rows):
                    parts = []
                    for i in short_indices:
                        parts.append(f"{col_names[i]}={repr(row[i])}")
                    for i in long_indices:
                        parts.append(f"{col_names[i]}={repr(row[i])}")
                    print(f"[{row_idx}] " + " | ".join(parts))

                print(f"Total: {len(rows)} rows")
            else:
                self.conn.commit()
                print(f"Done, rows affected: {self.cursor.rowcount}")
        except Exception as e:
            print(f"Error: {e}")

    def obs(self, obs_id: str):
        """查看obs_source文件完整内容"""
        try:
            self.cursor.execute("SELECT obs_source FROM observations WHERE obs_id = ?", (obs_id,))
            row = self.cursor.fetchone()
            if not row:
                print(f"No such obs_id: {obs_id}")
                return

            file_path = Path(row[0]).resolve()

            if not file_path.exists():
                print(f"File not found: {file_path}")
                return

            content = file_path.read_text(encoding='utf-8', errors='replace')
            print(f"=== {file_path} ({len(content)} chars) ===")
            print(content)  # 完整输出，不截断
            print("=== End ===")

        except Exception as e:
            print(f"Error: {e}")

    def chroma_list(self, n: int = 5):
        """列出Chroma条目，ID在前内容在后"""
        if not self.chroma_collection:
            print("Chroma not available")
            return
        try:
            result = self.chroma_collection.peek(limit=n)
            for i, (doc_id, doc) in enumerate(zip(result['ids'], result['documents'])):
                print(f"[{i}] ID={repr(doc_id)} | Doc={repr(doc)}")
        except Exception as e:
            print(f"Error: {e}")

    def chroma_get(self, mem_id: str):
        """获取特定Chroma条目，metadata在前document在后"""
        if not self.chroma_collection:
            print("Chroma not available")
            return
        try:
            result = self.chroma_collection.get(ids=[mem_id], include=['documents', 'metadatas'])
            if not result['ids']:
                print(f"Not found: {mem_id}")
                return

            print(f"ID: {repr(result['ids'][0])}")
            print(f"Metadata: {repr(result['metadatas'][0])}")
            print(f"Document: {repr(result['documents'][0] if result['documents'] else None)}")
        except Exception as e:
            print(f"Error: {e}")


def print_help():
    print("Commands:")
    print("  sql <query>        - Execute SQL (long fields shown last)")
    print("  obs <id>           - View obs_source file content (full)")
    print("  chroma list [n]    - List Chroma entries")
    print("  chroma get <id>    - Get specific Chroma entry")
    print("  tables             - Show tables")
    print("  schema <table>     - Show table schema")
    print("  help/?             - Show this help")
    print("  exit               - Exit")


def main():
    if len(sys.argv) < 2:
        print(f"Usage: python {sys.argv[0]} <database_directory>")
        sys.exit(1)

    dbg = MemoryDebugger(sys.argv[1])
    print_help()

    while True:
        try:
            cmd = input("\n> ").strip()
            if not cmd:
                continue
            if cmd == "exit":
                break

            parts = cmd.split(maxsplit=1)
            op, arg = parts[0], parts[1] if len(parts) > 1 else ""

            if op in ("help", "?"):
                print_help()
            elif op == "sql":
                dbg.sql(arg)
            elif op == "obs":
                dbg.obs(arg.split()[0])
            elif op == "chroma":
                subparts = arg.split(maxsplit=1)
                if subparts[0] == "list":
                    n = int(subparts[1]) if len(subparts) > 1 else 5
                    dbg.chroma_list(n)
                elif subparts[0] == "get" and len(subparts) > 1:
                    dbg.chroma_get(subparts[1])
            elif op == "tables":
                dbg.sql("SELECT name FROM sqlite_master WHERE type='table'")
            elif op == "schema":
                dbg.sql(f"PRAGMA table_info({arg})")
            else:
                print("Unknown command, type 'help' for help")

        except KeyboardInterrupt:
            break
        except Exception as e:
            print(f"Error: {e}")

    dbg.close()


if __name__ == "__main__":
    main()

# if __name__ == "__main__":
#     # client = chromadb.PersistentClient(path="./database/2026-02-08_15-08-28/chroma")
#     # collection = client.get_or_create_collection(name="memories")
#     # # pprint(collection.peek())
#     #
#     # embedding_model = EmbeddingModel()
#     # embedding = embedding_model.embedding("nmap")
#     # print(embedding[:5])
#     # results = collection.query(
#     #     ids=['mem_01KGY1CH5TDGG70E5M9SQBNWWT', 'mem_01KGY1AXKGQZ9TDBJD2SSQCVGJ'],
#     #     query_embeddings=[embedding],
#     #     n_results=5,
#     # )
#     # pprint(results)
#     # results = list(zip(results["ids"][0], results["distances"][0]))
#     # pprint(results)
#
#     conn = sqlite3.connect("./database/2026-02-08_15-08-28/sqlite.db")
#     # res = conn.execute("""
#     #     SELECT * FROM steps
#     # """)
#     # print("steps")
#     # pprint(res.fetchall())
#     # print()
#
#     # res = conn.execute("""
#     #     SELECT * FROM observations
#     # """)
#     # print("observations")
#     # pprint(res.fetchall())
#     # print()
#     #
#     res = conn.execute("""
#         SELECT * FROM memories
#     """)
#     print("memories")
#     pprint(res.fetchall())
#     print()
#     #
#     # res = conn.execute("""
#     #     SELECT * FROM obs_memory_links
#     # """)
#     # print("obs_memory_links")
#     # pprint(res.fetchall())
#     # print()











    
