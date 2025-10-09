import asyncio
import json
import time
import uuid
from typing import Dict, Tuple, Any, Optional

from redis.asyncio import Redis as AsyncRedis

class SessionHandler:
    """Handles session creation, updates, timestamps, and cleanup."""

    def __init__(self, async_redis: AsyncRedis, logger: Any, event_manager: Any, timeout_seconds: int):
        self.async_redis = async_redis
        self.logger = logger
        self.event_manager = event_manager
        self.timeout_seconds = timeout_seconds

        # Write-behind cache
        self._pending_updates: Dict[str, Dict[str, Any]] = {}
        self._update_lock = asyncio.Lock()

        #  Session caching and timestamp tracking
        self._session_cache: Dict[str, Tuple[Dict[str, Any], float]] = {}
        self._last_timestamp_updates: Dict[str, float] = {}
        self._cache_ttl = 30  # seconds #TODO hardcoded idk do something
        self.timestamp_update_interval = 30  #TODO seconds #hardcoded idk do something

        # Background tasks
        self._cleanup_task: Optional[asyncio.Task] = None

    async def get_or_create_session(self, user_id: str, chat_id: str, session_id: Optional[str] = None) -> Tuple[
        Dict[str, Any], str]:
        if session_id:
            # Check cache first
            try:
                if session_id in self._session_cache:
                    cached_data, cached_at = self._session_cache[session_id]
                    if time.time() - cached_at < self._cache_ttl:
                        self.logger.debug(f"Cache hit for session {session_id}")
                        return cached_data.copy(), session_id  # Return copy to avoid mutations
            except Exception as e:
                self.logger.warning(f"Cache read error for {session_id}: {e}")

            # Cache miss - fetch from Redis
            try:
                session_key = f"sessions:{session_id}"
                serialized = await self.async_redis.get(session_key)
                if serialized:
                    session = json.loads(serialized)
                    # Update cache
                    try:
                        self._session_cache[session_id] = (session.copy(), time.time())
                    except Exception as e:
                        self.logger.warning(f"Cache write error for {session_id}: {e}")

                    self.logger.info(f"Reused session {session_id} for {user_id}")
                    return session, session_id
            except json.JSONDecodeError as e:
                self.logger.error(f"Invalid session data for {session_id}: {e}")
            except Exception as e:
                self.logger.error(f"Session fetch error for {session_id}: {e}")

        # Create new session (existing code)
        new_session_id = str(uuid.uuid4())
        session = {
            "user_id": user_id,
            "chat_id": chat_id,
            "data": {"conversation": [], "api_key": None},
            "created_at": time.time(),
            "last_access": time.time()
        }
        session_key = f"sessions:{new_session_id}"
        await self.async_redis.set(session_key, json.dumps(session), ex=self.timeout_seconds)

        # Cache the new session
        try:
            self._session_cache[new_session_id] = (session.copy(), time.time())
        except Exception as e:
            self.logger.warning(f"Failed to cache new session {new_session_id}: {e}")

        self.logger.info(f"Created new session {new_session_id} for {user_id}")
        await self.event_manager.publish(f"events:session:new:{user_id}", {
            "session_id": new_session_id, "user_id": user_id, "chat_id": chat_id
        })
        return session, new_session_id

    async def update_session(self, user_id: str, chat_id: str, updates: Dict[str, Any], session_id: str):
        """Non-blocking update - queues to batch writer"""
        async with self._update_lock:
            if session_id not in self._pending_updates:
                self._pending_updates[session_id] = {
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "updates": updates.copy(),
                    "last_access": time.time()
                }
            else:
                # Merge updates
                self._pending_updates[session_id]["updates"].update(updates)
                self._pending_updates[session_id]["last_access"] = time.time()

    async def _batch_writer(self):
        """Background task: batch write every 100ms for high throughput"""
        while True:
            try:
                await asyncio.sleep(0.1)  # 100ms batches = 10 batches/sec

                if not self._pending_updates:
                    continue

                # Grab all pending updates
                async with self._update_lock:
                    to_process = self._pending_updates.copy()
                    self._pending_updates.clear()

                if not to_process:
                    continue

                # Pipeline: GET all sessions
                async with self.async_redis.pipeline(transaction=False) as pipe:
                    session_keys = {}
                    for session_id, data in to_process.items():
                        session_key = f"sessions:{session_id}"
                        session_keys[session_id] = session_key
                        await pipe.get(session_key)

                    results = await pipe.execute()

                # Process in memory
                async with self.async_redis.pipeline(transaction=False) as pipe:
                    for idx, (session_id, data) in enumerate(to_process.items()):
                        serialized = results[idx]
                        if serialized:
                            session = json.loads(serialized)
                            session["data"].update(data["updates"])
                            session["last_access"] = data["last_access"]

                            session_key = session_keys[session_id]
                            await pipe.set(session_key, json.dumps(session), ex=self.timeout_seconds)

                            # Optional: queue pub/sub separately to not block pipeline
                            asyncio.create_task(
                                self.event_manager.publish(
                                    f"events:session:update:{data['user_id']}",
                                    {
                                        "session_id": session_id,
                                        "updates": data["updates"],
                                        "chat_id": data["chat_id"]
                                    }
                                )
                            )

                    await pipe.execute()

                self.logger.debug(f"Batch wrote {len(to_process)} sessions")

            except Exception as e:
                self.logger.error(f"Batch writer error: {e}")
                await asyncio.sleep(0.5)

    async def delete_session(self, session_id: str):
        session_key = f"sessions:{session_id}"
        await self.async_redis.delete(session_key)
        self.logger.debug(f"Deleted session {session_id}")

    async def update_timestamp_only(self, session_id: str):
        current_time = time.time()
        last_update = self._last_timestamp_updates.get(session_id, 0)

        # Only update if 30+ seconds have passed
        if current_time - last_update >= self.timestamp_update_interval:
            session_key = f"sessions:{session_id}"
            serialized = await self.async_redis.get(session_key)
            if serialized:
                session = json.loads(serialized)
                session["last_access"] = current_time
                await self.async_redis.set(session_key, json.dumps(session), ex=self.timeout_seconds)
                self._last_timestamp_updates[session_id] = current_time

    async def cleanup_user_sessions(self, user_id: str):
        session_keys = await self.async_redis.keys("sessions:*")
        deleted_count = 0
        for key in session_keys:
            serialized = await self.async_redis.get(key)
            if serialized:
                session = json.loads(serialized)
                if session.get("user_id") == user_id:
                    await self.async_redis.delete(key)
                    deleted_count += 1
                    self.logger.debug(f"Deleted session {key} for {user_id}")
        if deleted_count > 0:
            self.logger.info(f"Cleaned up {deleted_count} sessions for user {user_id}")

    async def _cleanup_stale_cache(self):
        """Remove stale cache entries every 5 minutes"""
        while True:
            try:
                stale_sessions = None
                stale_timestamps = None
                await asyncio.sleep(300)  # 5 minutes
                now = time.time()

                # Clean session cache with safe iteration
                try:
                    stale_sessions = [
                        sid for sid, (_, cached_at) in list(self._session_cache.items())
                        if now - cached_at > self._cache_ttl * 2
                    ]
                    for sid in stale_sessions:
                        try:
                            del self._session_cache[sid]
                        except KeyError:
                            pass  # Already removed by another operation
                except Exception as e:
                    self.logger.error(f"Session cache cleanup error: {e}")

                # Clean timestamp tracking with safe iteration
                try:
                    stale_timestamps = [
                        sid for sid, last_update in list(self._last_timestamp_updates.items())
                        if now - last_update > 600  # 10 minutes
                    ]
                    for sid in stale_timestamps:
                        try:
                            del self._last_timestamp_updates[sid]
                        except KeyError:
                            pass  # Already removed
                except Exception as e:
                    self.logger.error(f"Timestamp cache cleanup error: {e}")

                if stale_sessions or stale_timestamps:
                    self.logger.debug(
                        f"Cache cleanup: {len(stale_sessions)} sessions, "
                        f"{len(stale_timestamps)} timestamps removed"
                    )

            except asyncio.CancelledError:
                self.logger.info("Cache cleanup task cancelled")
                break
            except Exception as e:
                self.logger.error(f"Cache cleanup loop error: {e}")
                await asyncio.sleep(60)  # Wait before retrying

    async def cleanup(self):
        """Graceful shutdown"""
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        self.logger.debug("SessionManager cleanup complete")
