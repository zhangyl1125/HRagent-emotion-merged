from __future__ import annotations

from pydantic import BaseModel, Field


class ConversationAnalysis(BaseModel):
    empathy: float = Field(default=0.0, ge=0, le=1)
    specificity: float = Field(default=0.0, ge=0, le=1)
    respectfulness: float = Field(default=0.0, ge=0, le=1)
    clarity: float = Field(default=0.0, ge=0, le=1)
    support_plan: float = Field(default=0.0, ge=0, le=1)
    pressure: float = Field(default=0.0, ge=0, le=1)
    objective_evidence: float = Field(default=0.0, ge=0, le=1)
    placement_support: float = Field(default=0.0, ge=0, le=1)
    recognition: float = Field(default=0.0, ge=0, le=1)
    growth_path: float = Field(default=0.0, ge=0, le=1)
    compensation_or_reward: float = Field(default=0.0, ge=0, le=1)
    red_line_hit: bool = False
    risk_flags: list[str] = Field(default_factory=list)
    analysis_reason: str = ""
