"""群聊社交图占位（**当前不实现**）。

仅作为目录预留 + 接口契约文档，禁止 import 后使用具体方法。

------------------------------------------------------------------
未来落地时的预期形态（来自用户原始需求）：

    class SocialGraph:
        # 多边关系：A↔B、A↔C、B↔C、以及任意 subject↔target
        edges: dict[tuple[str, int, str, int], "PairState"]

        # 世界状态知识：哪些角色知道哪些事实（含「秘密」可见性）
        #   例：{"char_5": {"knows_user_real_name": True},
        #        "char_7": {"knows_user_real_name": False}}
        world_state_knowledge: dict

        def upsert_edge(self, subject_type, subject_id,
                        target_type, target_id, *, pair_state=None) -> None: ...
        def get_edge(self, subject_type, subject_id,
                     target_type, target_id) -> "PairState | None": ...
        def knows_fact(self, who_type, who_id, fact_key) -> bool: ...

落地条件（按优先级）：
    1. 真正出现「角色 A 关心角色 B 对用户的态度」这类多边依赖
    2. 出现「事实可见性」需求（C 知道但 A 不知道）
    3. 当前 pair_state.py 的单边 PairState 已稳定运行一段时间

落地前请先确认：
    - pair_state.py 的 (subject_type, subject_id, target_type, target_id)
      命名约定无需改动；
    - 落地后所有 edges[] 里的对象就是 PairState 实例，
      即「社交图 = 多个 PairState 的集合 + 全局知识库」，
      不需要重新设计底层边对象。

**本文件故意没有实现，import 本模块仅用于类型提示或文档引用。**
"""
from __future__ import annotations


# 占位 class，禁止实例化（落地时再补全方法）
class SocialGraph:
    """群聊社交图（占位，未实现）。

    当前调用方应继续使用 :class:`relationship.pair_state.PairState`。
    """

    __slots__ = ()  # 防止误实例化时设属性

    def __init__(self, *args, **kwargs) -> None:
        raise NotImplementedError(
            "SocialGraph 尚未实现。当前请使用 PairState 管理单边关系；"
            "群聊扩展落地前，本 class 仅作为接口契约占位。"
        )
