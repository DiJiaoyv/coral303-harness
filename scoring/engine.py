"""对话质量评分主引擎。

v0.2 升级：从纯分数 → 诊断报告（DiagnosisReport）。
- 保留原 score_conversation() 兼容老调用方
- 新增 diagnose() 返回 DiagnosisReport（含 violations + rewrite_instruction）
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Literal

from scoring import config
from scoring import llm_scorer, rules

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ERROR_LOG = os.path.join(BASE_DIR, "scoring_error.log")

logger = logging.getLogger(__name__)

EVALUATOR_VERSION = "harness-evals:2.0"


# ======================================================================
# 诊断报告（替换原纯分数返回）
# ======================================================================
@dataclass
class Violation:
    """单条违规：类型 + 严重度 + 描述 + 证据 + 针对性改法。"""
    type: str                         # e.g. "expression_too_direct"
    severity: Literal["low", "medium", "high", "fatal"] = "medium"
    description: str = ""             # 人话描述
    evidence: dict[str, Any] = field(default_factory=dict)  # 引用 Profile/State 等
    rewrite_hint: str = ""           # 单条 violation 的针对性改法

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "severity": self.severity,
            "description": self.description,
            "evidence": self.evidence,
            "rewrite_hint": self.rewrite_hint,
        }


@dataclass
class DiagnosisReport:
    """完整诊断报告：分数 + 是否通过 + 违规列表 + 重写指令。"""
    scores: dict[str, float]                     # 保留原四维度分数
    passed: bool
    violations: list[Violation] = field(default_factory=list)
    rewrite_instruction: str = ""                 # 聚合后的重生成 instruction
    evaluator_version: str = EVALUATOR_VERSION
    evaluator_method: Literal["rule", "llm", "hybrid"] = "rule"
    attempt: int = 0                              # 第几次重生成（0=首轮）

    def to_dict(self) -> dict[str, Any]:
        return {
            "scores": self.scores,
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "rewrite_instruction": self.rewrite_instruction,
            "evaluator_version": self.evaluator_version,
            "evaluator_method": self.evaluator_method,
            "attempt": self.attempt,
        }


# ======================================================================
# 三维诊断规则（rule-based，毫秒级）
# ======================================================================

# 角色一致性：角色人设关键词 → 不应出现的表达
_CHARACTER_VIOLATION_PATTERNS: list[dict[str, Any]] = [
    {
        "profile_keywords": ["冷淡", "慢热", "不主动", "克制", "高冷", "毒舌"],
        "forbidden_expressions": ["我爱你", "好喜欢你", "宝贝", "亲爱的", "么么", "抱抱", "亲亲"],
        "violation_type": "expression_too_direct",
        "description": "表达爱意过于直接，与角色'冷淡慢热'人设不符",
        "rewrite_hint": "保持关心，但把直接告白改成隐晦表达，符合角色人设",
    },
    {
        "profile_keywords": ["毒舌", "刻薄", "嘴硬", "傲娇"],
        "forbidden_expressions": ["你真好", "谢谢你", "对不起", "我错了"],
        "violation_type": "too_polite_for_character",
        "description": "表达过于客气，与角色'毒舌/傲娇'人设不符",
        "rewrite_hint": "减少客套话，用角色特有的嘴硬方式表达同样的意思",
    },
    {
        "profile_keywords": ["温柔", "体贴", "暖"],
        "forbidden_expressions": ["滚", "烦死了", "别烦我", "真恶心"],
        "violation_type": "too_cold_for_character",
        "description": "表达过于冷漠，与角色'温柔体贴'人设不符",
        "rewrite_hint": "增加温暖感，用柔和语气表达同样意思",
    },
]

# 关系一致性：关系阶段 → 不应出现的表达
_RELATIONSHIP_STAGE_LIMITS: dict[str, list[str]] = {
    "stranger":     ["我爱你", "好喜欢你", "宝贝", "亲爱的", "么么", "抱抱", "想你", "离不开你"],
    "acquaintance": ["我爱你", "宝贝", "亲爱的", "么么", "离不开你"],
    "trust":        ["我爱你", "宝贝", "么么"],
}

# 情绪适当性：PAD 情绪 → 不应出现的表达
_EMOTION_MISMATCH: list[dict[str, Any]] = [
    {
        "condition": lambda pad: pad.get("pleasure", 5.0) < 3.0,  # 低愉悦
        "forbidden": ["哈哈哈", "太开心了", "好开心", "嘻嘻"],
        "violation_type": "emotion_mismatch_low_pleasure",
        "description": "角色当前情绪低落，但回复过于欢快",
        "rewrite_hint": "降低欢快程度，让回复更安静或低沉",
    },
    {
        "condition": lambda pad: pad.get("arousal", 5.0) > 7.0,  # 高唤醒（激动）
        "forbidden": ["嗯嗯", "好的", "行吧", "随便"],
        "violation_type": "emotion_mismatch_high_arousal",
        "description": "角色当前情绪激动，但回复过于平淡",
        "rewrite_hint": "增加情绪强度，让回复更激动或急切",
    },
]


def _check_character_consistency(
    bot_reply: str,
    character: dict | None,
) -> list[Violation]:
    """检查 AI 回复是否违反角色人设。"""
    violations: list[Violation] = []
    if not character:
        return violations

    # 从 character dict 里提取人设关键词
    profile_text = " ".join(str(v) for v in character.values() if isinstance(v, (str, int, float)))
    reply_lower = bot_reply.lower()

    for pattern in _CHARACTER_VIOLATION_PATTERNS:
        # 检查角色人设是否包含这些关键词
        if any(kw in profile_text for kw in pattern["profile_keywords"]):
            # 检查回复是否包含不该出现的表达
            hits = [expr for expr in pattern["forbidden_expressions"] if expr in reply_lower]
            if hits:
                violations.append(Violation(
                    type=pattern["violation_type"],
                    severity="high",
                    description=pattern["description"],
                    evidence={
                        "character_profile": ", ".join(pattern["profile_keywords"][:3]),
                        "matched_expressions": hits[:3],
                    },
                    rewrite_hint=pattern["rewrite_hint"],
                ))
    return violations


def _check_relationship_consistency(
    bot_reply: str,
    pair_axes: dict[str, float] | None,
    stage: str = "stranger",
) -> list[Violation]:
    """检查 AI 回复是否超出当前关系阶段。"""
    violations: list[Violation] = []
    if not pair_axes:
        pair_axes = {}
    stage = stage or "stranger"

    reply_lower = bot_reply.lower()
    # 获取当前阶段的限制
    limits = _RELATIONSHIP_STAGE_LIMITS.get(stage, [])
    # 也检查更低阶段的限制
    stage_order = ["stranger", "acquaintance", "trust", "intimate"]
    stage_idx = stage_order.index(stage) if stage in stage_order else 0
    for lower_stage in stage_order[:stage_idx + 1]:
        limits = limits + _RELATIONSHIP_STAGE_LIMITS.get(lower_stage, [])

    limits = list(set(limits))
    hits = [expr for expr in limits if expr in reply_lower]
    if hits:
        # 找到最相关的轴值
        emotional_closeness = pair_axes.get("emotional_closeness", 0.0)
        violations.append(Violation(
            type="relationship_stage_mismatch",
            severity="high",
            description=f"当前关系阶段({stage})不足以支持该措辞",
            evidence={
                "relationship_state": f"stage={stage}, emotional_closeness={emotional_closeness:.2f}",
                "matched_expressions": hits[:3],
            },
            rewrite_hint=f"降低亲密度表达，符合当前'{stage}'阶段的关系深度",
        ))
    return violations


def _check_emotional_appropriateness(
    bot_reply: str,
    pad_state: dict[str, float] | None,
) -> list[Violation]:
    """检查 AI 回复情绪是否匹配角色当前 PAD 情绪状态。"""
    violations: list[Violation] = []
    if not pad_state:
        return violations

    reply_lower = bot_reply.lower()
    for rule in _EMOTION_MISMATCH:
        if rule["condition"](pad_state):
            hits = [expr for expr in rule["forbidden"] if expr in reply_lower]
            if hits:
                violations.append(Violation(
                    type=rule["violation_type"],
                    severity="medium",
                    description=rule["description"],
                    evidence={
                        "pad_state": {k: round(v, 2) for k, v in pad_state.items()},
                        "matched_expressions": hits[:3],
                    },
                    rewrite_hint=rule["rewrite_hint"],
                ))
    return violations


def _aggregate_rewrite_instruction(violations: list[Violation]) -> str:
    """把所有 violation 的 rewrite_hint 聚合成一条 instruction。"""
    if not violations:
        return ""
    # 按严重度排序，high/fatal 优先
    severity_order = {"fatal": 0, "high": 1, "medium": 2, "low": 3}
    sorted_v = sorted(violations, key=lambda v: severity_order.get(v.severity, 9))
    parts = [v.rewrite_hint for v in sorted_v if v.rewrite_hint]
    if not parts:
        return ""
    if len(parts) == 1:
        return parts[0]
    return "；".join(parts)


# ======================================================================
# 主诊断入口
# ======================================================================
# llm_hybrid 模式阈值：规则总分低于此值时触发 LLM 兜底（一次调用输出三维度+violations+rewrite）
LLM_HYBRID_TRIGGER_THRESHOLD = 70.0


def _llm_judge_combined(
    user_message: str,
    bot_reply: str,
    character: dict | None,
    *,
    pair_axes: dict[str, float] | None = None,
    relationship_stage: str = "stranger",
    pad_state: dict[str, float] | None = None,
    llm_client=None,
) -> tuple[dict[str, float], list[Violation], str] | None:
    """LLM 兜底评估：**一次调用同时输出三维度评分 + violations + rewrite_instruction**。

    返回 (scores, violations, rewrite_instruction) 或 None（LLM 未启用 / 失败）。

    11.3 成本预算关键约束：
        - 本函数必须一次 LLM 调用同时输出三维度评分 + violations + rewrite，
          禁止调用 3 次 LLM 分别评分。
        - 实际接入 LLM 时复用 unified_analyzer.py 的「一次调用多输出」模式：
          prompt 让 LLM 输出 JSON，含 character/relationship/emotion 三维分 +
          violations 列表 + rewrite_instruction 字符串。

    本函数当前是占位实现（不调 LLM），返回 None，让上层回退到 rule 评分。
    真实接入 LLM 时：
        1. 接受 llm_client（OllamaClient 实例）
        2. 构造一次性 prompt（含 character meta + axes + stage + pad）
        3. 解析 JSON 输出，构造 Violation 列表
        4. 返回合并后的 scores/violations/rewrite_instruction
    """
    if llm_client is None:
        return None
    # TODO: 真实 LLM 兜底实现（保留架构位，不破坏 rule 模式）
    return None


def diagnose(
    user_message: str,
    bot_reply: str,
    character: dict | None = None,
    *,
    pair_axes: dict[str, float] | None = None,
    relationship_stage: str = "stranger",
    pad_state: dict[str, float] | None = None,
    attempt: int = 0,
    pass_threshold: float = 60.0,
    eval_mode: str | None = None,
    llm_client=None,
) -> DiagnosisReport:
    """
    对一轮对话做三维诊断：人设一致性 + 关系一致性 + 情绪适当性。

    返回 DiagnosisReport，包含分数、violations、rewrite_instruction。

    11.3 成本预算 EVAL_MODE 路由（默认读 scoring.config.EVAL_MODE）：
        - "rule":       纯规则评分（毫秒级，三维一次算完）
        - "llm_hybrid": 规则高分跳过 LLM；规则分低于 LLM_HYBRID_TRIGGER_THRESHOLD
                        才调一次 LLM，一次输出三维度评分 + violations + rewrite
        - "llm":        完全走 LLM（不推荐生产，仅供调试；当前 LLM 兜底未实现，
                        会回退到 rule）
    """
    # 默认从 config 读 EVAL_MODE
    if eval_mode is None:
        try:
            from scoring.config import EVAL_MODE as _MODE
            eval_mode = _MODE
        except Exception:
            eval_mode = "rule"

    # 先跑原有规则评分（保留兼容）
    scores = rules.score_all(user_message, bot_reply, character)
    total = _weighted_total(scores)  # 0-10 量纲
    total_100 = round(total * 10.0, 2)  # 转 0-100 量纲，与 pass_threshold 对齐

    # 三维诊断
    violations: list[Violation] = []
    violations.extend(_check_character_consistency(bot_reply, character))
    violations.extend(_check_relationship_consistency(bot_reply, pair_axes, relationship_stage))
    violations.extend(_check_emotional_appropriateness(bot_reply, pad_state))

    # fatal 级 violation 直接判不过
    has_fatal = any(v.severity == "fatal" for v in violations)
    has_high = any(v.severity == "high" for v in violations)
    passed = (total_100 >= pass_threshold) and not has_fatal and not has_high

    rewrite = _aggregate_rewrite_instruction(violations)

    # evaluator_method 记录实际走了哪条路
    method_used = "rule"

    # 11.3 llm_hybrid：规则分低于阈值才调 LLM 一次（不调 3 次）
    if eval_mode == "llm_hybrid" and not passed and total_100 < LLM_HYBRID_TRIGGER_THRESHOLD:
        llm_result = _llm_judge_combined(
            user_message, bot_reply, character,
            pair_axes=pair_axes,
            relationship_stage=relationship_stage,
            pad_state=pad_state,
            llm_client=llm_client,
        )
        if llm_result is not None:
            llm_scores, llm_violations, llm_rewrite = llm_result
            # 合并 LLM 结果（覆盖规则结果，因为 LLM 更准但更贵）
            scores = llm_scores
            violations = llm_violations
            rewrite = llm_rewrite or rewrite
            # 重新计算 passed
            total_100 = round(float(scores.get("total_score", total_100)), 2)
            has_fatal = any(v.severity == "fatal" for v in violations)
            has_high = any(v.severity == "high" for v in violations)
            passed = (total_100 >= pass_threshold) and not has_fatal and not has_high
            method_used = "llm_hybrid"
    elif eval_mode == "llm":
        # 完全走 LLM（当前兜底未实现，回退到 rule，不破坏生产）
        llm_result = _llm_judge_combined(
            user_message, bot_reply, character,
            pair_axes=pair_axes,
            relationship_stage=relationship_stage,
            pad_state=pad_state,
            llm_client=llm_client,
        )
        if llm_result is not None:
            scores, violations, rewrite = llm_result
            total_100 = round(float(scores.get("total_score", total_100)), 2)
            has_fatal = any(v.severity == "fatal" for v in violations)
            has_high = any(v.severity == "high" for v in violations)
            passed = (total_100 >= pass_threshold) and not has_fatal and not has_high
            method_used = "llm"

    return DiagnosisReport(
        scores={**scores, "total_score": total_100},  # 输出 0-100 量纲
        passed=passed,
        violations=violations,
        rewrite_instruction=rewrite,
        evaluator_version=EVALUATOR_VERSION,
        evaluator_method=method_used,  # type: ignore[arg-type]
        attempt=attempt,
    )


def build_rewrite_prompt(
    original_prompt: str,
    diagnosis: DiagnosisReport,
    *,
    user_message: str,
    character_name: str = "",
) -> str:
    """把诊断报告的 rewrite_instruction 拼入重生成 prompt。"""
    violation_descs = "\n".join(
        f"- [{v.severity}] {v.description}" for v in diagnosis.violations
    )
    return (
        f"{original_prompt.rstrip()}\n\n"
        f"【重生成要求】\n"
        f"之前的回复被拒绝，原因：\n{violation_descs}\n\n"
        f"修改建议：{diagnosis.rewrite_instruction}\n\n"
        f"请基于以上建议重新生成回复，保持角色'{character_name}'的身份。"
    )


def _log_error(message: str) -> None:
    try:
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(message + "\n")
    except OSError:
        pass


def _weighted_total(scores: dict[str, float]) -> float:
    fields = {
        "relevance": "relevance_score",
        "consistency": "consistency_score",
        "fluency": "fluency_score",
        "safety": "safety_score",
    }
    total = sum(
        scores.get(fields[key], 0.0) * weight
        for key, weight in config.DIMENSION_WEIGHTS.items()
    )
    return round(total, 2)


def score_conversation(
    user_message: str,
    bot_reply: str,
    character: dict | None = None,
    *,
    method: str | None = None,
) -> dict[str, Any]:
    """
    对一轮对话评分。

    Returns:
        dict 含各维度分数、total_score、scoring_method
    """
    method = method or config.DEFAULT_SCORING_METHOD
    scores: dict[str, float] | None = None
    used_method = "rule"

    if method == "model" and config.LLM_SCORING_ENABLED:
        try:
            scores = llm_scorer.score_with_llm(user_message, bot_reply, character)
            used_method = "model"
        except Exception as exc:
            _log_error(f"LLM 评分失败，回退规则: {exc}")
            scores = None

    if scores is None:
        scores = rules.score_all(user_message, bot_reply, character)
        used_method = "rule"

    return {
        **scores,
        "total_score": _weighted_total(scores),
        "scoring_method": used_method,
    }


def persist_score_log(
    *,
    user_id: int,
    character_id: int | None,
    conversation_id: int | None,
    user_message: str,
    bot_reply: str,
    scores: dict[str, Any],
    diagnosis: dict[str, Any] | None = None,
    candidates: list[dict] | None = None,
    final_accepted_index: int = 0,
    regen_count: int = 0,
) -> None:
    """将评分+诊断报告写入 score_logs 表，失败不影响主流程。"""
    import json as _json
    try:
        from datetime import datetime, timezone

        # v0.2 诊断报告字段
        violations_json = _json.dumps(
            diagnosis.get("violations", []) if diagnosis else [],
            ensure_ascii=False,
        )
        rewrite_instruction = (
            diagnosis.get("rewrite_instruction", "") if diagnosis else ""
        )
        candidates_json = _json.dumps(
            candidates or [],
            ensure_ascii=False,
        )

        row_data = dict(
            user_id=user_id,
            character_id=character_id,
            conversation_id=conversation_id,
            user_message=user_message,
            bot_reply=bot_reply,
            relevance_score=scores["relevance_score"],
            consistency_score=scores["consistency_score"],
            fluency_score=scores["fluency_score"],
            safety_score=scores["safety_score"],
            total_score=scores["total_score"],
            scoring_method=scores["scoring_method"],
            violations_json=violations_json,
            rewrite_instruction=rewrite_instruction,
            regen_count=regen_count,
            candidates_json=candidates_json,
            final_accepted_index=final_accepted_index,
            created_at=datetime.now(timezone.utc),
        )

        try:
            from flask import has_app_context
            if has_app_context():
                from app.models.user import ScoreLog as FlaskScoreLog
                from extensions import db

                db.session.add(FlaskScoreLog(**row_data))
                db.session.commit()
                return
        except ImportError:
            pass

        from database.models import ScoreLog
        from database.session import SessionLocal

        session = SessionLocal()
        try:
            session.add(ScoreLog(**row_data))
            session.commit()
        finally:
            session.close()
    except Exception as exc:
        _log_error(f"保存 score_logs 失败: {exc}")


def persist_evaluation_logs(
    *,
    user_id: int,
    character_id: int | None,
    conversation_id: int | None,
    user_message: str,
    candidates: list[dict],
    final_accepted_index: int,
) -> None:
    """把每个 candidate 写成 evaluation_logs 一行（quality improvement data，不进 Memory）。

    保存：candidate_response / scores / violations / rewrite_instruction / final_response
    + attempt / accepted 标记。失败不影响主流程。

    与 persist_score_log（一轮一条）互补：这里是「一个 candidate 一行」的明细，
    便于按 candidate 查询 / 分析违规模式。

    Args:
        candidates: [{candidate, attempt, passed, violations, rewrite_instruction, scores}, ...]
        final_accepted_index: 最终采纳的候选在 candidates 里的下标
    """
    import json as _json
    if not candidates:
        return
    try:
        final_response = (
            candidates[final_accepted_index].get("candidate", "")
            if 0 <= final_accepted_index < len(candidates)
            else (candidates[-1].get("candidate", "") if candidates else "")
        )

        rows = []
        for i, c in enumerate(candidates):
            rows.append(
                dict(
                    user_id=user_id,
                    character_id=character_id,
                    conversation_id=conversation_id,
                    user_message=user_message,
                    candidate_response=c.get("candidate", ""),
                    attempt=int(c.get("attempt", i)),
                    accepted=1 if i == final_accepted_index else 0,
                    scores_json=_json.dumps(c.get("scores") or {}, ensure_ascii=False),
                    violations_json=_json.dumps(c.get("violations") or [], ensure_ascii=False),
                    rewrite_instruction=c.get("rewrite_instruction") or "",
                    final_response=final_response,
                )
            )

        # Flask 上下文优先（与 persist_score_log 保持一致的双写路径）
        try:
            from flask import has_app_context

            if has_app_context():
                from app.models.user import EvaluationLog as FlaskEvaluationLog
                from extensions import db

                for row in rows:
                    db.session.add(FlaskEvaluationLog(**row))
                db.session.commit()
                return
        except ImportError:
            pass

        from database.models import EvaluationLog
        from database.session import SessionLocal

        session = SessionLocal()
        try:
            for row in rows:
                session.add(EvaluationLog(**row))
            session.commit()
        finally:
            session.close()
    except Exception as exc:
        _log_error(f"保存 evaluation_logs 失败: {exc}")


def score_and_persist(
    user_message: str,
    bot_reply: str,
    character: dict | None,
    *,
    user_id: int,
    character_id: int | None = None,
    conversation_id: int | None = None,
    method: str | None = None,
    diagnosis: dict[str, Any] | None = None,
    candidates: list[dict] | None = None,
    final_accepted_index: int = 0,
    regen_count: int = 0,
) -> None:
    """评分并持久化（异常安全）。

    method="partial" 用于用户取消后的部分回复（负样本/不耐烦信号）。
    v0.2: diagnosis/candidates/regen_count/final_accepted_index 为诊断报告扩展字段。
    """
    try:
        if method == "partial":
            # 仍用规则打分，但标记为 partial，便于后续分析取消样本
            scores = score_conversation(
                user_message, bot_reply or "", character, method="rule"
            )
            scores["scoring_method"] = "partial"
            if not (bot_reply or "").strip():
                # 空回复：记录取消事件，分数压低
                scores["relevance_score"] = 0.0
                scores["fluency_score"] = 0.0
                scores["total_score"] = _weighted_total(scores)
            persist_score_log(
                user_id=user_id,
                character_id=character_id,
                conversation_id=conversation_id,
                user_message=user_message,
                bot_reply=bot_reply or "[用户取消]",
                scores=scores,
            )
            return

        scores = score_conversation(
            user_message, bot_reply, character, method=method
        )
        # 从 diagnosis 提取完整候选链路：orchestrator 只传 diagnosis，
        # candidates / final_accepted_index / regen_count 都在其中。
        # 若调用方显式传了 candidates 则优先用调用方的（兼容旧调用方）。
        diag_dict = diagnosis or {}
        eff_candidates = (
            candidates if candidates is not None
            else (diag_dict.get("candidates") or [])
        )
        eff_final_index = (
            final_accepted_index if candidates is not None
            else int(diag_dict.get("final_accepted_index", 0) or 0)
        )
        eff_regen = (
            regen_count if candidates is not None
            else int(diag_dict.get("regen_count", 0) or 0)
        )

        persist_score_log(
            user_id=user_id,
            character_id=character_id,
            conversation_id=conversation_id,
            user_message=user_message,
            bot_reply=bot_reply,
            scores=scores,
            diagnosis=diagnosis,
            candidates=eff_candidates,
            final_accepted_index=eff_final_index,
            regen_count=eff_regen,
        )
        # v0.3：每个 candidate 一行写 evaluation_logs
        # （candidate_response / scores / violations / rewrite_instruction / final_response）
        if eff_candidates:
            persist_evaluation_logs(
                user_id=user_id,
                character_id=character_id,
                conversation_id=conversation_id,
                user_message=user_message,
                candidates=eff_candidates,
                final_accepted_index=eff_final_index,
            )
    except Exception as exc:
        _log_error(f"评分流程异常: {exc}")
