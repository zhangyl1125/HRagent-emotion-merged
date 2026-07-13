from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class BigFivePersonality(BaseModel):
    openness: int = Field(default=50, ge=0, le=100)
    conscientiousness: int = Field(default=50, ge=0, le=100)
    extraversion: int = Field(default=50, ge=0, le=100)
    agreeableness: int = Field(default=50, ge=0, le=100)
    neuroticism: int = Field(default=50, ge=0, le=100)


class MotiveOption(BaseModel):
    id: str
    name: str
    dimension: str
    description: str = ""
    examples: list[str] = Field(default_factory=list)


class VADVector(BaseModel):
    valence: float = Field(default=0.0, ge=-1.0, le=1.0)
    arousal: float = Field(default=0.0, ge=-1.0, le=1.0)
    dominance: float = Field(default=0.0, ge=-1.0, le=1.0)


class EmotionAnchor(BaseModel):
    id: str
    name: str
    description: str = ""
    vad: VADVector = Field(default_factory=VADVector)


class MotivationState(BaseModel):
    primary_motive_id: str
    secondary_motive_ids: list[str] = Field(min_length=2, max_length=2)
    primary_score: float = 50.0
    secondary_scores: dict[str, float] = Field(default_factory=dict)
    total_satisfaction: float = 50.0
    last_change_reason: str | None = None
    has_manager_response: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("primary_score")
    @classmethod
    def clamp_primary_score(cls, value: float) -> float:
        return max(-100.0, min(100.0, float(value)))

    @model_validator(mode="after")
    def normalize_scores(self) -> "MotivationState":
        unique_secondary = list(dict.fromkeys(self.secondary_motive_ids))
        if len(unique_secondary) != 2:
            raise ValueError("secondary_motive_ids must contain exactly two unique motives")
        if self.primary_motive_id in unique_secondary:
            raise ValueError("primary motive and secondary motives must be different")
        self.secondary_motive_ids = unique_secondary
        for motive_id in self.secondary_motive_ids:
            self.secondary_scores[motive_id] = max(
                -100.0,
                min(100.0, float(self.secondary_scores.get(motive_id, 50.0))),
            )
        self.total_satisfaction = max(
            -100.0,
            min(
                100.0,
                self.primary_score * 0.7
                + sum(
                    self.secondary_scores.get(motive_id, 50.0)
                    for motive_id in self.secondary_motive_ids
                )
                * 0.15,
            ),
        )
        return self


class MotivationScoringStructuredOutput(BaseModel):
    primary_score_delta: float = 0.0
    secondary_score_deltas: dict[str, float] = Field(default_factory=dict)
    detected_behaviors: list[str] = Field(default_factory=list)
    redline_hits: list[str] = Field(default_factory=list)
    reason_summary: str = ""


class EmotionTransitionStructuredOutput(BaseModel):
    vad_delta: VADVector = Field(default_factory=VADVector)
    transition_strategy: Literal["expected_value", "maximum_probability", "sampling"] = "expected_value"
    detected_emotion_triggers: list[str] = Field(default_factory=list)
    reply_emotion_guidance: str = ""
    reason_summary: str = ""
