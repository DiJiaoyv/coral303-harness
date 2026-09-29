"""群聊 / World / Social State 预留位。

**当前阶段不实现任何代码**，只为：
    1. 占住目录结构，未来 social_graph.py 落地时不必再大改 import 路径；
    2. 在文档上明确「relationship/future/」是群聊扩展的归宿，
       与已实现的 pair_state.py（subject ↔ target 单边关系）解耦。

预留设计意图（来自用户原始需求）：

    群聊场景下，A 喜欢用户、B 讨厌 A、C 知道一个秘密但 A 不知道
    ——单一 PairState 不够，需要一个图结构管理多边关系。

未来落地形态（**只是占位，禁止实例化**）：

    # future/social_graph.py
    class SocialGraph:
        edges: dict[tuple[str, int, str, int], PairState]
        world_state_knowledge: dict   # "哪些角色知道哪些事实"

落地条件：
    - 第一版（User ↔ 单个 Character）所有功能已由 pair_state.py 覆盖；
    - 当真出现 character ↔ character 关系、或全局事实可见性需求时，
      再在本目录新增 social_graph.py 等模块；
    - PairState 的接口签名已兼容 (subject_type, subject_id,
      target_type, target_id)，群聊扩展无需改签名。
"""
from __future__ import annotations
