# File: src/wss/websockets_manager.py
# Complete WebSocket manager with health monitoring and authorization

import asyncio
import os
import time
import orjson
from typing import Dict, Optional

from fastapi import APIRouter, WebSocket
from starlette.websockets import WebSocketState
from wss.models import WSResponse, CachedMessage, ConnectionState
from config import WEBSOCKETS_CONFIG


def _get_host() -> str:
    return os.getenv("HOST", "localhost")


def _get_port() -> str:
    return os.getenv("PORT", "8000")


async def _send_error(websocket: WebSocket, message: str) -> None:
    """Send error response to client"""
    if websocket.client_state == WebSocketState.CONNECTED:
        try:
            error_response = {"type": "error", "message": message}
            await websocket.send_bytes(orjson.dumps(error_response))
        except Exception:
            pass


class WebsocketsManager:
    """
    WebSocket manager with:
    - JWT authentication
    - Role-based message authorization
    - Ping/pong health checks
    - Inactivity monitoring
    - Message deduplication cache
    """

    def __init__(self, ws_registry, session_manager, logger_manager,
                 security_manager, httpx_manager, redis_client, url_manager=None):
        self.logger = logger_manager.create_logger(
            logger_name="WebsocketsManager",
            logging_level=WEBSOCKETS_CONFIG["LOGGING_LEVEL"]
        )
        self.ws_registry = ws_registry
        self.session_manager = session_manager
        self.security_manager = security_manager
        self.httpx_manager = httpx_manager
        self.redis_client = redis_client
        self.url_manager = url_manager

        # Message deduplication cache: {user_id: {session_id: {msg_type: CachedMessage}}}
        self.message_cache: Dict[str, Dict[str, Dict[str, CachedMessage]]] = {}
        self.cache_ttl = WEBSOCKETS_CONFIG['CACHE_TTL']
        self.cache_cleanup_interval = WEBSOCKETS_CONFIG['CACHE_CLEANUP_INTERVAL']
        self._cache_cleanup_task: Optional[asyncio.Task] = None

        # Connection health tracking: {user_id: ConnectionState}
        self.connection_states: Dict[str, ConnectionState] = {}
        self.ping_interval = WEBSOCKETS_CONFIG.get('PING_INTERVAL', 25)
        self.pong_timeout = WEBSOCKETS_CONFIG.get('PONG_TIMEOUT', 30)
        self.inactivity_timeout = WEBSOCKETS_CONFIG.get('INACTIVITY_TIMEOUT', 60)

        # Role-based message permissions

        self.message_permissions = {
            "user": ["update_api_key", "chat_message", "pong", "ping"],
            "admin": ["*"],  # Can send any message type
        }

        self.router = APIRouter(prefix="/ws", tags=["WebSockets"])
        self.setup_routes()
        self.logger.info("WebsocketsManager initialized")

    # ============================================================
    # ROUTES
    # ============================================================

    def setup_routes(self):
        @self.router.get("/health")
        async def ws_health():
            """Health check endpoint with statistics"""
            cache_stats = self._get_cache_stats()
            return {
                "status": "healthy",
                "active_connections": self.ws_registry._connections_count,
                "connection_states": len(self.connection_states),
                "cache_users": cache_stats["users"],
                "cache_sessions": cache_stats["sessions"],
                "cache_messages": cache_stats["messages"],
                "config": {
                    "ping_interval": self.ping_interval,
                    "pong_timeout": self.pong_timeout,
                    "inactivity_timeout": self.inactivity_timeout,
                    "cache_ttl": self.cache_ttl
                }
            }

        @self.router.websocket("/connect")
        async def ws_connect(websocket: WebSocket):
            """
            WebSocket connection endpoint with authentication.
            Required query params: session_id, token
            """
            await websocket.accept()

            query_params = dict(websocket.query_params)
            session_id = query_params.get("session_id")
            token = query_params.get("token")

            try:
                # AUTH CHECK 2: Verify JWT token
                user = self.security_manager.verify_token(token)
                if not user:
                    raise ValueError("Token verification returned None")

                user_id = user.get("user_id") or user.get("sub")
                user_role = user.get("role", "user")

                if not user_id:
                    raise ValueError("Invalid user ID in token")

                # AUTH CHECK 3: Verify session ownership
                conn_info = await self.session_manager.get_connection_info(user_id)
                if conn_info and conn_info.get("session_id") != session_id:
                    await websocket.close(code=1008, reason="Session mismatch")
                    self.logger.warning(f"WS rejected for {user_id}: session mismatch")
                    return

            except Exception as e:
                self.logger.warning(f"WS auth failed: {e}")
                await websocket.close(code=1008, reason="Invalid token")
                return

            # Connection accepted - start handling
            gateway_id = f"{_get_host()}:{_get_port()}"

            try:
                # Track in registry
                await self.ws_registry.track_ws_connection(
                    user_id, session_id, gateway_id, "default", websocket
                )

                # Initialize connection state
                current_time = time.time()
                self.connection_states[user_id] = ConnectionState(
                    last_activity=current_time,
                    last_pong=current_time,
                    ping_task=None,
                    inactivity_task=None
                )

                # Start health monitoring (this will populate the tasks)
                await self._start_health_monitoring(user_id, session_id, websocket)

                self.logger.info(f"WS connected: {user_id} (role: {user_role})")

                # Send welcome message
                await self._send_welcome(websocket, user_id, session_id)

                # Main message loop
                await self._message_loop(websocket, user_id, session_id, token, user_role)

            except Exception as e:
                self.logger.error(f"Connection error for {user_id}: {e}")
                self.logger.exception(e)
            finally:
                # Cleanup
                await self._stop_health_monitoring(user_id)
                if user_id in self.connection_states:
                    del self.connection_states[user_id]
                self._cleanup_user_cache(user_id, session_id)
                await self.ws_registry.remove_ws_connection(user_id, session_id)
                self.logger.info(f"WS disconnected: {user_id}")

    # ============================================================
    # HEALTH MONITORING
    # ============================================================

    async def _start_health_monitoring(self, user_id: str, session_id: str,
                                       websocket: WebSocket) -> None:
        """Start ping/pong and inactivity monitoring tasks"""
        await self._stop_health_monitoring(user_id)

        ping_task = asyncio.create_task(
            self._ping_loop(user_id, session_id, websocket)
        )
        inactivity_task = asyncio.create_task(
            self._inactivity_monitor(user_id, session_id, websocket)
        )

        if user_id in self.connection_states:
            self.connection_states[user_id].ping_task = ping_task
            self.connection_states[user_id].inactivity_task = inactivity_task

        self.logger.debug(f"Health monitoring started for {user_id}")

    async def _stop_health_monitoring(self, user_id: str) -> None:
        """Stop all health monitoring tasks for a connection"""
        if user_id not in self.connection_states:
            return

        state = self.connection_states[user_id]

        for task in [state.ping_task, state.inactivity_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        self.logger.debug(f"Health monitoring stopped for {user_id}")

    async def _ping_loop(self, user_id: str, session_id: str,
                         websocket: WebSocket) -> None:
        """Send periodic pings and monitor for pong responses"""
        try:
            while websocket.client_state == WebSocketState.CONNECTED:
                await asyncio.sleep(self.ping_interval)

                if websocket.client_state != WebSocketState.CONNECTED:
                    break

                # Send ping
                try:
                    ping_msg = {"type": "ping", "timestamp": time.time()}
                    await websocket.send_text(orjson.dumps(ping_msg).decode())
                    self.logger.debug(f"Ping sent to {user_id}")
                except Exception as e:
                    self.logger.debug(f"Ping failed for {user_id}: {e}")
                    break

                # Wait for pong
                await asyncio.sleep(5)

                # Check pong timeout
                if user_id in self.connection_states:
                    time_since_pong = time.time() - self.connection_states[user_id].last_pong
                    if time_since_pong > self.pong_timeout:
                        self.logger.warning(f"Pong timeout for {user_id}")
                        try:
                            await websocket.close(code=1008, reason="Pong timeout")
                        except Exception:
                            pass
                        break

        except asyncio.CancelledError:
            self.logger.debug(f"Ping loop cancelled for {user_id}")
        except Exception as e:
            self.logger.error(f"Ping loop error for {user_id}: {e}")

    async def _inactivity_monitor(self, user_id: str, session_id: str,
                                  websocket: WebSocket) -> None:
        """Monitor for inactivity and close if timeout exceeded"""
        try:
            while websocket.client_state == WebSocketState.CONNECTED:
                await asyncio.sleep(10)

                if user_id in self.connection_states:
                    time_since_activity = time.time() - self.connection_states[user_id].last_activity
                    if time_since_activity > self.inactivity_timeout:
                        self.logger.warning(f"Inactivity timeout for {user_id}")
                        try:
                            await websocket.close(code=1008, reason="Inactivity timeout")
                        except Exception:
                            pass
                        break

        except asyncio.CancelledError:
            self.logger.debug(f"Inactivity monitor cancelled for {user_id}")
        except Exception as e:
            self.logger.error(f"Inactivity monitor error for {user_id}: {e}")

    def _update_activity(self, user_id: str) -> None:
        """Update last activity timestamp"""
        if user_id in self.connection_states:
            self.connection_states[user_id].last_activity = time.time()

    def _update_pong(self, user_id: str) -> None:
        """Update last pong timestamp"""
        if user_id in self.connection_states:
            self.connection_states[user_id].last_pong = time.time()

    # ============================================================
    # MESSAGE HANDLING
    # ============================================================

    async def _message_loop(self, websocket: WebSocket, user_id: str,
                            session_id: str, token: str, user_role: str) -> None:
        """Main message loop with activity tracking"""
        last_session_update = time.time()
        session_update_interval = 60.0

        try:
            while True:
                message = await websocket.receive()

                if message["type"] == "websocket.receive":
                    self._update_activity(user_id)

                    # Get message data
                    if "text" in message:
                        data = message["text"].encode('utf-8')
                    elif "bytes" in message:
                        data = message["bytes"]
                    else:
                        continue

                    # Update registry timestamp
                    await self.ws_registry.update_connection_timestamp(user_id, session_id)

                    # Handle message with authorization
                    await self.handle_ws_message(
                        user_id, session_id, data, websocket, user_role
                    )

                    # Periodic session activity update
                    current_time = time.time()
                    if current_time - last_session_update >= session_update_interval:
                        try:
                            await self.session_manager.verify_and_update_activity(
                                token, session_id
                            )
                            last_session_update = current_time
                        except Exception as e:
                            self.logger.debug(f"Session update failed: {e}")

                elif message["type"] == "websocket.disconnect":
                    break

        except Exception as e:
            self.logger.error(f"Message loop error for {user_id}: {e}")

    async def handle_ws_message(self, user_id: str, session_id: str,
                                msg_data: bytes, websocket: WebSocket,
                                user_role: str) -> None:
        """Handle incoming WebSocket messages with authorization"""
        try:
            msg_dict = orjson.loads(msg_data)
            msg_type = msg_dict.get("type")

            if not msg_type:
                await _send_error(websocket, "Missing message type")
                return

            # Handle health check messages
            if msg_type == "pong":
                self._update_pong(user_id)
                self.logger.debug(f"Pong received from {user_id}")
                return

            if msg_type == "ping":
                await self._send_pong(websocket)
                return

            # AUTHORIZATION: Check message permissions
            if not self._is_message_allowed(msg_type, user_role):
                await _send_error(
                    websocket,
                    f"Unauthorized: role '{user_role}' cannot send '{msg_type}'"
                )
                self.logger.warning(
                    f"Unauthorized: {user_id} (role: {user_role}) tried '{msg_type}'"
                )
                return

            # Built-in handlers
            if msg_type == "update_api_key":
                await self._handle_api_key_update(user_id, session_id, msg_dict, websocket)

            # Dynamic handlers from url_manager
            elif self.url_manager and msg_type in self.url_manager.ws_handlers:
                await self._handle_dynamic_message(
                    user_id, session_id, msg_type, msg_dict, websocket, user_role
                )
            else:
                self.logger.debug(f"Unknown message type: {msg_type}")
                await _send_error(websocket, f"Unknown message type: {msg_type}")

        except orjson.JSONDecodeError:
            await _send_error(websocket, "Invalid JSON")
        except Exception as e:
            self.logger.error(f"Message handling error for {user_id}: {e}")
            await _send_error(websocket, "Internal error")

    def _is_message_allowed(self, message_type: str, user_role: str) -> bool:
        """Check if user role has permission to send this message type"""
        allowed = self.message_permissions.get(user_role, [])

        # Admin wildcard
        if "*" in allowed:
            return True

        # Explicit permission
        if message_type in allowed:
            return True

        # Check dynamic handlers
        if self.url_manager and message_type in self.url_manager.ws_handlers:
            handler_config = self.url_manager.ws_handlers[message_type]
            if not handler_config.require_auth:
                return True

        return False

    async def _handle_dynamic_message(self, user_id: str, session_id: str,
                                      msg_type: str, msg_dict: dict,
                                      websocket: WebSocket, user_role: str) -> None:
        """Handle dynamically registered message handlers"""
        handler_config = self.url_manager.ws_handlers[msg_type]

        try:
            # Get message data, default to empty dict if not present
            message_data = msg_dict.get("data", {})

            await handler_config.handler(
                user_id=user_id,
                session_id=session_id,
                websocket=websocket,
                message_data=message_data
            )
        except Exception as e:
            self.logger.error(f"Dynamic handler error ({msg_type}): {e}")
            await _send_error(websocket, f"Handler error: {msg_type}")

    async def _handle_api_key_update(self, user_id: str, session_id: str,
                                     msg_dict: dict, websocket: WebSocket) -> None:
        """Built-in handler: Update API key with deduplication"""
        key = msg_dict.get("key", "")
        message_type = "update_api_key"

        # Check cache for duplicates
        if self._is_duplicate_message(user_id, session_id, message_type, key):
            self.logger.debug(f"Duplicate API key update skipped for {user_id}")
            await self._send_ack(websocket, key, session_id)
            return

        # Cache the message
        self._cache_message(user_id, session_id, message_type, key)

        # Send immediate ACK
        await self._send_ack(websocket, key, session_id)

        # Background processing
        asyncio.create_task(self._process_api_key_update(user_id, session_id, key))

    # ============================================================
    # MESSAGE CACHE (Deduplication)
    # ============================================================

    def _is_duplicate_message(self, user_id: str, session_id: str,
                              message_type: str, message_data: str) -> bool:
        """Check if message is a duplicate within cache TTL"""
        if user_id not in self.message_cache:
            return False
        if session_id not in self.message_cache[user_id]:
            return False
        if message_type not in self.message_cache[user_id][session_id]:
            return False

        cached_msg = self.message_cache[user_id][session_id][message_type]
        is_recent = time.time() - cached_msg.timestamp < self.cache_ttl
        return cached_msg.message_data == message_data and is_recent

    def _cache_message(self, user_id: str, session_id: str,
                       message_type: str, message_data: str) -> None:
        """Cache a message to prevent duplicates"""
        if user_id not in self.message_cache:
            self.message_cache[user_id] = {}
        if session_id not in self.message_cache[user_id]:
            self.message_cache[user_id][session_id] = {}

        cached_msg = CachedMessage(
            message_type=message_type,
            message_data=message_data,
            timestamp=time.time(),
            user_id=user_id,
            session_id=session_id
        )
        self.message_cache[user_id][session_id][message_type] = cached_msg

    def _cleanup_user_cache(self, user_id: str, session_id: str) -> None:
        """Clean up cache for disconnected user"""
        if user_id in self.message_cache:
            if session_id in self.message_cache[user_id]:
                del self.message_cache[user_id][session_id]
            if not self.message_cache[user_id]:
                del self.message_cache[user_id]

    async def _cleanup_old_cache_entries(self) -> None:
        """Remove expired cache entries"""
        current_time = time.time()
        removed_count = 0

        users_to_remove = []
        for user_id, sessions in self.message_cache.items():
            sessions_to_remove = []
            for session_id, messages in sessions.items():
                messages_to_remove = []
                for message_type, cached_msg in messages.items():
                    if current_time - cached_msg.timestamp > self.cache_ttl:
                        messages_to_remove.append(message_type)
                        removed_count += 1

                for msg_type in messages_to_remove:
                    del messages[msg_type]
                if not messages:
                    sessions_to_remove.append(session_id)

            for session_id in sessions_to_remove:
                del sessions[session_id]
            if not sessions:
                users_to_remove.append(user_id)

        for user_id in users_to_remove:
            del self.message_cache[user_id]

        if removed_count > 0:
            self.logger.debug(f"Cache cleanup: removed {removed_count} entries")

    def _get_cache_stats(self) -> dict:
        """Get cache statistics"""
        users = len(self.message_cache)
        sessions = sum(len(s) for s in self.message_cache.values())
        messages = sum(
            len(m) for s in self.message_cache.values() for m in s.values()
        )
        return {"users": users, "sessions": sessions, "messages": messages}

    # ============================================================
    # WEBSOCKET RESPONSES
    # ============================================================

    async def _send_welcome(self, websocket: WebSocket, user_id: str,
                            session_id: str) -> None:
        """Send welcome message with connection info"""
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                gateway_id = f"{_get_host()}:{_get_port()}"
                welcome = {
                    "type": "connected",
                    "message": "WebSocket connection established",
                    "user_id": user_id,
                    "session_id": session_id,
                    "gateway_id": gateway_id,
                    "ping_interval": self.ping_interval,
                    "inactivity_timeout": self.inactivity_timeout
                }
                await websocket.send_text(orjson.dumps(welcome).decode())
            except Exception as e:
                self.logger.debug(f"Welcome send failed: {e}")

    async def _send_pong(self, websocket: WebSocket) -> None:
        """Send pong response"""
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                pong = {"type": "pong", "timestamp": time.time()}
                await websocket.send_text(orjson.dumps(pong).decode())
            except Exception as e:
                self.logger.debug(f"Pong send failed: {e}")

    async def _send_ack(self, websocket: WebSocket, key: str,
                        session_id: str) -> None:
        """Send ACK response"""
        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                gateway_id = f"{_get_host()}:{_get_port()}"
                response = WSResponse(
                    type="ack",
                    message="API key update acknowledged",
                    api_key=key,
                    session_id=session_id,
                    gateway_id=gateway_id,
                    data=None
                )
                await websocket.send_bytes(orjson.dumps(response.model_dump()))
            except Exception as e:
                self.logger.debug(f"ACK send failed: {e}")

    # ============================================================
    # BACKGROUND PROCESSING
    # ============================================================

    async def _process_api_key_update(self, user_id: str, session_id: str,
                                      key: str) -> None:
        """Background API key processing"""
        try:
            await self.session_manager.session_handler.update_session(
                user_id, "default", {"api_key": key}, session_id
            )
            self.logger.debug(f"API key updated for {user_id}")
        except Exception as e:
            self.logger.error(f"API key update failed for {user_id}: {e}")
            # Remove from cache to allow retry
            if (user_id in self.message_cache and
                    session_id in self.message_cache[user_id] and
                    "update_api_key" in self.message_cache[user_id][session_id]):
                del self.message_cache[user_id][session_id]["update_api_key"]

    # ============================================================
    # LIFECYCLE MANAGEMENT
    # ============================================================

    async def start_background_tasks(self) -> None:
        """Start background cache cleanup"""
        self._cache_cleanup_task = asyncio.create_task(
            self._continuous_cache_cleanup()
        )
        self.logger.info("Background tasks started")

    async def _continuous_cache_cleanup(self) -> None:
        """Continuous cache cleanup loop"""
        try:
            while True:
                await asyncio.sleep(self.cache_cleanup_interval)
                await self._cleanup_old_cache_entries()

                cache_stats = self._get_cache_stats()
                self.logger.debug(
                    f"Cache: {cache_stats['users']} users, "
                    f"{cache_stats['sessions']} sessions, "
                    f"{cache_stats['messages']} messages"
                )
        except asyncio.CancelledError:
            self.logger.info("Cache cleanup task cancelled")
        except Exception as e:
            self.logger.error(f"Cache cleanup error: {e}")

    async def cleanup(self) -> None:
        """Cleanup all resources"""
        # Stop all health monitoring
        for user_id in list(self.connection_states.keys()):
            await self._stop_health_monitoring(user_id)

        self.connection_states.clear()

        # Stop cache cleanup
        if self._cache_cleanup_task:
            self._cache_cleanup_task.cancel()
            try:
                await self._cache_cleanup_task
            except asyncio.CancelledError:
                pass

        self.message_cache.clear()
        self.logger.info("WebsocketsManager cleanup completed")

    # ============================================================
    # ADMIN METHODS
    # ============================================================

    def add_message_permission(self, role: str, message_type: str) -> None:
        """Add message type permission for a role"""
        if role not in self.message_permissions:
            self.message_permissions[role] = []

        if message_type not in self.message_permissions[role]:
            self.message_permissions[role].append(message_type)
            self.logger.info(f"Permission added: {role} -> {message_type}")

    def remove_message_permission(self, role: str, message_type: str) -> None:
        """Remove message type permission from a role"""
        if role in self.message_permissions:
            if message_type in self.message_permissions[role]:
                self.message_permissions[role].remove(message_type)
                self.logger.info(f"Permission removed: {role} -> {message_type}")

    def get_role_permissions(self, role: str) -> list:
        """Get all message types a role can send"""
        return self.message_permissions.get(role, [])

    def get_router(self) -> APIRouter:
        """Return FastAPI router"""
        return self.router