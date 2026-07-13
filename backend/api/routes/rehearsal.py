from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.api.dependencies import get_rehearsal_service
from backend.schemas.api import RehearsalContextUpdateRequest, RehearsalMessageRequest
from backend.schemas.state import SessionState
from backend.services.rehearsal_service import RehearsalService

router = APIRouter(prefix="/rehearsal", tags=["rehearsal"])


@router.post("/{session_id}/message", response_model=SessionState)
async def send_message(session_id: str, payload: RehearsalMessageRequest, service: RehearsalService = Depends(get_rehearsal_service)):
    return await service.send_manager_message(
        session_id,
        payload.message,
        input_mode=payload.input_mode,
        audio_emotion=payload.audio_emotion,
    )


def _sse(event: dict) -> str:
    event_name = str(event.get("event") or "message")
    data = {key: value for key, value in event.items() if key != "event"}
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/{session_id}/message/stream")
async def stream_message(session_id: str, payload: RehearsalMessageRequest, service: RehearsalService = Depends(get_rehearsal_service)):
    async def events():
        async for event in service.stream_manager_message(
            session_id,
            payload.message,
            input_mode=payload.input_mode,
            audio_emotion=payload.audio_emotion,
        ):
            yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.patch("/{session_id}/context", response_model=SessionState)
def update_rehearsal_context(
    session_id: str,
    payload: RehearsalContextUpdateRequest,
    service: RehearsalService = Depends(get_rehearsal_service),
):
    return service.update_runtime_context(
        session_id,
        runtime_note=payload.runtime_note,
        runtime_notes=payload.runtime_notes,
        persona_override=payload.persona_override,
        persona_id=payload.persona_id,
        difficulty_id=payload.difficulty_id,
        clear_context=payload.clear_context,
    )


@router.post("/{session_id}/end", response_model=SessionState)
def end_rehearsal(session_id: str, service: RehearsalService = Depends(get_rehearsal_service)):
    return service.end_rehearsal(session_id)


@router.post("/{session_id}/retry", response_model=SessionState)
def retry_rehearsal(session_id: str, service: RehearsalService = Depends(get_rehearsal_service)):
    return service.retry_rehearsal(session_id)
