# File: src/wss/websockets_models.py
# Pydantic models for WebSocket messages and state management

import asyncio
import time

from pydantic import BaseModel, Field
from typing import Optional, Any


class WSMessage(BaseModel):
    """Incoming WebSocket message"""
    type: str = Field(..., description="Message type (e.g., 'update_api_key', 'chat_message')")
    key: Optional[str] = Field(None, description="API key for update_api_key messages")
    content: Optional[str] = Field(None, description="Message content")
    data: Optional[dict] = Field(None, description="Additional message data")


class WSResponse(BaseModel):
    """Outgoing WebSocket response"""
    type: str = Field(..., description="Response type (e.g., 'connected', 'ack', 'error')")
    message: Optional[str] = Field(None, description="Response message")
    api_key: Optional[str] = Field(None, description="API key for ack responses")
    data: Optional[Any] = Field(None, description="Response data payload")
    session_id: Optional[str] = Field(None, description="Session identifier")
    gateway_id: Optional[str] = Field(None, description="Gateway identifier")


class CachedMessage(BaseModel):
    """Message cache entry for deduplication"""
    message_type: str = Field(..., description="Type of cached message")
    message_data: str = Field(..., description="Message data/content")
    timestamp: float = Field(..., description="Cache timestamp")
    user_id: str = Field(..., description="User identifier")
    session_id: str = Field(..., description="Session identifier")

    class Config:
        frozen = False  # Allow mutation for cache updates


class ConnectionState(BaseModel):
    """Connection health monitoring state"""
    last_activity: float = Field(..., description="Last activity timestamp")
    last_pong: float = Field(..., description="Last pong response timestamp")
    ping_task: Optional[asyncio.Task] = Field(default=None, description="Ping loop task")
    inactivity_task: Optional[asyncio.Task] = Field(default=None, description="Inactivity monitor task")

    class Config:
        arbitrary_types_allowed = True  # Allow asyncio.Task
        frozen = False  # Allow mutation for state updates


class HealthStatus(BaseModel):
    """WebSocket health check response"""
    status: str = Field(..., description="Health status (healthy/degraded/unhealthy)")
    active_connections: int = Field(..., description="Number of active WebSocket connections")
    connection_states: int = Field(..., description="Number of tracked connection states")
    cache_users: int = Field(..., description="Number of users in message cache")
    cache_sessions: int = Field(..., description="Number of sessions in message cache")
    cache_messages: int = Field(..., description="Total cached messages")
    config: dict = Field(..., description="Current configuration values")


class WelcomeMessage(BaseModel):
    """Initial connection welcome message"""
    type: str = Field(default="connected", Literal=True)
    message: str = Field(default="WebSocket connection established")
    user_id: str = Field(..., description="Connected user ID")
    session_id: str = Field(..., description="Session ID")
    ping_interval: int = Field(..., description="Server ping interval (seconds)")
    inactivity_timeout: int = Field(..., description="Connection inactivity timeout (seconds)")


class PingMessage(BaseModel):
    """Server ping message"""
    type: str = Field(default="ping", Literal=True)
    timestamp: float = Field(..., description="Ping timestamp")


class PongMessage(BaseModel):
    """Client pong response"""
    type: str = Field(default="pong", Literal=True)
    timestamp: Optional[float] = Field(None, description="Client timestamp")


class ErrorMessage(BaseModel):
    """Error response message"""
    type: str = Field(default="error", Literal=True)
    message: str = Field(..., description="Error message")
    code: Optional[str] = Field(None, description="Error code")


class AckMessage(BaseModel):
    """Acknowledgment response"""
    type: str = Field(default="ack", Literal=True)
    api_key: Optional[str] = Field(None, description="Acknowledged API key")
    session_id: str = Field(..., description="Session ID")
    timestamp: float = Field(..., description="Acknowledgment timestamp")


class MessagePermissions(BaseModel):
    """Role-based message permissions"""
    role: str = Field(..., description="User role")
    allowed_messages: list[str] = Field(..., description="List of allowed message types")
    wildcard: bool = Field(default=False, description="Whether role has wildcard access")


class ConnectionInfo(BaseModel):
    """Connection information for tracking"""
    user_id: str = Field(..., description="User identifier")
    session_id: str = Field(..., description="Session identifier")
    gateway_id: str = Field(..., description="Gateway identifier")
    connected_at: float = Field(default_factory=time.time, description="Connection timestamp")  # Add default
    last_seen: float = Field(..., description="Last activity timestamp")
    role: str = Field(default="user", description="User role")
    websocket: Any = Field(..., description="WebSocket object")

class DisconnectReason(BaseModel):
    """Disconnect reason information"""
    code: int = Field(..., description="WebSocket close code")
    reason: str = Field(..., description="Disconnect reason")
    initiated_by: str = Field(..., description="Who initiated disconnect (server/client)")