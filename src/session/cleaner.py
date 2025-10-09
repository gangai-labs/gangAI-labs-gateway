import asyncio
import json
import time
from typing import Any, Dict

from redis.asyncio import Redis as AsyncRedis


class SessionCleaner:
    def __init__(self, async_redis: AsyncRedis, logger: Any, event_manager: Any, users_cache: Dict[str, Dict[str, Any]],
                 session_manager: Any, connection_manager: Any):
        self.async_redis = async_redis
        self.logger = logger
        self.event_manager = event_manager  # For publishing user delete events
        self.users_cache = users_cache  # For in-memory cleanup (but we won't delete users now)
        self.session_manager = session_manager  # For cleaning user sessions
        self.connection_manager = connection_manager  # For removing user connections (destroys WS)

    # From SessionRegistry [3]: Cleanup expired sessions
    async def cleanup_expired_sessions(self, max_inactive_days: int = 365):
        keys = await self.async_redis.keys("sessions:*")
        now = time.time()
        deleted = []
        for key in keys:
            ttl = await self.async_redis.ttl(key)
            if ttl == -2:  # Expired
                deleted.append(key)
            else:  # Check inactivity
                serialized = await self.async_redis.get(key)
                if serialized:
                    session = json.loads(serialized)
                    last_access = session.get("last_access", 0)
                    if now - last_access > (max_inactive_days * 86400):  # >1 year
                        deleted.append(key)
                        self.logger.debug(f"Pruned old session {key.decode()} (inactive {max_inactive_days} days)")
        if deleted:
            await self.async_redis.delete(*deleted)
            self.logger.info(f"Cleaned {len(deleted)} expired/old sessions")

    # UPDATED: cleanup_inactive_users - Keep user in Redis/cache, but cleanup sessions/connections (destroy WS)
    async def cleanup_inactive_users(self, days_inactive: int = 365):
        cutoff = time.time() - (days_inactive * 86400)
        user_keys = await self.async_redis.keys("users:*")
        cleaned_users = 0
        for key in user_keys:
            username = key.split(":")[1]  # username == user_id in this setup
            user_data = await self.async_redis.hgetall(key)
            last_login = float(user_data.get("last_login", 0))
            if last_login < cutoff:
                #  Do NOT delete user; just cleanup resources (sessions + connections/WS)
                await self.session_manager.cleanup_user_sessions(username)  # Delete all sessions for user
                await self.connection_manager.remove_connection(username)  # Destroy connections (incl. WS)
                # Pub/sub for sync across instances (e.g., close WS on other nodes)
                await self.event_manager.publish(f"events:user:inactive_cleanup:{username}", {
                    "username": username,
                    "reason": "long_inactivity",
                    "action": "cleanup_sessions_and_ws"
                })
                cleaned_users += 1
                self.logger.info(f"Cleaned up inactive sessions/connections/WS for user {username} (last login: {last_login})")
        if cleaned_users > 0:
            self.logger.info(f"Cleaned up resources for {cleaned_users} inactive users (accounts preserved)")

    async def cleanup_loop(self, max_inactive_days: int = 365, check_interval_days: int = 24):
        # TODO: Check for old connections; add user notification for inactivity (e.g., email warning before cleanup)
        while True:
            await self.cleanup_expired_sessions(max_inactive_days)
            await self.cleanup_inactive_users(max_inactive_days)
            await asyncio.sleep(60 * 60 * check_interval_days)  # Every 24h

    async def cleanup(self,days_inactive:int=None):

        await self.cleanup_expired_sessions(max_inactive_days=days_inactive)
        await self.cleanup_inactive_users(days_inactive=days_inactive)
