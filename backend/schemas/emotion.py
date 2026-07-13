from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from backend.schemas.motivation import InterviewPurpose, MvpiMotivation
from backend.schemas.simulation import MotivationState, VADVector


class EmployeeAttitude(str, Enum):
    CALM_NEUTRAL = "calm_neutral"
    GUARDED_HESITANT = "guarded_hesitant"
    DEFENSIVE_RESISTANT = "defensive_resistant"
    FRUSTRATED_PUSHBACK = "frustrated_pushback"
    SILENT_WITHDRAWN = "silent_withdrawn"
    REFLECTIVE_SOFTENING = "reflective_softening"
    COOPERATIVE_CONSTRUCTIVE = "cooperative_constructive"


class EmotionSignal(BaseModel):
    user_text_emotion: str | None = None
    audio_emotion: str | None = None
    empathy: float = Field(default=0.0, ge=0, le=1)
    clarity: float = Field(default=0.0, ge=0, le=1)
    specificity: float = Field(default=0.0, ge=0, le=1)
    respectfulness: float = Field(default=0.0, ge=0, le=1)
    pressure: float = Field(default=0.0, ge=0, le=1)
    support_plan: float = Field(default=0.0, ge=0, le=1)
    objective_evidence: float = Field(default=0.0, ge=0, le=1)
    placement_support: float = Field(default=0.0, ge=0, le=1)
    recognition: float = Field(default=0.0, ge=0, le=1)
    growth_path: float = Field(default=0.0, ge=0, le=1)
    compensation_or_reward: float = Field(default=0.0, ge=0, le=1)
    red_line_hit: bool = False
    analysis_reason: str = ""
    primary_delta: float = 0.0
    secondary_delta: float = 0.0
    likely_employee_reaction: Literal["escalate", "soften", "withdraw", "stay"] = "stay"
    risk_flags: list[str] = Field(default_factory=list)


class EmotionState(BaseModel):
    """Combined legacy attitude and dynamic three-axis VAD state."""

    current_attitude: EmployeeAttitude = EmployeeAttitude.CALM_NEUTRAL
    previous_attitude: EmployeeAttitude | None = None
    intensity: int = Field(default=20, ge=0, le=100)
    transition_reason: str = "initial_state"
    interview_purpose: InterviewPurpose | str = InterviewPurpose.IMPROVEMENT
    primary_motivation: MvpiMotivation | str = MvpiMotivation.RECOGNITION
    secondary_motivation: MvpiMotivation | str = MvpiMotivation.SECURITY
    primary_satisfaction: float = Field(default=0.0, ge=0, le=100)
    secondary_satisfaction: float = Field(default=0.0, ge=0, le=100)
    total_satisfaction: float = Field(default=0.0, ge=0, le=100)
    emotion_band: str = "extreme_resistance"
    emotion_description: str = "初始状态，员工仍在观察 HRBP 是否能给出事实、尊重和支持。"
    last_primary_delta: float = 0.0
    last_secondary_delta: float = 0.0
    turn_index: int = 0
    current_vad: VADVector = Field(default_factory=VADVector)
    current_anchor_id: str | None = None
    transition_strategy: Literal["expected_value", "maximum_probability", "sampling"] = "expected_value"
    last_reason_summary: str = ""
    reply_emotion_guidance: str = ""
    has_manager_response: bool = False
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ConversationEmotionLog(BaseModel):
    turn_index: int
    hrbp_text: str
    input_mode: str = "text"
    audio_emotion: str | None = None
    employee_attitude_before: EmployeeAttitude
    employee_attitude_after: EmployeeAttitude
    intensity: int
    transition_reason: str
    employee_reply: str | None = None
    signal: EmotionSignal | None = None
    vad_before: VADVector | None = None
    vad_after: VADVector | None = None
    emotion_anchor_before: str | None = None
    emotion_anchor_after: str | None = None
    motivation_before: MotivationState | None = None
    motivation_after: MotivationState | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
