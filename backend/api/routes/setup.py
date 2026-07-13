from __future__ import annotations

from fastapi import APIRouter, Depends

from backend.api.dependencies import get_setup_service
from backend.schemas.api import (
    ConfirmIntentRequest,
    ConfirmPersonaRequest,
    ConfirmProfileRequest,
    ConfirmSimulationRequest,
)
from backend.schemas.state import SessionState
from backend.services.setup_service import SetupService

router = APIRouter(prefix="/setup", tags=["setup"])


@router.get("/options")
def setup_options(service: SetupService = Depends(get_setup_service)):
    return service.list_options()


@router.patch("/{session_id}/profile", response_model=SessionState)
def confirm_profile(session_id: str, payload: ConfirmProfileRequest, service: SetupService = Depends(get_setup_service)):
    return service.confirm_profile(session_id, payload.profile)


@router.patch("/{session_id}/intent", response_model=SessionState)
async def confirm_intent(session_id: str, payload: ConfirmIntentRequest, service: SetupService = Depends(get_setup_service)):
    return await service.confirm_intent(session_id, intent_id=payload.intent_id, free_text=payload.free_text)


@router.patch("/{session_id}/persona", response_model=SessionState)
def confirm_persona(session_id: str, payload: ConfirmPersonaRequest, service: SetupService = Depends(get_setup_service)):
    return service.confirm_persona(session_id, payload.persona_id, payload.difficulty_id, payload.run_mode)


@router.patch("/{session_id}/simulation", response_model=SessionState)
def confirm_simulation(
    session_id: str,
    payload: ConfirmSimulationRequest,
    service: SetupService = Depends(get_setup_service),
):
    return service.confirm_simulation(
        session_id,
        personality=payload.personality,
        primary_motive_id=payload.primary_motive_id,
        secondary_motive_ids=payload.secondary_motive_ids,
        run_mode=payload.run_mode,
    )


@router.post("/{session_id}/complete", response_model=SessionState)
def complete_setup(session_id: str, service: SetupService = Depends(get_setup_service)):
    return service.complete_setup(session_id)
