from __future__ import annotations

from pydantic import BaseModel, Field


class PersonaConfig(BaseModel):
    id: str
    name: str
    profile_short: str | None = None
    suitable_intents: list[str] = Field(default_factory=list)
    default_difficulty: str = "medium"
    profile_prompt: str | None = None
    trigger: str | None = None
    reply_style: dict = Field(default_factory=dict)
    emotion_range: list[str] = Field(default_factory=list)
    manager_handle: str | None = None
    escalation_by_difficulty: dict[str, str] = Field(default_factory=dict)
    avoid: list[str] = Field(default_factory=list)
