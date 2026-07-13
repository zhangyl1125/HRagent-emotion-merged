from __future__ import annotations

from fastapi import APIRouter, Depends
from backend.api.dependencies import get_session_service
from backend.schemas.api import CreateSessionRequest
from backend.schemas.state import SessionState
from backend.services.session_service import SessionService

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.post("", response_model=SessionState)
def create_session(payload: CreateSessionRequest, service: SessionService = Depends(get_session_service)):
    return service.create_session(max_user_turns=payload.max_user_turns)


@router.get("", response_model=list[SessionState])
def list_sessions(service: SessionService = Depends(get_session_service)):
    return service.list_sessions()


@router.get("/{session_id}", response_model=SessionState)
def get_session(session_id: str, service: SessionService = Depends(get_session_service)):
    return service.get_session(session_id)


@router.delete("/{session_id}", response_model=SessionState)
def delete_session(session_id: str, service: SessionService = Depends(get_session_service)):
    return service.delete_session(session_id)
