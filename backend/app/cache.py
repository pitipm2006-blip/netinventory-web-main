"""Caché con TTL: Redis si REDIS_URL está definido y responde; memoria como respaldo."""
import json
import logging
import os
import time

logger = logging.getLogger(__name__)


class TTLCache:
    def __init__(self, redis_url: str | None = None, prefix: str = "netinv:") -> None:
        self._memory: dict[str, tuple[float, str]] = {}
        self._prefix = prefix
        self._redis = None
        self.hits = 0
        self.misses = 0
        if redis_url:
            try:
                import redis.asyncio as aioredis

                self._redis = aioredis.from_url(redis_url, socket_timeout=1, decode_responses=True)
            except Exception:
                logger.warning("Redis no disponible; se usará caché en memoria")

    async def get_json(self, key: str):
        raw = None
        if self._redis is not None:
            try:
                raw = await self._redis.get(self._prefix + key)
            except Exception:
                logger.warning("Fallo de Redis en get; usando memoria")
        if raw is None:
            entry = self._memory.get(key)
            if entry and entry[0] > time.monotonic():
                raw = entry[1]
        if raw is None:
            self.misses += 1
            return None
        self.hits += 1
        return json.loads(raw)

    async def set_json(self, key: str, value, ttl: int) -> None:
        raw = json.dumps(value)
        self._memory[key] = (time.monotonic() + ttl, raw)
        if self._redis is not None:
            try:
                await self._redis.set(self._prefix + key, raw, ex=ttl)
            except Exception:
                logger.warning("Fallo de Redis en set")

    async def invalidate(self, key: str) -> None:
        self._memory.pop(key, None)
        if self._redis is not None:
            try:
                await self._redis.delete(self._prefix + key)
            except Exception:
                logger.warning("Fallo de Redis en delete")


cache = TTLCache(os.getenv("REDIS_URL"))
