from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from typing import Any

import httpx

from backend.config.settings import Settings, get_settings
from backend.services.cache_service import CacheService, cache_digest


class TtsConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True)
class TtsAudioResult:
    audio: bytes
    media_type: str
    filename: str


class TtsService:
    _MEDIA_TYPES = {
        "mp3": "audio/mpeg",
        "wav": "audio/wav",
        "opus": "audio/ogg",
        "aac": "audio/aac",
        "flac": "audio/flac",
    }

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.cache = CacheService(self.settings)

    async def synthesize(
        self,
        *,
        text: str,
        voice: str | None = None,
        response_format: str | None = None,
        speed: float | None = None,
    ) -> TtsAudioResult:
        safe_text = text.strip()
        if not safe_text:
            raise ValueError("请输入需要朗读的文本。")
        if len(safe_text) > self.settings.tts_max_chars:
            raise ValueError(f"朗读文本过长，最多支持 {self.settings.tts_max_chars} 个字符。")
        if not self.settings.tts_enabled:
            raise TtsConfigurationError("TTS 已关闭。")
        if not self.settings.tts_api_url:
            raise TtsConfigurationError("TTS_API_URL 为空，无法进行语音合成。")

        api_key = self.settings.tts_api_key or self.settings.asr_api_key or self.settings.chat_api_key
        if not api_key:
            raise TtsConfigurationError("TTS_API_KEY 为空，且没有可复用的 ASR_API_KEY/CHAT_API_KEY。")

        fmt = (response_format or self.settings.tts_response_format or "mp3").strip().lower()
        payload: dict[str, Any] = {
            "model": self.settings.tts_model,
            "input": safe_text,
            "voice": (voice or self.settings.tts_voice or "Cherry").strip(),
            "response_format": fmt,
        }
        effective_speed = speed if speed is not None else self.settings.tts_speed
        if effective_speed and effective_speed != 1.0:
            payload["speed"] = effective_speed

        cache_base = self._cache_base(payload, fmt)
        meta_key = f"{cache_base}:meta"
        audio_key = f"{cache_base}:audio"
        cached_meta, cached_audio = await asyncio.gather(
            self.cache.get_json_async(meta_key),
            self.cache.get_bytes_async(audio_key),
        )
        if cached_meta and cached_audio:
            return TtsAudioResult(
                audio=cached_audio,
                media_type=str(cached_meta.get("media_type") or self._MEDIA_TYPES.get(fmt, "audio/mpeg")),
                filename=str(cached_meta.get("filename") or f"employee-reply.{fmt}"),
            )

        headers = {"Authorization": f"Bearer {api_key}"}
        timeout = httpx.Timeout(self.settings.tts_timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(self.settings.tts_api_url, headers=headers, json=payload)
        except httpx.HTTPError as exc:
            raise RuntimeError(f"语音合成服务请求失败：{exc}") from exc

        if response.status_code in {401, 403}:
            raise TtsConfigurationError("语音合成鉴权失败：请确认现有 key 已开通 qwen3-tts-flash 权限。")
        if response.status_code >= 400:
            raise RuntimeError(f"语音合成服务返回错误 {response.status_code}: {response.text[-500:]}")

        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        media_type = content_type if content_type.startswith("audio/") else self._MEDIA_TYPES.get(fmt, "audio/mpeg")

        if content_type == "application/json" or response.content[:1] in {b"{", b"["}:
            audio = self._audio_from_json(response.json())
        else:
            audio = response.content

        if not audio:
            raise RuntimeError("语音合成服务未返回可用音频。")

        filename = f"employee-reply.{fmt}"
        result = TtsAudioResult(audio=audio, media_type=media_type, filename=filename)
        ttl = self.settings.tts_cache_ttl_seconds
        await asyncio.gather(
            self.cache.set_bytes_async(audio_key, audio, ttl),
            self.cache.set_json_async(meta_key, {"media_type": media_type, "filename": filename}, ttl),
        )
        return result

    def _cache_base(self, payload: dict[str, Any], fmt: str) -> str:
        digest = cache_digest({
            "provider": self.settings.tts_provider,
            "model": payload.get("model"),
            "voice": payload.get("voice"),
            "format": fmt,
            "speed": payload.get("speed", 1.0),
            "input": payload.get("input"),
        })
        return self.cache.namespaced("tts", digest)

    @classmethod
    def _audio_from_json(cls, payload: Any) -> bytes:
        if isinstance(payload, dict):
            for key in ("audio", "b64_json", "data", "content"):
                value = payload.get(key)
                if isinstance(value, str) and value.strip():
                    return cls._decode_base64(value)
            nested = payload.get("data")
            if isinstance(nested, list) and nested:
                return cls._audio_from_json(nested[0])
            if isinstance(nested, dict):
                return cls._audio_from_json(nested)
        if isinstance(payload, list) and payload:
            return cls._audio_from_json(payload[0])
        return b""

    @staticmethod
    def _decode_base64(value: str) -> bytes:
        text = value.strip()
        if "," in text and text.startswith("data:"):
            text = text.split(",", 1)[1]
        return base64.b64decode(text)
