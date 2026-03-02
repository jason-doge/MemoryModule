from typing import *
from pathlib import Path

# 文件地址为项目根目录/prompts/prompts-model-*.md
# 打开地址须保证项目的可迁移性

_prompts_directory = Path(__file__).resolve().parent.parent / "prompts"

with open(_prompts_directory / 'prompt-rag.md', encoding='utf-8') as f:
    rag_prompt = f.read()

with open(_prompts_directory / 'prompt-model-A.md', encoding='utf-8') as f:
    maintainer_prompt_policy = f.read()

# with open(_prompts_directory / 'prompt-model-Aplus.md', encoding='utf-8') as f:
#     maintainer_prompt_content = f.read()

with open(_prompts_directory / 'prompt-model-A-SUMMARIZE.md', encoding='utf-8') as f:
    maintainer_prompt_summarize = f.read()

with open(_prompts_directory / 'prompt-model-A-UPDATE.md', encoding='utf-8') as f:
    maintainer_prompt_update = f.read()

with open(_prompts_directory / 'prompt-model-B.md', encoding='utf-8') as f:
    consolidator_prompt_policy = f.read()

with open(_prompts_directory / 'prompt-model-Bplus.md', encoding='utf-8') as f:
    consolidator_prompt_content = f.read()

with open(_prompts_directory / 'prompt-model-Judge.md', encoding='utf-8') as f:
    judge_prompt = f.read()

if __name__ == '__main__':
    # print(_prompts_directory)
    # print(len(maintainer_prompt_summarize.encode('utf-8')))
    # print(len(maintainer_prompt_update.encode('utf-8')))
    print(len(judge_prompt.encode('utf-8')))
    # pass