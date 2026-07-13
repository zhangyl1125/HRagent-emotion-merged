from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class InterviewPurpose(str, Enum):
    MOTIVATION = "motivation"
    IMPROVEMENT = "improvement"
    EXIT = "exit"
    MOTIVATION_IMPROVEMENT = "motivation_improvement"
    IMPROVEMENT_EXIT = "improvement_exit"


class MvpiMotivation(str, Enum):
    COMMERCE = "commerce"
    POWER = "power"
    RECOGNITION = "recognition"
    AFFILIATION = "affiliation"
    SECURITY = "security"
    HEDONISM = "hedonism"


class SatisfactionDelta(BaseModel):
    primary_delta: float = 0.0
    secondary_delta: float = 0.0


def clamp_score(value: float, min_value: float = 0.0, max_value: float = 100.0) -> float:
    return max(min_value, min(max_value, value))


def get_satisfaction_band(total_satisfaction: float) -> str:
    if total_satisfaction < 20:
        return "extreme_resistance"
    if total_satisfaction < 40:
        return "negative_defensive"
    if total_satisfaction < 60:
        return "rational_softening"
    if total_satisfaction < 80:
        return "active_engagement"
    return "emotion_resolved"
