# from .prompts import maintainer_prompt_policy, maintainer_prompt_content, consolidator_prompt_policy, consolidator_prompt_content

from typing import *
from pathlib import Path

# 文件地址为项目根目录/prompts/prompts-model-*.md
# 打开地址须保证项目的可迁移性

_prompts_directory = Path(__file__).resolve().parent.parent / "prompts"

with open(_prompts_directory / 'prompt-model-A.md', encoding='utf-8') as f:
    maintainer_prompt_policy = f.read()

with open(_prompts_directory / 'prompt-model-Aplus.md', encoding='utf-8') as f:
    maintainer_prompt_content = f.read()

with open(_prompts_directory / 'prompt-model-B.md', encoding='utf-8') as f:
    consolidator_prompt_policy = f.read()

with open(_prompts_directory / 'prompt-model-Bplus.md', encoding='utf-8') as f:
    consolidator_prompt_content = f.read()

if __name__ == '__main__':
    print(_prompts_directory)
    print(len(maintainer_prompt_policy.encode('utf-8')))
    # pass