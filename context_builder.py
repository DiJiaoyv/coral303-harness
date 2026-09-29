"""Context Builder —— 对话前：结构化读取所有状态 → 组装 Generation Context。

**替换**的旧代码：
    - harness_core.build_prompt()           （line 381–401）
    - harness_core._prepare_emotion_for_turn()  （line 408–413）

**设计原则**：
    1. 「先结构化读取、再组装」：第一步只读不写，收集所有必需的 snapshot
       到 GenerationSnapshot 结构里；第二步基于 snapshot 拼 prompt 文本。
       好处：observability 能直接记录 snapshot，「prompt 为什么这么拼」可追溯。
    2. 兼容 v0.1：如果调用方还传 Soul 对象/旧 EmotionManager，也能兜底走兼容路径。
       但新架构的「完整模式」推荐传 Character(Profile/State)、Memory(三层)、Relationship、Emotion 全部。
    3. 不自己做「规则判定」：关系规则 / 行为规则的具体合规性留给 Harness Evaluator；
       Context Builder 只把「现在 axes 是多少、阶段是什么、有哪些 baseline rules 生效」
       告诉 LLM 就够了。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from character.profile import CharacterProfile
from character.state import CharacterState
from character.speech_style import SpeechStyle
from character.behavioral_rules import BehavioralRules
from character.relationship_rules import RelationshipRules
from memory.retrieval import MemoryRetriever, RetrievalResult
from relationship.pair_state import PairState

# 兼容 v0.1
try:
    from emotion.models import PADState  # type: ignore
    from emotion.renderer import render_emotion  # type: ignore
except Exception:  # pragma: no cover - emotion 不存在时用占位
    class PADState:  # type: ignore[no-redef]
        def __init__(self, **_: Any) -> None: ...  # noqa: D401

    def render_emotion(*a, **kw):  # type: ignore[no-redef]
        return "（情绪模块不可用）"


_ROLE_OUTPUT_RULES = (
    "- 严格禁止以 AI / 语言模型身份说话，必须始终沉浸在角色里\n"
    "- 不要输出元推理或分析过程（如'让我思考'），直接给出角色台词\n"
    "- 禁止出现括号内的动作描写（如（*笑*））；应使用引号内自然语言表达\n"
    "- 一次不要说过长（通常 1–3 句，视情绪阶段可适度展开）"
)


# ---------- 结构化读取产物（先读、后拼的中间态） ----------
@dataclass
class GenerationSnapshot:
    """
    组装 Generation Context 前的**结构化快照**。

    这是给 observability / tracing / debug 用的：
    以后你问「这一轮 prompt 里为什么出现了这条记忆？为什么关系阶段判定是信任？为什么
    情绪基线是这个数值？」，不用翻 prompt 文本，直接看 snapshot。
    """

    # 角色身份（静态 + 短期叙事）
    profile: CharacterProfile | None = None
    character_state: CharacterState | None = None
    speech_style: SpeechStyle | None = None

    # 情绪（v0.1 Emotion 系统的实时快照）
    emotion_pad: PADState | None = None
    emotion_stage: str = "stranger"
    emotion_rendered: str = ""

    # 关系（User ↔ Character）
    pair_state: PairState | None = None

    # 跨层检索结果（这一轮已经按用户 query 命中好）
    retrieval: RetrievalResult | None = None

    # 规则引用（给 LLM 的「不能做什么」提示摘要）
    behavioral_rules_hint: list[str] = field(default_factory=list)
    relationship_rules_hint: list[str] = field(default_factory=list)

    # 调试 / 审计：配置版本号
    meta: dict[str, Any] = field(default_factory=dict)

    def summary_for_trace(self) -> dict[str, Any]:
        """给 observability/trace 用的可序列化摘要。"""
        return {
            "profile_version": (
                self.profile.profile_version if self.profile else None
            ),
            "arc_stage": (
                self.character_state.arc_stage if self.character_state else None
            ),
            "emotion_pad": (
                self.emotion_pad.to_dict() if hasattr(self.emotion_pad, "to_dict") else None
            ),
            "emotion_stage": self.emotion_stage,
            "pair_axes": (
                self.pair_state.axes.as_dict() if self.pair_state else None
            ),
            "pair_stage": self.pair_state.stage if self.pair_state else None,
            "retrieved_raw_ids": [
                e.memory_id for e in (self.retrieval.raw_hits or [])
            ] if self.retrieval else [],
            "retrieved_semantic_keys": [
                e.key for e in (self.retrieval.semantic_hits or [])
            ] if self.retrieval else [],
            "behavioral_hint_count": len(self.behavioral_rules_hint),
            "relationship_hint_count": len(self.relationship_rules_hint),
            "meta": self.meta,
        }


class ContextBuilder:
    """
    对话前：
      1) read_snapshot(...)   —— 结构化读取所有状态（可被 tracing 记录）
      2) build_prompt(...)    —— 基于 snapshot 拼 prompt 文本

    两条设计原则：
      - read_snapshot 不触发 LLM，纯读
      - build_prompt 不触发 LLM，纯文本拼接
    """

    def __init__(
        self,
        *,
        recent_dialogue_rounds: int = 5,
        relevant_raw_memory_limit: int = 3,
        semantic_top_k: int = 8,
        semantic_min_confidence: float = 0.3,
        show_confidence_in_prompt: bool = True,
        system_prefix: str = (
            "你是角色扮演 AI。请始终以以下角色身份回复，不要打破角色，不要提及你是 AI。"
        ),
        extra_output_rules: str | None = None,
    ) -> None:
        self.recent_dialogue_rounds = recent_dialogue_rounds
        self.relevant_raw_memory_limit = relevant_raw_memory_limit
        self.semantic_top_k = semantic_top_k
        self.semantic_min_confidence = semantic_min_confidence
        self.show_confidence_in_prompt = show_confidence_in_prompt
        self.system_prefix = system_prefix
        self.extra_output_rules = extra_output_rules

    # =================== 阶段 1：结构化读取（read snapshot）====================
    def read_snapshot(
        self,
        *,
        user_message: str,
        # 推荐使用：新架构对象
        profile: CharacterProfile | None = None,
        character_state: CharacterState | None = None,
        speech_style: SpeechStyle | None = None,
        behavioral_rules: BehavioralRules | None = None,
        relationship_rules: RelationshipRules | None = None,
        pair_state: PairState | None = None,
        retriever: MemoryRetriever | None = None,
        # 情绪（v0.1 EmotionManager 或等价实现）
        emotion_manager: Any | None = None,
        emotion_pad: PADState | None = None,
        emotion_stage: str | None = None,
        # 兼容 v0.1：传 soul 对象即可兜底渲染 Profile+State
        soul: Any | None = None,
        # 额外元信息
        meta: dict[str, Any] | None = None,
    ) -> GenerationSnapshot:
        snap = GenerationSnapshot()

        # ---- Character Profile/State ----
        if profile is not None:
            snap.profile = profile
        elif soul is not None:
            snap.profile = self._profile_from_soul(soul)

        if character_state is not None:
            snap.character_state = character_state
        elif soul is not None:
            snap.character_state = self._character_state_from_soul(soul)

        if speech_style is not None:
            snap.speech_style = speech_style
        elif soul is not None:
            snap.speech_style = SpeechStyle.from_soul_fields(
                getattr(soul, "catchphrases", None),
                getattr(soul, "vocabulary", None),
            )

        # ---- Emotion ----
        if emotion_manager is not None:
            # 兼容 emotion/manager.EmotionManager 或 EmotionManagerV2
            pad = getattr(emotion_manager, "pad", None)
            stage = getattr(emotion_manager, "stage", None)
            if isinstance(pad, PADState):
                snap.emotion_pad = pad
            if isinstance(stage, str):
                snap.emotion_stage = stage
        if emotion_pad is not None:
            snap.emotion_pad = emotion_pad
        if emotion_stage is not None:
            snap.emotion_stage = emotion_stage
        # 注意：Context Builder 只「读」情绪当前状态，不更新它
        # （更新动作在 Harness 编排里、在 process_user_turn 之前完成，不在此处。
        #  这样能保证 build_prompt 是纯函数。）
        if snap.emotion_pad is not None:
            try:
                snap.emotion_rendered = render_emotion(
                    snap.emotion_pad, snap.emotion_stage or "stranger"
                )
            except Exception:
                snap.emotion_rendered = ""

        # ---- Relationship ----
        snap.pair_state = pair_state

        # ---- Retrieval（内存里已经存在的三层） ----
        if retriever is not None:
            snap.retrieval = retriever.query(
                user_message,
                recent_rounds_override=self.recent_dialogue_rounds,
                raw_limit_override=self.relevant_raw_memory_limit,
                semantic_limit_override=self.semantic_top_k,
            )

        # ---- Rules hints（只给 Evaluator 的基线规则摘要，不做具体违规判定） ----
        if behavioral_rules is not None:
            for r in behavioral_rules.effective_rules():
                text = f"- {r.description}"
                if r.hint_keywords:
                    text += f"（关键字 {'/'.join(r.hint_keywords[:3])}）"
                snap.behavioral_rules_hint.append(text)
        if relationship_rules is not None and snap.pair_state is not None:
            # 只提示「当前阶段适用」的约束，避免 prompt 被一堆无关规则淹没
            current_axes = snap.pair_state.axes.as_dict()
            violated_now = relationship_rules.match_violations(current_axes)
            # 加一点前瞻性：同时把阈值附近即将生效的规则也提示出来
            for rule in relationship_rules.effective_rules():
                # 已经触发的违规 → 标红式的"硬提示"
                if rule in violated_now:
                    snap.relationship_rules_hint.append(
                        f"- 【当前关系水平下禁止】{rule.description}\n"
                        f"   → 改写方向：{rule.rewrite_direction}"
                    )
        # ---- Meta ----
        snap.meta = dict(meta or {})
        return snap

    # =================== 阶段 2：组装 prompt 文本 ===================
    def build_prompt(
        self,
        snapshot: GenerationSnapshot,
        *,
        user_message: str | None = None,
    ) -> str:
        sections: list[str] = []
        sections.append(self.system_prefix)
        sections.append("")

        # 1) 角色设定
        character_desc = self._render_character_section(snapshot)
        if character_desc:
            sections.append("【角色设定】")
            sections.append(character_desc)
            sections.append("")

        # 2) 短期叙事状态（弧光/目标/mental notes）
        narrative = self._render_narrative_state_section(snapshot)
        if narrative:
            sections.append("【叙事当下】")
            sections.append(narrative)
            sections.append("")

        # 3) 情绪
        if snapshot.emotion_rendered:
            sections.append("【当前情绪】")
            sections.append(snapshot.emotion_rendered)
            sections.append("")

        # 4) 关系
        rel_section = self._render_relationship_section(snapshot)
        if rel_section:
            sections.append("【当前关系】")
            sections.append(rel_section)
            sections.append("")

        # 5) 行为规则 + 关系规则（基线约束摘要）
        rules_section = self._render_rules_hint_section(snapshot)
        if rules_section:
            sections.append("【底线约束】")
            sections.append(rules_section)
            sections.append("")

        # 6) 记忆（分 Semantic / Raw / 近期对话，按重要性降序呈现）
        memory_section = self._render_memory_section(snapshot)
        if memory_section:
            sections.append(memory_section)
            sections.append("")

        # 7) 输出规则（通用产品约束）
        output_rules = self._render_output_rules()
        sections.append("【指令】")
        if user_message is not None:
            name = self._character_name(snapshot)
            sections.append(
                f"请以「{name}」的身份，用符合角色性格、当前情绪与关系水平的语气，"
                f"回复用户的最新消息。"
            )
            sections.append(output_rules)
            sections.append(f"\n【用户最新消息】\n{user_message}\n")
            sections.append(f"{name}:")
        else:
            sections.append(output_rules)

        return "\n".join(sections)

    # =================== 子渲染器（每个 section 一个函数，便于单独测试） ===================
    def _render_character_section(self, s: GenerationSnapshot) -> str:
        lines: list[str] = []
        p = s.profile
        if p is None:
            return ""
        lines.append(f"姓名：{p.name}")
        lines.append(f"身份：{p.role}")
        if p.description:
            lines.append(f"简介：{p.description}")
        lines.append(f"核心性格特征：{'、'.join(p.core_traits) if p.core_traits else '—'}")
        lines.append(f"核心动机：{p.core_drive}")
        lines.append(f"深层恐惧：{p.fear}")
        if s.speech_style is not None:
            lines.append("—— 说话风格 ——")
            lines.append(s.speech_style.render_prompt_section())
        return "\n".join(lines)

    def _render_narrative_state_section(self, s: GenerationSnapshot) -> str:
        cs = s.character_state
        if cs is None:
            return ""
        lines: list[str] = []
        lines.append(f"弧光阶段：{cs.arc_stage}")
        lines.append(f"当前目标：{cs.current_goal}")
        if cs.mental_notes:
            lines.append("角色此刻的心智备忘（给你塑造态度和表情参考，不要直接念出来）：")
            for note in cs.mental_notes[-4:]:
                lines.append(f"- {note}")
        if cs.last_relationship_shift_summary:
            lines.append(
                f"最近一次关系变化：{cs.last_relationship_shift_summary}"
            )
        if cs.last_violation_summary:
            lines.append(
                f"上一轮被判定的问题（这一轮请务必避免）：{cs.last_violation_summary}"
            )
        return "\n".join(lines)

    def _render_relationship_section(self, s: GenerationSnapshot) -> str:
        ps = s.pair_state
        if ps is None:
            return ""
        lines: list[str] = []
        lines.append(f"关系阶段：{ps.stage_label}（{ps.stage}）")
        axes_names = {
            "familiarity": "熟悉度",
            "trust": "信任度",
            "emotional_closeness": "亲密度",
            "playfulness": "嬉玩度",
            "tension": "紧张度",
        }
        axes_lines = []
        for axis, value in ps.axes.as_dict().items():
            pct = int(round(value * 100))
            axes_lines.append(f"{axes_names.get(axis, axis)} {pct}%")
        lines.append("当前五轴值：" + " / ".join(axes_lines))
        last_changes = ps.last_change_summary(limit=3)
        if last_changes:
            lines.append("最近 3 次关系变化：")
            for c in last_changes:
                lines.append(f"- {c}")
        return "\n".join(lines)

    def _render_rules_hint_section(self, s: GenerationSnapshot) -> str:
        lines: list[str] = []
        if s.behavioral_rules_hint:
            lines.append("行为红线（绝对不能出现）：")
            lines.extend(s.behavioral_rules_hint[:8])
        if s.relationship_rules_hint:
            lines.append("关系水平限制（违反会被 Harness 重写）：")
            lines.extend(s.relationship_rules_hint[:6])
        return "\n".join(lines)

    def _render_memory_section(self, s: GenerationSnapshot) -> str:
        r = s.retrieval
        if r is None:
            return ""
        parts: list[str] = []

        # Semantic：最高重要性（用户画像/稳定知识）
        sem_lines = r.semantic_hit_texts(with_confidence=self.show_confidence_in_prompt)
        if sem_lines:
            parts.append("【用户画像（高置信度）】\n" + "\n".join(f"- {l}" for l in sem_lines))

        # Raw：具体事件
        raw_lines = r.raw_hit_texts()
        if raw_lines:
            parts.append("【相关事件记忆】\n" + "\n".join(f"- {l}" for l in raw_lines))
        else:
            parts.append("【相关事件记忆】\n（暂无命中的长期事件记忆）")

        # 近期对话
        if r.recent_messages:
            recent_lines: list[str] = []
            role_label = {"user": "用户", "assistant": "助手"}
            for m in r.recent_messages:
                label = role_label.get(m.get("role", ""), m.get("role", ""))
                recent_lines.append(f"{label}: {m.get('content','')}")
            parts.append("【近期对话】\n" + "\n".join(recent_lines))
        else:
            parts.append("【近期对话】\n（暂无近期对话）")

        return "\n\n".join(parts)

    def _render_output_rules(self) -> str:
        base = _ROLE_OUTPUT_RULES
        if self.extra_output_rules:
            base = base.rstrip() + "\n" + self.extra_output_rules
        return base

    def _character_name(self, s: GenerationSnapshot) -> str:
        if s.profile is not None:
            return s.profile.name or "角色"
        return "角色"

    # =================== v0.1 Soul 兼容构造（不是推荐路径，但能跑） ===================
    @staticmethod
    def _profile_from_soul(soul: Any) -> CharacterProfile:
        from character.profile import CharacterProfile

        def g(attr: str, default: Any = "") -> Any:
            return getattr(soul, attr, default)

        return CharacterProfile(
            name=str(g("name", "幽灵")),
            role=str(g("role", "星际赏金猎人")),
            description=str(g("role", "")),
            core_traits=list(g("core_traits") or ["坚韧", "多疑", "外冷内热"]),
            core_drive=str(
                g(
                    "core_drive",
                    "在法外之地维持脆弱的秩序，坚信'信息即货币，信誉高于生命'。",
                )
            ),
            fear=str(g("fear", "被最信任的系统背叛。")),
        )

    @staticmethod
    def _character_state_from_soul(soul: Any) -> CharacterState:
        from character.state import CharacterState

        return CharacterState(
            arc_stage=str(getattr(soul, "arc_stage", "起点")),
            current_goal=str(
                getattr(soul, "current_goal", "在涅克瑟斯星区获取下一份赏金契约。")
            ),
        )
