"""Relationship Rules —— 某个角色特有的关系推进规则。

用于 Harness Evaluator 回答「当前 relationship_state 下，哪些表达越界」：

例：
    emotional_closeness < 0.4 时，不允许直接说"我爱你"
    trust < 0.5 时，不允许向对方透露 core_drive 深层信息
    tension > 0.6 时，语气应该偏冷 / 避免使用 playfulness 词汇

第一版用 (axis, threshold, operator, description) 的简单四元组，
后续可升级为 DSL 或 JSON Schema。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any


_AXES = {"familiarity", "trust", "emotional_closeness", "playfulness", "tension"}
_OPS = {"<", "<=", ">", ">=", "=="}


@dataclass
class RelationshipRule:
    rule_id: str
    description: str
    severity: str = "medium"          # low / medium / high / fatal
    # 触发条件：轴 + 阈值 + 比较
    axis: str = "emotional_closeness"
    threshold: float = 0.5
    operator: str = "<"              # 当 <axis> <operator> <threshold> 时判定命中
    # 命中时给 Evaluator 的具体改写方向
    rewrite_direction: str = "保持礼貌距离，不要过度亲密。"

    def __post_init__(self) -> None:
        if self.axis not in _AXES:
            self.axis = "emotional_closeness"
        if self.operator not in _OPS:
            self.operator = "<"

    def evaluate(self, axes_snapshot: dict[str, float]) -> bool:
        """给当前 axes 值，判断是否触发本规则（True=违规）。"""
        if self.axis not in axes_snapshot:
            return False
        val = float(axes_snapshot[self.axis])
        thr = float(self.threshold)
        op = self.operator
        if op == "<":
            return val < thr
        if op == "<=":
            return val <= thr
        if op == ">":
            return val > thr
        if op == ">=":
            return val >= thr
        if op == "==":
            return abs(val - thr) < 1e-6
        return False


# 所有角色共享的保守基线（模块级常量，避免 dataclass 把它当作字段）
CONSERVATIVE_BASELINE_RULES: list[RelationshipRule] = [
    RelationshipRule(
        rule_id="baseline.direct_love_confession",
        description="亲密度不足以直接告白 / 称呼'亲爱的'等",
        severity="high",
        axis="emotional_closeness",
        threshold=0.75,
        operator="<",
        rewrite_direction="保持含蓄，不要用'我爱你'、'亲爱的'这种深层亲密表达。",
    ),
    RelationshipRule(
        rule_id="baseline.share_deep_fears_without_trust",
        description="信任不足时不应透露自己的 core_drive / fear 等深层信息",
        severity="medium",
        axis="trust",
        threshold=0.5,
        operator="<",
        rewrite_direction="保留戒备，不要主动透露自己的深层恐惧或动机。",
    ),
    RelationshipRule(
        rule_id="baseline.playfulness_under_tension",
        description="高紧张关系下开玩笑、轻浮语气",
        severity="medium",
        axis="tension",
        threshold=0.6,
        operator=">=",
        rewrite_direction="当下关系偏紧张，保持克制的对话，不要使用玩笑或轻浮语气。",
    ),
]


@dataclass
class RelationshipRules:
    """某个角色特有的关系推进规则集合。"""

    rules: list[RelationshipRule] = field(default_factory=list)

    # 所有角色共享的通用保守基线
    enable_conservative_baseline: bool = True

    def effective_rules(self) -> list[RelationshipRule]:
        if self.enable_conservative_baseline:
            return [*CONSERVATIVE_BASELINE_RULES, *self.rules]
        return list(self.rules)

    def match_violations(
        self,
        axes_snapshot: dict[str, float],
    ) -> list[RelationshipRule]:
        """返回所有命中（即当前状态违规）的规则。"""
        return [r for r in self.effective_rules() if r.evaluate(axes_snapshot)]

    def to_dict(self) -> dict[str, Any]:
        return {
            "enable_conservative_baseline": self.enable_conservative_baseline,
            "rules": [asdict(r) for r in self.rules],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "RelationshipRules":
        data = data or {}
        raw_rules = data.get("rules") or []
        rules = [
            RelationshipRule(**r)
            for r in raw_rules
            if isinstance(r, dict)
        ]
        return cls(
            rules=rules,
            enable_conservative_baseline=bool(
                data.get("enable_conservative_baseline", True)
            ),
        )
