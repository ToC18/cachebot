from decimal import Decimal
from typing import Optional
import logging
import redis.asyncio as aioredis
from app.config import settings

logger = logging.getLogger("cachebot.redis")


class RedisService:
    def __init__(self):
        self._memory_store = {}
        try:
            self.redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        except Exception as e:
            logger.warning(f"Could not connect to Redis ({e}), using in-memory cache fallback.")
            self.redis = None

    async def get_today_spent(self, user_id: int) -> Decimal:
        key = f"daily_spent:{user_id}"
        if self.redis:
            try:
                val = await self.redis.get(key)
                return Decimal(val) if val else Decimal("0.00")
            except Exception:
                pass
        val = self._memory_store.get(key)
        return Decimal(str(val)) if val else Decimal("0.00")

    async def add_today_spent(self, user_id: int, amount: Decimal) -> Decimal:
        key = f"daily_spent:{user_id}"
        if self.redis:
            try:
                val = await self.redis.incrbyfloat(key, float(amount))
                ttl = await self.redis.ttl(key)
                if ttl == -1:
                    await self.redis.expire(key, 86400)
                return Decimal(str(round(val, 2)))
            except Exception:
                pass
        current = Decimal(str(self._memory_store.get(key, "0.00")))
        new_val = current + amount
        self._memory_store[key] = str(round(new_val, 2))
        return new_val

    async def reset_today_spent(self, user_id: int):
        key = f"daily_spent:{user_id}"
        if self.redis:
            try:
                await self.redis.delete(key)
            except Exception:
                pass
        self._memory_store.pop(key, None)

    async def set_crisis_state(self, user_id: int, overspent_amount: Decimal):
        key = f"crisis_pending:{user_id}"
        if self.redis:
            try:
                await self.redis.set(key, str(overspent_amount), ex=3600 * 12)
                return
            except Exception:
                pass
        self._memory_store[key] = str(overspent_amount)

    async def get_crisis_state(self, user_id: int) -> Optional[Decimal]:
        key = f"crisis_pending:{user_id}"
        if self.redis:
            try:
                val = await self.redis.get(key)
                return Decimal(val) if val else None
            except Exception:
                pass
        val = self._memory_store.get(key)
        return Decimal(val) if val else None

    async def clear_crisis_state(self, user_id: int):
        key = f"crisis_pending:{user_id}"
        if self.redis:
            try:
                await self.redis.delete(key)
            except Exception:
                pass
        self._memory_store.pop(key, None)

    async def close(self):
        if self.redis:
            try:
                await self.redis.aclose()
            except Exception:
                pass


redis_client = RedisService()
