from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from fastapi import APIRouter, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect

from backend.config.settings import get_settings
from backend.services.asr_service import AsrConfigurationError, QwenRealtimeAsrProxy

router = APIRouter(tags=["asr"])




def _extract_transcript(payload: Any) -> str:
    if isinstance(payload, str):
        return payload.strip()
    if not isinstance(payload, dict):
        return ""
    for key in ("text", "transcript", "translation", "result"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    data = payload.get("data")
    if isinstance(data, dict):
        return _extract_transcript(data)
    if isinstance(data, list):
        parts = [_extract_transcript(item) for item in data]
        return "".join(part for part in parts if part)
    choices = payload.get("choices")
    if isinstance(choices, list):
        parts = [_extract_transcript(item) for item in choices]
        return "".join(part for part in parts if part)
    return ""


@router.post("/asr/transcribe")
async def asr_transcribe(
    file: UploadFile = File(...),
    session_id: str | None = Form(default=None),
    language: str | None = Form(default=None),
) -> dict[str, str | float | None]:
    settings = get_settings()
    if not settings.asr_api_key:
        raise HTTPException(status_code=400, detail="ASR_API_KEY 为空，无法进行语音转写。")
    if not settings.asr_http_url:
        raise HTTPException(status_code=400, detail="ASR_HTTP_URL 为空，无法进行语音转写。")

    audio = await file.read()
    if not audio:
        raise HTTPException(status_code=400, detail="没有收到录音内容。")

    headers = {"Authorization": f"Bearer {settings.asr_api_key}"}
    data = {"model": settings.asr_http_model, "language": language or settings.asr_language}
    if session_id:
        data["session_id"] = session_id
    files = {
        "file": (
            file.filename or "speech.webm",
            audio,
            file.content_type or "application/octet-stream",
        ),
    }
    timeout = httpx.Timeout(settings.asr_session_timeout_seconds)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(settings.asr_http_url, headers=headers, data=data, files=files)
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"语音转写服务请求失败：{exc}") from exc

    if response.status_code in {401, 403}:
        raise HTTPException(status_code=502, detail="语音转写鉴权失败：当前 key 未被音频转写服务接受，请确认该 key 已开通语音识别权限。")
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"语音转写服务返回错误 {response.status_code}: {response.text[-500:]}")

    try:
        payload = response.json()
    except ValueError as exc:
        raise HTTPException(status_code=502, detail="语音转写服务返回非 JSON 响应。") from exc

    transcript = _extract_transcript(payload)
    if not transcript:
        raise HTTPException(status_code=502, detail="语音转写服务未返回可用文本。")
    return {
        "text": transcript,
        "audio_emotion": None,
        "duration_seconds": 0.0,
        "provider": settings.asr_http_model,
    }

@router.websocket("/asr/realtime")
async def asr_realtime(websocket: WebSocket) -> None:
    await websocket.accept()
    settings = get_settings()
    proxy = QwenRealtimeAsrProxy(settings)
    receive_task: asyncio.Task | None = None

    async def send_frontend(payload: dict) -> None:
        await websocket.send_text(json.dumps(payload, ensure_ascii=False))

    try:
        await proxy.connect()
        await send_frontend({"type": "status", "message": "ASR connected"})

        receive_task = asyncio.create_task(proxy.receive_loop(send_frontend))

        while True:
            message = await websocket.receive()
            if message.get("bytes") is not None:
                await proxy.append_audio(message["bytes"] or b"")
                continue

            if message.get("text") is not None:
                try:
                    data = json.loads(message["text"] or "{}")
                except json.JSONDecodeError:
                    continue
                event_type = data.get("type")
                if event_type == "stop":
                    await proxy.finish()
                    break
                if event_type == "ping":
                    await send_frontend({"type": "status", "message": "pong"})

            if receive_task.done():
                break

        await proxy.finish()
        try:
            await asyncio.wait_for(receive_task, timeout=3)
        except asyncio.TimeoutError:
            receive_task.cancel()

    except WebSocketDisconnect:
        pass
    except AsrConfigurationError as exc:
        await send_frontend({"type": "error", "message": str(exc)})
    except Exception as exc:  # noqa: BLE001
        await send_frontend({"type": "error", "message": f"ASR failed: {exc}"})
    finally:
        if receive_task and not receive_task.done():
            receive_task.cancel()
        await proxy.close()
