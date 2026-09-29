"""Memory Writer —— 对话后：筛选 → 分层 → 写入（含门槛/置信度/理由）。

**替换**的旧代码：
    - harness_core._store_facts()         （line 451–469）
    - harness_core._post_process_turn()   （line 522–586）

**调用（不替换）的分析器**：
    - memory_extractor.MemoryExtractor   —— LLM 提取候选事实（{fact, importance} 列表）
    - unified_analyzer.UnifiedAnalyzer   —— 可选的单次合并分析（facts + narrative）
    注意：这两个文件是「纯分析器（只读）」，**不写存储**。写入决策和分发统一由此文件负责。

四层写入门槛：

| 层级         | 存储                                  | 是否筛选 | 筛选标准                                          |
|-------------|---------------------------------------|---------|--------------------------------------------------|
| Session Log | logger.py → logs/session_*.json       | 否      | 全部存（审计用）                                    |
| Session Buffer | memory/session_buffer.py            | 否      | 全部存，但只保留 N 轮（FIFO 弹掉，不进长期）            |
| Raw Memory  | memory/raw_memory.py                  | **是**  | MemoryImportanceEvaluator（规则优先 + 可选 LLM）     |
| Semantic Memory | memory/semantic_memory.py          | **是**  | 必须 ≥1 个 Raw Memory 证据，需 evidence_count 积累    |

数据流：

    对话发生
      ↓
    Session Log（全部保存，审计用）—— logger.py 已在做
      ↓
    Session Buffer（全部保存，FIFO N 轮）—— 不经过 Gate
      ↓
    MemoryImportanceEvaluator（门槛）
      ├── 不值得 → 只留 Session Log + Buffer，不进 Memory
      └── 值得 → 写入 Raw Memory → 可能提炼进 Semantic Memory

分层写入顺序（每轮）：
    1) Session Buffer：无条件写入（FIFO 管理）—— 不经过 Write Gate
    2) Write Gate：先判断「本轮对话是否值得进长期存储」
       - 通过 → 继续步骤 3/4/5
       - 灰区 → 根据 ENABLE_LLM_MEMORY_GATE 可选调 LLM 二次判断
       - 不通过 → 只写 Session Buffer，Raw/Semantic/Relationship 都不碰
    3) Raw Memory：把通过 Write Gate 的候选事件事实逐条写入（去重）
    4) Semantic Memory：把 unified_analyzer 返回的 semantic_candidates（若有）
       或从 raw entry 里的 preference_hint / identity 类条目按规则提炼
       → 走 upsert_candidate（自动 evidence_count 累加、confidence 计算）
    5) Relationship State：应用 memory_extractor / unified_analyzer /
       规则基线判定出来的 relationship_deltas（每条都带 cause）
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from memory.session_buffer import SessionBuffer
from memory.raw_memory import RawMemory, RawMemoryEntry
from memory.semantic_memory import SemanticMemory, SemanticEntry
from character.state import CharacterState
from relationship.pair_state import PairState, RelationshipChange

log = logging.getLogger(__name__)

# 模块级开关：是否在灰区调用 LLM 做二次判断（默认 False = 保守不写，省成本）
ENABLE_LLM_MEMORY_GATE: bool = False


# ======================================================================
# 一、Memory Importance Evaluator（写入门槛）：规则优先 + 可选 LLM 灰区判断
# ======================================================================
class MemoryImportanceEvaluator:
    """
    「哪些内容值得进入长期（Raw/Semantic）记忆」的筛选器。

    规则优先：毫秒级，命中强信号直接过，命中弱信号直接否；
    灰区：ENABLE_LLM_MEMORY_GATE=True 时才走 LLM 判断，省成本。

    四层门槛中的第三层（Raw Memory 入口）：
        Session Log  → 全部存（审计）
        Session Buffer → 全部存，FIFO N 轮
        Raw Memory → **本类筛选**（规则优先 + 可选 LLM）
        Semantic Memory → 必须 ≥1 个 Raw Memory 证据 + evidence_count 积累
    """

    # 强信号：命中任意一个 → 直接值得写长期记忆
    RULE_STRONG_SIGNALS: list[str] = [
        "小时候", "以前", "过去", "我记得",
        "我家人", "我爸", "我妈", "我弟", "我妹", "我哥", "我姐",
        "我的", "我家住", "我老家", "我的工作", "我的职业",
        "我害怕", "我怕", "我最讨厌", "我喜欢", "我爱",
        "梦想是", "目标是", "打算", "计划",
        "告诉过你", "记得吗", "还记得", "我说过",
        "第一次", "上次", "那时候", "当时",
        "过敏", "生病", "抑郁症", "强迫症", "焦虑",
        "生日", "身份证", "学校", "公司",
        "男朋友", "女朋友", "老公", "老婆", "对象",
        # 身份/自我披露
        "我叫", "我是", "我来自", "我在", "我住",
        "用户叫", "用户是", "用户来自", "用户在", "用户住",  # analyzer 常以"用户X…"输出事实
        # 内容长且包含个人信息标志
        "不喜欢", "讨厌", "喜欢", "害怕",
        "钱收了", "契约", "信用点",  # 角色相关也可记
    ]

    # 弱信号：纯闲聊/瞬时情绪 → 默认不进长期
    RULE_WEAK_SIGNALS: list[str] = [
        "今天", "现在", "此刻", "刚刚", "好饿", "好困", "好累",
        "哈哈", "哈哈哈", "嗯嗯", "嗯嗯嗯", "哦", "噢", "好吧",
        "好的", "行", "行吧", "呵呵", "嘻嘻", "233",
        "在吗", "忙吗", "睡了", "晚安", "早",
    ]

    def __init__(
        self,
        *,
        enable_strong: bool = True,
        enable_weak: bool = True,
        min_message_length_for_gate: int = 6,
    ) -> None:
        self.enable_strong = enable_strong
        self.enable_weak = enable_weak
        self.min_message_length_for_gate = min_message_length_for_gate

    # ---------- 用户要求的主接口 ----------
    def is_worth_remembering(self, user_msg: str, ai_response: str) -> bool:
        """判断这段对话是否值得进入 Raw Memory。

        简单 bool 接口，方便外部调用方直接 if 判断。
        内部委托 is_worth_raw_memory()，返回其 bool 部分。
        """
        ok, _reason = self.is_worth_raw_memory(user_msg, ai_response)
        return ok

    # ---------- 带理由的接口（tracing / observability 用） ----------
    def is_worth_raw_memory(
        self,
        user_message: str,
        ai_response: str,
        *,
        llm_judge_fn: Callable[[str, str], bool] | None = None,
    ) -> tuple[bool, str]:
        """
        返回 (True/False, reason)。reason 用于 observability / tracing。

        决策顺序：
          1) 空消息或极短 → 不写
          2) 强信号命中 → 写
          3) 弱信号命中 → 不写
          4) 灰区 → 若 ENABLE_LLM_MEMORY_GATE=True 且提供 llm_judge_fn 则调；
             否则保守不写（留 Session Log 审计）
        """
        combined = f"{user_message}\n{ai_response}"
        combined_stripped = combined.strip()
        user_stripped = (user_message or "").strip()
        ai_stripped = (ai_response or "").strip()

        if not user_stripped or not ai_stripped:
            return False, "对话任一侧为空"
        if len(user_stripped) < self.min_message_length_for_gate:
            return False, f"用户消息过短(<{self.min_message_length_for_gate}字)"

        # 2) 强信号
        if self.enable_strong:
            hits_strong = [s for s in self.RULE_STRONG_SIGNALS if s in combined]
            if hits_strong:
                return True, (
                    f"命中强信号[{','.join(hits_strong[:3])}]"
                    + ("..." if len(hits_strong) > 3 else "")
                )

        # 3) 弱信号
        if self.enable_weak:
            hits_weak = [s for s in self.RULE_WEAK_SIGNALS if s in combined]
            # 但如果整段话不只是弱信号（有其他内容），就不直接挡掉
            # 只在「完全由弱信号构成 / 非常短」时挡
            only_weak = len(combined_stripped) < 20 and hits_weak
            if only_weak:
                return False, f"纯闲聊弱信号[{','.join(hits_weak)}]"

        # 4) 灰区：LLM 判断或保守不写
        if ENABLE_LLM_MEMORY_GATE and llm_judge_fn is not None:
            try:
                ok = bool(llm_judge_fn(user_message, ai_response))
            except Exception:
                log.warning("Memory Write Gate LLM 判断异常，fallback 不写", exc_info=True)
                return False, "LLM judge 异常，保守不写"
            if ok:
                return True, "LLM 判断值得写入（灰区通过）"
            return False, "LLM 判断不值得写入（灰区拒绝）"

        # 默认：灰区先不写（Session Log 审计用）
        return False, "灰区未启用 LLM 判断，保守不写"


# 向后兼容别名（旧 smoke test / harness 仍用旧名）
MemoryWriteGate = MemoryImportanceEvaluator


# ======================================================================
# 二、WriteResult（每轮写完成的可观察输出）
# ======================================================================
@dataclass
class WriteResult:
    """Memory Writer 在单轮写后的结果。给 tracing / orchestration 调用方用。"""

    # Session Buffer 永远写
    session_buffer_added: int = 0

    # Write Gate
    gate_passed: bool = False
    gate_reason: str = ""

    # Raw Memory
    raw_added: list[str] = field(default_factory=list)      # list[memory_id]
    raw_skipped_duplicate: int = 0
    raw_category_count: dict[str, int] = field(default_factory=dict)

    # Semantic Memory
    semantic_upserts: list[dict[str, Any]] = field(default_factory=list)
        # 每项：{"key","bucket","action":"created|confirmed|contradicted|new_side_entry",
        #        "confidence_new":0.xx, "evidence_count_new":N}

    # Relationship State
    relationship_changes: list[dict[str, Any]] = field(default_factory=list)
        # 每项：RelationshipChange.to_dict()

    # Character State 同步更新摘要（mental_notes / shift_summary 等）
    character_state_updates: list[str] = field(default_factory=list)

    # 失败不致命：是否有任何异常（给 tracing 标记）
    warnings: list[str] = field(default_factory=list)

    def to_trace_dict(self) -> dict[str, Any]:
        return {
            "session_buffer_added": self.session_buffer_added,
            "gate_passed": self.gate_passed,
            "gate_reason": self.gate_reason,
            "raw_added_ids": list(self.raw_added),
            "raw_skipped_duplicate": self.raw_skipped_duplicate,
            "raw_category_count": dict(self.raw_category_count),
            "semantic_upserts": list(self.semantic_upserts),
            "relationship_changes": list(self.relationship_changes),
            "character_state_updates": list(self.character_state_updates),
            "warnings": list(self.warnings),
        }


# ======================================================================
# 三、Memory Writer（对话后统一入口）
# ======================================================================
class MemoryWriter:
    """
    对话后统一写入控制器。

    调用流程（harness_core.orchestrate_turn 里）：::

        writer.write_turn(
            user_message=...,
            ai_response=final_accepted_response,   # 只写通过的，不写 candidates
            turn_id=...,
            session_id=...,
            # 状态对象（就地修改，不做任何持久化）
            session_buffer=...,
            raw_memory=...,
            semantic_memory=...,
            pair_state=...,
            character_state=...,
            # 分析器（调用但不接管存储）
            extractor_candidates=...,          # memory_extractor.extract 返回的 facts
            analyzer_semantic_candidates=...,  # unified_analyzer 返回的 semantic[]
            analyzer_narrative=...,            # unified_analyzer 返回的 narrative{}
            relationship_delta_suggestions=...,  # Evaluator/Harness 给的 [{axis,delta,cause}]
            # Write Gate 可选的 LLM 兜底
            gate_llm_judge_fn=None,
        ) -> WriteResult
    """

    def __init__(
        self,
        *,
        gate: MemoryImportanceEvaluator | None = None,
        evaluator_version: str = "memory-writer:1.0",
    ) -> None:
        self.gate = gate or MemoryImportanceEvaluator()
        self.evaluator_version = evaluator_version

    # ==================================================================
    # 一等公民：所有 memory 写入的统一子接口
    #
    # 设计原则（用户原始约束）：
    #   「所有 memory 写入只能经过 memory_writer.py，不允许
    #     harness_core / character_memory / emotion 直接写」
    #
    # 分两类：
    #   A) 单步写入：实时写短期 buffer / 单条 raw / 单次关系变更 / emotion 更新
    #   B) 持久化：save_all / save_emotion 把内存对象落盘
    # ==================================================================

    # ---------- A1) Session Buffer 单步写入 ----------
    def add_session_message(
        self,
        *,
        role: str,
        content: str,
        session_buffer: SessionBuffer,
    ) -> None:
        """实时写一条消息到 Session Buffer（FIFO）。

        替代 harness_core / character_memory 中的 `session_buffer.add(role, content)`
        直接调用。对话中 user / assistant 消息可立即调此接口，不必等 write_turn 末尾。
        """
        if role not in ("user", "assistant"):
            raise ValueError(f"role 必须是 'user' 或 'assistant'，实际: {role!r}")
        session_buffer.add(role, content)

    # ---------- A2) Raw Memory 单条写入 ----------
    def write_raw_entry(
        self,
        *,
        raw_memory: RawMemory,
        fact: str,
        importance: int = 3,
        category: str = "fact",
        turn_id: str | None = None,
        session_id: str | None = None,
    ) -> str | None:
        """单条事实直接写 Raw Memory（绕过 Write Gate，仅供已通过判断的写入）。

        替代 harness_core._store_facts 里的 `self.raw_memory.add_from_extractor(...)`。
        返回 entry.memory_id 或 None（去重跳过时）。

        注意：本接口**不**走 Write Gate，调用方必须自行判断值得写入。
        若需要 Write Gate，请走 write_turn() 完整路径。
        """
        if not fact or not fact.strip():
            return None
        entry = raw_memory.add_from_extractor(
            fact=fact.strip(),
            importance=max(1, min(5, int(importance))),
            category=category,
            turn_id=turn_id,
            session_id=session_id,
        )
        return entry.memory_id if entry else None

    # ---------- A3) Semantic Memory 单条 upsert ----------
    def upsert_semantic_entry(
        self,
        *,
        semantic_memory: SemanticMemory,
        key: str,
        value: Any = True,
        bucket: str = "preferences",
        raw_memory_ref: str | None = None,
    ) -> tuple[Any, str] | None:
        """单条 semantic upsert（不走 Write Gate）。

        替代 harness_core 中 `semantic_memory.upsert_candidate(...)` 的直接调用。
        返回 (entry, action) 或 None（异常时）。
        """
        try:
            return semantic_memory.upsert_candidate(
                key=key,
                value=value,
                bucket=bucket,
                raw_memory_ref=raw_memory_ref,
            )
        except Exception as exc:
            log.warning("upsert_semantic_entry 异常: %s", exc, exc_info=True)
            return None

    # ---------- A4) Relationship 单次变更 ----------
    def update_relationship(
        self,
        *,
        pair_state: PairState,
        axis: str,
        delta: float,
        cause: str,
        raw_memory_ref: str | None = None,
        turn_id: str | None = None,
    ) -> RelationshipChange | None:
        """单次关系轴变更（必须带 cause）。

        替代 harness_core 中 `pair_state.update_axis(...)` 的直接调用。
        返回 RelationshipChange 或 None（参数不合法时）。
        """
        if not isinstance(cause, str) or not cause.strip():
            raise ValueError("update_relationship 必须带非空 cause（用户硬约束）")
        try:
            return pair_state.update_axis(
                axis=axis,
                delta=float(delta),
                cause=cause,
                raw_memory_ref=raw_memory_ref,
                evaluator_version=self.evaluator_version,
                turn_id=turn_id,
            )
        except Exception as exc:
            log.warning("update_relationship 异常: %s", exc, exc_info=True)
            return None

    # ---------- A5) Emotion 状态更新 ----------
    def update_emotion(
        self,
        *,
        emotion_manager: Any,
        user_message: str,
    ) -> None:
        """分析用户输入并更新 PAD 情绪状态（替代 harness_core._prepare_emotion_for_turn 的写入部分）。

        emotion_manager 是 PADEmotionManager 实例，其 process_user_turn() 会就地修改 state。
        本接口只做转发，便于将来在 MemoryWriter 层加预算控制 / trace。
        """
        try:
            emotion_manager.process_user_turn(user_message)
        except Exception as exc:
            log.warning("update_emotion 异常（fail-open）: %s", exc, exc_info=True)

    # ---------- B1) Emotion 持久化 ----------
    def save_emotion(
        self,
        *,
        emotion_manager: Any,
        emotion_path: str,
        character_id: int | None = None,
    ) -> None:
        """把 emotion 状态落盘到 emotion_path + 同步到 DB（替代 harness_core._persist_emotion_state）。

        emotion_manager.save(path) 由 emotion 模块自己实现；本接口只做转发，
        集中所有 memory 写入入口，便于预算控制 / trace。
        """
        try:
            emotion_manager.save(emotion_path)
            if hasattr(emotion_manager, "sync_to_database"):
                emotion_manager.sync_to_database(character_id)
        except Exception as exc:
            log.warning("save_emotion 异常: %s", exc, exc_info=True)

    # ---------- B2) 全量持久化 ----------
    def save_all(
        self,
        *,
        memory_dir: str,
        session_buffer: SessionBuffer,
        raw_memory: RawMemory,
        semantic_memory: SemanticMemory,
        pair_state: PairState | None = None,
        pair_state_path: str | None = None,
    ) -> dict[str, str]:
        """统一落盘所有 memory 层到 memory_dir 目录。

        替代 harness_core._save_memory_v2 的直接 `session_buffer.save() / raw_memory.save() / semantic_memory.save()` 调用。
        返回各层落盘文件路径字典。

        pair_state_path 单独传：因为 relationship state 与三层 memory 通常不同目录。
        """
        import os

        os.makedirs(memory_dir, exist_ok=True)
        paths: dict[str, str] = {}

        # 三层 memory
        paths["session"] = os.path.join(memory_dir, "memory_session.json")
        paths["raw"] = os.path.join(memory_dir, "memory_raw.json")
        paths["semantic"] = os.path.join(memory_dir, "memory_semantic.json")
        session_buffer.save(paths["session"])
        raw_memory.save(paths["raw"])
        semantic_memory.save(paths["semantic"])

        # Relationship state（可选，路径单独传）
        if pair_state is not None and pair_state_path:
            from relationship.pair_state import save_pair_state

            save_pair_state(pair_state_path, pair_state)
            paths["relationship"] = pair_state_path

        return paths

    # ---------- B3) legacy v0.1 双写（仅环境开关打开时） ----------
    def save_legacy_v01(
        self,
        *,
        memory_path: str,
        session_buffer: SessionBuffer,
        raw_memory: RawMemory,
        use_vector: bool = False,
    ) -> None:
        """legacy v0.1 memory_state.json 双写（仅 HARNESS_WRITE_LEGACY_V01=1 启用）。

        集中 legacy 双写逻辑，避免散落在 harness_core._save_memory_v2 里。
        默认不启用，物理删除 character_memory.py 后此接口可一并删除。
        """
        import json as _json
        import os

        if os.environ.get("HARNESS_WRITE_LEGACY_V01", "").strip().lower() not in (
            "1", "true", "yes", "on",
        ):
            return

        dir_ = os.path.dirname(os.path.abspath(memory_path)) or "."
        os.makedirs(dir_, exist_ok=True)
        legacy_path = os.path.join(dir_, "memory_state.json")
        legacy_data = {
            "max_messages": session_buffer.max_messages,
            "short_term": [
                {"role": m.role, "content": m.content, "timestamp": m.timestamp}
                for m in session_buffer.messages
            ],
            "long_term": [
                {"fact": e.content, "importance": e.importance, "timestamp": e.timestamp}
                for e in raw_memory.entries if not e.deleted
            ],
            "use_vector": use_vector,
        }
        with open(legacy_path, "w", encoding="utf-8") as f:
            _json.dump(legacy_data, f, ensure_ascii=False, indent=2)

    # ==================================================================
    # 以下为原有 write_turn 主入口（保留，作为「完整一轮」的批量写入）
    # ==================================================================

    # ---------- 对外主入口 ----------
    def write_turn(
        self,
        *,
        user_message: str,
        ai_response: str,
        # 状态容器（就地修改，不负责 save；持久化由调用方负责）
        session_buffer: SessionBuffer,
        raw_memory: RawMemory,
        semantic_memory: SemanticMemory,
        pair_state: PairState | None = None,
        character_state: CharacterState | None = None,
        # 本轮身份信息
        turn_id: str | None = None,
        session_id: str | None = None,
        # 分析器产物（传 None 表示该分析器未启用）
        extractor_candidates: list[dict[str, Any]] | None = None,
        analyzer_semantic_candidates: list[dict[str, Any]] | None = None,
        analyzer_narrative: dict[str, Any] | None = None,
        # Evaluator/Harness 给出的关系变化建议（每条至少 {axis,delta,cause}）
        relationship_delta_suggestions: list[dict[str, Any]] | None = None,
        # Write Gate 灰区兜底
        gate_llm_judge_fn: Callable[[str, str], bool] | None = None,
        # Phase 2 接口预留：调用方（如 harness_core）若已在 build_prompt 前写好
        # user message、在 _finalize_turn 里写好 assistant message，则传 True 跳过
        # Step 1 的 session buffer 写入，避免重复。默认 False 保持原行为。
        skip_session_buffer: bool = False,
    ) -> WriteResult:
        result = WriteResult()

        # ========================================================
        # Step 1：Session Buffer（永远写，不经过 Gate）
        # 若 skip_session_buffer=True（调用方已自行写入），则跳过。
        # ========================================================
        if not skip_session_buffer:
            try:
                count_before = len(session_buffer.messages)
                session_buffer.add("user", user_message)
                session_buffer.add("assistant", ai_response)
                result.session_buffer_added = len(session_buffer.messages) - count_before
            except Exception as exc:
                result.warnings.append(f"Session Buffer 写入异常: {exc}")
        else:
            # 调用方已经写好 session buffer；此处不重复写，只在 result 里标注
            result.session_buffer_added = 0

        # ========================================================
        # Step 2：Write Gate（决定要不要进长期）
        # ========================================================
        gate_passed, gate_reason = self.gate.is_worth_raw_memory(
            user_message, ai_response, llm_judge_fn=gate_llm_judge_fn
        )
        result.gate_passed = gate_passed
        result.gate_reason = gate_reason
        if not gate_passed:
            # 关系状态 & Character State 仍可能更新（比如一轮纯闲聊也可能让 familiarity 微调）
            # 所以这里不 return，继续走 relationship/character 部分
            pass

        # ========================================================
        # Step 3：Raw Memory（只在 gate 通过时写）
        # ========================================================
        raw_candidates: list[dict[str, Any]] = list(extractor_candidates or [])
        # unified_analyzer 的 facts 也走 Raw Memory
        if analyzer_narrative is None:
            analyzer_narrative = {}
        if gate_passed:
            # 如果 extractor 没传但 analyzer 给了 facts[]，也取它们
            if not raw_candidates and isinstance(analyzer_narrative.get("facts"), list):
                raw_candidates = list(analyzer_narrative["facts"])
            self._write_raw_memory(
                raw_memory,
                raw_candidates,
                turn_id=turn_id,
                session_id=session_id,
                result=result,
            )

        # ========================================================
        # Step 4：Semantic Memory（在 gate 通过且有候选 semantic 时写）
        # ========================================================
        if gate_passed:
            sem_candidates = list(analyzer_semantic_candidates or [])
            # 兜底：没有 semantic 候选，就从 Raw Memory 的 preference_hint / identity
            # 类别里启发式地挑一些（category 由 Write Gate 分类器打标）
            if not sem_candidates:
                sem_candidates = self._heuristic_semantic_from_raw(
                    raw_memory, new_ids=set(result.raw_added)
                )
            self._write_semantic_memory(
                semantic_memory,
                sem_candidates,
                result=result,
            )

        # ========================================================
        # Step 5：Relationship State（带 cause，gate 不通过也允许微调 familiarity）
        # ========================================================
        if pair_state is not None:
            self._apply_relationship_deltas(
                pair_state,
                suggestions=relationship_delta_suggestions or [],
                turn_id=turn_id,
                result=result,
            )

        # ========================================================
        # Step 6：Character State 同步（mental notes / 关系变化摘要 / 弧光）
        # ========================================================
        if character_state is not None:
            self._sync_character_state(
                character_state,
                pair_state=pair_state,
                narrative=analyzer_narrative or {},
                result=result,
            )

        return result

    # ======================================================================
    # 内部 helper：Raw / Semantic / Relationship / Character State 的分步写入
    # ======================================================================
    def _write_raw_memory(
        self,
        raw_memory: RawMemory,
        candidates: list[dict[str, Any]],
        *,
        turn_id: str | None,
        session_id: str | None,
        result: WriteResult,
    ) -> None:
        for item in candidates:
            if not isinstance(item, dict):
                continue
            fact_text = item.get("fact")
            if not isinstance(fact_text, str) or not fact_text.strip():
                continue
            importance = int(item.get("importance", 3))
            category = str(item.get("category") or "fact")
            try:
                before_count = len(raw_memory.entries)
                entry = raw_memory.add_from_extractor(
                    fact=fact_text.strip(),
                    importance=importance,
                    category=category,
                    turn_id=turn_id,
                    session_id=session_id,
                )
                after_count = len(raw_memory.entries)
                if after_count > before_count:
                    result.raw_added.append(entry.memory_id)
                    result.raw_category_count[entry.category] = (
                        result.raw_category_count.get(entry.category, 0) + 1
                    )
                else:
                    result.raw_skipped_duplicate += 1
            except Exception as exc:
                result.warnings.append(f"Raw Memory 写入失败: {exc}; fact={fact_text[:40]}")

    def _heuristic_semantic_from_raw(
        self,
        raw_memory: RawMemory,
        new_ids: set[str],
    ) -> list[dict[str, Any]]:
        """
        在 unified_analyzer 没返回 semantic 候选时兜底：
        把本轮新建的 category="preference_hint" / "fact"(identity 类) 的 Raw Memory
        条目按启发式规则转成 semantic 候选。宁可少写也不胡写。pattern：

            「用户喜欢/爱/对…感兴趣 X」  → preferences.likes_X = True
            「用户讨厌/不喜欢 X」          → preferences.dislikes_X = True
            「用户怕/害怕 X」              → preferences.dislikes_X + flags.fears_X
            「用户因[事件]曾[强烈情绪反应]」 → flags.{反应}_{事件摘要} = True
            「用户叫 XXX」                 → identity.display_name = XXX
            「用户是{职业/身份}」           → identity.occupation_or_role = {职业/身份}
            「角色自称我叫…」                → 跳过（不进用户画像）
        """
        candidates: list[dict[str, Any]] = []
        for e in raw_memory.entries:
            if e.memory_id not in new_ids:
                continue
            text = e.content.strip()
            if not text.startswith("用户"):
                # 启发式只提炼用户侧信息；若 category 不是 preference_hint 也跳过
                if e.category != "preference_hint":
                    continue
            lower = text

            # 1) 用户喜欢 / 爱 / 感兴趣 / 痴迷 X
            matched = False
            for pos_kw in ("喜欢", "爱", "对…感兴趣", "对…痴迷", "感兴趣于", "痴迷于"):
                marker = f"用户{pos_kw}"
                if marker in lower:
                    val = lower.split(marker, 1)[1].strip(" 。,.!?？！")
                    if val:
                        candidates.append({
                            "key": "likes_" + self._slug_suffix(val),
                            "value": True, "bucket": "preferences",
                            "raw_memory_ref": e.memory_id,
                        })
                        matched = True
                        break
            if matched:
                continue

            # 2) 用户讨厌 / 不喜欢 X → 偏好 dislike
            for neg_kw in ("讨厌", "不喜欢", "厌烦"):
                marker = f"用户{neg_kw}"
                if marker in lower:
                    val = lower.split(marker, 1)[1].strip(" 。,.!?？！")
                    if val:
                        candidates.append({
                            "key": "dislikes_" + self._slug_suffix(val),
                            "value": True, "bucket": "preferences",
                            "raw_memory_ref": e.memory_id,
                        })
                        matched = True
                        break
            if matched:
                continue

            # 3) 用户怕 / 害怕 X → fears_ flag + dislikes_
            for fear_kw in ("怕", "害怕", "恐惧"):
                marker = f"用户{fear_kw}"
                if marker in lower:
                    val = lower.split(marker, 1)[1].strip(" 。,.!?？！")
                    if val:
                        candidates.append({
                            "key": "dislikes_" + self._slug_suffix(val),
                            "value": True, "bucket": "preferences",
                            "raw_memory_ref": e.memory_id,
                        })
                        candidates.append({
                            "key": "fears_" + self._slug_suffix(val),
                            "value": True, "bucket": "flags",
                            "raw_memory_ref": e.memory_id,
                        })
                        matched = True
                        break
            if matched:
                continue

            # 4) 「用户叫 XXX」 / 「用户名叫 XXX」 → identity
            for name_marker in ("用户名叫", "用户叫"):
                if name_marker in lower:
                    val = lower.split(name_marker, 1)[1].strip(" 。,.!?？！")
                    if val:
                        candidates.append({
                            "key": "display_name", "value": val, "bucket": "identity",
                            "raw_memory_ref": e.memory_id,
                        })
                        matched = True
                        break
            if matched:
                continue

            # 5) 「用户是 X」 → identity.occupation_or_role（如果 X 像职业/身份：2–6字且没有标点）
            marker = "用户是"
            if marker in lower:
                val = lower.split(marker, 1)[1].strip(" 。,.!?？！")
                if val and 2 <= len(val) <= 10 and not any(p in val for p in "的很了着过…吗呢啊吧"):
                    candidates.append({
                        "key": "identity_label_short", "value": val, "bucket": "identity",
                        "raw_memory_ref": e.memory_id,
                    })
                    matched = True
                    continue

            # 6) 兜底：preference_hint / 有明显情绪词（"难过/伤心/开心/愤怒"）的 fact → flag
            #    格式：flags.{情绪词}_about_{内容摘要}
            if e.category in ("preference_hint", "event") and len(text) <= 60:
                for emo in ("难过", "伤心", "悲伤", "开心", "高兴", "愤怒", "生气",
                            "焦虑", "害怕", "愧疚", "羞耻", "惊讶", "惊喜"):
                    if emo in text:
                        subject_part = text[:25]
                        suffix = self._slug_suffix(subject_part)[:25] or "item"
                        candidates.append({
                            "key": f"emo_{emo}_event_{suffix}",
                            "value": True, "bucket": "flags",
                            "raw_memory_ref": e.memory_id,
                        })
                        matched = True
                        break
        return candidates

    @staticmethod
    def _slug_suffix(val: str) -> str:
        """把「猫」「恐怖片」「深色巧克力」变成方便当 key 后缀的 slug。"""
        s = val.strip().lower()
        # 非字母数字统一替换为 _
        out_chars: list[str] = []
        for ch in s:
            if ch.isascii() and (ch.isalnum()):
                out_chars.append(ch)
            elif ord(ch) < 128:
                out_chars.append("_")
            else:
                # 保留中文等 CJK 字符（我们 key 里支持 unicode）
                out_chars.append(ch)
        result = "".join(out_chars).strip("_")
        return result or "item"

    def _write_semantic_memory(
        self,
        semantic_memory: SemanticMemory,
        candidates: list[dict[str, Any]],
        *,
        result: WriteResult,
    ) -> None:
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            key = str(cand.get("key") or "").strip()
            if not key:
                continue
            bucket = str(cand.get("bucket") or "preferences").strip() or "flags"
            value = cand.get("value", True)
            ref = cand.get("raw_memory_ref")
            try:
                entry, action = semantic_memory.upsert_candidate(
                    key=key,
                    value=value,
                    bucket=bucket,
                    raw_memory_ref=ref,
                )
                result.semantic_upserts.append({
                    "key": entry.key,
                    "bucket": entry.bucket,
                    "value": entry.value,
                    "action": action,
                    "confidence_new": round(entry.confidence, 4),
                    "evidence_count_new": entry.evidence_count,
                    "contradiction_count_new": entry.contradiction_count,
                    "pending_cleanup": entry.pending_cleanup,
                })
            except Exception as exc:
                result.warnings.append(
                    f"Semantic upsert 异常: {exc}; key={key}, value={value}"
                )

    def _apply_relationship_deltas(
        self,
        pair_state: PairState,
        *,
        suggestions: list[dict[str, Any]],
        turn_id: str | None,
        result: WriteResult,
    ) -> None:
        if not suggestions:
            return
        for s in suggestions:
            if not isinstance(s, dict):
                continue
            axis = s.get("axis")
            delta = s.get("delta")
            cause = s.get("cause")
            if not isinstance(axis, str) or axis not in ("familiarity", "trust", "emotional_closeness", "playfulness", "tension"):
                result.warnings.append(f"关系建议缺少合法 axis: {s}")
                continue
            if not isinstance(delta, (int, float)):
                result.warnings.append(f"关系建议 delta 非数字: {s}")
                continue
            if not isinstance(cause, str) or not cause.strip():
                result.warnings.append(f"关系建议缺少 cause，跳过: {s}")
                continue
            try:
                change = pair_state.update_axis(
                    axis=axis,
                    delta=float(delta),
                    cause=cause,
                    raw_memory_ref=s.get("raw_memory_ref"),
                    evaluator_version=s.get("evaluator_version") or self.evaluator_version,
                    turn_id=turn_id,
                )
                if change.delta != 0.0:
                    result.relationship_changes.append(change.to_dict())
            except Exception as exc:
                result.warnings.append(f"关系更新异常: {exc}; suggestion={s}")

    def _sync_character_state(
        self,
        cs: CharacterState,
        *,
        pair_state: PairState | None,
        narrative: dict[str, Any],
        result: WriteResult,
    ) -> None:
        # 1) Narrative: arc_stage / current_goal
        if narrative.get("should_update"):
            new_stage = narrative.get("arc_stage")
            new_goal = narrative.get("current_goal")
            if isinstance(new_stage, str) and new_stage in {"起点", "转折点", "终点"}:
                if cs.arc_stage != new_stage:
                    cs.arc_stage = new_stage
                    result.character_state_updates.append(f"弧光阶段→{new_stage}")
            if isinstance(new_goal, str) and new_goal.strip():
                if cs.current_goal != new_goal.strip():
                    cs.current_goal = new_goal.strip()
                    result.character_state_updates.append(
                        f"目标更新（reason={narrative.get('reason','')[:40]}）"
                    )
        # 2) Relationship 变化摘要（给下一轮 prompt 快速感知）
        if pair_state is not None and result.relationship_changes:
            summaries: list[str] = []
            for rc in result.relationship_changes:
                axis = rc.get("axis", "")
                delta = float(rc.get("delta", 0.0))
                if delta == 0:
                    continue
                arrow = "上升" if delta > 0 else "下降"
                label = {
                    "familiarity": "熟悉度",
                    "trust": "信任度",
                    "emotional_closeness": "亲密度",
                    "playfulness": "嬉玩度",
                    "tension": "紧张度",
                }.get(axis, axis)
                summaries.append(
                    f"{label}{arrow}{abs(round(delta*100,1))}%"
                    f"（{str(rc.get('cause',''))[:30]}）"
                )
            if summaries:
                cs.last_relationship_shift_summary = "；".join(summaries[:2])
                result.character_state_updates.append(
                    "last_relationship_shift_summary 已同步"
                )
        cs.validate()
