"""记忆 API 数据模型。"""
from pydantic import BaseModel, Field


class MemoryItemResponse(BaseModel):
    id: str
    summary: str
    content: str
    importance_raw: int
    importance: str
    source: str
    created_at: str
    deleted: bool = False


class MemoryListResponse(BaseModel):
    items: list[MemoryItemResponse]
    total: int
    page: int


class MemoryUpdateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=2000)
    importance: int = Field(..., ge=1, le=5)
