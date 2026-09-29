import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

CHARACTER_KEY_PATTERN = re.compile(r"^[a-zA-Z0-9_]{3,32}$")


class CharacterCreate(BaseModel):
    character_key: str = Field(..., min_length=3, max_length=32)
    display_name: str = Field(..., min_length=1, max_length=64)
    role: str | None = Field(None, max_length=128)

    @field_validator("character_key")
    @classmethod
    def validate_character_key(cls, v: str) -> str:
        if not CHARACTER_KEY_PATTERN.match(v):
            raise ValueError("角色标识须为 3–32 位字母、数字或下划线")
        return v


class CharacterUpdate(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=64)
    role: str | None = Field(None, max_length=128)


class CharacterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    character_key: str
    display_name: str
    role: str | None
    created_at: datetime
