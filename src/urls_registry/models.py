# src/models.py
# ------------------------------------------------------------
# All Pydantic models that the URLManager uses.
# ------------------------------------------------------------
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional
from pydantic import BaseModel, Field


# ------------------------------------------------------------------
# External API configuration (what the gateway will proxy to)
# ------------------------------------------------------------------
@dataclass
class ExternalAPI:
    name: str
    base_url: str
    path: str
    method: str = Field(..., pattern="^(GET|POST|PUT|DELETE|PATCH)$")
    headers: Optional[Dict[str, str]] = None
    timeout: Optional[int] = 30
    require_auth: bool = False
    ws_supported: bool = False


# ------------------------------------------------------------------
# REST route configuration (used when you want a *custom* handler)
# ------------------------------------------------------------------
@dataclass
class RouteConfig:
    path: str
    methods: List[str]
    handler: object  # callable
    require_auth: bool = True
    tags: Optional[List[str]] = None
    summary: str = ""
    description: str = ""
    external_api: Optional[ExternalAPI] = None


# ------------------------------------------------------------------
# WS message handler configuration
# ------------------------------------------------------------------
@dataclass
class WSMessageConfig:
    message_type: str
    handler: object  # callable
    require_auth: bool = True
    description: str = ""
    external_api: Optional[ExternalAPI] = None


# ------------------------------------------------------------------
# REST API registration payloads
# ------------------------------------------------------------------
class ExternalAPIRequest(BaseModel):
    """Payload that the client sends to /api/register."""
    name: str
    base_url: str
    path: str
    method: str = Field(..., pattern="^(GET|POST|PUT|DELETE|PATCH)$")
    headers: Optional[Dict[str, str]] = None
    timeout: Optional[int] = 30
    require_auth: bool = False
    ws_supported: bool = False


class ExternalAPIResponse(BaseModel):
    """Response after a successful registration."""
    message: str
    name: str