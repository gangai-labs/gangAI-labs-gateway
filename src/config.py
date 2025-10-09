# file: ./config.py
"""
Central configuration for the FastAPI  .
Uses utils/env_loader.py wrapper for robust .env loading (auto-trims # comments, safe casts).
Load once in app.py: from utils.env_loader import load_env; load_env(".env")
Then access via get_env(key, default, cast=bool) or dicts below.
Design: Modular for providers (e.g., local vs. HF embeddings).
For production: Generate SECRET_KEY with openssl rand -hex 32; use env vars/secrets manager.
Defaults are dev-friendly (e.g., local embeddings for offline testing).
Or create .env if wanted to avoid default values.
"""

from utils.env_loader import get_env  # Wrapper for safe loading/casting
#=============================================================================
#MAIN_CONFIG: Global settings (used across all managers for logging, etc.)
#=============================================================================
MAIN_CONFIG = {
"LOGGING_LEVEL": get_env("LOGGING_LEVEL", default="ERROR"),  # Global log level)
}
#=============================================================================
#FASTAPI_CONFIG: FastAPI app setup (used in FastApiManager for server, CORS, docs)
#=============================================================================
FASTAPI_CONFIG = {
"LOGGING_LEVEL": get_env("FASTAPI_LOGGING_LEVEL", default="ERROR"),  # FastAPI-specific logging (uvicorn logs; overrides MAIN if set)
"APP_NAME": get_env("APP_NAME", default="Gateway"),  # App title (Swagger/OpenAPI docs)
"VERSION": get_env("VERSION", default="1.0"),  # App version (OpenAPI schema)
"RELOAD": get_env("RELOAD", default="True", cast=bool),  # Dev auto-reload (uvicorn --reload; false in prod)
"WORKERS": get_env("WORKERS", default="1", cast=int),  # Uvicorn worker count (scale for prod; 1 for dev)
"DEFAULT_PORT": get_env("DEFAULT_PORT", default="8000", cast=int),  # Server port)
"DEFAULT_HOST": get_env("DEFAULT_HOST", default="localhost"),  # Bind host (0.0.0.0 for Docker/external access)
"ALLOW_ORIGINS": get_env("ALLOW_ORIGINS", default="").split(","),  # CORS origins (e.g., "" for dev; restrict in prod, e.g., "https://yourdomain.com")
"ALLOW_CREDENTIALS": get_env("ALLOW_CREDENTIALS", default="True", cast=bool),  # CORS credentials (for auth cookies/JWT)
"ALLOW_METHODS": get_env("ALLOW_METHODS", default="").split(","),  # CORS methods (GET/POST for API/Chainlit)
"ALLOW_HEADERS": get_env("ALLOW_HEADERS", default=",Authorization").split(","),  # CORS headers (Authorization for Bearer JWT)
"EXPOSE_HEADERS": get_env("EXPOSE_HEADERS", default="*").split(","),  # Exposed CORS headers (e.g., for custom responses)
"ENABLE_DOCS": get_env("ENABLE_DOCS", default="True", cast=bool),  # Swagger UI (/docs; disable in prod for security)
"ENABLE_REDOC": get_env("ENABLE_REDOC", default="True", cast=bool),  # ReDoc UI (/redoc; alternative docs)
}
#=============================================================================
#OPENAI_CONFIG: Authentication, JWT, and rate limiting (used in SecurityManager for all routes)
#=============================================================================
SECURITY_CONFIG = {
"SECRET_KEY": get_env("SECRET_KEY", default="admin"), #TODO change later default  # JWT signing key (HS256; generate with openssl rand -hex 32)
"ALGORITHM": get_env("ALGORITHM", default="HS256"),  # JWT algorithm (HS256 for symmetric keys)
"ACCESS_TOKEN_EXPIRE_MINUTES": get_env("ACCESS_TOKEN_EXPIRE_MINUTES", default="30", cast=int),  # JWT expiry (30min; used in /auth/token)
}

#=============================================================================
#HTTPX_CONFIG: HTTP client for external APIs (reused accross the app in HttpxManager for async calls)
#=============================================================================

HTTPX_CONFIG = {
"LOGGING_LEVEL": get_env("HTTPX_LOGGING_LEVEL", default="ERROR"),  # Httpx-specific logs (e.g., retries, circuit breaker events)
"TIMEOUT": get_env("HTTPX_TIMEOUT", default="30.0", cast=float),  # Global request timeout (seconds; for all remote APIs like HF)
"CIRCUIT_FAILURE_THRESHOLD": get_env("HTTPX_CIRCUIT_FAILURE_THRESHOLD", default="5", cast=int),  # Circuit breaker: Fail after N errors (e.g., API down)
"CIRCUIT_RECOVERY_TIMEOUT": get_env("HTTPX_CIRCUIT_RECOVERY_TIMEOUT", default="30", cast=int),  # Time to recover after breaker (seconds)
"RETRY_ATTEMPTS": get_env("HTTPX_RETRY_ATTEMPTS", default="3", cast=int),  # Retry count for failures (timeouts, 5xx)
"RETRY_MULTIPLIER": get_env("HTTPX_RETRY_MULTIPLIER", default="1", cast=float),  # Exponential backoff multiplier (e.g., 1s, 2s, 4s)
"RETRY_MIN_WAIT": get_env("HTTPX_RETRY_MIN_WAIT", default="1", cast=float),  # Min wait between retries (seconds)
"RETRY_MAX_WAIT": get_env("HTTPX_RETRY_MAX_WAIT", default="10", cast=float),  # Max wait between retries (seconds)
}

#=============================================================================
#ROUTES_MANAGER_CONFIG:  
#=============================================================================

ROUTES_MANAGER_CONFIG = {
"LOGGING_LEVEL": get_env("URLMANAGER_LOGGING_LEVEL", default="ERROR"),  
}

#=============================================================================
#SESSION_CONFIG:  sessions control goal is to make able to select modules what to inject per user
#=============================================================================

SESSION_CONFIG = {
"LOGGING_LEVEL": get_env("SESSION_LOGGING_LEVEL", default="ERROR"),
# to keep user logged in if no activity scrap session logout.
"TIMEOUT_MINUTES": get_env("SESSION_TIMEOUT_MINUTES", default="30", cast=int),
#max inactive days default 365 send warning we will delete in another 30d
"MAX_INACTIVE_DAYS": get_env("SESSION_MAX_INACTIVE_DAYS", default="365", cast=int),
#will check every 24h or days for old accounts send warning we will delete in another 30d it is just loop.
"CHECK_INTERVAL_DAYS" : get_env("SESSION_CHECK_INTERVAL_DAYS", default="1", cast=int),

}
#=============================================================================
#REDIS_CONFIG: TODO add clusters
#=============================================================================
REDIS_CONFIG = {
"LOGGING_LEVEL": get_env("REDIS_LOGGING_LEVEL", default="ERROR"),
"SESSION_TIMEOUT_SECONDS": get_env("REDIS_SESSION_TIMEOUT_SECONDS", default="1800", cast=int),  # 30 min
"REDIS_URL": get_env("REDIS_URL", default="redis://redis:6379"),  # Default stays single-node for local
"REDIS_HOST": get_env("REDIS_HOST", default="redis"),  # Not used for cluster, but harmless
"REDIS_PORT": get_env("REDIS_PORT", default="6379", cast=int),  # Ignored for cluster URLs
}

#=============================================================================
#WEBSOCKETS_CONFIG:
#=============================================================================
WEBSOCKETS_CONFIG = {
"LOGGING_LEVEL": get_env("WEBSOCKETS_LOGGING_LEVEL", default="ERROR"),
# Cache settings
"CACHE_TTL": get_env("WEBSOCKETS_CACHE_TTL", default="300", cast=int),
"CACHE_CLEANUP_INTERVAL": get_env("WEBSOCKETS_CACHE_CLEANUP_INTERVAL", default="30", cast=int),
# Connection health settings
"PING_INTERVAL": get_env("WEBSOCKETS_PING_INTERVAL", default="25", cast=int),  # Send ping every 25s
#make sure fronend sends this back basic.
"PONG_TIMEOUT": get_env("WEBSOCKETS_PONG_TIMEOUT", default="30", cast=int),    # Close if no pong in 30s
#if no interaction will kill ws
"INACTIVITY_TIMEOUT": get_env("WEBSOCKETS_INACTIVITY_TIMEOUT", default="60", cast=int),  # Close if no activity in 60s
}

# Admin configuration
ADMIN_CONFIG = {
"LOGGING_LEVEL": get_env("ADMIN_LOGGING_LEVEL", default="ERROR"),
"ADMIN_USERNAMES": ["admin", "superuser"],  # Pre-defined admin usernames
"ALLOW_ADMIN_REGISTRATION": False,  # Whether new admins can be registered
"DEFAULT_USER_ROLE": "user"
}


