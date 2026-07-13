---
name: redis-cache-facade
description: Generic Redis caching facade pattern for Python projects. Cache failures never break the business flow — they degrade gracefully to the original uncached logic. Use when adding Redis caching to any service, designing cache keys, or implementing cache-aside patterns with TTL.
triggers:
  - Redis 缓存
  - cache
  - 添加缓存
  - 缓存 key
  - TTL
  - CacheService
scope: Python / FastAPI projects
---

# Redis 缓存门面模式 (Cache Facade Pattern)

## 核心原则

**缓存失败不阻断业务。** Redis 不可用时自动退化为原逻辑，不抛异常、不中断流程。

## CacheService 实现模板

来源：[backend/services/cache_service.py](../../backend/services/cache_service.py)

```python
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Any

from redis import Redis
from redis.exceptions import RedisError

logger = logging.getLogger(__name__)


def stable_json_dumps(value: Any) -> str:
    """稳定 JSON 序列化：sort_keys + 紧凑格式 + default=str。"""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def cache_digest(value: Any) -> str:
    """对任意可序列化对象生成稳定的 SHA256 digest。"""
    return sha256_text(stable_json_dumps(value))


class CacheService:
    """Small Redis facade. Cache failures never fail the business flow."""

    def __init__(self, settings):
        self.settings = settings
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

    # === JSON 操作 ===
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

    # === Bytes 操作 ===
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

    # === 删除 ===
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
```

## Cache Key 设计规范

### 命名空间

使用 `namespaced(namespace, digest)` 统一管理 key 前缀：

```
{cache_key_prefix}:{namespace}:{sha256_digest}
```

常用 namespace：`tts`、`doc_parse`、`guidance`、`rehearsal_aux`

### Key 内容要求

| 缓存类型 | Key 必须包含的字段 |
|---|---|
| TTS 音频 | model + voice + speed + format + text |
| 文档解析 | sha256(file_bytes) + parser + MinerU 配置 + KB 版本 |
| Guidance | employee profile + intent + persona + difficulty + model + KB 版本 + retrieval chunks |
| 预演情绪 | 只缓存 EmotionSignal，**不缓存完整员工回复** |

### 生成 digest 的标准方式

```python
digest = cache_digest({
    "provider": "xxx",
    "model": payload.get("model"),
    "voice": payload.get("voice"),
    "input": payload.get("input"),
    # ... 所有影响结果的字段
})
key = self.cache.namespaced("namespace", digest)
```

## 业务服务中的调用模式

```python
class MyService:
    def __init__(self, settings=None):
        self.settings = settings or get_settings()
        self.cache = CacheService(self.settings)

    async def do_something(self, *, input_data: str) -> Result:
        # 1. 生成 cache key
        digest = cache_digest({"input": input_data, "model": self.settings.xxx_model})
        cache_key = self.cache.namespaced("my_service", digest)

        # 2. 尝试读取缓存
        cached = await self.cache.get_json_async(cache_key)
        if cached is not None:
            return Result(**cached)

        # 3. 缓存未命中，执行原逻辑
        result = await self._expensive_operation(input_data)

        # 4. 写入缓存（不阻塞主流程）
        ttl = self.settings.my_service_cache_ttl_seconds
        await self.cache.set_json_async(cache_key, result.dict(), ttl)

        return result
```

## 配置项

```python
# settings.py 中需要的字段
redis_url: str = ""                              # Redis 连接地址
cache_enabled: bool = True                       # 缓存总开关
cache_key_prefix: str = "hragent05"              # key 前缀（区分项目）
redis_connect_timeout_seconds: float = 1.0       # 连接超时
redis_socket_timeout_seconds: float = 1.0        # 读写超时
redis_max_connections: int = 50                  # 连接池大小
xxx_cache_ttl_seconds: int = 3600                # 各业务 TTL
```

## 落地案例

在 HRagent-05 中已接入 5 层缓存，参见 [README.md](../../README.md)：

1. **TTS 缓存** — `tts_service.py`，TTL 7 天
2. **文档解析缓存** — `document_pipeline.py`，TTL 30 天
3. **Guidance 缓存** — `guidance_service.py`，TTL 6 小时
4. **预演情绪缓存** — `nodes.py`，TTL 1 小时（只缓存 EmotionSignal）
5. **通用缓存层** — `cache_service.py`

## 反模式（禁止）

- ❌ 缓存失败时抛异常阻断业务
- ❌ cache key 使用可变的 dict 直接拼接
- ❌ 缓存完整的 AI 对话回复（会导致对话固化）
- ❌ 在 cache key 中遗漏影响结果的参数
