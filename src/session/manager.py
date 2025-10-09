# File: src/session/manager.py

# Combined SessionManager  and SessionRegistry : Handles sessions, connections, pub/sub, routes.
# Redis-backed for K8s scaling; routes for create/update sessions with sticky WS URLs .
# Integrated user registration/login/logout (in-memory users for testing), JWT integration with SecurityManager.
# Activity tracking to extend session lifetime on interactions (HTTP/WS/routes).
# Provides FastAPI dependency for auth + activity update (reusable via Depends).
# For WS reuse: Manually call verify_and_update_activity(token, expected_user_id, session_id) in WS handlers.
#  Login deletes old session for same user_id (single active session per user).
#  /delete_account route: Deletes user from registry + all their sessions/connections in Redis.
import asyncio

import json


import os


from typing import Dict, Any, Optional, Tuple
from fastapi import APIRouter, Depends, Request, HTTPException
from fastapi.security import OAuth2PasswordBearer



from config import SESSION_CONFIG 
from session.cleaner import SessionCleaner
from session.connections import ConnectionManager
from session.events import EventManager
from session.decorators import check_session_owner_or_admin, check_session_owner, check_admin, \
    check_user_id_match_or_admin, check_authenticated
from session.handler import SessionHandler
from session.models import UpdateSessionRequest, SessionResponse, SessionCreateRequest, LoginRequest, \
    RegisterResponse, LoginResponse, RegisterRequest, LogoutResponse, DeleteAccountResponse  # [2]
from session.users import UserManager
from session.utils import get_redis_client, _get_gateway_id


class SessionManager:
    def __init__(self, logger_manager: object, redis_client: object, security_manager: object, config: dict):
        self.config = config
        self.logger = logger_manager.create_logger(logger_name="SessionHandler",
                                                   logging_level=self.config.get('LOGGING_LEVEL', 'INFO'))

        self.async_redis = redis_client or get_redis_client()
        self.security_manager = security_manager  # For JWT/auth in routes [4]


        self.users_cache: Dict[str, Dict[str, Any]] = {}  # Local cache (loads from Redis on startup)
        self.timeout_seconds = SESSION_CONFIG.get("TIMEOUT_MINUTES", 30) * 60  # 30 min default
        #  OAuth2 scheme for dependencies (tokenUrl points to login endpoint)
        self.oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/sessions/login")
        self.router = APIRouter(prefix="/sessions", tags=["Sessions"])

        # Compose managers (inject dependencies)
        self.event_manager = EventManager(self.async_redis, self.logger, self.users_cache)
        self.user_manager = UserManager(self.async_redis, self.logger, self.security_manager, self.event_manager,
                                        self.timeout_seconds, self.users_cache)
        self.session_handler = SessionHandler(self.async_redis, self.logger, self.event_manager, self.timeout_seconds)
        self.connection_manager = ConnectionManager(self.async_redis, self.logger, self.event_manager,
                                                    self.timeout_seconds)

        self.session_cleaner = SessionCleaner(self.async_redis, self.logger, self.event_manager, self.users_cache,
                                              self.session_handler, self.connection_manager)



        self.setup_routes()
    async def start_background_tasks(self):
        asyncio.create_task(self.session_cleaner.cleanup_loop(max_inactive_days=SESSION_CONFIG['MAX_INACTIVE_DAYS'],check_interval_days=1))
        # Load users and start background tasks
        asyncio.create_task(self.user_manager.load_users_from_redis())
        asyncio.create_task(self.event_manager.pubsub_listener())
        asyncio.create_task(self.session_handler._batch_writer())
        asyncio.create_task(self.session_handler._cleanup_stale_cache())

    # Delegated methods (public API remains on SessionHandler)
    async def load_users_from_redis(self):
        await self.user_manager.load_users_from_redis()

    async def save_user_to_redis(self, username: str, user_data: Dict[str, Any]):
        await self.user_manager.save_user_to_redis(username, user_data)

    async def delete_user_from_redis(self, username: str):
        await self.user_manager.delete_user_from_redis(username)

    async def get_user_from_redis(self, username: str) -> Optional[Dict[str, Any]]:
        return await self.user_manager.get_user_from_redis(username)


    # Reusable: In other routers, use Depends(session_handler.get_current_user_with_activity)
    # Returns user dict + session_id; extends session lifetime on every call (e.g., new route/WS message)
    def get_current_user_with_activity(self):
        # Factory pattern: Returns the async dependency function
        async def dep(
                token: str = Depends(OAuth2PasswordBearer(tokenUrl="/sessions/login"))
        ) -> Dict[str, Any]:
            try:
                # Verify JWT (using security_manager)
                payload = self.security_manager.verify_token(token)
                user_id = payload.get("sub") or payload.get("user_id")
                if not user_id:
                    raise HTTPException(status_code=401, detail="Invalid token: missing user_id")
                # Get connection info (or create default if none)
                conn = await self.connection_manager.get_connection_info(user_id)
                if not conn:
                    chat_id = "default"
                    session, session_id = await self.session_handler.get_or_create_session(user_id, chat_id)

                    gateway_id = _get_gateway_id()
                    await self.connection_manager.track_connection(user_id, session_id, gateway_id, ws_connected=False)
                    conn = await self.connection_manager.get_connection_info(user_id)  # Refresh
                session_id = conn.get("session_id")
                if not session_id:
                    raise HTTPException(status_code=400, detail="No active session found")
                # Update connection timestamp
                await self.connection_manager.update_connection_timestamp(user_id, session_id)
                # Update session last_access and renew expiry
                await self.session_handler.update_timestamp_only(session_id)
                # Return user + session_id
                return {
                    "user_id": user_id,
                    "username": payload.get("sub"),
                    "role": payload.get("role", "user"),
                    "session_id": session_id
                }
            except HTTPException:
                raise
            except Exception as e:
                self.logger.error(f"Auth/activity update error: {e}")
                raise HTTPException(status_code=500, detail="Internal auth error")
        return dep

    #  For WS reuse (manual call in WS handlers, e.g., on connect/message)
    # Verifies token, updates activity for given session_id (no Depends; raises HTTPException for close)
    async def verify_and_update_activity(self, token: str, expected_session_id: Optional[str] = None) -> Dict[str, Any]:
        try:
            payload = self.security_manager.verify_token(token)
            user_id = payload.get("sub") or payload.get("user_id")
            if not user_id:
                raise HTTPException(status_code=401, detail="Invalid token")
            # Get connection
            conn = await self.connection_manager.get_connection_info(user_id)
            if not conn:
                raise HTTPException(status_code=400, detail="No active session")
            session_id = conn.get("session_id")
            if expected_session_id and session_id != expected_session_id:
                raise HTTPException(status_code=400, detail="Session mismatch")
            # Update as in dependency
            await self.connection_manager.update_connection_timestamp(user_id, session_id)
            await self.session_handler.update_timestamp_only(session_id)
            return {
                "user_id": user_id,
                "username": payload.get("sub"),
                "role": payload.get("role", "user"),
                "session_id": session_id
            }
        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"WS auth/activity error: {e}")
            raise HTTPException(status_code=500, detail="Internal auth error")

    # Delegated session methods
    async def get_or_create_session(self, user_id: str, chat_id: str, session_id: Optional[str] = None) -> Tuple[
        Dict[str, Any], str]:
        return await self.session_handler.get_or_create_session(user_id, chat_id, session_id)



    async def track_connection(self, user_id: str, session_id: str, gateway_id: Optional[str] = None,
                               ws_connected: bool = False):
        await self.connection_manager.track_connection(user_id, session_id, gateway_id, ws_connected)

    async def get_connection_info(self, user_id: str) -> Optional[Dict[str, Any]]:
        return await self.connection_manager.get_connection_info(user_id)

    async def update_connection_timestamp(self, user_id: str, session_id: str):
        await self.connection_manager.update_connection_timestamp(user_id, session_id)

    async def remove_connection(self, user_id: str):
        await self.connection_manager.remove_connection(user_id)

    async def cleanup_user_sessions(self, user_id: str):
        await self.session_handler.cleanup_user_sessions(user_id)

    async def publish_event(self, channel: str, data: Dict[str, Any]):
        await self.event_manager.publish(channel, data)

    async def update_session_timestamp_only(self, session_id: str):
        await self.session_handler.update_timestamp_only(session_id)

    def setup_routes(self):
        """Setup routes with decorator-based auth checks"""

        # ========== PUBLIC ROUTES (No Auth) ==========

        @self.router.post("/register", response_model=RegisterResponse)
        async def register_user(request: RegisterRequest):
            """Register a new user account"""
            return await self.user_manager.register(request)

        @self.router.post("/login", response_model=LoginResponse)
        async def login_user(request: LoginRequest):
            """Login and get JWT token + session"""
            return await self.user_manager.login(
                request, self.connection_manager, self.session_handler
            )

        # ========== AUTHENTICATED ROUTES (Any User) ==========

        @self.router.post("/logout", response_model=LogoutResponse)
        @check_authenticated  #  Explicitly marks as auth required
        async def logout_user(
                current_user: Dict[str, Any] = Depends(self.get_current_user_with_activity())
        ):
            """Logout current user"""
            return await self.user_manager.logout(
                current_user, self.connection_manager, self.event_manager
            )

        @self.router.post("/delete_account", response_model=DeleteAccountResponse)
        @check_authenticated  #  Explicitly marks as auth required
        async def delete_account(
                current_user: Dict[str, Any] = Depends(self.get_current_user_with_activity())
        ):
            """Delete user account and all associated data"""
            return await self.user_manager.delete_account(
                current_user, self.session_handler,
                self.connection_manager, self.event_manager
            )

        @self.router.post("/create", response_model=SessionResponse)
        @check_authenticated  #  Explicitly marks as auth required
        async def create_or_get_session(
                request: SessionCreateRequest,
                request_obj: Request,
                current_user: Dict[str, Any] = Depends(self.get_current_user_with_activity())
        ):
            """Create or reuse a session"""
            user_id = current_user["user_id"]
            chat_id = request.chat_id or "default"
            session_id = request.session_id or current_user.get("session_id")

            session, session_id = await self.session_handler.get_or_create_session(
                user_id, chat_id, session_id
            )

            gateway_id = _get_gateway_id()
            await self.connection_manager.track_connection(
                user_id, session_id, gateway_id, ws_connected=False
            )

            client_host = request_obj.client.host if request_obj.client else os.getenv("HOST", "localhost")
            server_port = request_obj.scope.get('server', [('', 8000)])[1] if 'server' in request_obj.scope else int(
                os.getenv("PORT", 8000))
            ws_url = f"ws://{client_host}:{server_port}/ws/connect?session_id={session_id}&token={{access_token}}"

            self.logger.info(f"Session {session_id} created/reused for user {user_id} on {gateway_id}")

            return SessionResponse(
                session_id=session_id,
                user_id=user_id,
                chat_id=chat_id,
                data=session["data"],
                ws_url=ws_url
            )

        # ========== SESSION OWNER OR ADMIN ROUTES ==========

        @self.router.get("/{session_id}", response_model=SessionResponse)
        @check_session_owner_or_admin  #  Decorator handles auth!
        async def get_session(
                session_id: str,
                current_user: Dict[str, Any] = Depends(self.get_current_user_with_activity())
        ):
            """Get session details - owner or admin only"""
            session_key = f"sessions:{session_id}"
            serialized = await self.async_redis.get(session_key)
            if not serialized:
                raise HTTPException(status_code=404, detail="Session not found")

            session = json.loads(serialized)
            await self.session_handler.update_timestamp_only(session_id)

            return SessionResponse(
                session_id=session_id,
                user_id=session["user_id"],
                chat_id=session["chat_id"],
                data=session["data"],
                ws_url=""
            )

        @self.router.post("/update/{session_id}")
        @check_session_owner  #  Only session owner (no admin override for updates)
        async def update_session_route(
                session_id: str,
                request: UpdateSessionRequest,
                request_obj: Request,
                current_user: Dict[str, Any] = Depends(self.get_current_user_with_activity())
        ):
            """Update session data - owner only"""
            user_id = current_user["user_id"]
            chat_id = request.chat_id or 'default'

            await self.session_handler.update_session(
                user_id, chat_id, request.data, session_id
            )

            gateway_id = _get_gateway_id()
            await self.event_manager.publish(f"events:session:update:{user_id}", {
                "session_id": session_id,
                "user_id": user_id,
                "updates": request.data,
                "chat_id": chat_id,
                "gateway_id": gateway_id
            })

            client_host = request_obj.client.host if request_obj.client else os.getenv("HOST", "localhost")
            server_port = request_obj.scope.get('server', [('', 8000)])[1] if 'server' in request_obj.scope else int(
                os.getenv("PORT", 8000))
            ws_url = f"ws://{client_host}:{server_port}/ws/connect?session_id={session_id}&token={{access_token}}"

            self.logger.info(f"Session {session_id} updated for {user_id} via HTTP")

            return SessionResponse(
                session_id=session_id,
                user_id=user_id,
                chat_id=chat_id,
                data={'data': None},
                ws_url=ws_url
            )

        # ========== USER-SPECIFIC ROUTES ==========

        @self.router.get("/users/{user_id}/sessions")
        @check_user_id_match_or_admin  #  User can see own, admin can see any
        async def get_user_sessions(
                user_id: str,
                current_user: Dict[str, Any] = Depends(self.get_current_user_with_activity())
        ):
            """Get all sessions for a user - self or admin"""
            session_keys = await self.async_redis.keys("sessions:*")
            user_sessions = []

            for key in session_keys:
                serialized = await self.async_redis.get(key)
                if serialized:
                    session = json.loads(serialized)
                    if session.get("user_id") == user_id:
                        user_sessions.append({
                            "session_id": key.split(":")[-1] if isinstance(key, str) else key.decode().split(":")[-1],
                            "chat_id": session.get("chat_id"),
                            "last_access": session.get("last_access"),
                            "created_at": session.get("created_at")
                        })

            return {"sessions": user_sessions, "count": len(user_sessions)}

        @self.router.get("/users/{user_id}/connection")
        @check_user_id_match_or_admin  #  Self or admin
        async def get_user_connection(
                user_id: str,
                current_user: Dict[str, Any] = Depends(self.get_current_user_with_activity())
        ):
            """Get connection info for a user - self or admin"""
            conn = await self.connection_manager.get_connection_info(user_id)
            if not conn:
                raise HTTPException(status_code=404, detail="No active connection")
            return conn