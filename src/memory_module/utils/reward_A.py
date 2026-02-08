from swift.plugin import ORM, orms
from .framework import MemoryModule
from openai import OpenAI

class JudgeModel(ORM):
    """Reward ORM class."""
    def get_reward(
        self,
        memories,
    ):
        prompt = """abcd""" # !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        _, completions = self.memory_module.chat_model.chat(
            message=[{
                "role": "user",
                "content": prompt + sum(memories),
            }],
            history=[],
            logprobs=True
        )
        # 注意考虑错误答案的情况 !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
        logprobs = float(completions.choices[0].logprobs.content[0].logprob)
        
        return logprobs

    def __call__(
        self,
        completions,
        **kwargs
    ) -> List[float]:
        self.memory_module = MemoryModule(
            consolidator_model='api',
        )
        rewards = []
        for completion in completions:
            # 注意序列解包!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
            _, r1, r2 = self.memory_module.process_observation(
                obs=obs,
                pentest_target=pentest_target,
                pentest_plan=pentest_plan,
                tuner='tuner',
                actions = None,
                consolidated_results = completion,
                original_memories = original_memories,
                retrieved_memories_2=None,
                get_reward=get_reward,
            )
            if tuner == 'maintainer':
                rewards.append(r1 + r2)
            else:
                rewards.append(r2 - r1)
        return rewards

orms['judge'] = JudgeModel


        