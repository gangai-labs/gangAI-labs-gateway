# File: src/wss/registry.py
# WebSocket registry - connection tracking and management

import asyncio
import time
import orjson
from typing import Dict, Any, Optional

from config import REDIS_CONFIG
from wss.models import ConnectionInfo


class WebsocketsRegistry:
    """WebSocket registry for connection tracking and management"""

    def __init__(self, logger_manager: object, redis_client: object, config: dict):
        self.config = config
        self.logger = logger_manager.create_logger(
            logger_name="WebsocketsRegistry",
            logging_level=self.config.get("LOGGING_LEVEL", "INFO")
        )
        self.redis = redis_client
        self.timeout_seconds = REDIS_CONFIG["SESSION_TIMEOUT_SECONDS"]

        # Connection storage: {user_id: ConnectionInfo}
        self.active_connections: Dict[str, ConnectionInfo] = {}
        self._connections_count: int = 0

        # Background tasks
        self._cleanup_task: Optional[asyncio.Task] = None
        self._pubsub_task: Optional[asyncio.Task] = None

        # Configuration
        self.last_seen_update_interval = 30  # Update Redis every 30s
        self._connection_cleanup_loop_interval = 300  # Cleanup every 5 minutes

    async def track_ws_connection(self, user_id: str, session_id: str, gateway_id: str,
                                  chat_id: str, websocket: Any) -> None:
        """Track new WebSocket connection"""
        current_time = time.time()

        # Store in memory
        conn_info = ConnectionInfo(
            websocket=websocket,
            gateway_id=gateway_id,
            last_seen=current_time,
            user_id=user_id,
            session_id=session_id,
            connected_at=current_time,  # Add this required field
            role="user"  # Add default role
        )
        self.active_connections[user_id] = conn_info
        self._connections_count += 1

        # Update Redis
        key = f"connections:{user_id}"
        data = {
            "session_id": session_id,
            "gateway_id": gateway_id,
            "ws_connected": "1",
            "last_seen": str(current_time),
            "connected_at": str(current_time)  # Also store in Redis
        }
        await self.redis.hset(key, mapping=data)
        await self.redis.expire(key, self.timeout_seconds)

        self.logger.debug(f"Tracked WS connection: {user_id} on {gateway_id}")

    async def update_connection_timestamp(self, user_id: str, session_id: str) -> None:
        """Update connection activity timestamp (throttled to every 30s)"""
        if user_id in self.active_connections:
            current_time = time.time()
            last_seen = self.active_connections[user_id].last_seen

            # Only update if 30+ seconds have passed
            if current_time - last_seen >= self.last_seen_update_interval:
                self.active_connections[user_id].last_seen = current_time

                # Update Redis
                key = f"connections:{user_id}"
                await self.redis.hset(key, "last_seen", str(current_time))
                await self.redis.expire(key, self.timeout_seconds)

    async def remove_ws_connection(self, user_id: str, session_id: str) -> None:
        """Remove WebSocket connection"""
        # Remove from memory
        conn_info = self.active_connections.pop(user_id, None)
        if conn_info:
            self._connections_count -= 1

            # Close WebSocket if still connected
            try:
                await conn_info.websocket.close(code=1000, reason="Session ended")
            except Exception as e:
                self.logger.debug(f"WS close error for {user_id}: {e}")

        # Remove from Redis
        key = f"connections:{user_id}"
        await self.redis.hdel(key, "ws_connected")

        # Publish removal event
        await self.redis.publish(
            f"events:connection:removed:{user_id}",
            orjson.dumps({"user_id": user_id, "session_id": session_id}).decode()
        )

        self.logger.debug(f"Removed WS connection: {user_id}")

    async def get_ws_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get WebSocket connection info for a user"""
        # Check memory first
        if user_id in self.active_connections:
            conn = self.active_connections[user_id]
            return {
                "session_id": conn.session_id,
                "gateway_id": conn.gateway_id,
                "ws_connected": True,
                "last_seen": conn.last_seen
            }
        return None

    async def publish_event(self, channel: str, data: Dict[str, Any]) -> None:
        """Publish event to Redis pub/sub"""
        try:
            message = orjson.dumps(data).decode()
            await self.redis.publish(channel, message)
        except Exception as e:
            self.logger.debug(f"Publish event error: {e}")

    async def get_services_cached(self) -> Dict[str, Any]:
        """Get cached service discovery information"""
        services = {}
        try:
            async for key in self.redis.scan_iter("services:*"):
                service_name = key.decode().split(":")[1] if isinstance(key, bytes) else key.split(":")[1]
                services[service_name] = await self.redis.hgetall(key)
        except Exception as e:
            self.logger.error(f"Service discovery error: {e}")
        return services

    async def pubsub_listener(self) -> None:
        """Listen for Redis pub/sub events"""
        pubsub = self.redis.pubsub()
        try:
            await pubsub.subscribe("events:session:logout:*")

            async for message in pubsub.listen():
                if message["type"] != "message":
                    continue

                try:
                    event = orjson.loads(message["data"])
                    channel = message["channel"].decode() if isinstance(message["channel"], bytes) else message["channel"]

                    if "events:session:logout:" in channel:
                        user_id = channel.split(":")[-1]
                        if user_id in self.active_connections:
                            session_id = event.get("session_id", "unknown")
                            await self.remove_ws_connection(user_id, session_id)

                except Exception as e:
                    self.logger.debug(f"PubSub processing error: {e}")

        except Exception as e:
            self.logger.error(f"PubSub listener error: {e}")
            await asyncio.sleep(5)
            asyncio.create_task(self.pubsub_listener())

    async def start_background_tasks(self) -> None:
        """Start background maintenance tasks"""
        self._pubsub_task = asyncio.create_task(self.pubsub_listener())
        self._cleanup_task = asyncio.create_task(self._connection_cleanup_loop())
        self.logger.info("Background tasks started")

    async def _connection_cleanup_loop(self) -> None:
        """Periodic cleanup of stale connections"""
        while True:
            try:
                await asyncio.sleep(60)  # Run every minute

                now = time.time()
                stale_threshold = now - self._connection_cleanup_loop_interval

                # Find stale connections
                stale_users = []
                for user_id, conn in self.active_connections.items():
                    if conn.last_seen < stale_threshold:
                        stale_users.append(user_id)

                # Remove stale connections
                for user_id in stale_users:
                    self.logger.warning(f"Removing stale connection: {user_id}")
                    await self.remove_ws_connection(user_id, "stale_cleanup")

            except Exception as e:
                self.logger.error(f"Cleanup loop error: {e}")
                await asyncio.sleep(10)

    async def cleanup_all(self) -> None:
        """Graceful shutdown - close all connections"""
        # Stop background tasks
        for task in [self._pubsub_task, self._cleanup_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close all active connections
        user_ids = list(self.active_connections.keys())
        for user_id in user_ids:
            await self.remove_ws_connection(user_id, "shutdown")

        self.logger.info("All WebSocket connections cleaned up")

    def get_connection_count(self) -> int:
        """Get current connection count"""
        return self._connections_count

    def get_all_connections(self) -> Dict[str, Dict[str, Any]]:
        """Get all active connections"""
        return {
            user_id: {
                "session_id": conn.session_id,
                "gateway_id": conn.gateway_id,
                "last_seen": conn.last_seen
            }
            for user_id, conn in self.active_connections.items()
        }