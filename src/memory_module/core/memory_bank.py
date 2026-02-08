import os
from pathlib import Path
from typing import *
from datetime import datetime
import json
from pprint import pprint


import chromadb
from chromadb import Documents, EmbeddingFunction, Embeddings
import sqlite3
import numpy as np
from ulid import ULID

from memory_module.utils.model import EmbeddingModel
from memory_module.debug import log_entry

# 一个也不算太正式的正式方案: 使用ChromaDB管理向量数据库, 使用sqlite管理元数据

class MemoryBank:
    """向量记忆库: RAG + 记忆操作"""
    @log_entry
    def __init__(
        self,
        step_id: int = 0,
        db_dir: Optional[str] = None,
    ):
        # 一个表示已存入记忆条目个数的计数器
        self.count = 0
        self.step_id = step_id
        self.embedding_model = EmbeddingModel(model="qwen-text-embedding-v4")

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
                    step_id TEXT PRIMARY KEY,
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
                    step_id TEXT NOT NULL,
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
        # created_at_step_id: 创建时步骤ID
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
                    created_at_step_id TEXT NOT NULL,
                    updated_at_step_id TEXT NOT NULL,
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
    ) -> str:
        """
        处理新的step
        适用于：渗透测试执行阶段，记录执行上下文
        
        Returns:
            step_id: 新创建的step ID
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
    
    # S1_SUMMARIZE_ADD: 摘要后添加新记忆
    @log_entry
    def s1_summarize_add(
        self,
        obs_id: str,
        content: str,
        context: Dict[str, Any],
        key: Dict[str, Any],
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
        self.sqlite_cursor.execute("""
            INSERT INTO memories (mem_id, mem_type, content, phase, subgoal, state_summary, source_tool, source_command, mark_key, key_type, key_level, created_at_step_id, updated_at_step_id, superseded_by, current_obs_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (mem_id, mem_type, content, context.get("phase", ""), context.get("subgoal", ""), context.get("state_summary", ""), context.get("source_tool", ""), context.get("source_command", ""), int(key.get("mark_key", False)), key.get("key_type", ""), key.get("key_level", 0), self.step_id, self.step_id, None, obs_id))
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
        self.sqlite_cursor.execute("""
            INSERT INTO memories (mem_id, mem_type, content, phase, subgoal, state_summary, source_tool, source_command, mark_key, key_type, key_level, created_at_step_id, updated_at_step_id, superseded_by, current_obs_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (mem_id, mem_type, content, context.get("phase", ""), context.get("subgoal", ""), context.get("state_summary", ""), context.get("source_tool", ""), context.get("source_command", ""), int(key.get("mark_key", False)), key.get("key_type", ""), key.get("key_level", 0), self.step_id, self.step_id, None, obs_id))
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
        # 检查 key 参数
        if key.get("mark_key", False):
            key["key_type"] = None
            key["key_level"] = 0
        self.sqlite_cursor.execute("""
            INSERT INTO memories (mem_id, mem_type, content, phase, subgoal, state_summary, source_tool, source_command, mark_key, key_type, key_level, created_at_step_id, updated_at_step_id, superseded_by, current_obs_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (mem_id, mem_type, content, context.get("phase", ""), context.get("subgoal", ""), context.get("state_summary", ""), context.get("source_tool", ""), context.get("source_command", ""), int(key.get("mark_key", False)), key.get("key_type", ""), key.get("key_level", 0), self.step_id, self.step_id, None, obs_id))
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
    ) -> List | None:
        """
        检索记忆条目
        适用于：检索记忆条目
        
        Returns:
            memories: 匹配记忆条目列表
        """
        # 1. 向量化
        # 将context和obs合并为一个文本
        extended_content = context.copy()
        extended_content.update({"obs": obs})
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
        # 2. 从 sqlite 中检索 ACTIVE 记忆条目
        self.sqlite_cursor.execute("""
            SELECT mem_id, content, phase, subgoal, state_summary, source_tool, source_command, mark_key, key_type, key_level, created_at_step_id, updated_at_step_id, superseded_by, current_obs_id, status
            FROM memories
            WHERE status = 'ACTIVE'
        """)
        active_memories = self.sqlite_cursor.fetchall()
        # 修复索引错误：row[1]是content，不是mem_type
        active_memories_dict = {row[0]: {
            "mem_id": row[0],
            "mem_content": row[1],  # 修复：row[1]是content
            "context": {
                "phase": row[2],           # 修复：row[2]是phase
                "subgoal": row[3],         # 修复：row[3]是subgoal
                "state_summary": row[4],   # 修复：row[4]是state_summary
                "source_tool": row[5],     # 修复：row[5]是source_tool
                "source_command": row[6],  # 修复：row[6]是source_command
            },
            "key": {
                "mark_key": bool(row[7]),  # 修复：row[7]是mark_key
                "key_type": row[8],        # 修复：row[8]是key_type
                "key_level": row[9],       # 修复：row[9]是key_level
            },
        } for row in active_memories}

        # 如果没有任何活跃记忆，直接返回空列表
        if not active_memories:
            return []

        # 3. 从 Chroma 中检索记忆条目
        results = []
        
        # 3.1 检索 key_level=0 的记忆条目
        key_level_0_memory_ids = [row[0] for row in active_memories if row[9] == 0]  # 修复：row[9]是key_level
        if key_level_0_memory_ids:  # 修复：只有当列表非空时才查询
            actual_top_k_0 = min(top_k_for_0, len(key_level_0_memory_ids))  # 修复：防止n_results超过实际数量
            try:
                # ChromaDB的query方法：查询整个集合，然后手动过滤
                all_results = self.chroma_collection.query(
                    query_embeddings=[vector],
                    n_results=min(top_k_for_0 * 3, self.chroma_collection.count()),  # 多取一些，后面过滤
                    include=["distances"],
                )
                # 手动过滤出key_level=0的记忆
                key_level_0_results = [
                    (mem_id, dist) 
                    for mem_id, dist in zip(all_results["ids"][0], all_results["distances"][0])
                    if mem_id in key_level_0_memory_ids
                ][:actual_top_k_0]  # 只取top_k个
                
                key_level_0_results = [[active_memories_dict[mem_id], dist] for mem_id, dist in key_level_0_results if mem_id in active_memories_dict]
                results.extend(key_level_0_results)
            except Exception as e:
                print(f"[Warning] Failed to query key_level=0 memories: {e}")

        # 3.2 检索 key_level=1 的记忆条目
        key_level_1_memory_ids = [row[0] for row in active_memories if row[9] == 1]  # 修复：row[9]是key_level
        if key_level_1_memory_ids:  # 修复：只有当列表非空时才查询
            actual_top_k_1 = min(top_k_for_1, len(key_level_1_memory_ids))  # 修复：防止n_results超过实际数量
            try:
                all_results = self.chroma_collection.query(
                    query_embeddings=[vector],
                    n_results=min(top_k_for_1 * 3, self.chroma_collection.count()),
                    include=["distances"],
                )
                # 手动过滤出key_level=1的记忆
                key_level_1_results = [
                    (mem_id, dist) 
                    for mem_id, dist in zip(all_results["ids"][0], all_results["distances"][0])
                    if mem_id in key_level_1_memory_ids
                ][:actual_top_k_1]
                
                key_level_1_results = [[active_memories_dict[mem_id], dist] for mem_id, dist in key_level_1_results if mem_id in active_memories_dict]
                results.extend(key_level_1_results)
            except Exception as e:
                print(f"[Warning] Failed to query key_level=1 memories: {e}")

        # 3.3 检索 key_level=2 的记忆条目
        key_level_2_memory_ids = [row[0] for row in active_memories if row[9] == 2]  # 修复：row[9]是key_level
        if key_level_2_memory_ids:  # 修复：只有当列表非空时才查询
            top_k_for_2 = top_k_for_2 if top_k_for_2 else len(key_level_2_memory_ids)
            top_k_for_2 = max(1, top_k_for_2)  # 修复：确保至少为1
            actual_top_k_2 = min(top_k_for_2, len(key_level_2_memory_ids))  # 修复：防止n_results超过实际数量
            try:
                all_results = self.chroma_collection.query(
                    query_embeddings=[vector],
                    n_results=min(top_k_for_2 * 3, self.chroma_collection.count()),
                    include=["distances"],
                )
                # 手动过滤出key_level=2的记忆
                key_level_2_results = [
                    (mem_id, dist) 
                    for mem_id, dist in zip(all_results["ids"][0], all_results["distances"][0])
                    if mem_id in key_level_2_memory_ids
                ][:actual_top_k_2]
                
                key_level_2_results = [[active_memories_dict[mem_id], dist] for mem_id, dist in key_level_2_results if mem_id in active_memories_dict]
                results.extend(key_level_2_results)
            except Exception as e:
                print(f"[Warning] Failed to query key_level=2 memories: {e}")

        pprint(results)

        return results
    
    # 取出记忆条目
    @log_entry
    def get_memories(
        self,
        mem_ids: List[str] | str,
    ) -> List[Dict]:
        """
        取出记忆条目
        适用于：取出记忆条目
        
        Returns:
            memories: 记忆条目列表
        """
        if isinstance(mem_ids, str):
            mem_ids = [mem_ids]
        self.sqlite_cursor.execute("""
            SELECT mem_id, mem_type, content, phase, subgoal, state_summary, source_tool, source_command, mark_key, key_type, key_level, created_at_step_id, updated_at_step_id, superseded_by, current_obs_id, status
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
        return memory_list
    
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
        self.sqlite_cursor.execute("""
            SELECT mem_id FROM memories WHERE mem_id IN ({})
        """.format(",".join(["?"] * len(mem_ids))), tuple(mem_ids))
        exist_mem_ids = [row[0] for row in self.sqlite_cursor.fetchall()]
        exist_flags = [mem_id in exist_mem_ids for mem_id in mem_ids]
        return exist_flags

if __name__ == "__main__":
    # client = chromadb.PersistentClient(path="./database/2026-02-08_15-08-28/chroma")
    # collection = client.get_or_create_collection(name="memories")
    # # pprint(collection.peek())
    #
    # embedding_model = EmbeddingModel()
    # embedding = embedding_model.embedding("nmap")
    # print(embedding[:5])
    # results = collection.query(
    #     ids=['mem_01KGY1CH5TDGG70E5M9SQBNWWT', 'mem_01KGY1AXKGQZ9TDBJD2SSQCVGJ'],
    #     query_embeddings=[embedding],
    #     n_results=5,
    # )
    # pprint(results)
    # results = list(zip(results["ids"][0], results["distances"][0]))
    # pprint(results)

    conn = sqlite3.connect("./database/2026-02-08_15-08-28/sqlite.db")
    # res = conn.execute("""
    #     SELECT * FROM steps
    # """)
    # print("steps")
    # pprint(res.fetchall())
    # print()

    # res = conn.execute("""
    #     SELECT * FROM observations
    # """)
    # print("observations")
    # pprint(res.fetchall())
    # print()
    #
    res = conn.execute("""
        SELECT * FROM memories
    """)
    print("memories")
    pprint(res.fetchall())
    print()
    #
    # res = conn.execute("""
    #     SELECT * FROM obs_memory_links
    # """)
    # print("obs_memory_links")
    # pprint(res.fetchall())
    # print()











    
