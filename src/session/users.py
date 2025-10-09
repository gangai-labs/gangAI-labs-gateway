
import os
import time
from typing import Any, Dict, Optional
from redis.asyncio import Redis as AsyncRedis
from fastapi import HTTPException
from session.models import LogoutResponse, DeleteAccountResponse, LoginRequest, RegisterResponse, \
    RegisterRequest, LoginResponse
from session.utils import _hash_password


class UserManager:
    """Handles user registration, caching, Redis storage, and auth helpers."""
    def __init__(self, async_redis: AsyncRedis, logger: Any, security_manager: Any, event_manager: Any,
                 timeout_seconds: int, users_cache: Dict[str, Dict[str, Any]]):
        self.async_redis = async_redis
        self.logger = logger
        self.security_manager = security_manager
        self.event_manager = event_manager
        self.timeout_seconds = timeout_seconds
        self.users_cache = users_cache
        self.users_cache: Dict[str, Dict[str, Any]] = {}  # Local cache (loads from Redis on startup)

    async def load_users_from_redis(self):
        user_keys = await self.async_redis.keys("users:*")
        for key in user_keys:
            username = key.split(":")[1]
            user_data = await self.async_redis.hgetall(key)
            if user_data:
                # Deserialize (password already hashed)
                self.users_cache[username] = {
                    "password": user_data.get("password", ""),
                    "email": user_data.get("email", ""),
                    "role": user_data.get("role", "user"),
                    "last_login": float(user_data.get("last_login", 0))
                }
                self.logger.debug(f"Loaded user {username} from Redis")
        self.logger.info(f"Loaded {len(user_keys)} users from Redis to cache")

    async def save_user_to_redis(self, username: str, user_data: Dict[str, Any]):
        key = f"users:{username}"
        # Serialize (last_login as str if needed, but hset handles float)
        await self.async_redis.hset(key, mapping=user_data)
        await self.async_redis.expire(key, self.timeout_seconds * 12)  # Longer TTL for users (6h default; but now we keep indefinitely via cleanup changes)
        # Update cache
        self.users_cache[username] = user_data.copy()
        # Pub/sub for sync across instances
        await self.event_manager.publish(f"events:user:register:{username}", {
            "username": username,
            "user_data": user_data  # Exclude password for security; or hash only
        })
        self.logger.debug(f"Saved user {username} to Redis + cache")

    async def delete_user_from_redis(self, username: str):
        key = f"users:{username}"
        await self.async_redis.delete(key)
        # Remove from cache
        if username in self.users_cache:
            del self.users_cache[username]
        # Pub/sub
        await self.event_manager.publish(f"events:user:delete:{username}", {"username": username})
        self.logger.debug(f"Deleted user {username} from Redis + cache")

    async def get_user_from_redis(self, username: str) -> Optional[Dict[str, Any]]:
        if username in self.users_cache:
            return self.users_cache[username].copy()  # Cache hit
        # Fallback to Redis (cache miss, e.g., after pub/sub from other instance)
        key = f"users:{username}"
        user_data = await self.async_redis.hgetall(key)
        if user_data:
            # Load to cache
            self.users_cache[username] = {
                "password": user_data.get("password", ""),
                "email": user_data.get("email", ""),
                "role": user_data.get("role", "user"),
                "last_login": float(user_data.get("last_login", 0))
            }
            return self.users_cache[username].copy()
        return None



    async def register(self, request: RegisterRequest) -> RegisterResponse:
        existing_user = await self.get_user_from_redis(request.username)
        if existing_user:
            raise HTTPException(status_code=400, detail="Username already exists")
        hashed_pw = _hash_password(request.password)
        user_data = {
            "password": hashed_pw,
            "email": request.email,
            "role": "user",
            "last_login": time.time()  # Initial
        }
        await self.save_user_to_redis(request.username, user_data)
        self.logger.info(f"Registered user: {request.username}")
        return RegisterResponse(message="User registered successfully", username=request.username)

    async def login(self, request: LoginRequest, connection_manager: Any, session_manager: Any) -> LoginResponse:
        user_data = await self.get_user_from_redis(request.username)
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid username or password")
        stored_hash = user_data["password"]
        if stored_hash != _hash_password(request.password):
            raise HTTPException(status_code=401, detail="Invalid username or password")
        # Create JWT with user data (JWT used for all auth post-login)
        user_id = request.username
        user_data_jwt = {
            "sub": request.username,
            "user_id": request.username,
            "role": user_data["role"]
        }
        token = self.security_manager.create_access_token(user_data_jwt)
        # Update last_login in Redis + cache
        user_data["last_login"] = time.time()
        await self.save_user_to_redis(request.username, user_data)  # Syncs across instances via pub/sub
        # Check for and delete old session for this user (single session policy)
        existing_conn = await connection_manager.get_connection_info(user_id)
        if existing_conn:
            old_session_id = existing_conn.get("session_id")
            if old_session_id:
                # Delete old session and connection
                await session_manager.delete_session(old_session_id)
                await connection_manager.remove_connection(user_id)
                # Pub/sub to notify of implicit logout
                await self.event_manager.publish(f"events:session:logout:{user_id}", {
                    "user_id": user_id, "session_id": old_session_id, "reason": "new_login"
                })
                self.logger.info(f"Deleted old session {old_session_id} for {user_id} on new login")
        # Create new default session for user
        chat_id = "default"
        session, session_id = await session_manager.get_or_create_session(user_id, chat_id)
        # Track new HTTP connection (for activity)
        host = os.getenv("HOST", "localhost")
        port = os.getenv("PORT", "8000")

        gateway_id = f"{host}:{port}"  # Same format everywhere
        await connection_manager.track_connection(user_id, session_id, gateway_id, ws_connected=False)
        # Renew session expiry on login
        await session_manager.update_timestamp_only(session_id)
        expires_in = self.security_manager.access_token_expire_minutes * 60
        self.logger.info(f"User {user_id} logged in, new session {session_id} (old deleted if existed)")
        return LoginResponse(
            access_token=token,  # JWT for all subsequent auth
            token_type="bearer",
            expires_in=expires_in,
            user={"username": request.username, "role": user_data["role"]},
            session_id=session_id  # For WS sticky
        )

    async def logout(self, current_user: Dict[str, Any], connection_manager: Any, event_manager: Any) -> LogoutResponse:
        user_id = current_user["user_id"]
        session_id = current_user["session_id"]
        await connection_manager.remove_connection(user_id)
        # ENHANCED: Pub/sub with WS cleanup flag
        await event_manager.publish(f"events:session:logout:{user_id}", {
            "user_id": user_id,
            "session_id": session_id,
            "action": "cleanup_ws"  # Triggers WS close in registry listener
        })
        self.logger.info(f"User {user_id} logged out, session {session_id} removed; WS cleanup triggered")
        return LogoutResponse(message="Logged out successfully")

    async def delete_account(self, current_user: Dict[str, Any], session_manager: Any, connection_manager: Any,
                             event_manager: Any) -> DeleteAccountResponse:
        username = current_user["username"]
        user_id = current_user["user_id"]
        # Delete from Redis + cache (pub/sub syncs to other instances)
        await self.delete_user_from_redis(username)
        # Cleanup sessions (same)
        await session_manager.cleanup_user_sessions(user_id)
        # Also remove connection
        await connection_manager.remove_connection(user_id)
        # Pub/sub (same)
        await event_manager.publish(f"events:account:deleted:{user_id}", {
            "user_id": user_id, "username": username
        })
        self.logger.info(f"Account {user_id} fully deleted")
        return DeleteAccountResponse(message="Account deleted successfully")