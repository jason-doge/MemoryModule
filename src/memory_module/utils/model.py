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
from memory_module.debug import log_entry

class ChatModel:
    """LLM模型统一接口类"""
    @log_entry
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

        self.max_context_tokens = self.config.get("max_context_tokens", 262144)

        self.histories = [[
            {"role": "system", "content": self.system_prompt}
        ]]
        self.history_cnt = 0
        self.history_idx = 0

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    @log_entry
    def __repr__(self):
        return f"<ChatModel {self.model}: {self.model_name} @{self.base_url}>"

    @log_entry
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

    @log_entry
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

        if history is not None:
            self.change_history(history)

        self.histories[self.history_idx].append(
            {"role": "user", "content": message}
        )

        # 核心修改：构建参数字典并过滤 None
        api_params = {
            "model": self.model_name,
            "messages": self.histories[self.history_idx],
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            **kwargs
        }
        api_params = {k: v for k, v in api_params.items() if v is not None}

        if json_mode:
            api_params["response_format"] = {'type': 'json_object'}

        try:
            completion = self.client.chat.completions.create(**api_params)
        except Exception as e:
            print(f"[Error] LLMModel.chat failed: {e}")
            return "" if not json_mode else None

        reply = completion.choices[0].message.content
        self.histories[self.history_idx].append(
            {"role": "assistant", "content": reply}
        )

        if json_mode:
            try:
                result = json.loads(reply)
                return result, completion
            except json.JSONDecodeError:
                return None, completion

        return reply, completion

class EmbeddingModel:
    """统一的文本向量化接口类"""
    @log_entry
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
        self.max_context_tokens = self.config.get("max_context_tokens", 8192)

        self.client = OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )

    @log_entry
    def __repr__(self):
        return f"<EmbeddingModel {self.model}: {self.embedding_model} with {self.choose_dimensions} dimensions @{self.base_url}>"
    
    @staticmethod
    @log_entry
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

    @log_entry
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

        api_params = {
            "model": self.embedding_model,
            "input": input_text,
            "dimensions": dimensions
        }
        api_params = {k: v for k, v in api_params.items() if v is not None}

        if isinstance(input_text, str):
            completion = self.client.embeddings.create(**api_params)
            return completion.data[0].embedding

        elif isinstance(input_text, list):
            completion_json = []
            all_embeddings = []
            
            # 分批处理，避免超过API限制
            for i in range(0, len(input_text), self.max_context_tokens):
                batch = input_text[i:i + self.max_context_tokens]
                
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

