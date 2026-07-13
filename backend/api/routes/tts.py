from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from backend.schemas.api import TtsSpeechRequest
from backend.services.tts_service import TtsConfigurationError, TtsService

router = APIRouter(tags=["tts"])


@router.post("/tts/speech")
async def synthesize_speech(payload: TtsSpeechRequest) -> Response:
    try:
        result = await TtsService().synthesize(
            text=payload.text,
            voice=payload.voice,
            response_format=payload.response_format,
            speed=payload.speed,
        )
    except TtsConfigurationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return Response(
        content=result.audio,
        media_type=result.media_type,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'inline; filename="{result.filename}"',
        },
    )
