# File: src/admin/models.py
from pydantic import BaseModel
from typing import Dict, Any, List, Optional

class PromoteUserRequest(BaseModel):
    username: str

class DemoteUserRequest(BaseModel):
    username: str

class UserStatsResponse(BaseModel):
    total_users: int
    active_sessions: int
    ws_connections: int
    memory_usage: Dict[str, Any]

class SystemStatsResponse(BaseModel):
    redis_connections: int
    memory_usage_mb: float
    uptime_seconds: float
    active_workers: int

class AdminUserResponse(BaseModel):
    username: str
    email: str
    role: str
    last_login: float
    session_count: int
    is_online: bool
