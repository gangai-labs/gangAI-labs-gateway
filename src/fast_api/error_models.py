from typing import Optional, Any, Dict, List
from pydantic import BaseModel

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
    status_code: int
    timestamp: str
    path: Optional[str] = None

class ValidationErrorResponse(ErrorResponse):
    errors: Optional[List[Dict[str, Any]]] = None

class RateLimitResponse(ErrorResponse):
    retry_after: Optional[int] = None
