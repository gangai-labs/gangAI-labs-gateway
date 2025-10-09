# File: src/admin/events.py
import time
import psutil
from typing import Dict, Any, List
from fastapi import APIRouter, Depends, HTTPException

from config import ADMIN_CONFIG
from utils.logger import Logger
from session.decorators import check_admin
from admin.models import (
    PromoteUserRequest, 
    DemoteUserRequest, 
    UserStatsResponse,
    SystemStatsResponse,
    AdminUserResponse
)

class AdminManager:
    """Dedicated admin manager for user management and system monitoring"""
    
    def __init__(
        self, 
        logger_manager: Logger,
        session_manager,
        ws_registry,
        redis_client,
        security_manager
    ):
        self.logger = logger_manager.create_logger(
            logger_name="AdminManager",
            logging_level=ADMIN_CONFIG["LOGGING_LEVEL"]
        )
        self.session_manager = session_manager
        self.ws_registry = ws_registry
        self.redis_client = redis_client
        self.security_manager = security_manager
        self.config = ADMIN_CONFIG
        
        self.router = APIRouter(prefix="/admin", tags=["Admin"])
        self._start_time = time.time()
        self._setup_routes()

    def _setup_routes(self):
        """Setup all admin routes with proper authentication"""
        
        # User Management Routes
        @self.router.post("/users/promote")
        @check_admin
        async def promote_user(
            request: PromoteUserRequest,
            current_user: Dict[str, Any] = Depends(
                self.session_manager.get_current_user_with_activity()
            )
        ):
            """Promote a user to admin role"""
            return await self.promote_to_admin(
                request.username, 
                current_user
            )

        @self.router.post("/users/demote")
        @check_admin
        async def demote_user(
            request: DemoteUserRequest,
            current_user: Dict[str, Any] = Depends(
                self.session_manager.get_current_user_with_activity()
            )
        ):
            """Demote an admin to user role"""
            return await self.demote_from_admin(
                request.username, 
                current_user
            )

        @self.router.get("/users", response_model=List[AdminUserResponse])
        @check_admin
        async def list_all_users_detailed(
            current_user: Dict[str, Any] = Depends(
                self.session_manager.get_current_user_with_activity()
            )
        ):
            """Get detailed user list with online status"""
            return await self.get_detailed_users()

        @self.router.get("/users/stats", response_model=UserStatsResponse)
        @check_admin
        async def get_user_stats(
            current_user: Dict[str, Any] = Depends(
                self.session_manager.get_current_user_with_activity()
            )
        ):
            """Get comprehensive user statistics"""
            return await self.get_user_statistics()

        # System Management Routes
        @self.router.get("/system/stats", response_model=SystemStatsResponse)
        @check_admin
        async def get_system_stats(
            current_user: Dict[str, Any] = Depends(
                self.session_manager.get_current_user_with_activity()
            )
        ):
            """Get system performance statistics"""
            return await self.get_system_statistics()

        @self.router.get("/system/redis-info")
        @check_admin
        async def get_redis_info(
            current_user: Dict[str, Any] = Depends(
                self.session_manager.get_current_user_with_activity()
            )
        ):
            """Get Redis server information"""
            return await self.get_redis_stats()

        @self.router.post("/system/cleanup-sessions")
        @check_admin
        async def cleanup_sessions(
            current_user: Dict[str, Any] = Depends(
                self.session_manager.get_current_user_with_activity()
            )
        ):
            """Manually trigger session cleanup"""
            return await self.cleanup_all_sessions()

    # User Management Methods
    async def promote_to_admin(self, username: str, current_user: Dict[str, Any]):
        """Promote a user to admin role"""
        user_data = await self.session_manager.get_user_from_redis(username)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_data["role"] = "admin"
        await self.session_manager.save_user_to_redis(username, user_data)
        
        self.logger.info(f"User {username} promoted to admin by {current_user['user_id']}")
        return {"message": f"User {username} promoted to admin"}

    async def demote_from_admin(self, username: str, current_user: Dict[str, Any]):
        """Demote an admin to user role"""
        if username == current_user["username"]:
            raise HTTPException(status_code=400, detail="Cannot demote yourself")
        
        user_data = await self.session_manager.get_user_from_redis(username)
        if not user_data:
            raise HTTPException(status_code=404, detail="User not found")
        
        user_data["role"] = "user"
        await self.session_manager.save_user_to_redis(username, user_data)
        
        self.logger.info(f"User {username} demoted from admin by {current_user['user_id']}")
        return {"message": f"User {username} demoted to user"}

    async def get_detailed_users(self) -> List[AdminUserResponse]:
        """Get detailed user information with online status"""
        user_keys = await self.redis_client.keys("users:*")
        detailed_users = []

        for key in user_keys:
            username = key.split(":")[1] if isinstance(key, str) else key.decode().split(":")[1]
            user_data = await self.redis_client.hgetall(key)
            
            if user_data:
                # Get session count for user
                session_count = await self._get_user_session_count(username)
                
                # Check if user has active connection
                conn_info = await self.session_manager.get_connection_info(username)
                is_online = conn_info is not None and conn_info.get("ws_connected", False)

                detailed_users.append(AdminUserResponse(
                    username=username,
                    email=user_data.get("email", ""),
                    role=user_data.get("role", "user"),
                    last_login=float(user_data.get("last_login", 0)),
                    session_count=session_count,
                    is_online=is_online
                ))

        return detailed_users

    async def get_user_statistics(self) -> UserStatsResponse:
        """Get comprehensive user statistics"""
        # Total users
        user_keys = await self.redis_client.keys("users:*")
        total_users = len(user_keys)

        # Active sessions
        session_keys = await self.redis_client.keys("sessions:*")
        active_sessions = len(session_keys)

        # WebSocket connections
        ws_connections = self.ws_registry._connections_count

        # Memory usage approximation
        memory_usage = {
            "users_kb": len(user_keys) * 2,  # Approximate
            "sessions_kb": len(session_keys) * 5,
            "connections_kb": ws_connections * 1
        }

        return UserStatsResponse(
            total_users=total_users,
            active_sessions=active_sessions,
            ws_connections=ws_connections,
            memory_usage=memory_usage
        )

    # System Management Methods
    async def get_system_statistics(self) -> SystemStatsResponse:
        """Get system performance statistics"""
        # Redis connections
        redis_info = await self.redis_client.info('clients')
        redis_connections = redis_info.get('connected_clients', 0)

        # Memory usage
        process = psutil.Process()
        memory_usage_mb = process.memory_info().rss / 1024 / 1024

        # Uptime
        uptime_seconds = time.time() - self._start_time

        # Active workers (approximation)
        active_workers = len(psutil.Process().children()) + 1

        return SystemStatsResponse(
            redis_connections=redis_connections,
            memory_usage_mb=round(memory_usage_mb, 2),
            uptime_seconds=round(uptime_seconds, 2),
            active_workers=active_workers
        )

    async def get_redis_stats(self) -> Dict[str, Any]:
        """Get Redis server statistics"""
        try:
            info = await self.redis_client.info()
            return {
                "connected_clients": info.get('connected_clients'),
                "used_memory_human": info.get('used_memory_human'),
                "used_memory_peak_human": info.get('used_memory_peak_human'),
                "keyspace_hits": info.get('keyspace_hits'),
                "keyspace_misses": info.get('keyspace_misses'),
                "total_commands_processed": info.get('total_commands_processed'),
            }
        except Exception as e:
            self.logger.error(f"Failed to get Redis stats: {e}")
            return {"error": "Failed to retrieve Redis statistics"}

    async def cleanup_all_sessions(self):
        """Manually trigger cleanup of expired sessions and inactive users"""
        try:
            await self.session_manager.session_cleaner.cleanup_expired_sessions()
            await self.session_manager.session_cleaner.cleanup_inactive_users()
            
            self.logger.info("Manual session cleanup completed")
            return {"message": "Session cleanup completed successfully"}
        except Exception as e:
            self.logger.error(f"Manual cleanup failed: {e}")
            raise HTTPException(status_code=500, detail="Cleanup failed")

    # Helper Methods
    async def _get_user_session_count(self, username: str) -> int:
        """Get number of active sessions for a user"""
        session_keys = await self.redis_client.keys("sessions:*")
        user_session_count = 0

        for key in session_keys:
            serialized = await self.redis_client.get(key)
            if serialized:
                try:
                    import json
                    session = json.loads(serialized)
                    if session.get("user_id") == username:
                        user_session_count += 1
                except json.JSONDecodeError:
                    continue

        return user_session_count

    def get_router(self) -> APIRouter:
        """Get the admin router for inclusion in main app"""
        return self.router
