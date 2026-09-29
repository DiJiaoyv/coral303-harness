"""弧光 API 数据模型。"""
from pydantic import BaseModel, Field


class GoalResponse(BaseModel):
    id: str
    title: str
    description: str = ""
    completed: bool = False
    created_at: str = ""


class ArcResponse(BaseModel):
    character_id: int
    current_stage: str
    stages: list[str]
    goals: list[GoalResponse]
    progress: float
    auto_advance: bool


class ArcStageUpdate(BaseModel):
    new_stage: str = Field(..., min_length=1, max_length=50)


class ArcGoalCreate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)


class ArcGoalUpdate(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)


class ArcGoalComplete(BaseModel):
    completed: bool = True
