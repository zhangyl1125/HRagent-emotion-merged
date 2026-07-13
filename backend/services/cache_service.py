from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

from backend.config.settings import Settings, get_settings

logger = logging.getLogger(__name__)


def stable_json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def cache_digest(value: Any) -> str:
    return sha256_text(stable_json_dumps(value))


class CacheService:
    """Small Redis facade. Cache failures never fail the business flow."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self._client: Redis | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.cache_enabled and self.settings.redis_url)

    def _redis(self) -> Redis | None:
        if not self.enabled:
            return None
        if self._client is None:
            self._client = Redis.from_url(
                self.settings.redis_url,
                socket_connect_timeout=self.settings.redis_connect_timeout_seconds,
                socket_timeout=self.settings.redis_socket_timeout_seconds,
                decode_responses=False,
            )
        return self._client

    def namespaced(self, namespace: str, digest: str) -> str:
        safe_namespace = namespace.strip(":") or "general"
        return f"{self.settings.cache_key_prefix}:{safe_namespace}:{digest}"

    def get_json(self, key: str) -> Any | None:
        client = self._redis()
        if client is None:
            return None
        try:
            raw = client.get(key)
            if raw is None:
                return None
            return json.loads(raw.decode("utf-8"))
        except (RedisError, ValueError, UnicodeDecodeError) as exc:
            logger.warning("Redis JSON cache read failed key=%s: %s", key, exc)
            return None

    async def get_json_async(self, key: str) -> Any | None:
        return await asyncio.to_thread(self.get_json, key)

    def set_json(self, key: str, value: Any, ttl_seconds: int | None) -> None:
        client = self._redis()
        if client is None:
            return
        try:
            payload = stable_json_dumps(value).encode("utf-8")
            if ttl_seconds and ttl_seconds > 0:
                client.setex(key, ttl_seconds, payload)
            else:
                client.set(key, payload)
        except RedisError as exc:
            logger.warning("Redis JSON cache write failed key=%s: %s", key, exc)

    async def set_json_async(self, key: str, value: Any, ttl_seconds: int | None) -> None:
        await asyncio.to_thread(self.set_json, key, value, ttl_seconds)

    def get_bytes(self, key: str) -> bytes | None:
        client = self._redis()
        if client is None:
            return None
        try:
            raw = client.get(key)
            return bytes(raw) if raw is not None else None
        except RedisError as exc:
            logger.warning("Redis bytes cache read failed key=%s: %s", key, exc)
            return None

    async def get_bytes_async(self, key: str) -> bytes | None:
        return await asyncio.to_thread(self.get_bytes, key)

    def set_bytes(self, key: str, value: bytes, ttl_seconds: int | None) -> None:
        client = self._redis()
        if client is None:
            return
        try:
            if ttl_seconds and ttl_seconds > 0:
                client.setex(key, ttl_seconds, value)
            else:
                client.set(key, value)
        except RedisError as exc:
            logger.warning("Redis bytes cache write failed key=%s: %s", key, exc)

    async def set_bytes_async(self, key: str, value: bytes, ttl_seconds: int | None) -> None:
        await asyncio.to_thread(self.set_bytes, key, value, ttl_seconds)

    def delete(self, *keys: str) -> None:
        client = self._redis()
        if client is None or not keys:
            return
        try:
            client.delete(*keys)
        except RedisError as exc:
            logger.warning("Redis cache delete failed keys=%s: %s", keys, exc)

    async def delete_async(self, *keys: str) -> None:
        await asyncio.to_thread(self.delete, *keys)
