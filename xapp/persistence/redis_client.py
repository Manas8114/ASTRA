import os
import json
import logging
from typing import List
import redis.asyncio as redis

log = logging.getLogger("astra.redis")

class RedisClient:
    """Async Redis Client for persisting ASTRA state."""
    
    def __init__(self):
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", "6379"))
        self.pool = redis.ConnectionPool(host=host, port=port, decode_responses=True)
        self.client = redis.Redis(connection_pool=self.pool)
        log.info(f"Initialized Redis client targeting {host}:{port}")

    async def add_history(self, cell_id: str, kpi: dict):
        key = f"astra:{cell_id}:kpi_history"
        await self.client.xadd(key, {"data": json.dumps(kpi)}, maxlen=3600)

    async def get_history(self, cell_id: str, minutes: int = 60) -> List[dict]:
        key = f"astra:{cell_id}:kpi_history"
        # Since it's a stream, we fetch the latest elements
        # For simplicity, returning the whole stream or last X items
        limit = min(minutes * 60, 3600)
        messages = await self.client.xrevrange(key, max='+', min='-', count=limit)
        return [json.loads(m[1]["data"]) for m in reversed(messages)]

    async def add_anomaly(self, cell_id: str, anomaly: dict):
        key = f"astra:{cell_id}:anomalies"
        await self.client.lpush(key, json.dumps(anomaly))
        await self.client.ltrim(key, 0, 999)

    async def get_anomalies(self, cell_id: str, limit: int = 100) -> List[dict]:
        key = f"astra:{cell_id}:anomalies"
        items = await self.client.lrange(key, 0, limit - 1)
        return [json.loads(i) for i in items]

    async def add_healing_action(self, cell_id: str, action: dict):
        key = f"astra:{cell_id}:healing_log"
        await self.client.lpush(key, json.dumps(action))
        await self.client.ltrim(key, 0, 999)

    async def get_healing_actions(self, cell_id: str, limit: int = 100) -> List[dict]:
        key = f"astra:{cell_id}:healing_log"
        items = await self.client.lrange(key, 0, limit - 1)
        return [json.loads(i) for i in items]

    async def set_latest_attribution(self, cell_id: str, attribution: dict):
        key = f"astra:{cell_id}:attribution"
        await self.client.set(key, json.dumps(attribution))

    async def get_latest_attribution(self, cell_id: str) -> dict:
        key = f"astra:{cell_id}:attribution"
        val = await self.client.get(key)
        return json.loads(val) if val else {}

    async def health_check(self) -> bool:
        try:
            return await self.client.ping()
        except Exception as e:
            log.error(f"Redis health check failed: {e}")
            return False

redis_client = RedisClient()
