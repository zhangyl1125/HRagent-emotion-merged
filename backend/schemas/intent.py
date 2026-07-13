from __future__ import annotations

from pydantic import BaseModel, Field


class IntentConfig(BaseModel):
    id: str
    name: str
    business_goal: str
    red_lines: list[str] = Field(default_factory=list)
    expected_outcome: str
    employee_agent_hint: str | None = None
    coach_focus: list[str] = Field(default_factory=list)


class IntentResult(BaseModel):
    intent_id: str
    confidence: float = 0.0
    reason: str | None = None
    config: IntentConfig | None = None
