"""Harness v0.2 Context Builder + Memory Writer 全套 smoke tests。"""
from __future__ import annotations

import json

# ========== 1. SessionBuffer ==========
from memory.session_buffer import SessionBuffer
sb = SessionBuffer(max_messages=10)
sb.add("user", "你好")
sb.add("assistant", "嗯？什么事？")
sb2 = SessionBuffer.from_dict(sb.to_dict())
assert len(sb2.messages) == 2
assert sb2.messages[0].role == "user"
assert sb2.messages[1].content == "嗯？什么事？"
print("[OK] SessionBuffer round-trip")

# ========== 2. SemanticMemory（置信度 + evidence_count + 矛盾 + 待清理）==========
from memory.semantic_memory import (
    SemanticMemory, compute_confidence, _PENDING_CLEANUP_THRESHOLD,
)
assert round(compute_confidence(1, 0), 2) == 0.15  # 初始低！防单轮污染
c2 = compute_confidence(2, 0)
assert 0.15 < c2 < 0.98
cctr = compute_confidence(3, 2)
assert 0 < cctr < 0.6

sm = SemanticMemory(user_id=1)
e1, a1 = sm.upsert_candidate(key="likes_cats", value=True, bucket="preferences", raw_memory_ref="raw_001")
assert a1 == "created"
assert e1.confidence == 0.15 and e1.evidence_count == 1
conf_after_1 = e1.confidence  # 保存值，不是引用
# 单轮证据不应进入 Context Builder（get_for_context 默认 min_confidence=0.3）
assert e1 not in sm.get_for_context()

e2, a2 = sm.upsert_candidate(key="likes_cats", value=True, raw_memory_ref="raw_042")
assert a2 == "confirmed" and e2.evidence_count == 2
assert e2.confidence > conf_after_1, "第二次证据应提升 confidence"

# contradiction: 先加高 evidence，确保不触发 pending_cleanup 覆盖
for _ in range(5):
    sm.upsert_candidate(key="trusts_ai", value=True, bucket="flags")
e3, a3 = sm.upsert_candidate(key="trusts_ai", value=False, bucket="flags")
assert a3 == "contradicted", a3
assert e3.contradiction_count == 1, e3.contradiction_count
conf_before_contradiction = compute_confidence(6, 0)  # 6 次同向 + 0 矛盾
assert e3.confidence < conf_before_contradiction, "矛盾后 confidence 应下降"

# --- 用户原始需求：「最近想吃火锅」→ 单轮不应高置信 ---
sm_food = SemanticMemory(user_id=1)
fe1, fa1 = sm_food.upsert_candidate(key="pref_food_hotpot", value=True, bucket="preferences", raw_memory_ref="raw_101")
assert fa1 == "created"
assert fe1.confidence == 0.15, f"单轮 evidence_count=1 → confidence 必须 0.15, got {fe1.confidence}"
assert fe1 not in sm_food.get_for_context(), "单轮证据不应进入 Context Builder"

# 第 2 轮矛盾：「其实我更爱吃日料」→ 同 key 不同 value
# 只有 1 次证据，confidence=0.15，1 次矛盾后 confidence → 0.0 < 0.2 → pending_cleanup
# 但「不立即删除」：只标记，不覆盖（用户要求）
fe2, fa2 = sm_food.upsert_candidate(key="pref_food_hotpot", value="sushi", bucket="preferences", raw_memory_ref="raw_102")
assert fa2 == "contradicted", fa2
assert fe2.contradiction_count == 1
assert fe2.pending_cleanup, "1 证据 + 1 矛盾 → confidence <0.2 → 待清理"
assert fe2.value is True, "旧值应保留，不被新值覆盖"

# 清理后，pending 条目被移除
removed = sm_food.cleanup_pending()
assert removed >= 1
assert "pref_food_hotpot" not in sm_food.buckets["preferences"]

# 14 次同向证据后 confidence ≈ 0.92（用户示例数据）
sm_cats = SemanticMemory(user_id=1)
for i in range(14):
    sm_cats.upsert_candidate(key="likes_cats", value=True, bucket="preferences", raw_memory_ref=f"raw_{i:03d}")
ec = sm_cats.buckets["preferences"]["likes_cats"]
assert ec.evidence_count == 14
assert ec.confidence > 0.9, f"14 次证据 confidence 应 >0.9, got {ec.confidence}"
assert len(ec.evidence_refs) > 0, "应有 evidence_refs"
# 高置信度条目应该进入 Context Builder
assert ec in sm_cats.get_for_context()

# 序列化格式与用户要求的 JSON 一致
d = sm_cats.to_dict()
assert d["schema_version"] == "2.0"
assert d["user_id"] == 1
assert "preferences" in d and len(d["preferences"]) == 1
entry_d = d["preferences"][0]
for field_name in ("key", "value", "confidence", "evidence_count",
                    "contradiction_count", "first_observed", "last_confirmed",
                    "evidence_refs"):
    assert field_name in entry_d, f"序列化缺字段 {field_name}"
print("[OK] SemanticMemory: 置信度 + evidence_count + 矛盾 + pending_cleanup + get_for_context 过滤 + 序列化格式")

# ========== 3. PairState（五轴 + cause-required + 衰减 + 阶段 + 序列化）==========
from relationship.pair_state import PairState, RelationshipChange
ps = PairState(subject_type="user", subject_id=1, target_type="character", target_id=5)

# cause 必填：空 cause 直接 ValueError
try:
    RelationshipChange(axis="trust", old_value=0.5, new_value=0.6, delta=0.1, cause="")
    raise AssertionError("空 cause 应该 ValueError")
except ValueError:
    pass

# 用户示例场景：trust 0.58 → 0.62，cause 带完整人话
ch = ps.update_axis(
    "trust", 0.04,
    cause="用户主动透露了非常个人化的信息(小时候宠物走失)，角色给予回应后用户表示'你真的懂我'",
    raw_memory_ref="raw_mem_042",
    evaluator_version="harness-evals:1.3",
    turn_id="t042",
)
assert ch.axis == "trust" and ch.delta > 0
assert round(ch.new_value, 2) == 0.04
assert "你真的懂我" in ch.cause
assert ch.raw_memory_ref == "raw_mem_042"
assert ch.evaluator_version == "harness-evals:1.3"
assert ps.stage in ("stranger", "acquaintance")  # trust=0.04 还很低

# 多轴同时更新（模拟一轮对话影响多个轴）
ps.update_axis("familiarity", 0.30, cause="用户自报姓名和职业", turn_id="t043")
ps.update_axis("emotional_closeness", 0.25, cause="用户分享了童年回忆", turn_id="t043")
ps.update_axis("playfulness", 0.20, cause="用户开了个玩笑，角色接住了", turn_id="t043")
assert ps.axes.familiarity > 0.2
assert ps.axes.trust < 0.2
assert ps.stage == "acquaintance"  # familiarity >= 0.2 → acquaintance

# 衰减：不互动时 axes 缓慢回落
old_fam = ps.axes.familiarity
ps.apply_passive_decay(rounds=5)
assert ps.axes.familiarity < old_fam, "5 轮衰减后 familiarity 应下降"
assert ps.axes.familiarity > 0, "但不应归零（2%/轮 很慢）"

# tension 高 → conflict 阶段
ps_t = PairState(subject_type="user", subject_id=1, target_type="character", target_id=5)
ps_t.update_axis("tension", 0.60, cause="用户和角色发生了严重争吵", turn_id="t099")
ps_t.update_axis("emotional_closeness", 0.10, cause="争吵后情感疏远", turn_id="t099")
assert ps_t.stage == "conflict", f"tension=0.6, closeness=0.1 应判冲突, got {ps_t.stage}"

# 序列化格式与用户要求 JSON 一致
d = ps.to_dict()
assert d["schema_version"] == "1.0"
assert d["subject_type"] == "user" and d["subject_id"] == 1
assert d["target_type"] == "character" and d["target_id"] == 5
assert "axes" in d and "familiarity" in d["axes"] and "trust" in d["axes"]
assert "stage" in d, "序列化应包含 stage 派生字段"
assert "history" in d and len(d["history"]) >= 3
h0 = d["history"][0]
for fn in ("timestamp", "axis", "old_value", "new_value", "delta", "cause", "raw_memory_ref", "evaluator_version"):
    assert fn in h0, f"history 条目缺字段 {fn}"

# 群聊预留：subject_type / target_type 不硬编码 user/character
ps_cc = PairState(subject_type="character", subject_id=5, target_type="character", target_id=7)
ps_cc.update_axis("trust", 0.10, cause="角色A帮角色B解了围", turn_id="cc01")
assert ps_cc.subject_type == "character" and ps_cc.target_type == "character"

# last_change_summary 给 prompt 注入用
summaries = ps.last_change_summary(limit=3)
assert len(summaries) >= 1
assert any(k in summaries[0] for k in ("信任度", "熟悉度", "亲密度", "嬉玩度")), summaries[0]
print("[OK] PairState: 五轴 + cause-required + 衰减 + 阶段判定 + 群聊预留 + 序列化含 stage")

# ========== 3b. World / Social State 预留（接口签名约束 + 目录占位） ==========
import inspect
from relationship import (
    load_pair_state_by_id, save_pair_state_by_id, pair_state_file_path,
)

# 接口签名约束：按 (subject_type, subject_id, target_type, target_id) 查询，不硬编码 user/character
sig_load = inspect.signature(load_pair_state_by_id)
for p in ("subject_type", "subject_id", "target_type", "target_id", "base_dir"):
    assert p in sig_load.parameters, f"load_pair_state_by_id 缺参数 {p}"
# 不应出现 user_id / character_id 这种硬编码参数
assert "user_id" not in sig_load.parameters and "character_id" not in sig_load.parameters, \
    "load_pair_state_by_id 不应硬编码 user_id/character_id"

sig_save = inspect.signature(save_pair_state_by_id)
for p in ("state", "base_dir"):
    assert p in sig_save.parameters, f"save_pair_state_by_id 缺参数 {p}"

# 群聊签名扩展：character ↔ character 无需改签名即可调用
import tempfile
with tempfile.TemporaryDirectory() as tmp_dir:
    ps_g = PairState(subject_type="character", subject_id=5,
                     target_type="character", target_id=7)
    ps_g.update_axis("trust", 0.10, cause="A 帮 B 解了围", turn_id="cc01")
    out_path = save_pair_state_by_id(ps_g, base_dir=tmp_dir)
    assert "character_5" in out_path and "character_7" in out_path, out_path

    # 按身份四元组加载回来，状态保持
    loaded = load_pair_state_by_id("character", 5, "character", 7, base_dir=tmp_dir)
    assert loaded.subject_type == "character" and loaded.target_type == "character"
    assert abs(loaded.axes.trust - 0.10) < 1e-6
    assert loaded.history and loaded.history[0].cause == "A 帮 B 解了围"

# future/social_graph 占位：SocialGraph 不应可实例化（落地前禁止误用）
from relationship.future import social_graph as sg_mod
assert hasattr(sg_mod, "SocialGraph"), "future/social_graph.py 必须有 SocialGraph 占位 class"
try:
    sg_mod.SocialGraph()
    raise AssertionError("SocialGraph 占位类不应可实例化")
except NotImplementedError:
    pass

print("[OK] World/Social State 预留: load/save_pair_state_by_id 群聊扩展签名 + future/social_graph 占位")

# ========== 4. MemoryImportanceEvaluator（四层写入门槛）=========
from memory_writer import MemoryImportanceEvaluator, ENABLE_LLM_MEMORY_GATE
ev = MemoryImportanceEvaluator()

# is_worth_remembering：简单 bool 接口
assert ev.is_worth_remembering("我小时候养过一只金毛，后来它生病走了", "（静静听着，递了杯热茶）") is True
assert ev.is_worth_remembering("哈哈哈哈", "嗯嗯嗯") is False
assert ev.is_worth_remembering("好饿", "去吃点东西") is False
# "今天食堂鸡腿挺好吃" 这种不应该进 Raw Memory（用户的原始需求）
assert ev.is_worth_remembering("今天食堂鸡腿挺好吃", "是吗，那挺好") is False
# 但 "我叫林墨，上海人" 这种应该进
assert ev.is_worth_remembering("我叫林墨，上海人，工作三年了。我不喜欢恐怖片。", "（记在小本子上）上海人啊") is True

# is_worth_raw_memory：带 reason 的接口（tracing 用）
ok, reason = ev.is_worth_raw_memory("我小时候养过一只金毛", "（点头）")
assert ok is True and "强信号" in reason, (ok, reason)
ok2, reason2 = ev.is_worth_raw_memory("好饿", "去吃点东西")
assert ok2 is False, reason2

# 灰区：默认保守不写（ENABLE_LLM_MEMORY_GATE=False）
ok3, reason3 = ev.is_worth_raw_memory("今天看了一部很有意思的电影，讲的是关于时间旅行的", "听起来不错，讲的什么？")
assert ok3 is False and "灰区" in reason3, (ok3, reason3)

# 灰区：开 LLM gate 后通过 llm_judge_fn 判断
import memory_writer as _mw
_mw.ENABLE_LLM_MEMORY_GATE = True
ok4, reason4 = ev.is_worth_raw_memory(
    "今天看了一部很有意思的电影，讲的是关于时间旅行的",
    "听起来不错，讲的什么？",
    llm_judge_fn=lambda u, a: True,
)
assert ok4 is True and "LLM" in reason4, (ok4, reason4)
_mw.ENABLE_LLM_MEMORY_GATE = False  # 恢复

# 向后兼容别名
from memory_writer import MemoryWriteGate
assert MemoryWriteGate is MemoryImportanceEvaluator
print("[OK] MemoryImportanceEvaluator (四层写入门槛 + is_worth_remembering + 灰区 LLM 开关 + 向后兼容)")

# ========== 5. ContextBuilder ==========
from context_builder import ContextBuilder
from character.profile import CharacterProfile
from character.state import CharacterState
from character.speech_style import SpeechStyle
from character.behavioral_rules import BehavioralRules
from character.relationship_rules import RelationshipRules
from memory.retrieval import MemoryRetriever
from memory.raw_memory import RawMemory

sb_c = SessionBuffer(max_messages=20)
sb_c.add("user", "我小时候特别怕黑")
retriever = MemoryRetriever(sb_c, RawMemory(), SemanticMemory(user_id=1), prefer_vector=False)
ps_c = PairState()
ps_c.update_axis("trust", 0.35, cause="用户主动聊童年往事")

profile = CharacterProfile(
    name="Anya", role="太空走私船船长",
    core_traits=["嘴硬", "心软"],
    core_drive="把货安全送到",
    fear="同伴被背叛",
)
cs = CharacterState(
    current_goal="送完这批货就去休假",
    arc_stage="起点",
    mental_notes=["用户刚才提到了害怕黑暗"],
)
cb = ContextBuilder()
snap = cb.read_snapshot(
    user_message="我小时候特别怕黑，现在还好。",
    profile=profile,
    character_state=cs,
    speech_style=SpeechStyle(catchphrases=["啧"]),
    behavioral_rules=BehavioralRules(),
    relationship_rules=RelationshipRules(),
    pair_state=ps_c,
    retriever=retriever,
)
prompt = cb.build_prompt(snap, user_message="我小时候特别怕黑，现在还好。")
for tok in ("Anya", "太空走私船船长", "嘴硬", "心软", "把货安全送到",
            "同伴被背叛", "送完这批货就去休假", "弧光阶段", "害怕黑暗",
            "信任度", "近期对话", "底线约束", "啧"):
    assert tok in prompt, f"MISSING TOKEN: {tok!r}"
lines = [l for l in prompt.splitlines() if l.strip()]
assert lines[-1] == "Anya:", lines[-1]
# snapshot 摘要可追溯
snap.summary_for_trace()
print("[OK] ContextBuilder snapshot + prompt 组装")

# ========== 6. MemoryWriter 流程 1：正常披露内容（Gate 通过） ==========
from memory_writer import MemoryWriter
sb_w = SessionBuffer(max_messages=20)
rm_w = RawMemory()
sem_w = SemanticMemory(user_id=1)
ps_w = PairState(subject_type="user", subject_id=1, target_type="character", target_id=5)
cstate_w = CharacterState()
writer = MemoryWriter()
res1 = writer.write_turn(
    user_message="我小时候养过一只金毛，后来它生病走了，我特别难过",
    ai_response="……（轻轻递了杯热茶）这种事，我懂。",
    session_buffer=sb_w, raw_memory=rm_w, semantic_memory=sem_w,
    pair_state=ps_w, character_state=cstate_w,
    turn_id="t_001", session_id="s_001",
    extractor_candidates=[
        {"fact":"用户小时候养过一只金毛犬","importance":4,"category":"fact"},
        {"fact":"用户的金毛因病去世","importance":4,"category":"event"},
        {"fact":"用户因宠物去世曾非常难过","importance":3,"category":"preference_hint"},
    ],
    relationship_delta_suggestions=[
        {"axis":"emotional_closeness","delta":0.04,
         "cause":"用户主动透露了非常个人化的信息（童年宠物离世），角色给予了共情回应"},
    ],
)
assert res1.gate_passed, res1.gate_reason
assert res1.session_buffer_added == 2
assert len(res1.raw_added) == 3
assert res1.raw_category_count.get("fact") == 1
assert res1.raw_category_count.get("event") == 1
sem_created = [u for u in res1.semantic_upserts if u["action"] in ("created","confirmed")]
assert len(sem_created) >= 1, f"no sem upserts: {res1.semantic_upserts}"
assert len(res1.relationship_changes) == 1
assert res1.relationship_changes[0]["axis"] == "emotional_closeness"
assert "last_relationship_shift_summary 已同步" in res1.character_state_updates
print("[OK] MemoryWriter flow 1: Gate 通过 + 三层写 + Character State 同步")

# ========== 7. MemoryWriter 流程 2：纯闲聊（Gate 不通过 → 只写 Session Buffer） ==========
sb_w2 = SessionBuffer(max_messages=20)
rm_w2 = RawMemory(); sem_w2 = SemanticMemory(user_id=1)
ps_w2 = PairState(); cstate_w2 = CharacterState()
res2 = writer.write_turn(
    user_message="哈哈哈哈哈哈哈", ai_response="嗯嗯嗯23333",
    session_buffer=sb_w2, raw_memory=rm_w2, semantic_memory=sem_w2,
    pair_state=ps_w2, character_state=cstate_w2, turn_id="t_002",
    extractor_candidates=[],
)
assert res2.gate_passed is False
assert res2.session_buffer_added == 2
assert len(res2.raw_added) == 0
assert len(res2.semantic_upserts) == 0
print("[OK] MemoryWriter flow 2: 纯闲聊 Gate 不通过 → 只写 Session Buffer")

# ========== 8. MemoryWriter 流程 3：unified_analyzer 模式 + narrative 同步 ==========
sb_w3 = SessionBuffer(max_messages=20)
rm_w3 = RawMemory(); sem_w3 = SemanticMemory(user_id=1)
ps_w3 = PairState(); cstate_w3 = CharacterState(current_goal="初始目标", arc_stage="起点")
res3 = writer.write_turn(
    user_message="我叫林墨，上海人，工作三年了。我不喜欢恐怖片。",
    ai_response="林墨……上海。记住了。不喜欢恐怖片的话，下次我不会选这种。",
    session_buffer=sb_w3, raw_memory=rm_w3, semantic_memory=sem_w3,
    pair_state=ps_w3, character_state=cstate_w3,
    turn_id="t_003",
    extractor_candidates=[
        {"fact":"用户名叫林墨","importance":5,"category":"fact"},
        {"fact":"用户来自上海","importance":3,"category":"fact"},
        {"fact":"用户不喜欢恐怖片","importance":3,"category":"preference_hint"},
    ],
    analyzer_semantic_candidates=[
        {"key":"display_name","value":"林墨","bucket":"identity","raw_memory_ref":"x"},
        {"key":"city_of_residence","value":"上海","bucket":"identity","raw_memory_ref":"x"},
        {"key":"dislikes_horror_movies","value":True,"bucket":"preferences","raw_memory_ref":"x"},
    ],
    analyzer_narrative={
        "should_update": True,
        "arc_stage": "转折点",
        "current_goal": "熟悉林墨的背景，约定下次在上海线下见面的可能",
        "reason": "用户首次完整透露了真实身份+居住地+偏好，相当于自我披露里程碑",
    },
    relationship_delta_suggestions=[
        {"axis":"familiarity","delta":0.08,"cause":"用户首次透露真实姓名+城市+偏好"},
        {"axis":"trust","delta":0.03,"cause":"用户愿意把基础身份信息共享给角色"},
    ],
)
assert res3.gate_passed is True
keys = {u["key"] for u in res3.semantic_upserts}
assert keys >= {"display_name","city_of_residence","dislikes_horror_movies"}, keys
assert cstate_w3.arc_stage == "转折点", cstate_w3.arc_stage
assert cstate_w3.current_goal.startswith("熟悉林墨的背景")
axes_upd = {rc["axis"] for rc in res3.relationship_changes}
assert axes_upd == {"familiarity","trust"}, axes_upd

# PairState 序列化可恢复
ps_back = PairState.from_dict(json.loads(json.dumps(ps_w3.to_dict())))
assert abs(ps_back.axes.trust - 0.03) < 1e-4
assert abs(ps_back.axes.familiarity - 0.08) < 1e-4
assert len(ps_back.history) == 2
assert ps_back.stage in ("stranger", "acquaintance")
print("[OK] MemoryWriter flow 3: analyzer_semantic + narrative + relationship 持久化")

# ========== 9. GenerationSnapshot.summary_for_trace 字段存在 ==========
summary = snap.summary_for_trace()
assert "profile_version" in summary
assert "arc_stage" in summary
assert "pair_stage" in summary
print("[OK] GenerationSnapshot 可序列化为 observability/trace 友好的 dict")

print()
# ========== 9b. Harness 诊断报告 + 重生成循环 ==========
from scoring.engine import diagnose, build_rewrite_prompt, DiagnosisReport, Violation

# 场景 1：角色"冷淡慢热"，但 AI 回复了"我爱你" → 应有 violation
diag1 = diagnose(
    user_message="今天怎样",
    bot_reply="我爱你，宝贝，我好喜欢你",
    character={"display_name": "林月", "description": "冷淡、慢热、不主动表达爱意、克制"},
    pair_axes={"emotional_closeness": 0.15, "trust": 0.05},
    relationship_stage="stranger",
)
assert not diag1.passed, "冷淡角色在陌生人阶段说'我爱你'不应该通过"
assert len(diag1.violations) >= 2, f"应至少有2条violation(人设+关系), got {len(diag1.violations)}"
violation_types = [v.type for v in diag1.violations]
assert "expression_too_direct" in violation_types, violation_types
assert "relationship_stage_mismatch" in violation_types, violation_types
assert any(v.severity == "high" for v in diag1.violations)
assert diag1.rewrite_instruction, "应有聚合后的 rewrite_instruction"
assert "隐晦" in diag1.rewrite_instruction or "降低" in diag1.rewrite_instruction, diag1.rewrite_instruction

# 场景 2：正常回复 → pass（分数 ≥60 且无 high/fatal violation）
diag2 = diagnose(
    user_message="你好啊林月，今天怎么样",
    bot_reply="还行吧，就是有些无聊。你呢，今天做什么了？",
    character={"display_name": "林月", "description": "冷淡、慢热"},
    pair_axes={"emotional_closeness": 0.1, "trust": 0.05},
    relationship_stage="stranger",
)
assert diag2.passed, f"正常冷淡回复应通过(score={diag2.scores.get('total_score')}), got violations: {diag2.violations}"

# 场景 3：情绪不匹配（低愉悦但回复欢快）
diag3 = diagnose(
    user_message="你还好吗",
    bot_reply="哈哈哈太开心了！",
    character={"display_name": "林月", "description": "冷淡"},
    pad_state={"pleasure": 2.0, "arousal": 3.0, "dominance": 5.0},
)
assert not diag3.passed or any(v.type == "emotion_mismatch_low_pleasure" for v in diag3.violations)

# 场景 4：build_rewrite_prompt 生成重生成 prompt
rewrite_prompt = build_rewrite_prompt(
    original_prompt="你是林月。林月:",
    diagnosis=diag1,
    user_message="今天怎样",
    character_name="林月",
)
assert "重生成要求" in rewrite_prompt
assert "expression_too_direct" in rewrite_prompt or "表达爱意过于直接" in rewrite_prompt
assert "修改建议" in rewrite_prompt
assert "林月" in rewrite_prompt

# 场景 5：DiagnosisReport.to_dict() 序列化格式与用户要求一致
d = diag1.to_dict()
for key in ("scores", "passed", "violations", "rewrite_instruction", "evaluator_version", "evaluator_method"):
    assert key in d, f"诊断报告缺字段 {key}"
v0 = d["violations"][0]
for key in ("type", "severity", "description", "evidence", "rewrite_hint"):
    assert key in v0, f"violation 缺字段 {key}"
assert d["evaluator_version"] == "harness-evals:2.0"
assert d["evaluator_method"] == "rule"

# 场景 6：attempt 字段（重生成计数）
diag_attempt = diagnose("test", "ok", None, attempt=2)
assert diag_attempt.attempt == 2
print("[OK] Harness 诊断报告: 三维诊断 + violations + rewrite_instruction + build_rewrite_prompt + 序列化")

# ========== 9c. 失败候选不进 Memory + 评估链路完整 ==========
from logger import Logger

log = Logger(session_id="test_eval_link")

# 模拟「候选→拒绝→重写→采纳」链路
# 候选 0：被拒绝
log.log_candidate(
    "我爱你，宝贝，我好喜欢你",
    diagnosis={
        "passed": False,
        "violations": [{"type": "expression_too_direct", "severity": "high"}],
        "rewrite_instruction": "把直接告白改成隐晦表达",
        "scores": {"total_score": 45.0},
    },
    attempt=0, accepted=False,
)
# 候选 1：通过
log.log_candidate(
    "…嗯，你也在。无聊就坐那儿吧。",
    diagnosis={
        "passed": True,
        "violations": [],
        "rewrite_instruction": "",
        "scores": {"total_score": 72.0},
    },
    attempt=1, accepted=True,
)
# 记录完整链路
log.log_evaluation_link(
    user_message="今天怎样",
    candidates=[
        {"candidate": "我爱你，宝贝", "passed": False, "attempt": 0},
        {"candidate": "…嗯，你也在。", "passed": True, "attempt": 1},
    ],
    final_accepted_index=1,
    total_regen_count=1,
)

logs = log.get_logs()
# 验证 evaluation_candidate 条目
candidates = [e for e in logs if e["type"] == "evaluation_candidate"]
assert len(candidates) == 2, f"应有2个候选记录, got {len(candidates)}"
assert candidates[0]["data"]["accepted"] is False  # 第一个被拒绝
assert candidates[1]["data"]["accepted"] is True   # 第二个被采纳
assert candidates[0]["data"]["violations"] is not None  # 被拒绝的有 violations
assert candidates[1]["data"]["violations"] == [] or candidates[1]["data"]["violations"] is None

# 验证 evaluation_link 条目
links = [e for e in logs if e["type"] == "evaluation_link"]
assert len(links) == 1
link_data = links[0]["data"]
assert link_data["candidates_count"] == 2
assert link_data["final_accepted_index"] == 1
assert link_data["total_regen_count"] == 1
assert link_data["candidates"][0]["passed"] is False
assert link_data["candidates"][1]["passed"] is True

# 验证 score_logs 新字段（DiagnosisReport.to_dict 含 candidates）
from scoring.engine import diagnose, Violation, DiagnosisReport
diag = diagnose(
    "今天怎样", "我爱你，宝贝",
    character={"display_name": "林月", "description": "冷淡、慢热、克制"},
    pair_axes={"emotional_closeness": 0.1},
    relationship_stage="stranger",
)
diag_dict = diag.to_dict()
assert "violations" in diag_dict and len(diag_dict["violations"]) > 0
assert diag_dict["rewrite_instruction"]
assert diag_dict["evaluator_version"] == "harness-evals:2.0"
assert diag_dict["evaluator_method"] == "rule"

# 验证 persist_score_log 新参数签名
import inspect
from scoring.engine import persist_score_log
sig = inspect.signature(persist_score_log)
for param in ("diagnosis", "candidates", "final_accepted_index", "regen_count"):
    assert param in sig.parameters, f"persist_score_log 缺少参数 {param}"

# 验证 Memory Writer 只读 final_response（不读 candidates）
# _generate_with_diagnosis 返回 (ai_response, diag_dict)
# diag_dict 含 candidates 数组，但 _finalize_turn 只传 ai_response 给 _post_process_turn
# _post_process_turn → MemoryWriter.write_turn(user_msg, ai_response, ...)
# candidates 数组在 diag_dict 里，只传给 score_and_persist 做审计
from memory_writer import MemoryWriter
sig_mw = inspect.signature(MemoryWriter.write_turn)
assert "candidates" not in sig_mw.parameters, "MemoryWriter.write_turn 不应接受 candidates 参数"
assert "ai_response" in sig_mw.parameters or "response" in sig_mw.parameters, "MemoryWriter.write_turn 应接受最终回复"

# 验证 TurnResult 含 diagnosis 字段
import harness_core
sig_tr = inspect.signature(harness_core.TurnResult)
assert "diagnosis" in sig_tr.parameters, "TurnResult 应有 diagnosis 字段"

print("[OK] 失败候选不进 Memory + 评估链路完整(log_candidate + log_evaluation_link + score_logs 新字段)")

print("===== ALL SMOKE TESTS PASSED =====")
