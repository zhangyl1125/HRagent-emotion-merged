from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

from backend.schemas.conversation import ConversationTurn
from backend.schemas.profile import EmployeeProfile
from backend.schemas.intent import IntentResult
from backend.schemas.persona import PersonaConfig
from backend.schemas.difficulty import DifficultyConfig
from backend.schemas.emotion import ConversationEmotionLog, EmotionState
from backend.schemas.simulation import BigFivePersonality, MotivationState

SessionStage = Literal["created", "profile_ready", "setup_ready", "guidance_ready", "rehearsal", "report_ready", "ended"]
RunMode = Literal["guidance_only", "guidance_then_rehearsal", "rehearsal_report"]


class RehearsalRuntimeContext(BaseModel):
    runtime_notes: list[str] = Field(default_factory=list)
    persona_override: str | None = None
    active_persona_id: str | None = None
    active_difficulty_id: str | None = None
    initial_persona_id: str | None = None
    initial_difficulty_id: str | None = None
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)


class SessionState(BaseModel):
    session_id: str
    stage: SessionStage = "created"
    run_mode: RunMode = "guidance_then_rehearsal"
    employee_profile: EmployeeProfile | None = None
    intent: IntentResult | None = None
    persona: PersonaConfig | None = None
    difficulty: DifficultyConfig | None = None
    personality: BigFivePersonality | None = None
    motivation: MotivationState | None = None
    setup_ready: bool = False
    guidance_report_id: str | None = None
    coach_report_id: str | None = None
    rehearsal_context: RehearsalRuntimeContext = Field(default_factory=RehearsalRuntimeContext)
    emotion_state: EmotionState = Field(default_factory=EmotionState)
    emotion_log: list[ConversationEmotionLog] = Field(default_factory=list)
    conversation: list[ConversationTurn] = Field(default_factory=list)
    user_turn_count: int = 0
    max_user_turns: int = 0
    warnings: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None

    def touch(self) -> None:
        self.updated_at = datetime.now(timezone.utc)
