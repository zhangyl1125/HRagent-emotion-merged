from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from backend.api.dependencies import get_guidance_service
from backend.schemas.guidance import GuidanceReport
from backend.services.guidance_service import GuidanceService

router = APIRouter(prefix="/guidance", tags=["guidance"])


@router.post("/{session_id}", response_model=GuidanceReport)
async def generate_guidance(session_id: str, service: GuidanceService = Depends(get_guidance_service)):
    return await service.generate(session_id)


def _sse(event: dict) -> str:
    event_name = str(event.get("event") or "message")
    data = {key: value for key, value in event.items() if key != "event"}
    return f"event: {event_name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("/{session_id}/stream")
async def stream_guidance(session_id: str, service: GuidanceService = Depends(get_guidance_service)):
    async def events():
        async for event in service.stream_generate(session_id):
            yield _sse(event)

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{session_id}", response_model=GuidanceReport)
def get_guidance(session_id: str, service: GuidanceService = Depends(get_guidance_service)):
    return service.get(session_id)
