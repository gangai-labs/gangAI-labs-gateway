import os
import time
from typing import Optional, Dict, Any
from redis.asyncio import Redis as AsyncRedis

class ConnectionManager:
    """Handles connection tracking, timestamps, and removal."""
    def __init__(self, async_redis: AsyncRedis, logger: Any, event_manager: Any, timeout_seconds: int):
        self.async_redis = async_redis
        self.logger = logger
        self.event_manager = event_manager
        self.timeout_seconds = timeout_seconds

        self.timestamp_update_interval = 30 #Todo hard coded move to config
        self._last_connection_updates: Dict[str, float] = {}  # user_id -> last_update_time


    async def track_connection(self, user_id: str, session_id: str, gateway_id: Optional[str] = None,
                               ws_connected: bool = False):
        """Track connections with host:port-server_num format for sticky sessions."""
        """Track connections with consistent host:port format."""
        if gateway_id is None:
            # Use simple host:port format (no server_num)
            host = os.getenv("HOST", "localhost")
            port = os.getenv("PORT", "8000")
            gateway_id = f"{host}:{port}"  # Consistent format
        key = f"connections:{user_id}"
        data = {
            "session_id": session_id,
            "gateway_id": gateway_id,  # Always new format
            "ws_connected": "1" if ws_connected else "0",
            "last_seen": time.time()
        }
        await self.async_redis.hset(key, mapping=data)
        await self.async_redis.expire(key, self.timeout_seconds)
        # Pub/Sub push (same)
        await self.event_manager.publish(f"events:connection:{'ws' if ws_connected else 'http'}:{user_id}", data)
        self.logger.debug(f"Tracked connection for {user_id} on {gateway_id}")

    async def get_connection_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        key = f"connections:{user_id}"
        info = await self.async_redis.hgetall(key)
        if info:
            info["ws_connected"] = info.get("ws_connected", "0") == "1"
            info["last_seen"] = float(info.get("last_seen", 0))
        return info

    async def update_connection_timestamp(self, user_id: str, session_id: str):
        current_time = time.time()
        last_update = self._last_connection_updates.get(user_id, 0)

        if current_time - last_update >= self.timestamp_update_interval:
            key = f"connections:{user_id}"
            host = os.getenv("HOST", "localhost")
            port = os.getenv("PORT", "8000")
            gateway_id = f"{host}:{port}"
            await self.async_redis.hset(key, mapping={
                "last_seen": current_time,
                "gateway_id": gateway_id
            })
            await self.async_redis.expire(key, self.timeout_seconds)
            self._last_connection_updates[user_id] = current_time
            self.logger.debug(f"Updated timestamp/gateway for {user_id}: {gateway_id}")

    async def remove_connection(self, user_id: str):
        key = f"connections:{user_id}"
        await self.async_redis.delete(key)
        await self.event_manager.publish(f"events:connection:removed:{user_id}", {"user_id": user_id})
        self.logger.debug(f"Removed connection for {user_id}")