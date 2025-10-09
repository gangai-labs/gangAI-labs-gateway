# file: src/utils/httpx_manager.py

import logging

from config import HTTPX_CONFIG

#patch for logger_manager to supress internal httpx logs as we handle them internaly.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)

import json
from typing import Optional, Dict, Any
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from pydantic import BaseModel, AnyHttpUrl, Field
from aiocircuitbreaker import CircuitBreaker, CircuitBreakerError

 
# ----------------------------
# Pydantic Models
# ----------------------------
class RequestPayload(BaseModel):
    url: AnyHttpUrl
    method: str = Field(default="GET", pattern="^(GET|POST|PUT|DELETE)$")
    body: Optional[dict] = None
    headers: Optional[dict] = None
    timeout: Optional[float] = None
    follow_redirects: bool = True

class ResponsePayload(BaseModel):
    success: bool
    data: Optional[Any] = None
    status_code: Optional[int] = None
    error: Optional[str] = None

# ----------------------------
# Retry filter
# ----------------------------
def _should_retry(exception: Exception) -> bool:
    if isinstance(exception, (httpx.TimeoutException, httpx.NetworkError, CircuitBreakerError)):
        return True
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code >= 500 or exception.response.status_code == 429
    return False

# ----------------------------
# HTTPX Manager
# ----------------------------
class HttpxManager:
    def __init__(self, logger_manager:object=None,):

      
        self.logger = logger_manager.create_logger(logger_name="HttpxManager",logging_level=HTTPX_CONFIG['LOGGING_LEVEL'])

        self.timeout = HTTPX_CONFIG['TIMEOUT']
        # Circuit breaker configuration
        self.circuit_failure_threshold = HTTPX_CONFIG.get('CIRCUIT_FAILURE_THRESHOLD', 5)
        self.circuit_recovery_timeout = HTTPX_CONFIG.get('CIRCUIT_RECOVERY_TIMEOUT', 30)

        # Retry configuration
        self.retry_attempts = HTTPX_CONFIG.get('RETRY_ATTEMPTS', 3)
        self.retry_multiplier = HTTPX_CONFIG.get('RETRY_MULTIPLIER', 1)
        self.retry_min_wait = HTTPX_CONFIG.get('RETRY_MIN_WAIT', 1)
        self.retry_max_wait = HTTPX_CONFIG.get('RETRY_MAX_WAIT', 10)

        # Circuit breaker
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=self.circuit_failure_threshold,
            recovery_timeout=self.circuit_recovery_timeout,
            expected_exception=(httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError),
            name="HttpxManagerCircuitBreaker"
        )

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((
            httpx.TimeoutException,
            httpx.NetworkError,
            CircuitBreakerError,
            httpx.HTTPStatusError
        )),
        reraise=True
    )
    async def make_request(self, payload: RequestPayload) -> Dict[str, Any]:
        """Accepts a RequestPayload Pydantic model for GET/POST/PUT/DELETE requests."""

        # Ensure url is str for httpx
        url = str(payload.url)
        method = payload.method.upper()
        body = payload.body
        headers = payload.headers
        timeout = payload.timeout or self.timeout
        follow_redirects = payload.follow_redirects

        # Use circuit breaker to wrap actual request
        try:
            decorated_execute = self.circuit_breaker.decorate(self._execute_request)
            return await decorated_execute(url, method, body, headers, timeout, follow_redirects)
        except CircuitBreakerError as e:
            self.logger.warning(f"Circuit breaker open: {url} - {e}")
            return {"error": "CIRCUIT_BREAKER_OPEN", "message": "Service temporarily unavailable"}
        except Exception as e:
            if isinstance(e, httpx.HTTPStatusError) and e.response.status_code < 500:
                return {"error": f"HTTP_{e.response.status_code}", "message": str(e)}
            raise

    async def _execute_request(self, url: str, method: str, body: Optional[dict],
                               headers: Optional[dict], timeout: float, follow_redirects: bool = True) -> Dict[str, Any]:
        """Actual HTTP request execution."""
        self.logger.debug(f"Making {method} request to {url}")
        self.logger.debug(f"Request body: {body}")

        headers = headers or {"Content-Type": "application/json"}

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=follow_redirects) as client:
                resp = await client.request(method, url, json=body, headers=headers)
                resp.raise_for_status()
                try:
                    return resp.json()
                except json.JSONDecodeError:
                    return {"data": resp.text, "status_code": resp.status_code}
        except Exception as e:
            self.logger.exception(e)
            raise

