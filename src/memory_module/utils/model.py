"""
LLM模型封装类
提供统一的聊天生成和embedding接口，支持不同模型配置
"""

from typing import *
from openai import OpenAI
import numpy as np
import json
from pprint import pprint
from memory_module.config.llm_config import LLMConfig

class ChatModel:
    """LLM模型统一接口类"""
    def __init__(
        self,
        model: str = "qwen-max", 
        temperature: Optional[float] = None,
        top_p: Optional[int] = None,
        max_tokens: Optional[int] = None,
        system_prompt: str = "You are a helpful assistant.",
        config_file_path: Optional[str] = None,
        **kwargs
    ):
        """
        初始化模型实例
        """
        self.model = model
        self.config_object = LLMConfig(model=model, type='chat', **kwargs)
        self.config = self.config_object.config

        # 如果self.config中存在temperature, top_p, max_tokens, 则优先使用这些参数
        self.temperature = self.config.pop("temperature", temperature)
        self.top_p = self.config.pop("top_p", top_p)
        self.max_tokens = self.config.pop("max_tokens", max_tokens)

        self.system_prompt = system_prompt
        self.model_name = self.config.get("model_name", model)
        self.base_url = self.config.get("base_url", "")
        self.api_key = self.config.get("api_key", "")
        self.histories = [[
            {"role": "system", "content": self.system_prompt}
        ]]
        self.history_cnt = 0
        self.history_idx = 0

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def __repr__(self):
        return f"<ChatModel {self.model}: {self.model_name} @{self.base_url}>"
    

    def change_history(self, history: List[Dict[str, str]]):
        """更改对话历史（增加会话计数）"""
        # 检查是否和某一个对话历史相同
        find = False
        for idx, h in enumerate(self.histories):
            if history == h:
                find = True
                self.history_idx = idx
                break
        if not find:
            self.histories.append(history)
            self.history_cnt += 1
            self.history_idx = self.history_cnt

    def chat(
            self, 
            message: str,
            history: Optional[List[Dict[str, str]]] = None, 
            temperature: Optional[float] = None,
            top_p: Optional[int] = None,
            max_tokens: Optional[int] = None,
            json_mode: bool = False,
            **kwargs
        ):
        """
        同步生成文本
        
        Args:
            messages: 提示词 (字符串) 或对话历史 [{"role": "user", "content": "..."}] (会更新会话计数)
            temperature: 覆盖默认的温度
            max_tokens: 覆盖默认的最大token数
            json_mode: 是否强制JSON输出
        
        Returns:
            生成的文本字符串
        """
        temperature = temperature if temperature is not None else self.temperature
        top_p = top_p if top_p is not None else self.top_p
        max_tokens = max_tokens if max_tokens is not None else self.max_tokens
        
        # 如果提供了history, 则修改历史
        if history is not None:
            self.change_history(history)

        # 将message添加到历史
        self.histories[self.history_idx].append(
            {"role": "user", "content": message}
        )

        if not json_mode:
            try:
                completion = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=self.histories[self.history_idx],
                    temperature=temperature,
                    top_p=top_p,
                    max_tokens=max_tokens,
                    **kwargs
                )
            except Exception as e:
                print(f"[Error] LLMModel.chat failed: {e}")
                return ""
        else:
            error_list = []
            for i in range(5):
                try:
                    completion = self.client.chat.completions.create(
                        model=self.model_name,
                        messages=self.histories[self.history_idx],
                        temperature=temperature,
                        top_p=top_p,
                        max_tokens=max_tokens,
                        response_format={'type': 'json_object'},
                        **kwargs
                    )
                    result = json.loads(completion.choices[0].message.content)
                    break
                except Exception as e:
                    error_list.append(e)
                    print(f"[Error] LLMModel.chat failed: {e}")
                    if 'completion' in locals():
                        print('LLM返回内容:\n' + completion.choices[0].message.content)
                    continue
            else:
                print(f"[Error] LLMModel.chat failed: 5 次请求均失败")
                print(f"错误列表：{error_list}")
        
        # 调用记录 (后期用于日志记录)
        completion_json = completion.model_dump_json()
        # c_json = json.loads(completion_json)
        # pprint(c_json)

        reply = completion.choices[0].message.content
        self.histories[self.history_idx].append(
            {"role": "assistant", "content": reply}
        )
        if not json_mode:
            return reply, completion
        else:
            return result, completion

class EmbeddingModel:
    """统一的文本向量化接口类"""
    def __init__(
            self,
            model: str = "qwen-text-embedding-v4",
            dimensions: Optional[int] = None,
        ):
        """
        初始化embedding模型实例
        """
        self.model = model
        self.config_object = LLMConfig(model=model, type='embedding')
        self.config = self.config_object.config

        self.embedding_model = self.config.get("model_name", model)
        self.base_url = self.config.get("base_url", "")
        self.api_key = self.config.get("api_key", "")
        self.dimensions = self.config.get("dimensions", {})
        self.choose_dimensions = self._check_choose_dimensions(self.dimensions, dimensions)

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    def __repr__(self):
        return f"<EmbeddingModel {self.model}: {self.embedding_model} with {self.choose_dimensions} dimensions @{self.base_url}>"
    
    @staticmethod
    def _check_choose_dimensions(dimensions: Dict | int, suggest_dimensions: Optional[int] = None):
        """检查并设置选择的维度"""
        # 如果dimensions只是int, 则直接返回dimensions
        # 如果dimensions是dict, 支持两个字段: default和supported
        # 如果没有suggest_dimensions, 则使用default(若存在, 不存在则用supported最大值)
        # 如果有suggest_dimensions, 则使用suggest_dimensions最接近的维度
        global abs
        if isinstance(dimensions, int):
            return dimensions
        elif isinstance(dimensions, dict):
            if "default" in dimensions:
                return dimensions["default"]
            elif "supported" in dimensions:
                abs_value = [abs(x - suggest_dimensions) for x in dimensions["supported"]]
                return dimensions["supported"][abs_value.index(min(abs_value))]
            else:
                raise ValueError("Invalid dimensions configuration")
        else:
            raise ValueError("Invalid dimensions configuration")

    def embedding(
            self,
            input_text: Union[str, List[str]],
            dimensions: Optional[int] = None
        ) -> Union[List[float], List[List[float]]]:
        """
        获取文本的向量表示（自动处理批量限制）
        
        Args:
            input_text: 输入文本（字符串或字符串列表）
            dimensions: 指定输出维度（部分模型支持）
        
        Returns:
            单条输入返回 List[float]，多条输入返回 List[List[float]]
        """
        dimensions = dimensions or self.choose_dimensions
        
        max_batch_size = self.config.get(self.model, {}).get("max_batch_size", 10)
        
        # 处理单条字符串
        if isinstance(input_text, str):
            completion = self.client.embeddings.create(
                model=self.embedding_model,
                input=input_text,
                dimensions=dimensions
            )
            # 调用记录 (后期用于日志记录)
            completion_json = completion.model_dump_json()
            return completion.data[0].embedding
        
        # 处理列表（需要分批）
        elif isinstance(input, list):
            completion_json = []
            all_embeddings = []
            
            # 分批处理，避免超过API限制
            for i in range(0, len(input), max_batch_size):
                batch = input[i:i + max_batch_size]
                
                completion = self.client.embeddings.create(
                    model=self.embedding_model,
                    input=batch,
                    dimensions=dimensions
                )
                # 调用记录 (后期用于日志记录)
                completion_json.append(completion.model_dump_json())
                
                batch_embeddings = [
                    item.embedding 
                    for item in completion.data
                ]
                all_embeddings.extend(batch_embeddings)
            
            return all_embeddings
        
        else:
            raise TypeError(f"输入必须是str或List[str]，但收到{type(input)}")

if __name__ == "__main__":
    model_type = input()
    if 'chat' in model_type:
        model = ChatModel(model='qwen-max')
        print(model)
        while (human_input := input("User: ")) != "exit":
            response = model.chat(human_input, logprobs=True)
            print(f"Assistant: {response}")
    elif 'embedding' in model_type:
        model = EmbeddingModel(model='qwen-text-embedding-v4')
        print(model)
        while (human_input := input("Input: ")) != "exit":
            emb = model.embedding(human_input)
            print(f"Embedding ({len(emb)} dims): {emb[:5]}...")

    # # chat_model = ChatModel(model="qwen-max")
    # chat_model = ChatModel(model="deepseek-chat")
    # # embedding_model = EmbeddingModel(model="qwen-text-embedding-v4")
    #
    # print(chat_model)
    # # print(embedding_model)
    #
    # while (human_input := input("User: ")) != "exit":
    #     response = chat_model.chat(human_input, logprobs=True)
    #     print(f"Assistant: {response}")
    #
    #     # emb = embedding_model.embedding(human_input)
    #     # print(f"Embedding ({len(emb)} dims): {emb[:5]}...")

