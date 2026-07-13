from __future__ import annotations

from pydantic import BaseModel, Field


class DifficultyConfig(BaseModel):
    id: str
    name: str
    description: str
    user_turn_budget: int = 12
    response_style: dict = Field(default_factory=dict)
