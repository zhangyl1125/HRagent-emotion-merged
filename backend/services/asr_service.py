from __future__ import annotations

import base64
import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from backend.config.settings import Settings

SendFrontend = Callable[[dict[str, Any]], Awaitable[None]]


class AsrConfigurationError(RuntimeError):
    pass


class QwenRealtimeAsrProxy:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._qwen_ws: Any | None = None
        self._started_at = time.monotonic()
        self._closed = False
        self._audio_bytes = 0

    @property
    def audio_seconds(self) -> float | None:
        if self.settings.asr_input_audio_format.lower() != "pcm":
            return None
        bytes_per_second = self.settings.asr_sample_rate * 2
        return self._audio_bytes / bytes_per_second if bytes_per_second > 0 else None

    def validate(self) -> None:
        if not self.settings.asr_enabled:
            raise AsrConfigurationError("ASR is disabled")
        if not self.settings.asr_api_key:
            raise AsrConfigurationError("ASR_API_KEY is empty")
        if not self.settings.asr_ws_url:
            raise AsrConfigurationError("ASR_WS_URL is empty")
        ws_url = self.settings.asr_ws_url.strip().lower()
        if not ws_url.startswith(("ws://", "wss://")):
            raise AsrConfigurationError("ASR_WS_URL 必须是 ws:// 或 wss:// 开头的实时 WebSocket 地址。")
        if "/audio/transcriptions" in ws_url or "/audio/translations" in ws_url:
            raise AsrConfigurationError("当前 ASR_WS_URL 是普通音频转写 HTTP 接口，不是 Realtime WebSocket 地址；请配置类似 wss://.../api-ws/v1/realtime 的地址。")

    def _qwen_url(self) -> str:
        return self.settings.asr_realtime_url

    async def connect(self) -> None:
        self.validate()
        headers = {
            "Authorization": f"Bearer {self.settings.asr_api_key}",
            "OpenAI-Beta": "realtime=v1",
        }
        try:
            try:
                self._qwen_ws = await websockets.connect(
                    self._qwen_url(),
                    additional_headers=headers,
                    open_timeout=self.settings.asr_connect_timeout_seconds,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=8 * 1024 * 1024,
                )
            except TypeError:
                self._qwen_ws = await websockets.connect(
                    self._qwen_url(),
                    extra_headers=headers,
                    open_timeout=self.settings.asr_connect_timeout_seconds,
                    ping_interval=20,
                    ping_timeout=20,
                    max_size=8 * 1024 * 1024,
                )
        except InvalidStatus as exc:
            message = str(exc)
            if "HTTP 200" in message or "status code 200" in message:
                raise AsrConfigurationError("ASR_WS_URL 返回了 HTTP 200，说明它是普通 HTTP 接口，不是 Realtime WebSocket 地址。") from exc
            if "HTTP 401" in message or "status code 401" in message:
                raise AsrConfigurationError("ASR 实时服务鉴权失败：当前 ASR_API_KEY 未被 Realtime ASR 服务接受，请使用百炼/DashScope 实时语音识别 Key，或确认该 key 已开通 qwen3-asr-flash-realtime 权限。") from exc
            if "HTTP 403" in message or "status code 403" in message:
                raise AsrConfigurationError("ASR 实时服务无访问权限：请确认 ASR_API_KEY 已开通 qwen3-asr-flash-realtime 模型和 WebSocket 访问权限。") from exc
            raise
        except Exception as exc:
            message = str(exc)
            if "server rejected WebSocket connection: HTTP 200" in message:
                raise AsrConfigurationError("ASR_WS_URL 返回了 HTTP 200，说明它是普通 HTTP 接口，不是 Realtime WebSocket 地址。") from exc
            if "server rejected WebSocket connection: HTTP 401" in message:
                raise AsrConfigurationError("ASR 实时服务鉴权失败：当前 ASR_API_KEY 未被 Realtime ASR 服务接受，请使用百炼/DashScope 实时语音识别 Key，或确认该 key 已开通 qwen3-asr-flash-realtime 权限。") from exc
            if "server rejected WebSocket connection: HTTP 403" in message:
                raise AsrConfigurationError("ASR 实时服务无访问权限：请确认 ASR_API_KEY 已开通 qwen3-asr-flash-realtime 模型和 WebSocket 访问权限。") from exc
            raise
        await self._send_session_update()

    async def _send_json(self, payload: dict[str, Any]) -> None:
        if not self._qwen_ws:
            raise RuntimeError("Qwen ASR websocket is not connected")
        await self._qwen_ws.send(json.dumps(payload, ensure_ascii=False))

    async def _send_session_update(self) -> None:
        session: dict[str, Any] = {
            "modalities": ["text"],
            "input_audio_format": self.settings.asr_input_audio_format,
            "sample_rate": self.settings.asr_sample_rate,
        }
        if self.settings.asr_language:
            session["input_audio_transcription"] = {"language": self.settings.asr_language}
        if self.settings.asr_enable_server_vad:
            session["turn_detection"] = {
                "type": "server_vad",
                "threshold": self.settings.asr_vad_threshold,
                "silence_duration_ms": self.settings.asr_vad_silence_duration_ms,
            }
        else:
            session["turn_detection"] = None

        await self._send_json({
            "event_id": f"session_update_{int(time.time() * 1000)}",
            "type": "session.update",
            "session": session,
        })

    async def append_audio(self, pcm_bytes: bytes) -> None:
        if self._closed:
            return
        if time.monotonic() - self._started_at > self.settings.asr_max_session_seconds:
            raise TimeoutError("ASR session exceeded maximum duration")
        if not pcm_bytes:
            return
        self._audio_bytes += len(pcm_bytes)
        audio_b64 = base64.b64encode(pcm_bytes).decode("ascii")
        await self._send_json({
            "event_id": f"audio_{int(time.time() * 1000)}",
            "type": "input_audio_buffer.append",
            "audio": audio_b64,
        })

    async def finish(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if not self.settings.asr_enable_server_vad:
                await self._send_json({
                    "event_id": f"commit_{int(time.time() * 1000)}",
                    "type": "input_audio_buffer.commit",
                })
            await self._send_json({
                "event_id": f"finish_{int(time.time() * 1000)}",
                "type": "session.finish",
            })
        except Exception:
            pass

    async def close(self) -> None:
        self._closed = True
        if self._qwen_ws:
            await self._qwen_ws.close(code=1000, reason="client closed")

    async def receive_loop(self, send_frontend: SendFrontend) -> None:
        if not self._qwen_ws:
            raise RuntimeError("Qwen ASR websocket is not connected")
        try:
            async for raw in self._qwen_ws:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                normalized = self.normalize_qwen_event(data)
                if normalized:
                    await send_frontend(normalized)
                if data.get("type") == "session.finished":
                    break
        except ConnectionClosed:
            return

    @staticmethod
    def _first_text(data: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        nested = data.get("data")
        if isinstance(nested, dict):
            for key in keys:
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return ""

    @staticmethod
    def normalize_qwen_event(data: dict[str, Any]) -> dict[str, Any] | None:
        event_type = str(data.get("type") or "")
        if event_type == "session.created":
            return {"type": "status", "message": "ASR session created"}
        if event_type == "input_audio_buffer.speech_started":
            return {"type": "status", "code": "speech_started", "message": "speech_started"}
        if event_type == "input_audio_buffer.speech_stopped":
            return {"type": "status", "code": "speech_stopped", "message": "speech_stopped"}

        if event_type in {
            "conversation.item.input_audio_transcription.completed",
            "conversation.item.input_audio_transcription.done",
            "response.audio_transcript.done",
            "response.audio_transcript.completed",
        } or ("input_audio_transcription" in event_type and event_type.endswith((".done", ".completed"))):
            transcript = QwenRealtimeAsrProxy._first_text(data, ("transcript", "text", "content"))
            return {
                "type": "final",
                "transcript": transcript,
                "emotion": data.get("emotion"),
            }

        if event_type in {
            "conversation.item.input_audio_transcription.text",
            "conversation.item.input_audio_transcription.delta",
            "response.audio_transcript.delta",
            "response.audio_transcript.text.delta",
        } or "input_audio_transcription" in event_type or "audio_transcript" in event_type:
            text = QwenRealtimeAsrProxy._first_text(data, ("text", "delta", "transcript", "content"))
            stash = str(data.get("stash") or "")
            preview = f"{text}{stash}".strip()
            if not preview:
                return None
            return {
                "type": "partial",
                "text": text,
                "preview": preview,
                "emotion": data.get("emotion"),
            }

        if event_type == "error":
            error = data.get("error")
            message = ""
            if isinstance(error, dict):
                message = str(error.get("message") or error.get("detail") or "")
            return {
                "type": "error",
                "message": message or str(data.get("message") or data),
            }
        return None
