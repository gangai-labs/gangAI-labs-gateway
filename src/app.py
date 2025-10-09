# File: src/app.py
from utils.env_loader import load_env, get_env

load_env()
import asyncio
import uvloop
asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())
from fastapi import FastAPI
import uvicorn
import os
from contextlib import asynccontextmanager

# Local imports
from config import MAIN_CONFIG, FASTAPI_CONFIG, SECURITY_CONFIG, REDIS_CONFIG, SESSION_CONFIG, WEBSOCKETS_CONFIG
from fast_api.fastapi_manager import FastApiManager
from utils.logger import Logger
from utils.httpx_manager import HttpxManager
from session.manager import SessionManager, get_redis_client
from wss.manager import WebsocketsManager
from wss.registry import WebsocketsRegistry
from fast_api.security_manager import SecurityManager
from urls_registry.manager import URLManager
from admin.manager import AdminManager

# Global managers (shared across app, scalable for K8s replicas)
logger_manager = Logger(project_root=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # [10]
logger = logger_manager.create_logger(logger_name='MAIN', logging_level=MAIN_CONFIG.get('LOGGING_LEVEL', 'DEBUG'))


DOCS_CONFIG = {
    "LOGGING_LEVEL": get_env("DOCS_LOGGING_LEVEL", default="ERROR"),
    "ENABLED": get_env("DOCS_ENABLED", default="True", cast=bool),
}

# =============================================================================
# Shared redis client
redis_client = get_redis_client()

# Httpx for backend orchestration (e.g., call auth-backend)
httpx_manager = HttpxManager(logger_manager=logger_manager)

# Security for JWT/token validation
security_manager = SecurityManager(logger_manager=logger_manager,
                                   config=SECURITY_CONFIG)

#session handler to track sessions
session_manager = SessionManager(
    logger_manager=logger_manager,
    redis_client=redis_client,
    security_manager=security_manager,
    config=SESSION_CONFIG,
)


#URL Manager for dynamic routes (WITH AUTH)
url_manager = URLManager(
    logger_manager=logger_manager,
    security_manager=security_manager,
    session_manager=session_manager,  # Pass session_manager for auth
    httpx_manager=httpx_manager
)

# WS handling (tracks connections in Redis for pub/sub across gateways)
ws_registry = WebsocketsRegistry(logger_manager=logger_manager,
                                 redis_client=redis_client,
                                 config=WEBSOCKETS_CONFIG)

#WebSocket Manager with URL Manager for dynamic WS handlers
ws_manager = WebsocketsManager(
    ws_registry=ws_registry,
    session_manager=session_manager,
    logger_manager=logger_manager,
    security_manager=security_manager,
    httpx_manager=httpx_manager,
    redis_client=redis_client,
    url_manager=url_manager  #  Pass url_manager for dynamic WS message handlers
)

#FastApi Manager for health and fastapi
fast_api_manager = FastApiManager(logger_manager=logger_manager,
                                  security_manager=security_manager,
                                  redis_client=redis_client,
                                  session_manager=session_manager,
                                  ws_registry=ws_registry)

admin_manager = AdminManager(
    logger_manager=logger_manager,
    session_manager=session_manager,
    ws_registry=ws_registry,
    redis_client=redis_client,
    security_manager=security_manager
)


# FastAPI app setup (reuse your config for CORS, docs, etc.) [3][15]
app = FastAPI(
    title=FASTAPI_CONFIG.get("APP_NAME", "API Gateway"),
    version=FASTAPI_CONFIG.get("VERSION", "1.0.0"),
    docs_url="/docs" if FASTAPI_CONFIG.get("ENABLE_DOCS", True) else None,
    redoc_url="/redoc" if FASTAPI_CONFIG.get("ENABLE_REDOC", True) else None
)

@asynccontextmanager
async def lifespan(app: FastAPI):

    logger.debug(f"Gateway started with Redis at {REDIS_CONFIG['REDIS_URL']} - Loaded users")
    # Load users and start background tasks
    asyncio.create_task(session_manager.start_background_tasks())
    asyncio.create_task(ws_registry.start_background_tasks())
    yield
    # Shutdown: Cleanup connections/sessions
    await ws_registry.cleanup_all()  # Remove WS tracks
    await session_manager.session_cleaner.cleanup(days_inactive=SESSION_CONFIG['MAX_INACTIVE_DAYS'])
    
    await redis_client.close()
    logger_manager.close_all_loggers()

app = fast_api_manager.setup(lifespan=lifespan)
app.include_router(fast_api_manager.router)     # /health, etc.
app.include_router(session_manager.router)      # /sessions/* (with auth)
app.include_router(ws_manager.get_router())     # /ws/* (with auth)
app.include_router(url_manager.get_router())    # /api/* (with auth) allows to add remove dynamic rest/wss routes
app.include_router(admin_manager.get_router())  # /admin/* routes



if __name__ == "__main__":
    # K8s-friendly: Use env vars (e.g., PORT from Deployment, REDIS_URL from ConfigMap) [15][16]
    host = os.getenv("HOST", FASTAPI_CONFIG.get("DEFAULT_HOST", "0.0.0.0"))
    port = int(os.getenv("PORT", FASTAPI_CONFIG.get("DEFAULT_PORT", 8000)))
    reload = os.getenv("RELOAD", str(FASTAPI_CONFIG.get("RELOAD", True)).lower()) == "true"
    workers = int(os.getenv("WORKERS", FASTAPI_CONFIG.get("WORKERS", 1)))  # leave one worker for this as sticky sessions wont work with ws otherwise.We use docker for this.
    uvicorn_log_level = MAIN_CONFIG.get("LOGGING_LEVEL", "INFO").lower()
    logger.info(f"Starting Gateway: {FASTAPI_CONFIG['APP_NAME']} on {host}:{port} (Redis: {REDIS_CONFIG['REDIS_URL']})")
    uvicorn.run(
        "app:app",
        host=host,
        port=port,
        workers=workers if not reload else 1,
        reload=reload,
        log_level=uvicorn_log_level,
        ws='wsproto'
    )

#while developing use this otherwise start in docker ex:
#docker-compose down -v && docker-compose up --build -d add more settings for prod auto restart etc..
#uvicorn app:app --reload --port 8000 #