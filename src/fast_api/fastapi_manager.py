# file:src/fast_api_utils/fastapi_manager.py


import sys
from datetime import datetime, timezone

import setproctitle
from fastapi import FastAPI, Request, HTTPException, APIRouter
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from slowapi.errors import RateLimitExceeded
from starlette.middleware.cors import CORSMiddleware
from fast_api.error_models import ErrorResponse, ValidationErrorResponse, RateLimitResponse
from config import FASTAPI_CONFIG

class FastApiManager:
    """
    FastAPI Manager - Handles FastAPI application setup, routing, and configuration
    Features:
    - Process naming for better process identification
    - CORS middleware configuration
    - Health check endpoints
    - Admin and user role management (DISABLED for dev mode)
    - Command-line argument parsing for host/port configuration
    """
    def __init__(self, logger_manager: object,
                 security_manager: object,
                 redis_client:object,
                 session_manager:object,
                 ws_registry:object):
        """
        Initialize FastAPI Manager
        Args:
            logger_manager: Logger manager instance for logging
            security_manager: Security manager instance for authentication (IGNORED in dev mode)
        """
        self.logger = logger_manager.create_logger(logger_name="FastApiManager",
                                                   logging_level=FASTAPI_CONFIG["LOGGING_LEVEL"])
        self.DEFAULT_PORT = FASTAPI_CONFIG['DEFAULT_PORT']
        self.DEFAULT_HOST = FASTAPI_CONFIG['DEFAULT_HOST']
        self.security_manager = security_manager  # Kept but not used in dev mode
        self.redis_client = redis_client
        self.session_manager = session_manager
        self.ws_registry = ws_registry
        self.router = APIRouter(tags=['FastAPI Manager'])
        self._setup_routes()  # Ensure routes are defined on init
    def setup(self, lifespan=None, app_name: str = FASTAPI_CONFIG["APP_NAME"]) -> FastAPI:
        try:
            setproctitle.setproctitle(title=app_name)
            app = FastAPI(
                title=app_name,
                version=FASTAPI_CONFIG["VERSION"],
                lifespan=lifespan,
                docs_url="/docs" if FASTAPI_CONFIG.get("ENABLE_DOCS", True) else None,
                redoc_url="/redoc" if FASTAPI_CONFIG.get("ENABLE_REDOC", True) else None,
            )
            # ---------- Add Exception Handlers FIRST ----------
            self._setup_exception_handlers(app)

            # ---------- CORS ----------
            app.add_middleware(
                CORSMiddleware,
                allow_origins=FASTAPI_CONFIG["ALLOW_ORIGINS"],
                allow_credentials=FASTAPI_CONFIG["ALLOW_CREDENTIALS"],
                allow_methods=FASTAPI_CONFIG["ALLOW_METHODS"],
                allow_headers=FASTAPI_CONFIG["ALLOW_HEADERS"],
                expose_headers=FASTAPI_CONFIG["EXPOSE_HEADERS"],
            )
            # ---------- Rate limiting (kept, but can be disabled if needed) ----------

            # ---------- Register router ----------
            app.include_router(self.router)

            self.logger.debug(f"FastAPI app '{app_name}' ready with comprehensive error handling (auth disabled for dev)")
            return app
        except Exception as exc:
            self.logger.exception(f"Failed to build FastAPI app: {exc}")
            raise
    def _setup_exception_handlers(self, app: FastAPI):
        """Setup comprehensive exception handlers (JWT handler DISABLED for dev mode)"""
        @app.exception_handler(HTTPException)
        async def http_exception_handler(request: Request, exc: HTTPException):
            """Handle HTTP exceptions (400, 401, 403, 404, etc.)"""
            error_detail = exc.detail
            if isinstance(error_detail, dict):
                error_message = error_detail.get('error', 'HTTP Error')
                detail_message = error_detail.get('detail', str(exc.detail))
            else:
                error_message = str(exc.detail)
                detail_message = None
            error_response = ErrorResponse(
                error=error_message,
                detail=detail_message,
                status_code=exc.status_code,
                timestamp=datetime.now(timezone.utc).isoformat(),
                path=request.url.path
            )
            self.logger.warning(f"HTTP {exc.status_code} at {request.url.path}: {error_message}")
            return JSONResponse(
                status_code=exc.status_code,
                content=error_response.model_dump()
            )
        @app.exception_handler(RequestValidationError)
        async def validation_exception_handler(request: Request, exc: RequestValidationError):
            """Handle Pydantic validation errors (422)"""
            errors = []
            for error in exc.errors():
                error_info = {
                    "loc": error["loc"],
                    "msg": error["msg"],
                    "type": error["type"]
                }
                errors.append(error_info)
            error_response = ValidationErrorResponse(
                error="Validation Error",
                detail="One or more fields failed validation",
                status_code=422,
                timestamp=datetime.now(timezone.utc).isoformat(),
                path=request.url.path,
                errors=errors
            )
            self.logger.warning(f"Validation error at {request.url.path}: {errors}")
            return JSONResponse(
                status_code=422,
                content=error_response.model_dump()
            )
        @app.exception_handler(RateLimitExceeded)
        async def rate_limit_exception_handler(request: Request, exc: RateLimitExceeded):
            """Handle rate limiting errors (429)"""
            retry_after = getattr(exc, 'retry_after', None)
            error_response = RateLimitResponse(
                error="Rate Limit Exceeded",
                detail="Too many requests. Please try again later.",
                status_code=429,
                timestamp=datetime.now(timezone.utc).isoformat(),
                path=request.url.path,
                retry_after=retry_after
            )
            self.logger.warning(f"Rate limit exceeded at {request.url.path} from {request.client.host}")
            headers = {}
            if retry_after:
                headers["Retry-After"] = str(retry_after)
                headers["X-RateLimit-Limit"] = "60"  # Example limit
                headers["X-RateLimit-Remaining"] = "0"
                headers["X-RateLimit-Reset"] = str(int(datetime.now(timezone.utc).timestamp()) + retry_after)
            return JSONResponse(
                status_code=429,
                content=error_response.model_dump(),
                headers=headers
            )
        # @app.exception_handler(JWTError)
        # async def jwt_exception_handler(request: Request, exc: JWTError):
        #     """Handle JWT token errors (DISABLED for dev mode)"""
        #     error_response = ErrorResponse(
        #         error="Authentication Error",
        #         detail="Invalid or expired token",
        #         status_code=401,
        #         timestamp=datetime.now(timezone.utc).isoformat(),
        #         path=request.url.path
        #     )
        #     self.logger.warning(f"JWT error at {request.url.path}: {exc}")
        #     return JSONResponse(
        #         status_code=401,
        #         content=error_response.model_dump(),
        #         headers={"WWW-Authenticate": "Bearer"}
        #     )
        @app.exception_handler(500)
        @app.exception_handler(Exception)
        async def general_exception_handler(request: Request, exc: Exception):
            """Handle all other exceptions (500)"""
            # Log the full exception for debugging
            self.logger.error(f"Internal server error at {request.url.path}: {exc}", exc_info=True)
            # Don't expose internal details in production
            if FASTAPI_CONFIG.get("ENVIRONMENT") == "production":
                detail = "An internal server error occurred. Please try again later."
            else:
                detail = f"Internal server error: {str(exc)}"
            error_response = ErrorResponse(
                error="Internal Server Error",
                detail=detail,
                status_code=500,
                timestamp=datetime.now(timezone.utc).isoformat(),
                path=request.url.path
            )
            return JSONResponse(
                status_code=500,
                content=error_response.model_dump()
            )
        @app.exception_handler(404)
        async def not_found_exception_handler(request: Request, exc: Exception):
            """Handle 404 Not Found"""
            error_response = ErrorResponse(
                error="Not Found",
                detail=f"The requested URL {request.url.path} was not found on this server.",
                status_code=404,
                timestamp=datetime.now(timezone.utc).isoformat(),
                path=request.url.path
            )
            self.logger.warning(f"404 Not Found: {request.url.path}")
            return JSONResponse(
                status_code=404,
                content=error_response.model_dump()
            )
        @app.exception_handler(405)
        async def method_not_allowed_handler(request: Request, exc: Exception):
            """Handle 405 Method Not Allowed"""
            error_response = ErrorResponse(
                error="Method Not Allowed",
                detail=f"The method {request.method} is not allowed for the URL {request.url.path}.",
                status_code=405,
                timestamp=datetime.now(timezone.utc).isoformat(),
                path=request.url.path
            )
            self.logger.warning(f"405 Method Not Allowed: {request.method} {request.url.path}")
            return JSONResponse(
                status_code=405,
                content=error_response.model_dump()
            )
    # Background task for Pub/Sub listener (listens for session/WS events across K8s replicas)
    async def pubsub_listener(self):
        """Listens to Redis pub/sub for real-time sync (e.g., session updates push to other gateways)."""
        await self.session_manager.pubsub_listener()  # Events: session:update:*, connection:* [7]
        await self.ws_registry.pubsub_listener()  # WS-specific events [13]
    # ------------------------------------------------------------------
    # Route definitions (AUTH DISABLED for dev mode)
    # ------------------------------------------------------------------
    def _setup_routes(self) -> None:
         #add any if needed in the future.
         pass




    def args(self):
        """
        Parse command-line arguments for host and port configuration
        Returns:
            Tuple of (host, port) configuration
        Supported arguments:
            --port, -p: Port number (default: 8000)
            --host, -h: Host address (default: localhost)
            --default, -d: Use default configuration
            --help: Show help message
        """
        _args = (
            "\n"
            "FastAPI Server Configuration\n"
            "============================\n"
            "Example usage:\n"
            "  Option 1 (recommended for dev/prod):\n"
            "    uv run uvicorn app:app --host=0.0.0.0 --port 8081 --reload --workers 4\n\n"
            "  Option 2 (runs via config.py, more flexible/scalable):\n"
            "    uv run app.py --host=0.0.0.0 --port 8081 --reload --workers 4\n\n"
            "  Option 3 (runs via default variables as it is at config):\n"
            "    uv run app.py --default\n\n"
            "Note: Option 2 and 3 may have double logging due to multiple processes started by python and uvicorn reload.\n\n"
            "Options:\n"
            "  --port=PORT, -p PORT    Port number to run the server on (default: 8000)\n"
            "  --host=HOST, -h HOST    Host address to bind to (default: localhost)\n"
            f"  --default, -d          Use default port:{self.DEFAULT_PORT} and host:{self.DEFAULT_HOST}\n"
            "  --help                  Show this help message and exit"
        )
        args = sys.argv[1:]  # Skip the script name itself
        host = self.DEFAULT_HOST
        port = self.DEFAULT_PORT
        if "--help" in args or "-h" in args or not args:
            self.logger.error(_args)
            sys.exit(0)
        i = 0
        while i < len(args):
            arg = args[i]
            if arg in ["--default", "-d"]:
                host = self.DEFAULT_HOST
                port = self.DEFAULT_PORT
                self.logger.warning(f"Using default configuration: host={host}, port={port}")
            elif arg in ["--port", "-p"]:
                try:
                    port = int(args[i + 1])
                    i += 1
                    self.logger.debug(f"Custom port configured: {port}")
                except (IndexError, ValueError):
                    self.logger.error(f"Invalid port number: {args[i + 1] if i + 1 < len(args) else 'missing'}")
                    sys.exit(1)
            elif arg in ["--host", "-h"]:
                try:
                    host = args[i + 1]
                    i += 1
                    self.logger.debug(f"Custom host configured: {host}")
                except IndexError:
                    self.logger.error(f"Missing host value for: {arg}")
                    sys.exit(1)
            elif arg.startswith("--port="):
                try:
                    port = int(arg.split("=")[1])
                    self.logger.debug(f"Custom port configured: {port}")
                except ValueError:
                    self.logger.error(f"Invalid port number: {arg}")
                    sys.exit(1)
            elif arg.startswith("--host="):
                host = arg.split("=")[1]
                self.logger.debug(f"Custom host configured: {host}")
            else:
                self.logger.error(f"Unknown argument: {arg}")
                self.logger.error(_args)
                sys.exit(1)
            i += 1
        self.logger.debug(f'Command line arguments processed: host={host}, port={port}')
        return host, port