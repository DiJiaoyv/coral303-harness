"""Observability 子包：每轮对话的完整链路追踪。

设计目标：
    你调参的时候一定会问——「这次到底检索了哪些 memory？第一次生成了啥？
    Harness 拒绝它的具体原因是什么？」没有 trace 你只能瞎猜。

落地形态（与 logger.py 互补）：
    - TurnTrace / TurnStep 数据类：定义链路结构
    - Logger.log_turn_step() / log_turn_trace()：实际落盘到 session log
    - harness_core._generate_with_diagnosis / _finalize_turn 调用：
      在每个关键步骤（context_built / llm_generated / harness_evaluated /
      regenerated / memory_written）调 log_turn_step() 写一条
"""
from __future__ import annotations

from observability.trace import TurnStep, TurnTrace, new_turn_id

__all__ = ["TurnStep", "TurnTrace", "new_turn_id"]
