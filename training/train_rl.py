"""
第二阶段奖励学习入口（GRPO/PPO）。

当前为占位实现，待 SFT 基线稳定后接入。
参见 training/reward.py 中的奖励公式与 Judge 设计。
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


def main():
    print("Phase 2: Reward learning (GRPO/PPO) - not yet implemented.")
    print("Prerequisites: stable SFT baseline, Judge API, candidate generation pipeline.")
    print("See training/reward.py for reward formulas and JudgeEvaluator.")
    sys.exit(0)


if __name__ == "__main__":
    main()
