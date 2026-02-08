from typing import List, Dict, Tuple, Callable, Optional, Any, Union
from datetime import datetime
# from sklearn.metrics.pairwise import cosine_similarity
import numpy as np
import json
from pprint import pprint

from .model import EmbeddingModel

# 暂时是一个手工搭建的极简的方案
# 后续可以使用成熟的解决方案: 1. 借鉴Memroy-R1的代码; 2. 向量数据库Chroma; 3. PostgreSQL数据库

class MemoryBank:
    """简单向量记忆库：RAG + 增删改查"""
    def __init__(
            self,
            step_id: int = 0,
            add_meta_to_content: bool = False,
        ):
        self.memories: List[Dict] = []  # 每条: {id, content, embedding, timestamp}
        self.embedding_model = EmbeddingModel(model="qwen-text-embedding-v4")
        self.step_id = step_id
        self.add_meta_to_content = add_meta_to_content

        # 日志文件
        # 文件名打一个时间戳吧
        self.log_file = f"memory_bank_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        with open(self.log_file, "w", encoding="utf-8") as f:
            f.write(f"MemoryBank created at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    def __repr__(self):
        return f"<MemoryBank: {len(self.memories)} memories>"

    def __len__(self):
        return len(self.memories)

    def __getitem__(self, idx):
        return self.memories[idx]

    def __iter__(self):
        for mem in self.memories:
            yield mem

    # 一个IDs属性输出所有的ID
    @property
    def ids(self):
        return [m["id"] for m in self.memories]

    # 导出所有记忆内容
    def export_memory(
        self,
        file_path: Optional[str] = None,
        export_embedding: bool = False,
    ):
        if file_path is None:
            file_path = f"memory_bank_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            if export_embedding:
                json.dump(self.memories, f, ensure_ascii=False, indent=4)
            else:
                memories = self.memories.copy()
                for m in memories:
                    m.pop("embedding")
                json.dump(memories, f, ensure_ascii=False, indent=4)
        print(f"MemoryBank exported to {file_path}")

    def retrieve(
            self,
            query: str,
            top_k: Optional[int] = 5,
            similarity_func: Optional[Callable] = None
        ):
        """检索相关记忆，返回前top_k条"""
        if not self.memories:
            return [], None
        if similarity_func is None:
            similarity_func = self.euclidean_distance
        # 1. 计算查询向量
        query_embedding = self.embedding_model.embedding(query)
        # 2. 构建记忆向量矩阵
        memory_embeddings = [m["embedding"] for m in self.memories]
        # 3. 计算相似度
        scores, _, indices = similarity_func(memory_embeddings, query_embedding)
        # 4. 排序并返回
        top_k = min(top_k, len(self.memories))
        results = [self.memories[i] for i in indices]
        # pprint(results)
        # 去掉不"active"的结果
        results = [r for r in results if r['metadata']['status']['state'] == 'ACTIVE']
        # 取出前top_k
        results = results[:top_k]
        return results, scores[:top_k]

    def add(
            self,
            content: str | dict | list,
            metadata: dict | list = None,
            pentest_info: dict | list = None,
        ) -> int | list[int]:
        """添加记忆，返回memory_id"""

        if not isinstance(content, list):
            content = [content]

        if metadata is None:
            metadata = {}
        if not isinstance(metadata, list):
            metadata = [metadata] * len(content)
        for m in metadata:
            m.update({
                "created_at_step": self.step_id,
                "last_updated_step": self.step_id,
            })

        if pentest_info is None:
            pentest_info = {}
        if not isinstance(pentest_info, list):
            pentest_info = [pentest_info] * len(content)

        tmp_contents = []
        for idx, item in enumerate(content):
            if self.add_meta_to_content:
                m = metadata[idx].copy()
                m.update(pentest_info[idx])
                m["content"] = item
                item_str = json.dumps(m, ensure_ascii=False)
            else:
                if isinstance(item, dict):
                    item_str = json.dumps(item, ensure_ascii=False)
                elif isinstance(item, str):
                    item_str = item
            tmp_contents.append(item_str)

        embedding = self.embedding_model.embedding(tmp_contents)

        for idx, c in enumerate(content):
            memory_id = self.memories[-1]["id"] + 1 if self.memories else 0
            if self.add_meta_to_content:
                content_dict = metadata[idx].copy()
                content_dict.update(pentest_info[idx])
                content_dict["content"] = c
                content_ = json.dumps(content_dict, ensure_ascii=False)
            else:
                content_ = c

            if isinstance(c, dict):
                raw_content = json.dumps(c, ensure_ascii=False)
            elif isinstance(c, str):
                raw_content = c

            new_memory = {
                "id": memory_id,
                "content": content_,
                "raw_content": raw_content,
                "embedding": embedding[idx],
                "timestamp": datetime.now().isoformat(),
                "metadata": metadata[idx],
                "pentest_info": pentest_info[idx],
            }

            self.memories.append(new_memory)

            with open(self.log_file, "a", encoding="utf-8") as f:
                # json格式记录新添加的记忆
                # 不用记录embedding，太大了
                # 先删去embedding字段和content字段，再json.dumps
                log_memory = new_memory.copy()
                log_memory.pop("embedding")
                log_memory.pop("content")
                f.write(f"Memory added: {json.dumps(log_memory, ensure_ascii=False)}\n")

        if len(content) == 1:
            return self.memories[-1]["id"]
        else:
            return [m["id"] for m in self.memories[-len(content):]]

    def update(
        self,
        memory_id: int | list[int],
        content: str | dict | list,
        metadata: dict | list = None,
        pentest_info: dict | list = None,
    ) -> None:
        """更新记忆"""
        if not isinstance(memory_id, list):
            memory_id = [memory_id]

        if not isinstance(content, list):
            content = [content]

        if metadata is None:
            metadata = {}
        if not isinstance(metadata, list):
            metadata = [metadata] * len(content)
        for m in metadata:
            m.update({
                "last_updated_step": self.step_id,
            })

        if pentest_info is None:
            pentest_info = {}
        if not isinstance(pentest_info, list):
            pentest_info = [pentest_info] * len(content)

        # 2. 查找目标并准备embedding内容（先查找，再批量embedding）
        target_memories = []
        contents_for_embedding = []

        for idx, mid in enumerate(memory_id):
            # 查找记忆
            target_mem = next((mem for mem in self.memories if mem["id"] == mid), None)
            if target_mem is None:
                raise ValueError(f"Memory ID {mid} not found")

            # 准备更新后的metadata（保留created_at_step）
            old_metadata = target_mem["metadata"]
            new_metadata = old_metadata.copy()
            new_metadata.update(metadata[idx])

            # 准备更新后的pentest_info（完全覆盖）
            new_pentest_info = pentest_info[idx]

            # 准备embedding内容
            c = content[idx]
            if self.add_meta_to_content:
                content_dict = new_metadata.copy()
                content_dict.update(new_pentest_info)
                content_dict["content"] = c
                content_for_embedding = json.dumps(content_dict, ensure_ascii=False)
            else:
                content_for_embedding = json.dumps(c, ensure_ascii=False) if isinstance(c, dict) else c

            target_memories.append((target_mem, new_metadata, new_pentest_info))
            contents_for_embedding.append(content_for_embedding)

        # 3. 批量embedding（核心优化）
        embeddings = self.embedding_model.embedding(contents_for_embedding)

        # 4. 批量更新记忆
        for idx, (target_mem, new_metadata, new_pentest_info) in enumerate(target_memories):
            c = content[idx]
            embedding = embeddings[idx]

            # 准备raw_content
            raw_content = json.dumps(c, ensure_ascii=False) if isinstance(c, dict) else c

            # 准备content字段
            if self.add_meta_to_content:
                content_dict = new_metadata.copy()
                content_dict.update(new_pentest_info)
                content_dict["content"] = c
                content_ = json.dumps(content_dict, ensure_ascii=False)
            else:
                content_ = c

            # 更新所有字段
            target_mem.update({
                "content": content_,
                "raw_content": raw_content,
                "embedding": embedding,
                "timestamp": datetime.now().isoformat(),
                "metadata": new_metadata,
                "pentest_info": new_pentest_info  # 更新pentest_info字段
            })

            # 日志记录
            with open(self.log_file, "a", encoding="utf-8") as f:
                log_memory = {k: v for k, v in target_mem.items() if k not in ("embedding", "content")}
                f.write(f"Memory updated: {json.dumps(log_memory, ensure_ascii=False)}\n")


    def delete(
        self,
        memory_id: int | list[int]
    ) -> None:
        """删除记忆"""
        if not isinstance(memory_id, list):
            memory_id = [memory_id]

        # 检查ID是否存在
        try:
            ids = [m["id"] for m in self.memories]
            not_found = [mid for mid in memory_id if mid not in ids]
            if not_found:
                raise ValueError(f"Memory IDs {not_found} not found")
        except Exception as e:
            print(f"{e}")
            return

        self.memories = [m for m in self.memories if m["id"] not in memory_id]
        with open(self.log_file, "a", encoding="utf-8") as f:
            for mid in memory_id:
                f.write(f"Memory deleted: {mid}\n")

    @staticmethod
    def cosine_similarity(
            key: np.ndarray | list[list],
            query: np.ndarray | list,
        ) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """
        余弦相似度: (A·B) / (||A|| × ||B||)
        返回: (scores_topk, indices_topk)
        """
        key = np.array(key)
        query = np.array(query)

        # 1. 计算点积: (n_vectors,)
        dot_products = np.dot(key, query)

        # 2. 计算查询向量模长
        query_norm = np.linalg.norm(query)

        # 3. 计算key矩阵每行的模长 → (n_vectors,)
        key_norms = np.linalg.norm(key, axis=1)

        # 4. 计算分母：逐元素相乘（key_norms[i] * query_norm）
        denominators = key_norms * query_norm

        # 5. 防止除零
        denominators = np.maximum(denominators, 1e-8)

        # 6. 计算余弦相似度
        scores = dot_products / denominators

        # 7. 获取top_k（降序）
        indices = np.argsort(-scores)

        # 8. 将相似度归一化到[0,1]
        norm_scores = (scores + 1) / 2

        return norm_scores[indices].tolist(), scores[indices].tolist(), indices.tolist()

    @staticmethod
    def euclidean_distance(
            key: np.ndarray | list[list],
            query: np.ndarray | list,
        ) -> Tuple[np.ndarray, np.ndarray]:
        """
        欧氏距离: √Σ(Ai - Bi)²
        返回: (scores_topk, indices_topk)
        """
        key = np.array(key)
        query = np.array(query)

        # 1. 计算平方差: (n_vectors, dim)
        diff = key - query

        # 2. 计算距离: (n_vectors,)
        distances = np.sqrt(np.sum(diff ** 2, axis=1))

        # 3. 获取top_k（升序）
        indices = np.argsort(distances)

        # 4. 将相似度归一化到[0,1]
        max_dist = np.max(distances) if np.max(distances) > 0 else 1e-8
        norm_scores = 1 - (distances / max_dist)

        return norm_scores[indices].tolist(), distances[indices].tolist(), indices.tolist()

    @staticmethod
    def dot_product(
            key: np.ndarray | list[list],
            query: np.ndarray | list,
        ) -> Tuple[np.ndarray, np.ndarray]:
        """
        内积相似度: A·B（无归一化）
        返回: (scores_topk, indices_topk)
        """
        key = np.array(key)
        query = np.array(query)

        # 1. 计算点积: (n_vectors,)
        scores = np.dot(key, query)

        # 2. 获取top_k（降序）
        indices = np.argsort(-scores)

        # 3. 相似度归一化到[0,1]
        max_score = np.max(scores) if np.max(scores) > 0 else 1e-8
        norm_scores = scores / max_score

        return norm_scores[indices].tolist(), scores[indices].tolist(), indices.tolist()

    @staticmethod
    def manhattan_distance(
            key: np.ndarray | list[list],
            query: np.ndarray | list,
        ) -> Tuple[np.ndarray, np.ndarray]:
        """
        曼哈顿距离: Σ|Ai - Bi|
        返回: (scores_topk, indices_topk)
        """
        key = np.array(key)
        query = np.array(query)

        # 1. 计算绝对差值: (n_vectors, dim)
        diff = np.abs(key - query)

        # 2. 计算距离: (n_vectors,)
        distances = np.sum(diff, axis=1)

        # 3. 获取top_k
        indices = np.argsort(distances)

        # 4. 将相似度归一化到[0,1]
        max_dist = np.max(distances) if np.max(distances) > 0 else 1e-8
        norm_scores = 1 - (distances / max_dist)

        return norm_scores[indices].tolist(), distances[indices].tolist(), indices.tolist()

if __name__ == "__main__":
    memory_bank = MemoryBank()
    print(memory_bank)

    human_inputs = []
    while (human_input := input("Add memory (or 'exit'): ")) != "exit":
        if human_input.strip():
            human_inputs.append(human_input.strip())

    print(f"memories: {memory_bank.ids}")

    memory_ids = memory_bank.add(human_inputs)
    print(f"Added {len(memory_ids)} memories: {memory_bank.ids}")

    # 随机删掉三条, 用numpy的随机数
    delete_ids = np.random.choice(memory_bank.ids, size=min(3, len(memory_ids)), replace=False).tolist()
    memory_bank.delete(delete_ids)
    print(f"Deleted {len(delete_ids)} memories: {delete_ids}")
    print(f"Memory bank now has {len(memory_bank)} memories: {memory_bank.ids}")

    # 随机更新三条属性, 用numpy的随机数
    update_ids = np.random.choice(memory_bank.ids, size=min(3, len(memory_ids)), replace=False).tolist()
    update_contents = [f"Updated {i}" for i in range(len(update_ids))]
    update_metas = [{"key": f"value{i}"} for i in range(len(update_ids))]
    memory_bank.update(update_ids, update_contents, update_metas)
    print(f"Updated {len(update_ids)} memories: {update_ids}")
    print(f"Memory bank now has {len(memory_bank)} memories: {memory_bank.ids}")


    while (human_input := input("Query memory (or 'exit'): ")) != "exit":
        if human_input.strip():
            results, scores = memory_bank.retrieve(human_input.strip(), top_k=10)
            print(f"Top memories':")
            # pprint(results)
            for mem, score in zip(results, scores):
                print(f"- ID {mem['id']}: {mem['content']}, score: {score:.4f}")