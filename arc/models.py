"""弧光状态数据类。"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from arc.config import DEFAULT_STAGE, DEFAULT_STAGES


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class GoalItem:
    id: str
    title: str
    description: str = ""
    completed: bool = False
    created_at: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "completed": self.completed,
            "created_at": self.created_at or _now_iso(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GoalItem":
        return cls(
            id=str(data.get("id", uuid.uuid4().hex[:12])),
            title=str(data.get("title", "")),
            description=str(data.get("description", "")),
            completed=bool(data.get("completed", False)),
            created_at=str(data.get("created_at", "")),
        )

    @classmethod
    def create(cls, title: str, description: str = "") -> "GoalItem":
        return cls(
            id=uuid.uuid4().hex[:12],
            title=title,
            description=description,
            completed=False,
            created_at=_now_iso(),
        )


@dataclass
class ArcState:
    character_id: int
    current_stage: str = DEFAULT_STAGE
    stages: list[str] = field(default_factory=lambda: list(DEFAULT_STAGES))
    goals: list[GoalItem] = field(default_factory=list)
    progress: float = 0.0
    auto_advance: bool = True

    def completed_goal_count(self) -> int:
        return sum(1 for g in self.goals if g.completed)

    def stage_index(self) -> int:
        try:
            return self.stages.index(self.current_stage)
        except ValueError:
            return 0

    def compute_progress(self) -> float:
        """根据阶段位置与目标完成率计算 0~1 进度。"""
        if len(self.stages) <= 1:
            stage_part = 1.0 if self.current_stage == self.stages[0] else 0.0
        else:
            stage_part = self.stage_index() / (len(self.stages) - 1)

        if not self.goals:
            return round(min(1.0, max(0.0, stage_part)), 4)

        goal_part = self.completed_goal_count() / len(self.goals)
        combined = stage_part * 0.7 + goal_part * 0.3
        return round(min(1.0, max(0.0, combined)), 4)

    def to_dict(self) -> dict:
        return {
            "character_id": self.character_id,
            "current_stage": self.current_stage,
            "stages": list(self.stages),
            "goals": [g.to_dict() for g in self.goals],
            "progress": self.progress,
            "auto_advance": self.auto_advance,
        }

    @classmethod
    def from_db_row(cls, row) -> "ArcState":
        stages = row.stages if isinstance(row.stages, list) else DEFAULT_STAGES
        raw_goals = row.goals if isinstance(row.goals, list) else []
        goals = [GoalItem.from_dict(g) for g in raw_goals]
        state = cls(
            character_id=row.character_id,
            current_stage=row.current_stage or DEFAULT_STAGE,
            stages=list(stages),
            goals=goals,
            progress=float(row.progress or 0.0),
            auto_advance=bool(row.auto_advance if row.auto_advance is not None else True),
        )
        state.progress = state.compute_progress()
        return state
