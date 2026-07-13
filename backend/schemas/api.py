from __future__ import annotations

from pydantic import BaseModel, Field

from backend.schemas.profile import EmployeeProfile
from backend.schemas.simulation import BigFivePersonality


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class CreateSessionRequest(BaseModel):
    max_user_turns: int | None = None


class TextDocumentRequest(BaseModel):
    session_id: str | None = None
    text: str
    filename: str | None = "pasted_text.txt"


class ConfirmProfileRequest(BaseModel):
    profile: EmployeeProfile


class ConfirmIntentRequest(BaseModel):
    intent_id: str | None = None
    free_text: str | None = None


class ConfirmPersonaRequest(BaseModel):
    persona_id: str
    difficulty_id: str = "medium"
    run_mode: str = "guidance_then_rehearsal"


class ConfirmSimulationRequest(BaseModel):
    personality: BigFivePersonality
    primary_motive_id: str
    secondary_motive_ids: list[str] = Field(min_length=2, max_length=2)
    run_mode: str = "guidance_then_rehearsal"


class RehearsalMessageRequest(BaseModel):
    message: str = Field(min_length=1)
    input_mode: str = "text"
    audio_emotion: str | None = None


class TtsSpeechRequest(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    voice: str | None = None
    response_format: str | None = None
    speed: float | None = Field(default=None, ge=0.25, le=4.0)


class RehearsalContextUpdateRequest(BaseModel):
    runtime_note: str | None = None
    runtime_notes: list[str] | str | None = None
    persona_override: str | None = None
    persona_id: str | None = None
    difficulty_id: str | None = None
    clear_context: bool = False


class GenericStatusResponse(BaseModel):
    ok: bool = True
    message: str = "ok"
