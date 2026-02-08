from typing import *
import json
from pprint import pprint
from pathlib import Path

class LLMConfig:
    """
    LLM配置类
    """
    def __init__(
            self,
            model: str = "qwen-max",
            type: str = "chat",
            config_file_path: Optional[str] = None,
            **kwargs,
    ):
        self.config_file_path = self._find_config_path(config_file_path)
        self.model = model
        self.config = kwargs
        with open(self.config_file_path, "r", encoding="utf-8") as f:
            config_from_file = json.load(f)
        self.config.update(config_from_file.get(type, {}).get(model, {}))
        if not self.config:
            raise ValueError(f"No config found for model {model} and type {type}.")
        base_url = self.config.get("base_url", "")
        api_key = self.config.get("api_key", "")
        model_name = self.config.get("model_name", "")
        if not base_url or not api_key or not model_name:
            raise ValueError(f"Invalid config for model {model} and type {type}.")

    @staticmethod
    def _find_config_path(
        path: Optional[str] = None
    ) -> Path:
        """
        Find the config file path.
        """
        if path is None:
            config_cwd = Path.cwd() / "llm_config.json"
            if config_cwd.exists():
                return config_cwd
            config_home = Path.home() / ".config" / "memory_module" / "llm_config.json"
            if config_home.exists():
                return config_home
            raise FileNotFoundError("No config file found.")
        else:
            config = Path(path)
            if config.exists():
                return config
            raise FileNotFoundError(f"No config file found at {path}.")

if __name__ == "__main__":
    config = LLMConfig()
    pprint(config.config)


