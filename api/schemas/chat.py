from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    character_id: int = Field(..., gt=0)
    message: str = Field(..., min_length=1, max_length=8000)


class ChatResponse(BaseModel):
    reply: str
