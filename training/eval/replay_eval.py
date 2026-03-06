"""
Replay 评估：在完整轨迹回放中评估训练后模型。

当前实现：加载 checkpoint，在 test 集上运行离线推理并计算指标。
后续可扩展：将训练后模型接入 MemoryModule 替换 API 模型，进行端到端轨迹回放评估。
"""

from __future__ import annotations

import sys
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from training.eval.offline_eval import main as offline_main


def main():
    """复用 offline_eval 作为 replay 评估入口。"""
    offline_main()


if __name__ == "__main__":
    main()
