#File:src/session/models.py

# Pydantic models for session requests/responses.
from pydantic import BaseModel
from typing import Optional, Dict, Any


class SessionCreateRequest(BaseModel):
    user_id: str
    chat_id: Optional[str] = None
    session_id: Optional[str] = None  # For reuse

class SessionResponse(BaseModel):
    session_id: str  # UUID for stickiness
    user_id: str
    chat_id: str
    data: Dict[str, Any]
    ws_url: str  # Generated for WS connect

class UpdateSessionRequest(BaseModel):
    chat_id: Optional[str] = None
    data: Dict[str, Any]  # Updates like {"api_key": "new"}

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str

class RegisterResponse(BaseModel):
    message: str
    username: str


class LoginRequest(BaseModel):
    username: str  # Allow login by username (email optional for now)
    password: str

class LoginResponse(BaseModel):
    access_token: str
    token_type: str
    expires_in: int
    user: Dict[str, str]
    session_id: str

class LogoutResponse(BaseModel):
    message: str

class DeleteAccountResponse(BaseModel):
    message: str