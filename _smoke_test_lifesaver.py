"""三个救命设计 smoke tests：Versioning / Observability / 成本预算。"""
from __future__ import annotations

import inspect
from observability import TurnStep, TurnTrace, new_turn_id


# ========== 1. Versioning（11.1）==========
# 所有需要版本号的对象都有 schema_version / *_VERSION 常量

# 1a. CharacterProfile
from character.profile import CharacterProfile, CHARACTER_PROFILE_SCHEMA_VERSION
prof = CharacterProfile(name="测试", role="测试角色")
assert hasattr(prof, "schema_version"), "CharacterProfile 必须有 schema_version 字段"
assert prof.schema_version == CHARACTER_PROFILE_SCHEMA_VERSION
prof_d = prof.to_dict()
assert "schema_version" in prof_d, "CharacterProfile.to_dict() 必须输出 schema_version"
assert prof_d["schema_version"] == CHARACTER_PROFILE_SCHEMA_VERSION
print(f"[OK] CharacterProfile.schema_version = {CHARACTER_PROFILE_SCHEMA_VERSION}")

# 1b. RawMemory
from memory.raw_memory import RawMemory, RAW_MEMORY_SCHEMA_VERSION
rm = RawMemory()
assert hasattr(rm, "schema_version") and rm.schema_version == RAW_MEMORY_SCHEMA_VERSION
assert "schema_version" in rm.to_dict()
print(f"[OK] RawMemory.schema_version = {RAW_MEMORY_SCHEMA_VERSION}")

# 1c. SemanticMemory
from memory.semantic_memory import SemanticMemory, SEMANTIC_MEMORY_SCHEMA_VERSION
sm = SemanticMemory(user_id=1)
assert hasattr(sm, "schema_version") and sm.schema_version == SEMANTIC_MEMORY_SCHEMA_VERSION
assert "schema_version" in sm.to_dict()
print(f"[OK] SemanticMemory.schema_version = {SEMANTIC_MEMORY_SCHEMA_VERSION}")

# 1d. PairState
from relationship.pair_state import PairState, RELATIONSHIP_STATE_SCHEMA_VERSION
ps = PairState()
assert ps.schema_version == RELATIONSHIP_STATE_SCHEMA_VERSION
assert "schema_version" in ps.to_dict()
print(f"[OK] PairState.schema_version = {RELATIONSHIP_STATE_SCHEMA_VERSION}")

# 1e. DiagnosisReport（每条诊断报告带 evaluator_version）
from scoring.engine import DiagnosisReport, EVALUATOR_VERSION, diagnose
diag = diagnose("hi", "ok", None)
assert diag.evaluator_version == EVALUATOR_VERSION
assert "evaluator_version" in diag.to_dict()
print(f"[OK] DiagnosisReport.evaluator_version = {EVALUATOR_VERSION}")

# 1f. Safety rules version（新增）
from safety.loader import SAFETY_RULES_VERSION, get_rules_version
assert SAFETY_RULES_VERSION == get_rules_version()
print(f"[OK] safety.loader.SAFETY_RULES_VERSION = {SAFETY_RULES_VERSION}")

# 1g. Scoring rules version（新增）
from scoring.config import SCORING_RULES_VERSION
assert SCORING_RULES_VERSION
print(f"[OK] scoring.config.SCORING_RULES_VERSION = {SCORING_RULES_VERSION}")

# 1h. trace 自身也带 schema_versions 快照
trace_v = TurnTrace(turn_id="t_v", user_message="hi")
trace_v.schema_versions = {"profile": CHARACTER_PROFILE_SCHEMA_VERSION}
assert "schema_versions" in trace_v.to_dict()
print("[OK] TurnTrace.schema_versions 用于审计回溯")

print()


# ========== 2. Observability（11.2 链路追踪）==========

# 2a. TurnStep / TurnTrace 数据类
step = TurnStep(step_name="context_built", detail={"prompt_tokens_approx": 1200})
step.mark_end()
assert step.end_ts != "", "mark_end 必须补 end_ts"
assert step.to_dict()["step_name"] == "context_built"
print("[OK] TurnStep: step_name + start_ts/end_ts + detail 可序列化")

# 2b. TurnTrace 生命周期：begin_step / end_step / add_step / finalize
trace = TurnTrace(turn_id=new_turn_id(), user_message="测试 trace")
s1 = trace.begin_step("context_built")
trace.end_step(s1, detail={"prompt_tokens_approx": 1200, "axes_values_at_turn": {"trust": 0.62}})

trace.add_step(TurnStep(
    step_name="llm_generated",
    detail={"candidate_preview": "我爱你...", "tokens": 15, "attempt": 0},
).mark_end())

trace.add_step(TurnStep(
    step_name="harness_evaluated",
    detail={"scores": {"total_score": 40.0}, "violations": [{"type": "expression_too_direct"}], "passed": False},
).mark_end())

trace.add_step(TurnStep(
    step_name="regen_attempt",
    detail={"attempt": 1, "triggered_by_violation": "expression_too_direct"},
).mark_end())

trace.add_step(TurnStep(
    step_name="llm_generated",
    detail={"candidate_preview": "……谁让你这么晚还不回来", "tokens": 20, "attempt": 1},
).mark_end())

trace.add_step(TurnStep(
    step_name="harness_evaluated",
    detail={"scores": {"total_score": 82.0}, "violations": [], "passed": True, "attempt": 1},
).mark_end())

trace.add_step(TurnStep(
    step_name="memory_written",
    detail={"raw_added": 1, "semantic_updated": 0, "relationship_updated": {"trust": "+0.04"}, "gate_passed": True},
).mark_end())

trace.finalize(duration_ms=1234.5)

assert trace.finalized
assert trace.final_duration_ms == 1234.5
assert trace.list_step_names() == [
    "context_built", "llm_generated", "harness_evaluated",
    "regen_attempt", "llm_generated", "harness_evaluated",
    "memory_written",
], trace.list_step_names()

# 序列化
td = trace.to_dict()
for key in ("turn_id", "user_message", "steps", "schema_versions", "finalized", "final_duration_ms"):
    assert key in td, f"TurnTrace.to_dict() 缺字段 {key}"
assert len(td["steps"]) == 7
print(f"[OK] TurnTrace: {len(td['steps'])} 步骤链路完整 + finalize + 可序列化")

# 2c. logger.py 升级为链路追踪
from logger import Logger

log = Logger(session_id="test_trace")
# 单步写入
log.log_turn_step("t_001", "context_built", {"prompt_tokens_approx": 1000})
# 整轮 trace 落盘
log.log_turn_trace(trace)

logs = log.get_logs()
step_entries = [e for e in logs if e["type"] == "turn_step"]
trace_entries = [e for e in logs if e["type"] == "turn_trace"]
assert len(step_entries) == 1
assert step_entries[0]["data"]["step_name"] == "context_built"
assert step_entries[0]["data"]["turn_id"] == "t_001"
assert len(trace_entries) == 1
assert trace_entries[0]["data"]["turn_id"] == trace.turn_id
assert len(trace_entries[0]["data"]["steps"]) == 7
print("[OK] logger.log_turn_step / log_turn_trace 落盘完整")

# 2d. harness_core 引擎已注入 trace 调用点（静态扫描关键方法）
import harness_core

# process_message / _generate_with_diagnosis / _finalize_turn 内必须出现 _trace_log_step
def _func_body_text(func) -> str:
    """返回函数源代码字符串。"""
    import ast
    import inspect as _ins
    try:
        src = _ins.getsource(func)
        return src
    except (OSError, TypeError):
        return ""

pm_body = _func_body_text(harness_core.HarnessEngine.process_message)
assert "_begin_trace" in pm_body and "_finalize_trace" in pm_body, \
    "process_message 必须含 _begin_trace / _finalize_trace 调用"
assert "_trace_log_step" in pm_body, "process_message 必须含至少一个 _trace_log_step"
assert "context_built" in pm_body, "process_message 必须记录 context_built step"
assert "turn_finalized" in pm_body, "process_message 必须记录 turn_finalized step"

gd_body = _func_body_text(harness_core.HarnessEngine._generate_with_diagnosis)
for sn in ("llm_generated", "harness_evaluated", "regen_attempt"):
    assert sn in gd_body, f"_generate_with_diagnosis 必须记录 {sn} step"

ft_body = _func_body_text(harness_core.HarnessEngine._finalize_turn)
assert "memory_written" in ft_body, "_finalize_turn 必须记录 memory_written step"

print("[OK] harness_core 三个核心方法已注入 trace 调用点")

print()


# ========== 3. 成本与延迟预算（11.3）==========

# 3a. ORCHESTRATION_BUDGET 配置
from scoring.config import (
    ORCHESTRATION_BUDGET, get_budget_limit,
    EVAL_MODE, MEMORY_GATE_MODE, MEM_EXTRACT_MODE,
)
for key in ("max_regen_per_turn", "max_llm_calls_per_turn",
            "total_timeout_seconds", "rule_fallback_on_budget_exceeded"):
    assert key in ORCHESTRATION_BUDGET, f"ORCHESTRATION_BUDGET 缺 key {key}"
assert get_budget_limit("max_regen_per_turn") == ORCHESTRATION_BUDGET["max_regen_per_turn"]
assert get_budget_limit("max_llm_calls_per_turn") == 3
assert get_budget_limit("total_timeout_seconds") == 30
assert get_budget_limit("rule_fallback_on_budget_exceeded") is True
print(f"[OK] ORCHESTRATION_BUDGET: {ORCHESTRATION_BUDGET}")

# 3b. EVAL_MODE 路由：rule / llm_hybrid / llm
assert EVAL_MODE in ("rule", "llm_hybrid", "llm")
assert MEMORY_GATE_MODE in ("rule", "llm", "hybrid")
assert MEM_EXTRACT_MODE in ("unified", "split")

# 3c. diagnose() 接受 eval_mode 参数
sig_d = inspect.signature(diagnose)
assert "eval_mode" in sig_d.parameters, "diagnose 必须支持 eval_mode 参数"
assert "llm_client" in sig_d.parameters, "diagnose 必须支持 llm_client 参数（用于 LLM 兜底）"

# 3d. EVAL_MODE=rule 走纯规则（默认行为）
import scoring.config as scfg
old_mode = scfg.EVAL_MODE
scfg.EVAL_MODE = "rule"
diag_rule = diagnose(
    "今天怎样", "我爱你宝贝",
    character={"display_name": "林月", "description": "冷淡、慢热"},
    pair_axes={"emotional_closeness": 0.1},
    relationship_stage="stranger",
)
assert diag_rule.evaluator_method == "rule", \
    f"EVAL_MODE=rule 时 method 必须是 'rule', 实际: {diag_rule.evaluator_method}"

# 3e. EVAL_MODE=llm_hybrid：当前 LLM 兜底未实现，应回退到 rule（不破坏生产）
scfg.EVAL_MODE = "llm_hybrid"
diag_hybrid = diagnose(
    "今天怎样", "我爱你宝贝",
    character={"display_name": "林月", "description": "冷淡、慢热"},
    pair_axes={"emotional_closeness": 0.1},
    relationship_stage="stranger",
    llm_client=None,  # 不传 client，应回退到 rule
)
assert diag_hybrid.evaluator_method == "rule", \
    f"LLM 兜底未实现时必须回退 rule, 实际: {diag_hybrid.evaluator_method}"

# 3f. EVAL_MODE=llm_hybrid：传 mock LLM client，触发兜底路径
class _MockLLMClient:
    """模拟 LLM client，用于触发 _llm_judge_combined 的 'has client' 分支。"""
    pass

# 但 _llm_judge_combined 仍是 TODO，会返回 None，回退 rule（行为正确，不破坏生产）
diag_hybrid_with_client = diagnose(
    "今天怎样", "我爱你宝贝",
    character={"display_name": "林月", "description": "冷淡、慢热"},
    pair_axes={"emotional_closeness": 0.1},
    relationship_stage="stranger",
    llm_client=_MockLLMClient(),
)
assert diag_hybrid_with_client.evaluator_method == "rule", \
    "LLM 兜底占位未实现时，即使有 client 也应回退 rule"

scfg.EVAL_MODE = old_mode  # 恢复

print("[OK] EVAL_MODE 路由: rule 默认 / llm_hybrid 兜底未实现时安全回退 rule")

# 3g. _llm_judge_combined 是「一次 LLM 调用输出三维度+violations+rewrite」的占位
from scoring.engine import _llm_judge_combined, LLM_HYBRID_TRIGGER_THRESHOLD
sig_llm = inspect.signature(_llm_judge_combined)
# 必须接受 character + pair_axes + relationship_stage + pad_state + llm_client
# 一次调用同时输出三维 + violations + rewrite（不分 3 次）
for p in ("user_message", "bot_reply", "character", "llm_client"):
    assert p in sig_llm.parameters, f"_llm_judge_combined 缺参数 {p}"
# 占位：无 client 返回 None
assert _llm_judge_combined("x", "y", None, llm_client=None) is None
# 占位：有 client 也返回 None（未实现 TODO）
assert _llm_judge_combined("x", "y", None, llm_client=_MockLLMClient()) is None
assert LLM_HYBRID_TRIGGER_THRESHOLD == 70.0
print("[OK] _llm_judge_combined 占位接口 + LLM_HYBRID_TRIGGER_THRESHOLD=70.0")

print()
print("===== ALL THREE LIFESAVER SMOKE TESTS PASSED =====")
